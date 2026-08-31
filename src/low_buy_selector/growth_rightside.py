"""Unified growth plus right-side trading factor.

The score is stock-level and stable across market regimes.  Individual trend
structure and the market regime are separate point-in-time execution gates;
they never overwrite the score.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .growth_backtest import (
    DEFAULT_HORIZONS,
    DEFAULT_TOP_N,
    ONE_WAY_COST,
    code6,
    evaluate_gated_factor,
)
from .trend_contract import MARKET_GATE_POSITIVE_R20_MIN, MARKET_GATE_WIDTH_MIN


GROWTH_RIGHTSIDE_VERSION = "growth-rightside-v1"
PRIMARY_FACTOR = "gr_7030"
PREFERRED_SETUPS = ("continuation", "pullback")
WEIGHT_SPECS: dict[str, dict[str, object]] = {
    "growth_gate_only": {
        "growth_weight": 1.00,
        "trend_weight": 0.00,
        "hypothesis": "成长财务分不加技术权重，只使用右侧条件门控",
    },
    "gr_8020": {
        "growth_weight": 0.80,
        "trend_weight": 0.20,
        "hypothesis": "成长为主，趋势只做轻度确认",
    },
    "gr_7030": {
        "growth_weight": 0.70,
        "trend_weight": 0.30,
        "hypothesis": "预登记主公式：成长定方向，右侧趋势决定时点",
    },
    "gr_6040": {
        "growth_weight": 0.60,
        "trend_weight": 0.40,
        "hypothesis": "提高价格趋势权重，检验是否改善持仓效率",
    },
}
LEVELS = {
    "ranking": "unified_rankable",
    "structure": "rightside_structure",
    "trigger": "rightside_trigger",
    "execution": "rightside_tradeable",
}


def _boolean(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False).astype(bool)
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def build_market_gate_table(trend_history: pd.DataFrame) -> pd.DataFrame:
    """Calculate the canonical market gate from the complete trend universe."""

    frame = trend_history.copy()
    frame["date"] = frame["date"].astype(str)
    frame["eligible"] = _boolean(frame["eligible"])
    frame["r20"] = pd.to_numeric(frame["r20"], errors="coerce")
    rows: list[dict[str, object]] = []
    for signal_date, group in frame.groupby("date", sort=True):
        valid_r20 = group["r20"].dropna()
        width = float(group["eligible"].mean()) if len(group) else 0.0
        positive = float((valid_r20 > 0).mean()) if len(valid_r20) else 0.0
        rows.append(
            {
                "date": str(signal_date),
                "market_universe_rows": int(len(group)),
                "market_eligible_count": int(group["eligible"].sum()),
                "market_trend_width": width,
                "market_positive_r20_ratio": positive,
                "market_gate_pass": bool(
                    width >= MARKET_GATE_WIDTH_MIN
                    and positive >= MARKET_GATE_POSITIVE_R20_MIN
                ),
            }
        )
    return pd.DataFrame(rows)


def build_growth_rightside_panel(
    growth_panel: pd.DataFrame,
    trend_history: pd.DataFrame,
) -> pd.DataFrame:
    """Join financial and trend evidence available on the same signal close."""

    growth = growth_panel.copy()
    growth["date"] = growth["date"].astype(str)
    growth["code6"] = growth["code6"].map(code6)
    trend = trend_history.copy()
    trend["date"] = trend["date"].astype(str)
    trend["code6"] = trend["code"].map(code6)
    trend["eligible"] = _boolean(trend["eligible"])
    trend_columns = [
        "date", "code6", "trend_score", "eligible", "setup", "full_alignment",
        "liquid", "r20", "r60", "gap20", "volume_ratio",
    ]
    available_columns = [column for column in trend_columns if column in trend.columns]
    trend_slice = trend[available_columns].drop_duplicates(["date", "code6"], keep="last")
    result = growth.merge(trend_slice, on=["date", "code6"], how="left", validate="one_to_one")
    result = result.merge(build_market_gate_table(trend), on="date", how="left", validate="many_to_one")

    result["trend_score"] = pd.to_numeric(result["trend_score"], errors="coerce")
    result["financial_score"] = pd.to_numeric(result["financial_score"], errors="coerce")
    result["financial_valid"] = _boolean(result["financial_valid"])
    result["eligible"] = _boolean(result["eligible"])
    result["market_gate_pass"] = _boolean(result["market_gate_pass"])
    result["unified_rankable"] = (
        result["financial_valid"]
        & result["financial_score"].notna()
        & result["trend_score"].notna()
    )
    result["rightside_structure"] = result["unified_rankable"] & result["eligible"]
    result["rightside_trigger"] = (
        result["rightside_structure"] & result["setup"].isin(PREFERRED_SETUPS)
    )
    result["rightside_tradeable"] = result["rightside_trigger"] & result["market_gate_pass"]
    for factor, spec in WEIGHT_SPECS.items():
        result[factor] = (
            result["financial_score"] * float(spec["growth_weight"])
            + result["trend_score"] * float(spec["trend_weight"])
        ).where(result["unified_rankable"])
    result["growth_rightside_score"] = result[PRIMARY_FACTOR]
    return result.sort_values(["date", "growth_rightside_score"], ascending=[True, False]).reset_index(drop=True)


def _top10_metrics(result: Mapping[str, object]) -> dict[str, object]:
    top10 = (result.get("top_n") or {}).get("10") or {}
    return {
        "periods": top10.get("periods"),
        "net_return": (top10.get("net") or {}).get("mean"),
        "net_excess": (top10.get("net_excess") or {}).get("mean"),
        "win_rate": (top10.get("net") or {}).get("positive_rate"),
        "max_drawdown": top10.get("max_drawdown"),
        "rank_ic": (result.get("ic") or {}).get("rank_ic_mean"),
        "monotonicity": (result.get("deciles") or {}).get("monotonicity"),
        "rows": result.get("rows"),
        "dates": result.get("dates"),
    }


def _development_score(result: Mapping[str, object]) -> float:
    metrics = _top10_metrics(result)

    def number(key: str, default: float = -1.0) -> float:
        value = metrics.get(key)
        return float(value) if value is not None else default

    return (
        number("net_excess")
        + 0.25 * number("rank_ic", 0.0)
        + 0.01 * number("monotonicity", 0.0)
        + 0.005 * (number("win_rate", 0.0) - 0.5)
        + 0.10 * number("max_drawdown", -1.0)
    )


def evaluate_growth_rightside_backtest(
    panel: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    one_way_cost: float = ONE_WAY_COST,
    confirmation_periods: int = 6,
) -> dict[str, object]:
    """Evaluate registered weights across ranking, structure and trade gates."""

    if panel.empty:
        raise ValueError("growth right-side panel is empty")
    dates = sorted(panel["date"].dropna().astype(str).unique())
    confirm_count = min(max(1, confirmation_periods), max(1, len(dates) - 1))
    confirm_dates = set(dates[-confirm_count:])
    windows = {
        "full": panel,
        "development": panel[~panel["date"].isin(confirm_dates)],
        "confirmation": panel[panel["date"].isin(confirm_dates)],
    }
    results: dict[str, object] = {}
    for window_name, rows in windows.items():
        results[window_name] = {}
        for factor in WEIGHT_SPECS:
            results[window_name][factor] = {}
            for level, gate_column in LEVELS.items():
                results[window_name][factor][level] = {
                    str(horizon): evaluate_gated_factor(
                        rows,
                        factor,
                        horizon,
                        gate_column,
                        one_way_cost=one_way_cost,
                    )
                    for horizon in horizons
                }

    development_primary = results["development"][PRIMARY_FACTOR]["trigger"]
    selected_horizon = max(horizons, key=lambda horizon: _development_score(development_primary[str(horizon)]))
    confirmation = _top10_metrics(
        results["confirmation"][PRIMARY_FACTOR]["trigger"][str(selected_horizon)]
    )
    execution = _top10_metrics(
        results["full"][PRIMARY_FACTOR]["execution"][str(selected_horizon)]
    )
    confirmation_pass = bool(
        float(confirmation.get("net_return") or 0) > 0
        and float(confirmation.get("net_excess") or 0) > 0
        and float(confirmation.get("rank_ic") or 0) > 0
    )
    execution_sample_ok = int(execution.get("periods") or 0) >= 20
    execution_direction_ok = bool(
        float(execution.get("net_return") or 0) > 0
        and float(execution.get("net_excess") or 0) > 0
    )
    posthoc_candidates: list[dict[str, object]] = []
    for factor in WEIGHT_SPECS:
        for horizon in horizons:
            item = _top10_metrics(results["full"][factor]["execution"][str(horizon)])
            posthoc_candidates.append({"factor": factor, "horizon": horizon, **item})
    posthoc_best = max(
        posthoc_candidates,
        key=lambda item: float(item.get("net_excess") or -1.0),
    )

    if confirmation_pass and execution_sample_ok and execution_direction_ok:
        status = "统一因子方向通过；仍需扩展独立历史后才能实盘启用"
    elif not confirmation_pass and not execution_sample_ok:
        status = "确认段未通过且严格市场门控样本不足；不替换成长v1"
    elif not execution_sample_ok:
        status = "统一排序可继续研究；严格市场门控样本不足，不替换成长v1"
    else:
        status = "统一因子未通过确认门槛；不替换成长v1"

    market_dates = panel[["date", "market_gate_pass"]].drop_duplicates("date")
    tested = len(WEIGHT_SPECS) * len(LEVELS) * len(horizons) * len(DEFAULT_TOP_N)
    return {
        "version": GROWTH_RIGHTSIDE_VERSION,
        "updated_at": datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds"),
        "source": "同花顺问财历史财务截面 + 同花顺问财前复权历史趋势截面",
        "window": {
            "start": dates[0],
            "end": dates[-1],
            "signal_dates": len(dates),
            "development_end": sorted(set(dates) - confirm_dates)[-1],
            "confirmation_start": min(confirm_dates),
            "confirmation_periods": len(confirm_dates),
        },
        "universe": {
            "name": "历史沪深主板非ST，信号日成交额>=5000万元",
            "panel_rows": int(len(panel)),
            "unique_stocks": int(panel["code6"].nunique()),
            "trend_coverage": float(panel["trend_score"].notna().mean()),
            "rightside_structure_rows": int(panel["rightside_structure"].sum()),
            "rightside_trigger_rows": int(panel["rightside_trigger"].sum()),
            "strict_tradeable_rows": int(panel["rightside_tradeable"].sum()),
            "market_gate_pass_dates": int(market_dates["market_gate_pass"].sum()),
        },
        "formula": {
            "name": "成长右侧统一因子",
            "score": "70%财务综合分 + 30%趋势强度分",
            "financial_score": "50%成长核心 + 33.33%成长质量 + 16.67%负债质量",
            "individual_gate": "完整多头与流动性结构内，仅健康延续/缩量回踩可交易",
            "market_gate": "趋势宽度>=8% 且 全主板R20为正占比>=50%",
            "score_gate_separation": "门控只决定是否交易，不修改个股统一分",
        },
        "execution": {
            "signal": "月末收盘后确认财务分和右侧结构",
            "entry": "下一交易日开盘（前复权）",
            "exit_horizons": list(horizons),
            "one_way_cost": one_way_cost,
            "round_trip_cost": one_way_cost * 2.0,
        },
        "research_registry": [
            {"factor": factor, **spec} for factor, spec in WEIGHT_SPECS.items()
        ],
        "decision": {
            "active_factor": "financial_score",
            "primary_factor": PRIMARY_FACTOR,
            "replace_existing_growth_factor": False,
            "selected_horizon": selected_horizon,
            "selection_basis": "仅用开发段个股右侧触发层选择5/10/20日持有期；70/30权重预先固定",
            "confirmation": confirmation,
            "strict_execution": execution,
            "strict_execution_sample_ok": execution_sample_ok,
            "posthoc_best_strict_variant": posthoc_best,
            "posthoc_warning": "事后最优仅作诊断；若开发段、IC和单调性不一致，不得采用",
            "status": status,
        },
        "statistical_hygiene": {
            "registered_weight_hypotheses": len(WEIGHT_SPECS),
            "tested_combinations": tested,
            "bonferroni_threshold": 0.05 / tested,
            "confirmation_warning": "确认段仅6个月；严格市场门控有效期更少，不宣称统计显著",
        },
        "limitations": [
            "本轮组合因子属于增长v1之后的探索迭代，历史区间已被前序研究查看",
            "严格市场门控仅在少数月份通过，实际交易样本必须继续积累",
            "历史资讯未纳入统一分，避免资讯覆盖不完整造成样本选择偏差",
            "问财历史财务值可能包含后续更正，无法还原更正前版本",
        ],
        "results": results,
    }


def select_primary_signals(
    panel: pd.DataFrame,
    *,
    horizon: int,
    top_n: int = 10,
) -> pd.DataFrame:
    """Return strict market-gated stock-level signals for audit."""

    rows: list[pd.DataFrame] = []
    for _, group in panel[panel["rightside_tradeable"]].groupby("date", sort=True):
        selected = group.dropna(subset=[PRIMARY_FACTOR, f"fwd{horizon}"]).nlargest(top_n, PRIMARY_FACTOR).copy()
        if not selected.empty:
            rows.append(selected)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def build_stock_effects(signals: pd.DataFrame, *, horizon: int) -> pd.DataFrame:
    """Summarize each stock's own selected-signal history."""

    if signals.empty:
        return pd.DataFrame()
    return_column = f"fwd{horizon}"
    adverse_column = f"mae{horizon}"
    grouped = signals.groupby(["code6", "name"], dropna=False)
    result = grouped.agg(
        signals=("date", "count"),
        first_signal=("date", "min"),
        last_signal=("date", "max"),
        avg_return=(return_column, "mean"),
        median_return=(return_column, "median"),
        avg_adverse=(adverse_column, "mean"),
        last_score=(PRIMARY_FACTOR, "last"),
    ).reset_index()
    wins = grouped[return_column].apply(lambda values: float((pd.to_numeric(values, errors="coerce") > 0).mean()))
    result = result.merge(wins.rename("win_rate").reset_index(), on=["code6", "name"], how="left")
    return result.sort_values(["signals", "avg_return"], ascending=[False, False]).reset_index(drop=True)
