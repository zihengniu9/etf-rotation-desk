"""Point-in-time backtest utilities for the growth factor.

Financial reports become usable only after their announcement date.  Because
the vendor response exposes a date but not an intraday timestamp, reports
announced on the signal date are conservatively deferred to the next signal.
Forward returns are evaluation labels and never participate in factor scores.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .growth_engine import code6, is_main_board_name


GROWTH_BACKTEST_VERSION = "growth-backtest-v1"
ONE_WAY_COST = 0.003
MIN_DAILY_AMOUNT = 50_000_000.0
DEFAULT_TOP_N = (1, 3, 5, 10)
DEFAULT_HORIZONS = (5, 10, 20)
BASELINE_FACTORS = ("growth_core", "quality_score", "financial_score")
EXPLORATORY_FACTORS = (
    "double_high_min",
    "growth_quality_geom",
    "quality_heavy",
    "balanced_gq",
    "top30_growth_quality",
    "persistent_quality",
    "growth_type_quality",
)
DEFAULT_FACTORS = BASELINE_FACTORS + EXPLORATORY_FACTORS
FACTOR_HYPOTHESES = {
    "growth_core": "既有v1：增速、加速度与持续性直接排序",
    "quality_score": "既有v1：现金兑现、ROE与利润率直接排序",
    "financial_score": "既有v1：50%成长 + 33.33%质量 + 16.67%负债质量",
    "double_high_min": "探索v2：成长与质量取较弱一侧，惩罚单腿突出",
    "growth_quality_geom": "探索v2：成长与质量几何均值",
    "quality_heavy": "探索v2：30%成长 + 55%质量 + 15%负债质量",
    "balanced_gq": "探索v2：40%成长 + 45%质量 + 15%负债质量",
    "top30_growth_quality": "探索v2：成长核心前30%且收入利润正增长后按质量排序",
    "persistent_quality": "探索v2：仅持续成长组内按质量排序",
    "growth_type_quality": "探索v2：持续/加速成长组内按质量排序",
}


def _first_column(frame: pd.DataFrame, labels: Iterable[str], period: str) -> str | None:
    """Resolve a Wencai field while keeping the requested report period exact."""

    for label in labels:
        exact = f"{label}[{period}]"
        if exact in frame.columns:
            return exact
    for label in labels:
        matches = [str(column) for column in frame.columns if str(column).startswith(f"{label}[")]
        period_matches = [column for column in matches if f"[{period}]" in column]
        if period_matches:
            return period_matches[0]
    for label in labels:
        if label in frame.columns:
            return label
    return None


def _series(frame: pd.DataFrame, labels: Iterable[str], period: str) -> pd.Series:
    column = _first_column(frame, labels, period)
    if column is None:
        return pd.Series(pd.NA, index=frame.index, dtype="object")
    return frame[column]


def _parse_vendor_date(values: pd.Series) -> pd.Series:
    cleaned = values.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    compact = pd.to_datetime(cleaned, format="%Y%m%d", errors="coerce")
    generic = pd.to_datetime(cleaned.where(compact.isna()), errors="coerce")
    return compact.fillna(generic)


def normalize_report_snapshot(frame: pd.DataFrame, report_period: str) -> pd.DataFrame:
    """Normalize one historical Wencai report response into a stable schema."""

    if frame.empty:
        return pd.DataFrame()
    code_column = _first_column(frame, ("股票代码", "code"), report_period)
    name_column = _first_column(frame, ("股票简称", "name"), report_period)
    if code_column is None:
        raise ValueError(f"report {report_period} has no 股票代码 field")

    result = pd.DataFrame(index=frame.index)
    result["code6"] = frame[code_column].map(code6)
    result["name"] = frame[name_column].astype(str) if name_column else result["code6"]
    result["report_period"] = pd.Timestamp(report_period)
    announcement = _series(
        frame,
        ("公告日期", "实际披露日期", "定期报告实际披露日期", "披露日期"),
        report_period,
    )
    result["announce_date"] = _parse_vendor_date(announcement)
    result["revenue_growth"] = _series(frame, ("营业收入同比增长率", "revenue_growth"), report_period)
    result["profit_growth"] = _series(
        frame,
        ("归母净利润同比增长率", "归属母公司股东的净利润同比增长率", "profit_growth"),
        report_period,
    )
    result["cash_flow"] = _series(
        frame,
        ("经营活动产生的现金流量净额", "经营活动现金流量净额", "cash_flow"),
        report_period,
    )
    result["roe"] = _series(frame, ("净资产收益率", "加权净资产收益率", "roe"), report_period)
    result["net_margin"] = _series(frame, ("销售净利率", "净利率", "net_margin"), report_period)
    result["debt_ratio"] = _series(frame, ("资产负债率", "debt_ratio"), report_period)
    result["revenue"] = _series(frame, ("营业收入", "revenue"), report_period)
    result["net_profit"] = _series(
        frame,
        ("归母净利润", "归属母公司股东的净利润", "net_profit"),
        report_period,
    )
    for column in (
        "revenue_growth", "profit_growth", "cash_flow", "roe", "net_margin",
        "debt_ratio", "revenue", "net_profit",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result[result.apply(lambda row: is_main_board_name(row["code6"], row["name"]), axis=1)]
    result = result.dropna(subset=["announce_date"])
    return result.drop_duplicates(["code6", "report_period"], keep="last").reset_index(drop=True)


def combine_report_snapshots(snapshots: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine report-period responses and remove duplicate stock-period rows."""

    normalized = [normalize_report_snapshot(frame, period) for period, frame in snapshots.items()]
    normalized = [frame for frame in normalized if not frame.empty]
    if not normalized:
        return pd.DataFrame()
    result = pd.concat(normalized, ignore_index=True)
    return result.sort_values(["code6", "report_period", "announce_date"]).drop_duplicates(
        ["code6", "report_period"], keep="last"
    ).reset_index(drop=True)


def _rank_score(values: pd.Series, *, low: float | None = None, high: float | None = None) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if low is not None or high is not None:
        numeric = numeric.clip(lower=low, upper=high)
    return numeric.rank(pct=True) * 100.0


def _weighted_available(frame: pd.DataFrame, components: Mapping[str, float]) -> pd.Series:
    numerator = pd.Series(0.0, index=frame.index)
    denominator = pd.Series(0.0, index=frame.index)
    for column, weight in components.items():
        values = pd.to_numeric(frame[column], errors="coerce")
        available = values.notna()
        numerator = numerator.add(values.fillna(0.0) * weight, fill_value=0.0)
        denominator = denominator.add(available.astype(float) * weight, fill_value=0.0)
    return (numerator / denominator).where(denominator > 0)


def _attach_report_lags(available: pd.DataFrame) -> pd.DataFrame:
    ordered = available.sort_values(["code6", "report_period", "announce_date"]).copy()
    ordered["report_lag"] = ordered.groupby("code6").cumcount(ascending=False)
    pieces: list[pd.DataFrame] = []
    fields = [
        "report_period", "announce_date", "revenue_growth", "profit_growth", "cash_flow",
        "roe", "net_margin", "debt_ratio", "revenue", "net_profit",
    ]
    for lag, prefix in ((0, "current"), (1, "prev"), (2, "prev2")):
        part = ordered[ordered["report_lag"] == lag].set_index("code6")
        part = part[[column for column in fields if column in part.columns]].rename(
            columns={column: f"{prefix}_{column}" for column in fields}
        )
        pieces.append(part)
    if not pieces:
        return pd.DataFrame()
    result = pieces[0]
    for part in pieces[1:]:
        result = result.join(part, how="left")
    return result.reset_index()


def _score_cross_section(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["revenue_acceleration"] = result["current_revenue_growth"] - result["prev_revenue_growth"]
    result["profit_acceleration"] = result["current_profit_growth"] - result["prev_profit_growth"]
    result["cash_margin"] = (result["current_cash_flow"] / result["current_revenue"]).where(
        result["current_revenue"].ne(0)
    )
    result["cash_to_profit"] = (result["current_cash_flow"] / result["current_net_profit"]).where(
        result["current_net_profit"].ne(0)
    )

    persistence_fields = [
        "current_revenue_growth", "prev_revenue_growth", "prev2_revenue_growth",
        "current_profit_growth", "prev_profit_growth", "prev2_profit_growth",
    ]
    result["report_history_complete"] = result[persistence_fields].notna().all(axis=1)
    result["persistence_score"] = (
        sum((result[column] > 0).astype(float) for column in persistence_fields) / len(persistence_fields) * 100.0
    ).where(result["report_history_complete"])

    result["financial_valid"] = (
        result["current_revenue"].gt(0)
        & result["current_net_profit"].gt(0)
        & result["current_revenue_growth"].notna()
        & result["current_profit_growth"].notna()
        & result["prev_revenue_growth"].notna()
        & result["prev_profit_growth"].notna()
    )
    score_rows = result["financial_valid"]
    result.loc[score_rows, "rev_growth_score"] = _rank_score(
        result.loc[score_rows, "current_revenue_growth"], low=-50, high=200
    )
    result.loc[score_rows, "profit_growth_score"] = _rank_score(
        result.loc[score_rows, "current_profit_growth"], low=-80, high=500
    )
    result.loc[score_rows, "rev_acceleration_score"] = _rank_score(
        result.loc[score_rows, "revenue_acceleration"], low=-100, high=150
    )
    result.loc[score_rows, "profit_acceleration_score"] = _rank_score(
        result.loc[score_rows, "profit_acceleration"], low=-300, high=500
    )
    result["growth_core"] = _weighted_available(
        result,
        {
            "rev_growth_score": 0.25,
            "profit_growth_score": 0.35,
            "rev_acceleration_score": 0.15,
            "profit_acceleration_score": 0.15,
            "persistence_score": 0.10,
        },
    ).where(score_rows)

    result.loc[score_rows, "cash_margin_score"] = _rank_score(
        result.loc[score_rows, "cash_margin"], low=-0.5, high=1.0
    )
    result.loc[score_rows, "cash_to_profit_score"] = _rank_score(
        result.loc[score_rows, "cash_to_profit"], low=-1.0, high=3.0
    )
    result.loc[score_rows, "roe_score"] = _rank_score(
        result.loc[score_rows, "current_roe"], low=-5, high=30
    )
    result.loc[score_rows, "net_margin_score"] = _rank_score(
        result.loc[score_rows, "current_net_margin"], low=-20, high=60
    )
    result["quality_score"] = _weighted_available(
        result,
        {
            "cash_margin_score": 0.35,
            "cash_to_profit_score": 0.25,
            "roe_score": 0.20,
            "net_margin_score": 0.20,
        },
    ).where(score_rows)
    result["balance_score"] = (100.0 - result["current_debt_ratio"].clip(0, 100)).where(score_rows)
    # This is the live v1 financial score with the unavailable 10% news layer
    # removed and the remaining weights renormalized to one.
    result["financial_score"] = _weighted_available(
        result,
        {"growth_core": 0.50, "quality_score": 1.0 / 3.0, "balance_score": 1.0 / 6.0},
    ).where(score_rows)

    persistent = result["report_history_complete"] & result[persistence_fields].gt(0).all(axis=1)
    acceleration = (
        result["current_profit_growth"].gt(result["prev_profit_growth"] + 10)
        & result["current_revenue_growth"].gt(0)
        & result["current_net_profit"].gt(0)
    )
    reversal = (
        result["current_profit_growth"].gt(200)
        | result["prev_net_profit"].le(0)
        | result["prev2_net_profit"].le(0)
    ).fillna(False)
    result["growth_profile"] = "增速观察"
    result.loc[persistent, "growth_profile"] = "持续成长"
    result.loc[acceleration & ~persistent, "growth_profile"] = "加速成长"
    result.loc[reversal & ~persistent, "growth_profile"] = "反转/低基数"

    # Exploratory v2 hypotheses are kept explicitly, including the variants
    # expected to fail, so the multiple-testing denominator remains auditable.
    result["double_high_min"] = result[["growth_core", "quality_score"]].min(axis=1)
    result["growth_quality_geom"] = np.sqrt(
        result["growth_core"].clip(lower=0) * result["quality_score"].clip(lower=0)
    )
    result["quality_heavy"] = (
        result["growth_core"] * 0.30
        + result["quality_score"] * 0.55
        + result["balance_score"] * 0.15
    )
    result["balanced_gq"] = (
        result["growth_core"] * 0.40
        + result["quality_score"] * 0.45
        + result["balance_score"] * 0.15
    )
    positive_growth = result["current_revenue_growth"].gt(0) & result["current_profit_growth"].gt(0)
    result["top30_growth_quality"] = result["quality_score"].where(
        result["growth_core"].ge(70) & positive_growth
    )
    result["persistent_quality"] = result["quality_score"].where(result["growth_profile"].eq("持续成长"))
    result["growth_type_quality"] = result["quality_score"].where(
        result["growth_profile"].isin(["持续成长", "加速成长"])
    )
    return result


def build_point_in_time_panel(
    reports: pd.DataFrame,
    market_history: pd.DataFrame,
    *,
    min_amount: float = MIN_DAILY_AMOUNT,
) -> pd.DataFrame:
    """Build monthly growth-factor cross-sections without future information."""

    if reports.empty or market_history.empty:
        return pd.DataFrame()
    report_frame = reports.copy()
    report_frame["announce_date"] = pd.to_datetime(report_frame["announce_date"], errors="coerce")
    report_frame["report_period"] = pd.to_datetime(report_frame["report_period"], errors="coerce")
    market = market_history.copy()
    market["signal_date"] = pd.to_datetime(market["date"], errors="coerce")
    market["code6"] = market["code"].map(code6)
    market["amount"] = pd.to_numeric(market.get("amount"), errors="coerce")
    market = market[
        market["signal_date"].notna()
        & market["code6"].map(lambda value: is_main_board_name(value, ""))
        & market["amount"].ge(float(min_amount))
    ].copy()

    panels: list[pd.DataFrame] = []
    for signal_date, market_slice in market.groupby("signal_date", sort=True):
        # Strictly earlier is intentional: a date-only announcement stamped on
        # signal day may have arrived after the close.
        available = report_frame[report_frame["announce_date"] < signal_date]
        if available.empty:
            continue
        lagged = _attach_report_lags(available)
        joined = market_slice.merge(lagged, on="code6", how="inner")
        if joined.empty:
            continue
        joined["signal_date"] = signal_date
        panels.append(_score_cross_section(joined))
    if not panels:
        return pd.DataFrame()
    result = pd.concat(panels, ignore_index=True)
    result["date"] = result["signal_date"].dt.strftime("%Y-%m-%d")
    return result.sort_values(["signal_date", "financial_score"], ascending=[True, False]).reset_index(drop=True)


def _normal_p_value(t_stat: float | None) -> float | None:
    if t_stat is None or not math.isfinite(t_stat):
        return None
    return math.erfc(abs(t_stat) / math.sqrt(2.0))


def _series_summary(values: pd.Series) -> dict[str, float | int | None]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"count": 0, "mean": None, "median": None, "std": None, "positive_rate": None}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "std": float(clean.std(ddof=1)) if len(clean) > 1 else None,
        "positive_rate": float((clean > 0).mean()),
    }


def _ic_summary(rows: pd.DataFrame, factor: str, return_column: str) -> dict[str, object]:
    values: list[float] = []
    by_date: list[dict[str, object]] = []
    for signal_date, group in rows.groupby("date", sort=True):
        valid = group[[factor, return_column]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(valid) < 20 or valid[factor].nunique() < 3 or valid[return_column].nunique() < 3:
            continue
        ic = float(valid[factor].rank(method="average").corr(valid[return_column].rank(method="average")))
        if math.isfinite(ic):
            values.append(ic)
            by_date.append({"date": str(signal_date), "rank_ic": ic, "stocks": int(len(valid))})
    series = pd.Series(values, dtype="float64")
    mean = float(series.mean()) if len(series) else None
    std = float(series.std(ddof=1)) if len(series) > 1 else None
    t_stat = mean / (std / math.sqrt(len(series))) if mean is not None and std and std > 0 else None
    return {
        "periods": int(len(series)),
        "rank_ic_mean": mean,
        "rank_ic_median": float(series.median()) if len(series) else None,
        "rank_ic_ir": mean / std if mean is not None and std and std > 0 else None,
        "positive_rate": float((series > 0).mean()) if len(series) else None,
        "t_stat": t_stat,
        "p_value_normal_approx": _normal_p_value(t_stat),
        "by_date": by_date,
    }


def _decile_summary(rows: pd.DataFrame, factor: str, return_column: str) -> dict[str, object]:
    pieces: list[pd.DataFrame] = []
    for _, group in rows.groupby("date", sort=True):
        valid = group[[factor, return_column]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(valid) < 100 or valid[factor].nunique() < 10:
            continue
        ranked = valid[factor].rank(method="first", pct=True)
        valid = valid.copy()
        valid["decile"] = np.ceil(ranked * 10).clip(1, 10).astype(int)
        pieces.append(valid)
    if not pieces:
        return {"groups": [], "monotonicity": None, "top_bottom_spread": None}
    pooled = pd.concat(pieces, ignore_index=True)
    grouped = pooled.groupby("decile")[return_column].agg(["count", "mean", "median"])
    groups = [
        {
            "decile": int(index),
            "count": int(row["count"]),
            "mean_return": float(row["mean"]),
            "median_return": float(row["median"]),
        }
        for index, row in grouped.iterrows()
    ]
    means = grouped["mean"].reindex(range(1, 11))
    monotonicity = means.rank(method="average").corr(
        pd.Series(range(1, 11), index=range(1, 11), dtype="float64").rank(method="average")
    )
    spread = means.loc[10] - means.loc[1] if 10 in means.index and 1 in means.index else None
    return {
        "groups": groups,
        "monotonicity": float(monotonicity) if pd.notna(monotonicity) else None,
        "top_bottom_spread": float(spread) if pd.notna(spread) else None,
    }


def _max_drawdown(returns: pd.Series) -> float | None:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return None
    nav = (1.0 + clean).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    return float(drawdown.min())


def _topn_summary(
    rows: pd.DataFrame,
    factor: str,
    return_column: str,
    top_n: int,
    *,
    one_way_cost: float,
    benchmark_rows: pd.DataFrame | None = None,
) -> dict[str, object]:
    events: list[dict[str, object]] = []
    round_trip = one_way_cost * 2.0
    benchmark_frame = rows if benchmark_rows is None else benchmark_rows
    benchmark_by_date = (
        benchmark_frame.groupby("date")[return_column]
        .apply(lambda values: pd.to_numeric(values, errors="coerce").mean())
        .to_dict()
    )
    for signal_date, group in rows.groupby("date", sort=True):
        valid = group.dropna(subset=[factor, return_column]).sort_values(factor, ascending=False)
        selected = valid.head(top_n)
        if selected.empty:
            continue
        raw_return = float(pd.to_numeric(selected[return_column], errors="coerce").mean())
        benchmark_value = benchmark_by_date.get(signal_date)
        benchmark = float(benchmark_value) if benchmark_value is not None and pd.notna(benchmark_value) else 0.0
        events.append(
            {
                "date": str(signal_date),
                "stocks": int(len(selected)),
                "candidate_pool": int(len(valid)),
                "raw_return": raw_return,
                "net_return": raw_return - round_trip,
                "benchmark_return": benchmark,
                "net_excess_return": raw_return - benchmark - round_trip,
                "codes": selected["code6"].astype(str).tolist(),
            }
        )
    event_frame = pd.DataFrame(events)
    if event_frame.empty:
        return {"top_n": top_n, "periods": 0, "events": []}
    periods = len(event_frame)
    net_nav = float((1.0 + event_frame["net_return"]).prod())
    annualized = net_nav ** (12.0 / periods) - 1.0 if net_nav > 0 else -1.0
    return {
        "top_n": int(top_n),
        "periods": int(periods),
        "average_stocks": float(event_frame["stocks"].mean()),
        "raw": _series_summary(event_frame["raw_return"]),
        "net": _series_summary(event_frame["net_return"]),
        "net_excess": _series_summary(event_frame["net_excess_return"]),
        "event_compound_net": net_nav - 1.0,
        "event_annualized_net": annualized,
        "max_drawdown": _max_drawdown(event_frame["net_return"]),
        "events": events,
    }


def evaluate_factor(
    panel: pd.DataFrame,
    factor: str,
    horizon: int,
    *,
    one_way_cost: float = ONE_WAY_COST,
    top_ns: tuple[int, ...] = DEFAULT_TOP_N,
) -> dict[str, object]:
    return_column = f"fwd{horizon}"
    valid_column = f"label_valid{horizon}"
    rows = panel[panel["financial_valid"].fillna(False)].copy()
    if valid_column in rows:
        rows = rows[rows[valid_column].fillna(False)]
    rows = rows.dropna(subset=[factor, return_column])
    return {
        "factor": factor,
        "horizon": int(horizon),
        "rows": int(len(rows)),
        "dates": int(rows["date"].nunique()) if len(rows) else 0,
        "ic": _ic_summary(rows, factor, return_column),
        "deciles": _decile_summary(rows, factor, return_column),
        "top_n": {
            str(top_n): _topn_summary(rows, factor, return_column, top_n, one_way_cost=one_way_cost)
            for top_n in top_ns
        },
    }


def evaluate_gated_factor(
    panel: pd.DataFrame,
    factor: str,
    horizon: int,
    eligibility_column: str,
    *,
    one_way_cost: float = ONE_WAY_COST,
    top_ns: tuple[int, ...] = DEFAULT_TOP_N,
) -> dict[str, object]:
    """Evaluate a factor inside a point-in-time gate against the full base universe.

    The gate controls which stocks may be selected.  It never alters the
    stock score itself, and the benchmark remains the financially valid
    universe for the same signal date.
    """

    return_column = f"fwd{horizon}"
    valid_column = f"label_valid{horizon}"
    base = panel[panel["financial_valid"].fillna(False)].copy()
    if valid_column in base:
        base = base[base[valid_column].fillna(False)]
    base = base.dropna(subset=[return_column])
    if eligibility_column not in base.columns:
        raise ValueError(f"eligibility column not found: {eligibility_column}")
    rows = base[base[eligibility_column].fillna(False).astype(bool)].dropna(subset=[factor, return_column])
    all_dates = int(base["date"].nunique()) if len(base) else 0
    eligible_dates = int(rows["date"].nunique()) if len(rows) else 0
    return {
        "factor": factor,
        "horizon": int(horizon),
        "eligibility": eligibility_column,
        "rows": int(len(rows)),
        "dates": eligible_dates,
        "all_dates": all_dates,
        "no_signal_dates": max(0, all_dates - eligible_dates),
        "ic": _ic_summary(rows, factor, return_column),
        "deciles": _decile_summary(rows, factor, return_column),
        "top_n": {
            str(top_n): _topn_summary(
                rows,
                factor,
                return_column,
                top_n,
                one_way_cost=one_way_cost,
                benchmark_rows=base,
            )
            for top_n in top_ns
        },
    }


def _profile_summary(panel: pd.DataFrame, horizon: int) -> list[dict[str, object]]:
    column = f"fwd{horizon}"
    rows: list[dict[str, object]] = []
    for profile, group in panel[panel["financial_valid"].fillna(False)].groupby("growth_profile"):
        values = pd.to_numeric(group[column], errors="coerce").dropna()
        rows.append({"profile": str(profile), "horizon": horizon, **_series_summary(values)})
    return rows


def evaluate_growth_backtest(
    panel: pd.DataFrame,
    *,
    factors: tuple[str, ...] = DEFAULT_FACTORS,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    one_way_cost: float = ONE_WAY_COST,
    oos_periods: int = 12,
) -> dict[str, object]:
    """Evaluate full, in-sample and trailing out-of-sample windows."""

    if panel.empty:
        raise ValueError("growth backtest panel is empty")
    dates = sorted(panel["date"].dropna().astype(str).unique())
    oos_count = min(max(1, oos_periods), max(1, len(dates) - 1))
    oos_dates = set(dates[-oos_count:])
    windows = {
        "full": panel,
        "in_sample": panel[~panel["date"].isin(oos_dates)],
        "out_of_sample": panel[panel["date"].isin(oos_dates)],
    }
    results: dict[str, object] = {}
    for window_name, rows in windows.items():
        results[window_name] = {
            factor: {
                str(horizon): evaluate_factor(rows, factor, horizon, one_way_cost=one_way_cost)
                for horizon in horizons
            }
            for factor in factors
        }

    profile_results = {
        str(horizon): _profile_summary(panel, horizon) for horizon in horizons
    }
    tested_strategies = len(factors) * len(horizons) * len(DEFAULT_TOP_N)

    def candidate_metrics(factor: str) -> dict[str, object]:
        ins = results["in_sample"][factor]["20"]["top_n"]["10"]
        oos_result = results["out_of_sample"][factor]["20"]
        oos = oos_result["top_n"]["10"]
        return {
            "factor": factor,
            "in_sample_net_excess": (ins.get("net_excess") or {}).get("mean"),
            "out_of_sample_net": (oos.get("net") or {}).get("mean"),
            "out_of_sample_net_excess": (oos.get("net_excess") or {}).get("mean"),
            "out_of_sample_win_rate": (oos.get("net") or {}).get("positive_rate"),
            "out_of_sample_max_drawdown": oos.get("max_drawdown"),
            "out_of_sample_rank_ic": oos_result["ic"].get("rank_ic_mean"),
            "out_of_sample_monotonicity": oos_result["deciles"].get("monotonicity"),
        }

    def robust_score(item: Mapping[str, object]) -> float:
        def number(key: str) -> float:
            value = item.get(key)
            return float(value) if value is not None else -1.0

        return (
            number("out_of_sample_net_excess")
            + number("in_sample_net_excess")
            + 0.25 * number("out_of_sample_rank_ic")
            + 0.02 * number("out_of_sample_monotonicity")
            + 0.005 * (number("out_of_sample_win_rate") - 0.5)
            + 0.10 * number("out_of_sample_max_drawdown")
        )

    baseline_candidates = [candidate_metrics(factor) for factor in BASELINE_FACTORS if factor in factors]
    baseline_qualified = [
        item for item in baseline_candidates
        if float(item.get("in_sample_net_excess") or 0) > 0
        and float(item.get("out_of_sample_net_excess") or 0) > 0
        and float(item.get("out_of_sample_rank_ic") or 0) > 0
        and float(item.get("out_of_sample_monotonicity") or 0) > 0
    ]
    baseline_winner = max(baseline_qualified, key=robust_score) if baseline_qualified else None
    exploratory_candidates = [candidate_metrics(factor) for factor in EXPLORATORY_FACTORS if factor in factors]
    exploratory_qualified = [
        item for item in exploratory_candidates
        if float(item.get("in_sample_net_excess") or 0) > 0
        and float(item.get("out_of_sample_net_excess") or 0) > 0
        and float(item.get("out_of_sample_rank_ic") or 0) > 0
        and float(item.get("out_of_sample_monotonicity") or 0) > 0
    ]
    exploratory_winner = max(exploratory_qualified, key=robust_score) if exploratory_qualified else None
    return {
        "version": GROWTH_BACKTEST_VERSION,
        "updated_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
        "source": "同花顺问财历史财务截面 + 同花顺问财前复权历史行情",
        "window": {
            "start": dates[0],
            "end": dates[-1],
            "signal_dates": len(dates),
            "in_sample_end": sorted(set(dates) - oos_dates)[-1] if set(dates) - oos_dates else None,
            "out_of_sample_start": min(oos_dates),
            "out_of_sample_periods": len(oos_dates),
        },
        "universe": {
            "name": "历史沪深主板非ST，信号日成交额>=5000万元",
            "panel_rows": int(len(panel)),
            "financial_valid_rows": int(panel["financial_valid"].fillna(False).sum()),
            "unique_stocks": int(panel["code6"].nunique()),
        },
        "execution": {
            "signal": "月末收盘后按已披露财报评分",
            "entry": "下一交易日开盘（前复权）",
            "exit": "第5/10/20个交易日收盘（前复权）",
            "one_way_cost": one_way_cost,
            "round_trip_cost": one_way_cost * 2.0,
            "same_day_announcement": "公告日期无时分秒，公告日等于信号日时延后使用",
        },
        "factor_formula": {
            "growth_core": "25%收入增速 + 35%利润增速 + 15%收入加速度 + 15%利润加速度 + 10%最近三期持续性",
            "quality_score": "35%现金流/收入 + 25%现金流/净利润 + 20%ROE + 20%净利率",
            "financial_score": "50%成长核心 + 33.33%成长质量 + 16.67%资产负债质量；历史资讯未入分",
        },
        "research_registry": [
            {
                "factor": factor,
                "stage": "pre_registered_v1" if factor in BASELINE_FACTORS else "exploratory_v2",
                "hypothesis": FACTOR_HYPOTHESES[factor],
            }
            for factor in factors
        ],
        "decision": {
            "formal_baseline": baseline_winner,
            "formal_status": "样本外方向通过但统计显著性不足" if baseline_winner else "既有v1未通过样本外方向门槛",
            "exploratory_candidate": exploratory_winner,
            "exploratory_status": "已使用本轮样本外做选择，必须用新历史区间复核" if exploratory_winner else "探索v2暂无幸存者",
            "execution_candidate": "Top10、持有20日；仅研究候选，不直接生成实盘买入",
        },
        "statistical_hygiene": {
            "factor_hypotheses": len(factors),
            "tested_topn_strategies": tested_strategies,
            "bonferroni_threshold": 0.05 / tested_strategies,
            "ic_p_value": "基于月度RankIC t统计量的正态近似，仅作诊断",
        },
        "limitations": [
            "历史资讯未实现全市场逐时点覆盖，因此不参与本轮回测",
            "问财历史财务值可能包含后续更正，当前无法还原每次更正前版本",
            "历史非ST股票池由各报告期查询锚定，仍可能存在退市样本覆盖不足",
            "月末信号共约36期，样本外仅12期，显著性结论需继续积累",
        ],
        "results": results,
        "profiles": profile_results,
    }


def round_for_json(value: object, digits: int = 8) -> object:
    """Recursively convert NumPy/Pandas values into strict JSON values."""

    if isinstance(value, dict):
        return {str(key): round_for_json(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [round_for_json(item, digits) for item in value]
    if isinstance(value, tuple):
        return [round_for_json(item, digits) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return round(number, digits) if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if value is pd.NA:
        return None
    return value
