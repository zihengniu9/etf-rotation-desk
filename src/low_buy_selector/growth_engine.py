"""Growth-factor research engine.

The engine deliberately separates reported growth from the evidence that may
explain or challenge that growth.  Financial fields are point-in-time inputs;
news is an evidence layer and never replaces the financial score.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date

import pandas as pd


GROWTH_FACTOR_VERSION = "growth-factor-v1"
MAIN_BOARD_PREFIXES = ("000", "001", "002", "003", "600", "601", "603", "605")
MIN_MARKET_CAP = 5_000_000_000.0

POSITIVE_NEWS_GROUPS: dict[str, tuple[str, ...]] = {
    "业绩兑现": ("业绩预增", "利润预增", "净利润同比", "营收同比", "营收净利双增", "年报", "中报", "半年报", "一季报", "三季报"),
    "需求订单": ("订单", "中标", "签约", "合同", "客户"),
    "产能产品": ("扩产", "产能", "投产", "放量", "量产", "产品获批", "新品", "送样", "认证"),
    "研发技术": ("研发投入", "研发费用", "技术突破", "专利", "技术迭代", "高端产品"),
    "行业景气": ("涨价", "价格上涨", "量价齐升", "景气度", "供需改善", "市场份额"),
    "战略拓展": ("出海", "海外订单", "海外市场", "战略合作", "市场拓展", "资产注入", "回购", "股权激励"),
}

NEGATIVE_NEWS_GROUPS: dict[str, tuple[str, ...]] = {
    "业绩风险": ("业绩下滑", "亏损", "不及预期", "预亏", "下降", "减值"),
    "现金与负债": ("现金流压力", "现金流减少", "高负债", "债务", "偿债"),
    "治理监管": ("减持", "处罚", "监管", "问询", "诉讼", "立案", "警示"),
    "扩张不确定": ("终止", "延期", "暂停", "尚未确定", "不确定性", "套现"),
    "经营质量": ("应收账款", "存货", "关联销售", "商誉", "客户集中", "单一产品"),
}


def code6(value: object) -> str:
    """Normalize a vendor code to the six-digit A-share code."""

    match = re.search(r"([0-9]{6})", str(value))
    return match.group(1) if match else str(value).strip().upper()


def is_main_board_name(code: object, name: object = "") -> bool:
    """Return whether a row belongs to the project's default main-board pool."""

    normalized = code6(code)
    label = str(name or "")
    return normalized.startswith(MAIN_BOARD_PREFIXES) and not re.search(r"ST|退", label, re.IGNORECASE)


def _first_column(frame: pd.DataFrame, labels: Iterable[str], period: str | None = None) -> str | None:
    for label in labels:
        if label in frame.columns:
            return label
        prefix = f"{label}["
        matches = [str(column) for column in frame.columns if str(column).startswith(prefix)]
        if period:
            exact = [column for column in matches if f"[{period}]" in column]
            if exact:
                return exact[0]
        if matches:
            return matches[0]
    return None


def _series(frame: pd.DataFrame, labels: Iterable[str], period: str | None = None) -> pd.Series:
    column = _first_column(frame, labels, period)
    if column is None:
        return pd.Series(pd.NA, index=frame.index, dtype="object")
    return frame[column]


def normalize_finance_snapshot(frame: pd.DataFrame, *, period: str | None, prefix: str) -> pd.DataFrame:
    """Normalize one Wencai financial response without filling missing values."""

    if frame.empty:
        return pd.DataFrame(columns=["code6"])
    code_column = _first_column(frame, ("股票代码", "code"))
    name_column = _first_column(frame, ("股票简称", "name"))
    if code_column is None:
        raise ValueError("financial snapshot must contain 股票代码 or code")

    result = pd.DataFrame(index=frame.index)
    result["code6"] = frame[code_column].map(code6)
    result["name"] = frame[name_column].astype(str) if name_column else ""
    result[f"{prefix}_revenue_growth"] = _series(
        frame, ("营业收入同比增长率", "营业收入(同比增长率)", "revenue_growth"), period
    )
    result[f"{prefix}_profit_growth"] = _series(
        frame, (
            "归母净利润同比增长率", "归属母公司股东的净利润同比增长率",
            "归属于母公司所有者的净利润同比增长率", "profit_growth",
        ), period
    )
    result[f"{prefix}_cash_flow"] = _series(
        frame, ("经营活动产生的现金流量净额", "经营活动现金流量净额", "cash_flow"), period
    )
    result[f"{prefix}_roe"] = _series(
        frame, ("净资产收益率", "净资产收益率roe(加权,公布值)", "加权净资产收益率", "roe"), period
    )
    result[f"{prefix}_net_margin"] = _series(frame, ("销售净利率", "净利率", "net_margin"), period)
    result[f"{prefix}_debt_ratio"] = _series(frame, ("资产负债率", "debt_ratio"), period)
    result[f"{prefix}_revenue"] = _series(frame, ("营业收入", "revenue"), period)
    result[f"{prefix}_net_profit"] = _series(
        frame, ("归母净利润", "归属母公司股东的净利润", "归属于母公司所有者的净利润", "net_profit"), period
    )

    if prefix == "current":
        result["vendor_code"] = frame[code_column].astype(str)
        result["latest_price"] = _series(frame, ("最新价", "收盘价:不复权", "latest_price"))
        result["latest_change"] = _series(frame, ("最新涨跌幅", "涨跌幅:前复权", "latest_change"))
        result["market_cap"] = _series(frame, ("总市值", "a股流通市值", "market_cap"))
        result["pe"] = _series(frame, ("动态市盈率", "市盈率(pe)", "市盈率", "pe"))
        result["market_type"] = _series(frame, ("股票市场类型", "market_type"))

    numeric_columns = [column for column in result.columns if column not in {"code6", "name", "vendor_code", "market_type"}]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.drop_duplicates("code6", keep="last").reset_index(drop=True)


def _rank_score(values: pd.Series, *, low: float | None = None, high: float | None = None) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if low is not None or high is not None:
        numeric = numeric.clip(lower=low, upper=high)
    return numeric.rank(pct=True) * 100.0


def _weighted_available(frame: pd.DataFrame, components: Mapping[str, float]) -> pd.Series:
    total = pd.Series(0.0, index=frame.index)
    weighted = pd.Series(0.0, index=frame.index)
    weight_sum = float(sum(components.values()))
    for column, weight in components.items():
        values = pd.to_numeric(frame[column], errors="coerce")
        available = values.notna()
        weighted = weighted.add(values.fillna(0.0) * weight, fill_value=0.0)
        total = total.add(available.astype(float) * weight, fill_value=0.0)
    return (weighted / total * weight_sum).where(total > 0)


def _positive_count(frame: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    parts = []
    for column in columns:
        parts.append(pd.to_numeric(frame[column], errors="coerce").gt(0).astype(float))
    return sum(parts, pd.Series(0.0, index=frame.index))


def build_finance_factors(
    current: pd.DataFrame,
    annual_2025: pd.DataFrame,
    annual_2024: pd.DataFrame,
) -> pd.DataFrame:
    """Build a main-board cross-section from current and two annual snapshots."""

    current_n = normalize_finance_snapshot(current, period="20260630", prefix="current")
    fy25 = normalize_finance_snapshot(annual_2025, period="20251231", prefix="fy25")
    fy24 = normalize_finance_snapshot(annual_2024, period="20241231", prefix="fy24")
    result = current_n.merge(fy25.drop(columns=["name"], errors="ignore"), on="code6", how="left")
    result = result.merge(fy24.drop(columns=["name"], errors="ignore"), on="code6", how="left")
    result["name"] = result["name"].replace("nan", "").fillna("")
    result = result[result.apply(lambda row: is_main_board_name(row["code6"], row["name"]), axis=1)].copy()
    # A 50亿元 floor keeps tiny shell-like names and extreme low-base cases
    # from dominating a growth study.  It is an explicit universe rule, not a
    # hidden ranking preference; missing market cap therefore removes a row.
    result["market_cap"] = pd.to_numeric(result["market_cap"], errors="coerce")
    result = result[result["market_cap"].ge(MIN_MARKET_CAP)].copy()

    current_revenue = pd.to_numeric(result["current_revenue"], errors="coerce")
    current_profit = pd.to_numeric(result["current_net_profit"], errors="coerce")
    current_cash = pd.to_numeric(result["current_cash_flow"], errors="coerce")
    result["cash_to_profit"] = (current_cash / current_profit).where(current_profit.ne(0))
    result["cash_margin"] = (current_cash / current_revenue).where(current_revenue.ne(0))
    result["revenue_acceleration"] = result["current_revenue_growth"] - result["fy25_revenue_growth"]
    result["profit_acceleration"] = result["current_profit_growth"] - result["fy25_profit_growth"]
    result["revenue_positive_periods"] = _positive_count(
        result, ("fy24_revenue_growth", "fy25_revenue_growth", "current_revenue_growth")
    )
    result["profit_positive_periods"] = _positive_count(
        result, ("fy24_profit_growth", "fy25_profit_growth", "current_profit_growth")
    )
    result["persistence_score"] = (
        result["revenue_positive_periods"] / 3.0 * 50.0
        + result["profit_positive_periods"] / 3.0 * 50.0
    ).where(
        result[["fy24_revenue_growth", "fy25_revenue_growth", "current_revenue_growth", "fy24_profit_growth", "fy25_profit_growth", "current_profit_growth"]].notna().any(axis=1)
    )

    result["rev_growth_score"] = _rank_score(result["current_revenue_growth"], low=-50, high=200)
    result["profit_growth_score"] = _rank_score(result["current_profit_growth"], low=-80, high=500)
    result["rev_acceleration_score"] = _rank_score(result["revenue_acceleration"], low=-100, high=150)
    result["profit_acceleration_score"] = _rank_score(result["profit_acceleration"], low=-300, high=500)
    result["growth_core"] = _weighted_available(
        result,
        {
            "rev_growth_score": 0.25,
            "profit_growth_score": 0.35,
            "rev_acceleration_score": 0.15,
            "profit_acceleration_score": 0.15,
            "persistence_score": 0.10,
        },
    )

    result["cash_margin_score"] = _rank_score(result["cash_margin"], low=-0.5, high=1.0)
    result["cash_to_profit_score"] = _rank_score(result["cash_to_profit"], low=-1.0, high=3.0)
    result["roe_score"] = _rank_score(result["current_roe"], low=-5, high=30)
    result["net_margin_score"] = _rank_score(result["current_net_margin"], low=-20, high=60)
    result["quality_score"] = _weighted_available(
        result,
        {"cash_margin_score": 0.35, "cash_to_profit_score": 0.25, "roe_score": 0.20, "net_margin_score": 0.20},
    )

    debt = pd.to_numeric(result["current_debt_ratio"], errors="coerce")
    result["balance_score"] = (100.0 - debt.clip(lower=0, upper=100)).where(debt.notna())
    result["valuation_score"] = 100.0 - _rank_score(result["pe"].where(result["pe"] > 0), low=0, high=200)

    result["financial_valid"] = (
        result["current_revenue"].gt(0)
        & result["current_net_profit"].gt(0)
        & result["current_revenue_growth"].notna()
        & result["current_profit_growth"].notna()
    )
    result["low_base_flag"] = (
        result["current_profit_growth"].gt(200)
        | result["fy25_profit_growth"].gt(200)
        | result["fy24_net_profit"].le(0)
        | result["fy25_net_profit"].le(0)
    ).fillna(False)
    result["cash_mismatch_flag"] = (result["current_cash_flow"].lt(0) | result["cash_to_profit"].lt(0)).fillna(False)
    result["high_debt_flag"] = result["current_debt_ratio"].gt(70).fillna(False)

    result["growth_profile"] = "增速观察"
    persistent = (
        result["current_revenue_growth"].gt(0)
        & result["fy25_revenue_growth"].gt(0)
        & result["fy24_revenue_growth"].gt(0)
        & result["current_profit_growth"].gt(0)
        & result["fy25_profit_growth"].gt(0)
        & result["fy24_profit_growth"].gt(0)
    )
    result.loc[persistent, "growth_profile"] = "持续成长"
    acceleration = (
        result["current_profit_growth"].gt(result["fy25_profit_growth"] + 10)
        & result["current_revenue_growth"].gt(0)
        & result["current_net_profit"].gt(0)
    )
    result.loc[acceleration & ~persistent, "growth_profile"] = "加速成长"
    reversal = result["low_base_flag"] & ~persistent
    result.loc[reversal, "growth_profile"] = "反转/低基数"

    raw_core_fields = [
        "current_revenue_growth", "current_profit_growth", "current_cash_flow",
        "current_roe", "current_net_margin", "current_debt_ratio",
        "fy25_revenue_growth", "fy25_profit_growth", "fy24_revenue_growth", "fy24_profit_growth",
    ]
    result["factor_coverage"] = result[raw_core_fields].notna().sum(axis=1) / len(raw_core_fields)
    result["factor_status"] = "有效"
    result.loc[~result["financial_valid"], "factor_status"] = "基础数据不足"
    result.loc[result["financial_valid"] & (result["factor_coverage"] < 0.70), "factor_status"] = "字段覆盖不足"
    return result.reset_index(drop=True)


def _normalized_title(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _keyword_groups(text: str, groups: Mapping[str, tuple[str, ...]]) -> list[str]:
    return [name for name, keywords in groups.items() if any(keyword in text for keyword in keywords)]


def score_news_records(records: Iterable[Mapping[str, object]], *, as_of: str | date | None = None) -> dict[str, object]:
    """Score historical news as evidence, excluding records published after as_of."""

    cutoff = pd.Timestamp(as_of).normalize() if as_of else None
    unique: list[dict[str, object]] = []
    seen_titles: set[str] = set()
    future_excluded = 0
    for record in records:
        published = pd.to_datetime(record.get("publish_date") or record.get("publish_time"), errors="coerce")
        if pd.isna(published):
            continue
        published = pd.Timestamp(published).tz_localize(None) if getattr(published, "tzinfo", None) else pd.Timestamp(published)
        if cutoff is not None and published.normalize() > cutoff:
            future_excluded += 1
            continue
        title = str(record.get("title") or "").strip()
        summary = str(record.get("summary") or record.get("source_original") or "").strip()
        normalized = _normalized_title(title)
        if not normalized or normalized in seen_titles:
            continue
        seen_titles.add(normalized)
        text = f"{title} {summary}"
        soft_article = bool(re.search(r"分析|解读|研报|预测|涨停|深度", title))
        unique.append(
            {
                "title": title,
                "summary": summary,
                "url": str(record.get("url") or ""),
                "publish_date": published.strftime("%Y-%m-%d"),
                "positive_groups": _keyword_groups(text, POSITIVE_NEWS_GROUPS),
                "negative_groups": _keyword_groups(text, NEGATIVE_NEWS_GROUPS),
                "article_weight": 0.35 if soft_article else 1.0,
            }
        )

    total = len(unique)
    positive = [item for item in unique if item["positive_groups"]]
    negative = [item for item in unique if item["negative_groups"]]
    positive_groups = {group for item in positive for group in item["positive_groups"]}
    negative_groups = {group for item in negative for group in item["negative_groups"]}
    if total:
        recency_values = []
        today = cutoff or pd.Timestamp(date.today())
        for item in unique:
            age = max(0, (today - pd.Timestamp(item["publish_date"])).days)
            recency_values.append(1.0 / (1.0 + age / 180.0))
        recency = sum(recency_values) / len(recency_values)
    else:
        recency = 0.0
    total_weight = sum(float(item["article_weight"]) for item in unique)
    positive_weight = sum(float(item["article_weight"]) for item in positive)
    negative_weight = sum(float(item["article_weight"]) for item in negative)
    positive_ratio = positive_weight / total_weight if total_weight else 0.0
    negative_ratio = negative_weight / total_weight if total_weight else 0.0
    catalyst_score = min(100.0, positive_ratio * 55.0 + len(positive_groups) / len(POSITIVE_NEWS_GROUPS) * 30.0 + recency * 15.0)
    risk_penalty = min(100.0, negative_ratio * 65.0 + len(negative_groups) / len(NEGATIVE_NEWS_GROUPS) * 35.0)
    news_score = max(0.0, min(100.0, 50.0 + catalyst_score * 0.50 - risk_penalty * 0.50)) if total else None
    return {
        "news_status": "已查询" if total else "已查询但无可用记录",
        "news_count": total,
        "positive_articles": len(positive),
        "negative_articles": len(negative),
        "positive_groups": sorted(positive_groups),
        "negative_groups": sorted(negative_groups),
        "catalyst_score": round(catalyst_score, 2),
        "risk_penalty": round(risk_penalty, 2),
        "news_score": round(news_score, 2) if news_score is not None else None,
        "future_news_excluded": future_excluded,
        "evidence": sorted(unique, key=lambda item: item["publish_date"], reverse=True)[:5],
    }


def attach_news_evidence(
    finance: pd.DataFrame,
    records_by_code: Mapping[str, Iterable[Mapping[str, object]]],
    *,
    as_of: str | date | None = None,
) -> pd.DataFrame:
    """Attach news evidence and produce a final research ranking."""

    result = finance.copy()
    evidence_rows = []
    for value in result["code6"]:
        evidence = score_news_records(records_by_code.get(str(value), []), as_of=as_of)
        evidence_rows.append(evidence)
    evidence_frame = pd.DataFrame(evidence_rows, index=result.index)
    for column in evidence_frame.columns:
        result[f"news_{column}"] = evidence_frame[column]
    result["news_available"] = result["news_news_count"].fillna(0).gt(0)
    result["final_score"] = _weighted_available(
        result,
        {"growth_core": 0.45, "quality_score": 0.30, "balance_score": 0.15, "news_news_score": 0.10},
    )
    result["news_risk_flag"] = result["news_risk_penalty"].fillna(0).ge(55)
    result["final_status"] = "观察"
    result.loc[result["factor_status"] != "有效", "final_status"] = result.loc[
        result["factor_status"] != "有效", "factor_status"
    ]
    strong = (
        (result["factor_status"] == "有效")
        & result["growth_profile"].eq("持续成长")
        & result["quality_score"].ge(60)
        & ~result["cash_mismatch_flag"]
        & ~result["news_risk_flag"]
    )
    result.loc[strong, "final_status"] = "成长质量优先"
    result.loc[
        (result["factor_status"] == "有效")
        & result["growth_profile"].isin(["加速成长", "反转/低基数"]),
        "final_status",
    ] = "加速/反转观察"
    return result.sort_values(["final_score", "growth_core"], ascending=False, na_position="last").reset_index(drop=True)


def build_growth_snapshot(
    current: pd.DataFrame,
    annual_2025: pd.DataFrame,
    annual_2024: pd.DataFrame,
    records_by_code: Mapping[str, Iterable[Mapping[str, object]]],
    *,
    as_of: str,
    top: int = 30,
) -> dict[str, object]:
    """Build a JSON-ready snapshot for the future growth subpage."""

    finance = build_finance_factors(current, annual_2025, annual_2024)
    ranked = attach_news_evidence(finance, records_by_code, as_of=as_of)
    numeric = ranked.select_dtypes(include=["number"]).columns
    ranked[numeric] = ranked[numeric].round(4)
    rows = ranked.head(top).to_dict(orient="records")
    for row in rows:
        for key, value in list(row.items()):
            if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
                row[key] = None
        row["risk_flags"] = []
        if row.get("low_base_flag"):
            row["risk_flags"].append("低基数/反转可能")
        if row.get("cash_mismatch_flag"):
            row["risk_flags"].append("现金流不匹配")
        if row.get("high_debt_flag"):
            row["risk_flags"].append("高负债")
        if row.get("news_risk_flag"):
            row["risk_flags"].append("资讯负面证据")
    news_queried = sum(1 for code in records_by_code if records_by_code[code])
    return {
        "version": GROWTH_FACTOR_VERSION,
        "updated_at": pd.Timestamp.now(tz="Asia/Hong_Kong").isoformat(timespec="seconds"),
        "data_as_of": as_of,
        "source": "同花顺问财财务查询 + 同花顺问财 news-search 历史资讯",
        "point_in_time_status": "当前截面研究；财报字段已按报告期分层，逐股披露日回溯尚待接入，不用于宣称历史回测优胜",
        "universe": {
            "name": "沪深主板非ST、盈利为正、总市值>50亿元",
            "board": "mainboard",
            "stocks_scanned": int(len(current)),
            "stocks_mainboard": int(len(finance)),
            "stocks_financial_valid": int(finance["financial_valid"].sum()),
            "news_queried_stocks": news_queried,
            "news_records_loaded": int(sum(len(list(records_by_code[code])) for code in records_by_code)),
        },
        "formula": {
            "growth_core": "25%收入增速 + 35%归母净利润增速 + 15%收入加速度 + 15%利润加速度 + 10%两年持续性",
            "quality_score": "35%经营现金流/收入 + 25%经营现金流/净利润 + 20%ROE + 20%销售净利率",
            "balance_score": "100 - 资产负债率",
            "news_score": "中性50；正面证据、主题多样性、时间衰减加分；负面证据扣分；只作为10%证据层",
            "final_score": "45%成长核心 + 30%成长质量 + 15%资产负债风险 + 10%历史资讯证据（缺失项按可用项归一）",
        },
        "factor_definitions": [
            {"name": "成长增速", "field": "current_revenue_growth/current_profit_growth", "meaning": "当前报告期的收入和利润同比"},
            {"name": "成长加速度", "field": "revenue_acceleration/profit_acceleration", "meaning": "当前报告期同比减去上一年度同比"},
            {"name": "成长持续性", "field": "persistence_score", "meaning": "2024、2025、当前三个报告期收入和利润同比为正的连续性"},
            {"name": "成长质量", "field": "cash_margin/cash_to_profit/ROE/net_margin", "meaning": "利润是否有现金、资本回报是否匹配"},
            {"name": "资讯证据", "field": "news_score", "meaning": "订单、产能、产品、研发、行业景气等可核验事件与负面事件的结构化摘要"},
        ],
        "candidates": rows,
    }
