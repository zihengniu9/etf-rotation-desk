"""Dividend-quality factor engine.

The factor is a point-in-time research screen, not a trading signal.  It keeps
valuation, dividend sustainability and cash-flow quality separate so a high
headline yield cannot hide weak dividend coverage.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping

import pandas as pd


DIVIDEND_FACTOR_VERSION = "dividend-quality-v1"
YEARS = (2023, 2024, 2025)
FINANCIAL_KEYWORDS = ("银行", "证券", "保险", "多元金融")


def code6(value: object) -> str:
    match = re.search(r"([0-9]{6})", str(value))
    return match.group(1) if match else str(value or "").strip()


def _first_column(frame: pd.DataFrame, labels: Iterable[str]) -> str | None:
    for label in labels:
        if label in frame.columns:
            return label
        matches = [str(column) for column in frame.columns if label in str(column)]
        if matches:
            return matches[0]
    return None


def _period_column(frame: pd.DataFrame, labels: Iterable[str], year: int) -> str | None:
    year_text = str(year)
    candidates: list[str] = []
    for column in frame.columns:
        text = str(column)
        if year_text in text and any(label in text for label in labels):
            candidates.append(text)
    if not candidates:
        return None
    # Prefer an annual report date over announcement dates embedded in labels.
    annual = [column for column in candidates if f"{year}1231" in column]
    return annual[0] if annual else candidates[0]


def _numeric(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    values = frame[column]
    if values.dtype == "object":
        values = values.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    return pd.to_numeric(values, errors="coerce")


def _text(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series("", index=frame.index, dtype="object")

    def normalize(value: object) -> str:
        if isinstance(value, (list, tuple, set)):
            return " / ".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    return frame[column].map(normalize)


def _industry_text(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series("未分类", index=frame.index, dtype="object")

    def normalize(value: object) -> str:
        if isinstance(value, (list, tuple)):
            parts = [str(item).strip() for item in value if str(item).strip()]
        else:
            parts = [part.strip() for part in re.split(r"[/,;；，]", str(value or "")) if part.strip()]
        # Wencai normally returns 一级 / 二级 / 三级.  The secondary industry
        # is granular enough for neutralization without creating tiny groups.
        return parts[1] if len(parts) >= 2 else (parts[0] if parts else "未分类")

    return frame[column].map(normalize)


def normalize_dividend_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a Wencai dividend response without inventing missing fields."""

    if frame.empty:
        return pd.DataFrame(columns=["code6", "name"])
    code_column = _first_column(frame, ("股票代码", "证券代码", "code"))
    if code_column is None:
        raise ValueError("dividend snapshot must contain 股票代码 or code")

    result = pd.DataFrame(index=frame.index)
    result["code6"] = frame[code_column].map(code6)
    result["name"] = _text(frame, _first_column(frame, ("股票简称", "股票名称", "name")))
    result["market_type"] = _text(frame, _first_column(frame, ("上市板块", "股票市场类型", "市场类型")))
    result["industry"] = _industry_text(frame, _first_column(frame, ("所属同花顺行业", "所属行业", "行业")))
    result["latest_price"] = _numeric(frame, _first_column(frame, ("最新价", "收盘价")))
    result["latest_change"] = _numeric(frame, _first_column(frame, ("最新涨跌幅", "涨跌幅")))
    result["market_cap"] = _numeric(frame, _first_column(frame, ("总市值", "A股市值", "流通市值")))
    result["dividend_yield"] = _numeric(frame, _first_column(frame, ("股息率", "股息率TTM")))
    result["pe_ttm"] = _numeric(frame, _first_column(frame, ("市盈率(pe,ttm)", "市盈率TTM", "市盈率")))
    result["pb"] = _numeric(frame, _first_column(frame, ("市净率(pb)", "市净率")))

    dividend_labels = ("现金分红总额", "分红金额", "分红总额", "派现总额")
    cash_labels = ("经营活动产生的现金流量净额", "经营活动现金流量净额")
    profit_labels = ("归属于母公司股东的净利润", "归属母公司股东的净利润", "归母净利润")
    for year in YEARS:
        result[f"dividend_{year}"] = _numeric(frame, _period_column(frame, dividend_labels, year))
        result[f"cfo_{year}"] = _numeric(frame, _period_column(frame, cash_labels, year))
        result[f"profit_{year}"] = _numeric(frame, _period_column(frame, profit_labels, year))

    result = result.drop_duplicates("code6", keep="last")
    result = result[~result["name"].str.contains(r"ST|退", case=False, regex=True, na=False)]
    result = result[~result["industry"].str.contains("|".join(FINANCIAL_KEYWORDS), regex=True, na=False)]
    return result.reset_index(drop=True)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = pd.to_numeric(denominator, errors="coerce")
    numerator = pd.to_numeric(numerator, errors="coerce")
    return (numerator / denominator).where(denominator.ne(0))


def _row_stability(frame: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    values = frame[list(columns)].apply(pd.to_numeric, errors="coerce")
    mean = values.mean(axis=1)
    coefficient = values.std(axis=1, ddof=0) / mean.abs().replace(0, float("nan"))
    return (1.0 - coefficient).clip(lower=0.0, upper=1.0).where(values.notna().sum(axis=1) >= 3)


def _percentile(values: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if not higher_is_better:
        numeric = -numeric
    return numeric.rank(method="average", pct=True) * 100.0


def _sector_percentile(frame: pd.DataFrame, column: str, *, higher_is_better: bool = True) -> pd.Series:
    global_score = _percentile(frame[column], higher_is_better=higher_is_better)
    sector_source = pd.to_numeric(frame[column], errors="coerce")
    if not higher_is_better:
        sector_source = -sector_source
    sector_score = sector_source.groupby(frame["industry"], dropna=False).rank(method="average", pct=True) * 100.0
    sector_count = frame.groupby("industry", dropna=False)["code6"].transform("count")
    return global_score.where(sector_count.lt(5), global_score * 0.40 + sector_score * 0.60)


def _weighted_available(frame: pd.DataFrame, components: Mapping[str, float]) -> pd.Series:
    weighted = pd.Series(0.0, index=frame.index)
    available_weight = pd.Series(0.0, index=frame.index)
    for column, weight in components.items():
        values = pd.to_numeric(frame[column], errors="coerce")
        available = values.notna()
        weighted += values.fillna(0.0) * weight
        available_weight += available.astype(float) * weight
    return (weighted / available_weight).where(available_weight.gt(0))


def _payout_safety(payout: pd.Series) -> pd.Series:
    values = pd.to_numeric(payout, errors="coerce")
    score = pd.Series(float("nan"), index=values.index)
    score.loc[values.gt(0) & values.le(0.70)] = 100.0
    mid = values.gt(0.70) & values.le(0.85)
    score.loc[mid] = 100.0 - (values.loc[mid] - 0.70) / 0.15 * 50.0
    high = values.gt(0.85) & values.le(1.20)
    score.loc[high] = 50.0 - (values.loc[high] - 0.85) / 0.35 * 50.0
    score.loc[values.gt(1.20) | values.le(0)] = 0.0
    return score.clip(0, 100)


def build_dividend_factors(frame: pd.DataFrame) -> pd.DataFrame:
    """Build DQC scores for the non-financial A-share cross-section."""

    result = normalize_dividend_snapshot(frame)
    if result.empty:
        return result

    dividend_columns = [f"dividend_{year}" for year in YEARS]
    cfo_columns = [f"cfo_{year}" for year in YEARS]
    profit_columns = [f"profit_{year}" for year in YEARS]
    result["financial_valid"] = (
        result[dividend_columns].gt(0).all(axis=1)
        & result[cfo_columns].gt(0).all(axis=1)
        & result[profit_columns].gt(0).all(axis=1)
        & result["dividend_yield"].gt(0)
        & result["pe_ttm"].gt(0)
        & result["pb"].gt(0)
    )

    result["earnings_yield"] = _safe_ratio(pd.Series(1.0, index=result.index), result["pe_ttm"])
    result["book_yield"] = _safe_ratio(pd.Series(1.0, index=result.index), result["pb"])
    for year in YEARS:
        result[f"payout_{year}"] = _safe_ratio(result[f"dividend_{year}"], result[f"profit_{year}"])
        result[f"cash_conversion_{year}"] = _safe_ratio(result[f"cfo_{year}"], result[f"profit_{year}"])
        result[f"cash_coverage_{year}"] = _safe_ratio(result[f"cfo_{year}"], result[f"dividend_{year}"])

    result["average_payout"] = result[[f"payout_{year}" for year in YEARS]].median(axis=1)
    result["cash_conversion"] = result[[f"cash_conversion_{year}" for year in YEARS]].median(axis=1)
    result["cash_coverage"] = result[[f"cash_coverage_{year}" for year in YEARS]].median(axis=1)
    result["dividend_stability"] = _row_stability(result, dividend_columns)
    result["cfo_stability"] = _row_stability(result, cfo_columns)
    result["profit_stability"] = _row_stability(result, profit_columns)
    result["dividend_cagr"] = (
        (result["dividend_2025"] / result["dividend_2023"]).pow(0.5) - 1.0
    ).where(result["dividend_2023"].gt(0) & result["dividend_2025"].gt(0))

    rank_columns = {
        "earnings_yield_score": "earnings_yield",
        "book_yield_score": "book_yield",
        "yield_score": "dividend_yield",
        "dividend_stability_score": "dividend_stability",
        "dividend_cagr_score": "dividend_cagr",
        "cash_conversion_score": "cash_conversion",
        "cfo_stability_score": "cfo_stability",
        "cash_coverage_score": "cash_coverage",
        "profit_stability_score": "profit_stability",
    }
    for score_column, raw_column in rank_columns.items():
        result[score_column] = _sector_percentile(result, raw_column)
    result["payout_safety_score"] = _payout_safety(result["average_payout"])

    result["valuation_score"] = _weighted_available(
        result, {"earnings_yield_score": 0.60, "book_yield_score": 0.40}
    )
    result["dividend_score"] = _weighted_available(
        result,
        {
            "yield_score": 0.45,
            "payout_safety_score": 0.20,
            "dividend_stability_score": 0.20,
            "dividend_cagr_score": 0.15,
        },
    )
    result["cashflow_score"] = _weighted_available(
        result,
        {
            "cash_conversion_score": 0.35,
            "cfo_stability_score": 0.25,
            "cash_coverage_score": 0.20,
            "profit_stability_score": 0.20,
        },
    )
    result["dqc_score"] = _weighted_available(
        result, {"valuation_score": 0.30, "dividend_score": 0.35, "cashflow_score": 0.35}
    )

    result["dividend_drop_flag"] = (
        result["dividend_2025"] < result["dividend_2023"] * 0.80
    ).fillna(False)
    result["profit_drop_flag"] = (
        result["profit_2025"] < result["profit_2023"] * 0.80
    ).fillna(False)
    result["high_payout_flag"] = result["average_payout"].gt(0.85).fillna(False)
    result["weak_cash_flag"] = result["cash_conversion"].lt(0.80).fillna(False)
    flag_columns = ["dividend_drop_flag", "profit_drop_flag", "high_payout_flag", "weak_cash_flag"]
    result["risk_flag_count"] = result[flag_columns].sum(axis=1)

    result["factor_coverage"] = result[
        ["dividend_yield", "pe_ttm", "pb", *dividend_columns, *cfo_columns, *profit_columns]
    ].notna().mean(axis=1)
    result["factor_status"] = "有效"
    result.loc[~result["financial_valid"], "factor_status"] = "基础数据不足"
    result.loc[result["financial_valid"] & result["factor_coverage"].lt(0.90), "factor_status"] = "字段覆盖不足"
    result.loc[~result["financial_valid"], "dqc_score"] = float("nan")

    result["research_status"] = "普通观察"
    result.loc[result["risk_flag_count"].ge(2), "research_status"] = "价值陷阱复核"
    result.loc[
        result["dqc_score"].ge(65) & result["risk_flag_count"].le(1), "research_status"
    ] = "稳健观察"
    result.loc[
        result["dqc_score"].ge(75)
        & result["risk_flag_count"].eq(0)
        & result["dividend_yield"].ge(2.5),
        "research_status",
    ] = "红利质量优先"
    return result.sort_values(["dqc_score", "dividend_yield"], ascending=[False, False]).reset_index(drop=True)


def _safe_json_number(value: object, digits: int = 4) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return round(parsed, digits)


def _candidate_record(row: pd.Series, rank: int) -> dict[str, object]:
    flag_labels = {
        "dividend_drop_flag": "三年分红下降超过20%",
        "profit_drop_flag": "三年利润下降超过20%",
        "high_payout_flag": "派息率超过85%",
        "weak_cash_flag": "经营现金/利润中位数低于0.8",
    }
    flags = [label for column, label in flag_labels.items() if bool(row.get(column))]
    return {
        "rank": rank,
        "code": str(row.get("code6") or ""),
        "name": str(row.get("name") or ""),
        "industry": str(row.get("industry") or "未分类"),
        "market_type": str(row.get("market_type") or ""),
        "latest_price": _safe_json_number(row.get("latest_price"), 2),
        "latest_change": _safe_json_number(row.get("latest_change"), 2),
        "market_cap": _safe_json_number(row.get("market_cap"), 2),
        "score": _safe_json_number(row.get("dqc_score"), 2),
        "valuation_score": _safe_json_number(row.get("valuation_score"), 2),
        "dividend_score": _safe_json_number(row.get("dividend_score"), 2),
        "cashflow_score": _safe_json_number(row.get("cashflow_score"), 2),
        "dividend_yield": _safe_json_number(row.get("dividend_yield"), 2),
        "pe_ttm": _safe_json_number(row.get("pe_ttm"), 2),
        "pb": _safe_json_number(row.get("pb"), 2),
        "average_payout": _safe_json_number(row.get("average_payout"), 4),
        "cash_conversion": _safe_json_number(row.get("cash_conversion"), 2),
        "cash_coverage": _safe_json_number(row.get("cash_coverage"), 2),
        "dividend_stability": _safe_json_number(row.get("dividend_stability"), 3),
        "dividend_cagr": _safe_json_number(row.get("dividend_cagr"), 4),
        "factor_coverage": _safe_json_number(row.get("factor_coverage"), 3),
        "status": str(row.get("research_status") or "普通观察"),
        "risk_flags": flags,
    }


def build_dividend_snapshot(
    frame: pd.DataFrame,
    *,
    as_of: str,
    source: str,
    query: str,
    matched_count: int | None = None,
    top: int = 30,
    max_per_industry: int = 2,
) -> tuple[dict[str, object], pd.DataFrame]:
    """Return the dashboard snapshot and full scored cross-section."""

    scored = build_dividend_factors(frame)
    valid = scored[scored["factor_status"].eq("有效") & scored["dqc_score"].notna()].copy()
    selected_rows: list[pd.Series] = []
    industry_counts: dict[str, int] = {}
    for _, row in valid.iterrows():
        industry = str(row.get("industry") or "未分类")
        if industry_counts.get(industry, 0) >= max_per_industry:
            continue
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        selected_rows.append(row)
        if len(selected_rows) >= top:
            break

    candidates = [_candidate_record(row, rank) for rank, row in enumerate(selected_rows, start=1)]
    raw_top = [_candidate_record(row, rank) for rank, (_, row) in enumerate(valid.head(10).iterrows(), start=1)]
    top_industries = []
    if not valid.empty:
        counts = valid["industry"].replace("", "未分类").value_counts().head(8)
        top_industries = [
            {"industry": str(industry), "count": int(count), "share": round(count / len(valid), 4)}
            for industry, count in counts.items()
        ]

    snapshot: dict[str, object] = {
        "version": DIVIDEND_FACTOR_VERSION,
        "data_as_of": as_of,
        "source": source,
        "universe": {
            "definition": "沪深A股非ST、非金融、上市满3年；近3年分红、经营现金流和归母净利润均为正",
            "matched": int(matched_count if matched_count is not None else len(frame)),
            "normalized": int(len(scored)),
            "valid": int(len(valid)),
            "financials_excluded": True,
            "annual_periods": list(YEARS),
            "industry_cap": max_per_industry,
        },
        "formula": {
            "total": "DQC = 30%估值 + 35%分红 + 35%现金流质量",
            "valuation": "60%盈利收益率(E/P) + 40%账面收益率(B/P)",
            "dividend": "45%股息率 + 20%派息安全 + 20%分红稳定 + 15%分红增长",
            "cashflow": "35%现金利润匹配 + 25%现金流稳定 + 20%现金覆盖分红 + 20%利润稳定",
            "neutralization": "单项排名 = 40%全市场分位 + 60%同行业分位（行业样本不足5只时仅用全市场）",
        },
        "gates": {
            "priority": "DQC≥75、股息率≥2.5%、无风险旗标",
            "watch": "DQC≥65、风险旗标不超过1项",
            "value_trap": "风险旗标达到2项：分红下降、利润下降、高派息或现金利润不匹配",
            "note": "这是当前截面研究排序，不代表买入触发；需等待历史回测和价格侧触发验证。",
        },
        "validation": {
            "current_cross_section": True,
            "panda_backtest": "pending_parameter_confirmation",
            "backtest_claim_allowed": False,
        },
        "industry_distribution": top_industries,
        "raw_top": raw_top,
        "candidates": candidates,
        "query": query,
    }
    return snapshot, scored
