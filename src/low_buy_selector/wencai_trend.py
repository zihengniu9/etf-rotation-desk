"""Point-in-time trend scoring for 同花顺问财 cross-sections.

The signal columns are dated at or before ``signal_date``. Forward prices are
parsed separately and are used only as evaluation labels. This keeps the
Wencai workflow consistent with the anti-lookahead rules in ``trend_engine``.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Mapping

import pandas as pd

from .trend_contract import (
    CANONICAL_HORIZON,
    CANONICAL_STRATEGY,
    CANONICAL_TREND_VERSION,
    CanonicalTrendConfig,
    MARKET_GATE_POSITIVE_R20_MIN,
    MARKET_GATE_WIDTH_MIN,
    apply_canonical_scores,
)
from .trend_engine import is_main_board_code


# Compatibility name for callers that already import the Wencai adapter's
# configuration.  The scoring thresholds now live in one shared contract.
WencaiTrendConfig = CanonicalTrendConfig


def chinese_date(value: str | date | pd.Timestamp) -> str:
    stamp = pd.Timestamp(value)
    return f"{stamp.year}年{stamp.month}月{stamp.day}日"


def build_wencai_query(signal_date: str, *, include_forward: bool) -> str:
    day = chinese_date(signal_date)
    fields = [
        f"{day}沪深主板非ST股票",
        "股票代码",
        "股票简称",
        "所属同花顺行业",
        f"{day}收盘价（前复权）",
        f"{day}20日均线",
        f"{day}60日均线",
        f"{day}120日均线",
        f"{day}前20个交易日涨跌幅",
        f"{day}前60个交易日涨跌幅",
        f"{day}前120个交易日涨跌幅",
        f"{day}前60个交易日最高价",
        f"{day}量比",
        f"{day}成交额",
        f"{day}换手率",
    ]
    if include_forward:
        fields.extend(
            [
                f"{day}后第1个交易日开盘价（前复权）",
                f"{day}后第5个交易日收盘价（前复权）",
                f"{day}后第10个交易日收盘价（前复权）",
                f"{day}后第20个交易日收盘价（前复权）",
                f"{day}后第1个交易日最低价（前复权）",
                f"{day}后5个交易日最低价",
                f"{day}后10个交易日最低价",
                f"{day}后20个交易日最低价",
            ]
        )
    return "，".join(fields)


def build_wencai_label_query(signal_date: str) -> str:
    """Build a short labels-only query to keep Wencai's relative-date parser stable."""

    day = chinese_date(signal_date)
    return "，".join(
        [
            f"{day}沪深主板非ST股票",
            "股票代码",
            "股票简称",
            # This point-in-time field anchors Wencai's historical universe.
            # Without it, some dates collapse to a small latest-data subset.
            f"{day}收盘价（前复权）",
            f"{day}后第1个交易日开盘价（前复权）",
            f"{day}后第5个交易日收盘价（前复权）",
            f"{day}后第10个交易日收盘价（前复权）",
            f"{day}后第20个交易日收盘价（前复权）",
            f"{day}后第1个交易日最低价（前复权）",
            f"{day}后5个交易日最低价",
            f"{day}后10个交易日最低价",
            f"{day}后20个交易日最低价",
        ]
    )


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in {"--", "None", "nan", "NaN"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _timestamp(column: Mapping[str, object]) -> str:
    return str(column.get("timestamp") or "")


def _index_name(column: Mapping[str, object]) -> str:
    return str(column.get("index_name") or "")


def _key(column: Mapping[str, object]) -> str:
    return str(column.get("key") or column.get("feKey") or "")


def _range_start(timestamp: str) -> str:
    return timestamp.split("-", 1)[0]


def _range_end(timestamp: str) -> str:
    return timestamp.split("-", 1)[-1]


def _first_key(columns: Iterable[Mapping[str, object]], predicate) -> str | None:
    for column in columns:
        if predicate(column):
            return _key(column)
    return None


def _adjustment_rank(column: Mapping[str, object]) -> int:
    """Prefer explicitly 前复权 fields when Wencai emits duplicate dates."""

    return 0 if _column_contains(column, "前复权") else 1


def _preferred_key(columns: Iterable[Mapping[str, object]], predicate) -> str | None:
    matches = [column for column in columns if predicate(column)]
    matches.sort(key=_adjustment_rank)
    return _key(matches[0]) if matches else None


def _unique_dated_keys(
    columns: Iterable[Mapping[str, object]],
    predicate,
    *,
    date_key,
) -> list[str]:
    """Return one preferred field per date/range end in chronological order."""

    grouped: dict[str, list[Mapping[str, object]]] = {}
    for column in columns:
        if predicate(column):
            grouped.setdefault(str(date_key(column)), []).append(column)
    keys: list[str] = []
    for stamp in sorted(grouped):
        grouped[stamp].sort(key=_adjustment_rank)
        keys.append(_key(grouped[stamp][0]))
    return keys


def _row_value(row: Mapping[str, object], key: str | None) -> object:
    return row.get(key) if key else None


def _column_contains(column: Mapping[str, object], *terms: str) -> bool:
    text = f"{_index_name(column)} {_key(column)}"
    return any(term in text for term in terms)


def _is_numeric_column(column: Mapping[str, object]) -> bool:
    return str(column.get("type") or "").upper() != "DATE"


def merge_wencai_responses(*responses: Mapping[str, object]) -> dict[str, object]:
    """Merge feature and label responses by stock code before normalization."""

    merged_columns: list[Mapping[str, object]] = []
    seen_keys: set[str] = set()
    merged_rows: dict[str, dict[str, object]] = {}
    for response in responses:
        columns = list(response.get("columns") or [])
        code_key = _first_key(columns, lambda c: _index_name(c) == "股票代码") or "股票代码"
        for column in columns:
            key = _key(column)
            if key and key not in seen_keys:
                seen_keys.add(key)
                merged_columns.append(column)
        for row in list(response.get("datas") or []):
            code = str(row.get(code_key) or "")
            if not code:
                continue
            merged_rows.setdefault(code, {}).update(dict(row))
    return {"columns": merged_columns, "datas": list(merged_rows.values())}


def normalize_wencai_response(response: Mapping[str, object], signal_date: str) -> pd.DataFrame:
    """Normalize one Wencai response into a dated trend cross-section."""

    token = pd.Timestamp(signal_date).strftime("%Y%m%d")
    columns = list(response.get("columns") or [])
    rows = list(response.get("datas") or [])

    code_key = _first_key(columns, lambda c: _index_name(c) == "股票代码") or "股票代码"
    name_key = _first_key(columns, lambda c: _index_name(c) == "股票简称") or "股票简称"
    industry_key = _first_key(columns, lambda c: "同花顺行业" in _index_name(c) or "同花顺行业" in _key(c))
    close_key = _preferred_key(
        columns,
        lambda c: _timestamp(c) == token and _index_name(c).startswith("收盘价"),
    )
    ma_keys = {
        window: _first_key(
            columns,
            lambda c, window=window: _timestamp(c) == token and f"{window}日均线" in _key(c),
        )
        for window in (20, 60, 120)
    }
    amount_key = _first_key(columns, lambda c: _timestamp(c) == token and _index_name(c) == "成交额")
    turnover_key = _first_key(columns, lambda c: _timestamp(c) == token and _index_name(c) == "换手率")
    volume_ratio_key = _first_key(columns, lambda c: _timestamp(c) == token and _index_name(c) == "量比")

    return_columns = [
        c
        for c in columns
        if "涨跌幅" in _index_name(c)
        and "-" in _timestamp(c)
        and _range_end(_timestamp(c)) < token
    ]
    return_columns.sort(key=lambda c: _range_start(_timestamp(c)), reverse=True)
    return_keys = [_key(c) for c in return_columns[:3]]

    prior_high_key = _first_key(
        columns,
        lambda c: _column_contains(c, "最高价", "最高值")
        and _is_numeric_column(c)
        and "-" in _timestamp(c)
        and _range_end(_timestamp(c)) < token,
    )

    entry_columns = [
        c for c in columns if _index_name(c).startswith("开盘价") and _timestamp(c) > token
    ]
    entry_timestamp = min((_timestamp(c) for c in entry_columns), default="")
    entry_key = _preferred_key(entry_columns, lambda c: _timestamp(c) == entry_timestamp)

    exit_keys = _unique_dated_keys(
        columns,
        lambda c: _index_name(c).startswith("收盘价")
        and _timestamp(c) > token
        and _timestamp(c) != entry_timestamp,
        date_key=_timestamp,
    )[:3]

    entry_low_key = _preferred_key(
        columns,
        lambda c: _column_contains(c, "最低价", "最低值")
        and _is_numeric_column(c)
        and _timestamp(c) == entry_timestamp,
    )
    adverse_keys = _unique_dated_keys(
        columns,
        lambda c: _column_contains(c, "最低价", "最低值")
        and _is_numeric_column(c)
        and "-" in _timestamp(c)
        and _range_end(_timestamp(c)) > token
        and _range_end(_timestamp(c)) != entry_timestamp,
        date_key=lambda c: _range_end(_timestamp(c)),
    )[:3]

    normalized: list[dict[str, object]] = []
    for row in rows:
        code = str(_row_value(row, code_key) or "")
        if not is_main_board_code(code):
            continue
        item: dict[str, object] = {
            "date": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
            "code": code,
            "name": str(_row_value(row, name_key) or code),
            "theme": _row_value(row, industry_key) or "—",
            "close": _number(_row_value(row, close_key)),
            "ma20": _number(_row_value(row, ma_keys[20])),
            "ma60": _number(_row_value(row, ma_keys[60])),
            "ma120": _number(_row_value(row, ma_keys[120])),
            "amount": _number(_row_value(row, amount_key)),
            "turnover": _number(_row_value(row, turnover_key)),
            "volume_ratio": _number(_row_value(row, volume_ratio_key)),
            "prior_high60": _number(_row_value(row, prior_high_key)),
            "entry": _number(_row_value(row, entry_key)),
        }
        entry_low = _number(_row_value(row, entry_low_key))
        for index, window in enumerate((20, 60, 120)):
            raw = _number(_row_value(row, return_keys[index] if index < len(return_keys) else None))
            item[f"r{window}"] = raw / 100.0 if raw is not None else None
        for index, horizon in enumerate((5, 10, 20)):
            exit_value = _number(_row_value(row, exit_keys[index] if index < len(exit_keys) else None))
            interval_low = _number(_row_value(row, adverse_keys[index] if index < len(adverse_keys) else None))
            lows = [value for value in (entry_low, interval_low) if value is not None]
            adverse_value = min(lows) if lows else None
            item[f"exit{horizon}"] = exit_value
            item[f"low{horizon}"] = adverse_value
        normalized.append(item)

    frame = pd.DataFrame(normalized)
    if frame.empty:
        return frame
    for column in (
        "close", "ma20", "ma60", "ma120", "amount", "turnover", "volume_ratio", "prior_high60",
        "entry", "r20", "r60", "r120", "exit5", "exit10", "exit20", "low5", "low10", "low20",
    ):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for horizon in (5, 10, 20):
        raw_forward = frame[f"exit{horizon}"] / frame["entry"] - 1.0
        raw_adverse = frame[f"low{horizon}"] / frame["entry"] - 1.0
        lower, upper = {5: (-0.80, 0.80), 10: (-0.90, 2.00), 20: (-0.95, 6.00)}[horizon]
        frame[f"label_valid{horizon}"] = raw_forward.between(lower, upper, inclusive="both")
        frame[f"fwd{horizon}"] = raw_forward.where(frame[f"label_valid{horizon}"])
        frame[f"mae{horizon}"] = raw_adverse.where(raw_adverse.between(-0.95, upper, inclusive="both"))
    return frame


def score_wencai_cross_section(
    frame: pd.DataFrame,
    *,
    config: WencaiTrendConfig | None = None,
) -> pd.DataFrame:
    """Score one dated Wencai cross-section without using forward columns."""
    return apply_canonical_scores(frame, config=config, require_turnover=True)


def _profit_factor(values: pd.Series) -> float | None:
    gains = float(values[values > 0].sum())
    losses = float(values[values < 0].abs().sum())
    if losses <= 0:
        return None
    return gains / losses


def evaluate_rows(rows: pd.DataFrame) -> dict[str, object]:
    horizons: dict[str, dict[str, object]] = {}
    max_count = 0
    for horizon in (5, 10, 20):
        forward = rows[f"fwd{horizon}"] if f"fwd{horizon}" in rows else pd.Series(dtype=float)
        adverse_source = rows[f"mae{horizon}"] if f"mae{horizon}" in rows else pd.Series(dtype=float)
        values = pd.to_numeric(forward, errors="coerce").dropna()
        max_count = max(max_count, len(values))
        adverse = pd.to_numeric(adverse_source, errors="coerce").dropna()
        horizons[str(horizon)] = {
            "count": int(len(values)),
            "win_rate": float((values > 0).mean()) if len(values) else None,
            "avg_return": float(values.mean()) if len(values) else None,
            "median_return": float(values.median()) if len(values) else None,
            "profit_factor": _profit_factor(values) if len(values) else None,
            "max_adverse": float(adverse.min()) if len(adverse) else None,
            "avg_adverse": float(adverse.mean()) if len(adverse) else None,
        }
    ten = horizons["10"]
    if int(ten["count"] or 0) < 20:
        label = "样本不足"
    elif float(ten["avg_return"] or 0) > 0 and float(ten["win_rate"] or 0) >= 0.5:
        label = "趋势赚钱效应偏正"
    else:
        label = "趋势赚钱效应偏弱"
    return {"signals": int(len(rows)), "evaluated": int(max_count), "horizons": horizons, "label": label}


def evaluate_strategies(history: pd.DataFrame) -> dict[str, dict[str, object]]:
    masks = {
        "流动性趋势结构": history["eligible"],
        "健康延续": history["setup"] == "continuation",
        "放量突破": history["setup"] == "breakout",
        "缩量回踩": history["setup"] == "pullback",
        "综合Top1%": history["eligible"] & (history["eligible_score_percentile"] >= 0.99),
        "综合Top3%": history["eligible"] & (history["eligible_score_percentile"] >= 0.97),
        "综合Top5%": history["eligible"] & (history["eligible_score_percentile"] >= 0.95),
        "综合Top10%": history["eligible"] & (history["eligible_score_percentile"] >= 0.90),
    }
    return {name: evaluate_rows(history[mask]) for name, mask in masks.items()}


def select_best_holding(summary: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    choices: list[dict[str, object]] = []
    for strategy, effect in summary.items():
        for horizon, stats in (effect.get("horizons") or {}).items():
            count = int(stats.get("count") or 0)
            avg_return = stats.get("avg_return")
            median_return = stats.get("median_return")
            win_rate = stats.get("win_rate")
            if count < 80 or avg_return is None or median_return is None or win_rate is None:
                continue
            confidence = min(1.0, count / 300.0)
            quality = (float(avg_return) * 0.55 + float(median_return) * 0.25 + (float(win_rate) - 0.5) * 0.20) * confidence
            choices.append(
                {
                    "strategy": strategy,
                    "horizon": int(horizon),
                    "count": count,
                    "avg_return": float(avg_return),
                    "median_return": float(median_return),
                    "win_rate": float(win_rate),
                    "profit_factor": stats.get("profit_factor"),
                    "quality": quality,
                }
            )
    if not choices:
        return {"label": "样本不足"}
    best = max(choices, key=lambda item: item["quality"])
    best["tradable"] = bool(
        best["avg_return"] > 0
        and best["median_return"] >= 0
        and best["win_rate"] >= 0.50
        and float(best.get("profit_factor") or 0) >= 1.15
    )
    best["selection_rule"] = (
        "标准回测优先：10日平均收益、中位数、胜率与盈亏质量综合；"
        "样本数至少80，且平均收益/中位数/胜率/PF分别通过交易门槛"
    )
    best["label"] = f"{best['strategy']} · 持有{best['horizon']}日"
    return best


def market_snapshot_metrics(frame: pd.DataFrame) -> dict[str, object]:
    rows = int(len(frame))
    eligible_count = int(frame["eligible"].fillna(False).astype(bool).sum()) if rows else 0
    return {
        "rows": rows,
        "eligible_count": eligible_count,
        "eligible_ratio": eligible_count / rows if rows else 0.0,
        "positive_r20_ratio": float((pd.to_numeric(frame["r20"], errors="coerce") > 0).mean()) if rows else 0.0,
        "median_r20": float(pd.to_numeric(frame["r20"], errors="coerce").median()) if rows else None,
        "full_alignment_ratio": float(frame["full_alignment"].fillna(False).astype(bool).mean()) if rows else 0.0,
    }


def _market_gate(metrics: Mapping[str, object]) -> bool:
    return (
        float(metrics.get("eligible_ratio") or 0) >= MARKET_GATE_WIDTH_MIN
        and float(metrics.get("positive_r20_ratio") or 0) >= MARKET_GATE_POSITIVE_R20_MIN
    )


def evaluate_market_gated_strategies(history: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Evaluate stock triggers only when the contemporaneous trend regime is on."""

    date_metrics = {
        str(signal_date): market_snapshot_metrics(group)
        for signal_date, group in history.groupby("date", sort=True)
    }
    active_dates = {signal_date for signal_date, metrics in date_metrics.items() if _market_gate(metrics)}
    masks = {
        "健康延续": history["eligible"] & history["setup"].eq("continuation") & history["date"].astype(str).isin(active_dates),
        "缩量回踩": history["eligible"] & history["setup"].eq("pullback") & history["date"].astype(str).isin(active_dates),
        "放量突破": history["eligible"] & history["setup"].eq("breakout") & history["date"].astype(str).isin(active_dates),
    }
    output: dict[str, dict[str, object]] = {}
    for name, mask in masks.items():
        rows = history[mask]
        effect = evaluate_rows(rows)
        effect["active_dates"] = len(active_dates)
        for horizon in (5, 10, 20):
            column = f"fwd{horizon}"
            valid = rows.dropna(subset=[column]) if column in rows else rows.iloc[0:0]
            date_returns = valid.groupby("date")[column].mean() if not valid.empty else pd.Series(dtype=float)
            effect["horizons"][str(horizon)].update(
                {
                    "date_count": int(len(date_returns)),
                    "date_avg_return": float(date_returns.mean()) if len(date_returns) else None,
                    "date_median_return": float(date_returns.median()) if len(date_returns) else None,
                    "positive_date_rate": float((date_returns > 0).mean()) if len(date_returns) else None,
                    "worst_date_return": float(date_returns.min()) if len(date_returns) else None,
                    "best_date_return": float(date_returns.max()) if len(date_returns) else None,
                }
            )
        output[name] = effect
    return output


def _gate_candidate_result(history: pd.DataFrame, width_min: float, positive_min: float) -> dict[str, object]:
    date_metrics = {
        str(signal_date): market_snapshot_metrics(group)
        for signal_date, group in history.groupby("date", sort=True)
    }
    active_dates = {
        signal_date
        for signal_date, metrics in date_metrics.items()
        if float(metrics.get("eligible_ratio") or 0) >= width_min
        and float(metrics.get("positive_r20_ratio") or 0) >= positive_min
    }
    rows = history[
        history["date"].astype(str).isin(active_dates)
        & history["eligible"]
        & history["setup"].eq("continuation")
    ].dropna(subset=["fwd10"])
    values = pd.to_numeric(rows["fwd10"], errors="coerce").dropna()
    date_returns = rows.groupby("date")["fwd10"].mean() if not rows.empty else pd.Series(dtype=float)
    ordered_dates = sorted(date_metrics)
    split_date = ordered_dates[max(0, len(ordered_dates) // 2 - 1)] if ordered_dates else ""
    early_active_dates = sum(1 for value in active_dates if value <= split_date)
    late_active_dates = sum(1 for value in active_dates if value > split_date)
    return {
        "width_min": width_min,
        "positive_r20_min": positive_min,
        "active_dates": int(len(active_dates)),
        "early_active_dates": int(early_active_dates),
        "late_active_dates": int(late_active_dates),
        "signals": int(len(values)),
        "avg_return": float(values.mean()) if len(values) else None,
        "median_return": float(values.median()) if len(values) else None,
        "win_rate": float((values > 0).mean()) if len(values) else None,
        "positive_date_rate": float((date_returns > 0).mean()) if len(date_returns) else None,
        "worst_date_return": float(date_returns.min()) if len(date_returns) else None,
    }


def validate_market_gate_thresholds(history: pd.DataFrame) -> dict[str, object]:
    """Record a small neighboring-threshold check without optimizing noise.

    The selected gate keeps at least eight historical active dates in the
    current sample.  This deliberately favors coverage and repeatability over
    choosing the single highest in-sample average from a small grid.
    """

    candidates = [
        _gate_candidate_result(history, width, positive)
        for width in (0.05, 0.08, 0.10)
        for positive in (0.50, 0.55)
    ]
    selected = next(
        item for item in candidates
        if item["width_min"] == MARKET_GATE_WIDTH_MIN
        and item["positive_r20_min"] == MARKET_GATE_POSITIVE_R20_MIN
    )
    return {
        "selected": selected,
        "selection_rule": "趋势宽度先保留8%的安全下限；在R20扩散50%与55%邻近组合中，选择后半样本仍有至少8个有效期的50%门槛，不因小样本均值最高而过拟合",
        "candidates": candidates,
    }


def build_market_decision(current: pd.DataFrame) -> dict[str, object]:
    metrics = market_snapshot_metrics(current)
    breadth = float(metrics["eligible_ratio"])
    positive = float(metrics["positive_r20_ratio"])
    if breadth < 0.03:
        mode = "趋势模式关闭"
        action = "不新开趋势仓，候选仅观察"
        reason = "中期多头结构尚未扩散到足够多的主板股票"
        allow = False
        tone = "warning"
    elif breadth < MARKET_GATE_WIDTH_MIN:
        mode = "趋势模式观察"
        action = "等待趋势宽度升至8%"
        reason = "趋势仍是少数个股行情，固定持有的稳定性不足"
        allow = False
        tone = "warning"
    elif positive < MARKET_GATE_POSITIVE_R20_MIN:
        mode = "趋势退潮"
        action = "停止新增，优先处理失效持仓"
        reason = "虽有中期结构，但近20日上涨股票不足半数"
        allow = False
        tone = "danger"
    elif breadth <= 0.16:
        mode = "趋势模式开启"
        action = "优先健康延续，缩量回踩次选，默认观察10日"
        reason = "趋势宽度与短期赚钱扩散同时达到历史门槛"
        allow = True
        tone = "ready"
    else:
        mode = "趋势扩散"
        action = "优先健康延续，缩量回踩次选，避免把20日持有机械拉长"
        reason = "趋势已广泛扩散，10日效果优于长期追随"
        allow = True
        tone = "ready"
    return {
        "mode": mode,
        "action": action,
        "reason": reason,
        "allow_new_entries": allow,
        "tone": tone,
        "preferred_setups": ["continuation", "pullback"] if allow else [],
        "default_holding_days": 10 if allow else None,
        "gate": {
            "eligible_ratio_min": MARKET_GATE_WIDTH_MIN,
            "positive_r20_ratio_min": MARKET_GATE_POSITIVE_R20_MIN,
            **metrics,
        },
    }


def build_dashboard_snapshot(
    current: pd.DataFrame,
    history: pd.DataFrame,
    summary: Mapping[str, Mapping[str, object]],
    *,
    source: str,
    top: int = 20,
) -> dict[str, object]:
    best = select_best_holding(summary)
    gated_strategies = evaluate_market_gated_strategies(history)
    gate_validation = validate_market_gate_thresholds(history)
    decision = build_market_decision(current)
    recommended_strategy = str(best.get("strategy") or CANONICAL_STRATEGY)
    aggregate = dict(summary.get(recommended_strategy) or summary.get(CANONICAL_STRATEGY) or evaluate_rows(history.iloc[0:0]))
    eligible = current[current["eligible"]].head(top)
    current_eligible_count = int(current["eligible"].sum())
    current_eligible_ratio = current_eligible_count / len(current) if len(current) else 0.0
    historical_breadth = history.groupby("date")["eligible"].mean() if not history.empty else pd.Series(dtype=float)
    breadth_percentile = (
        float((historical_breadth <= current_eligible_ratio).mean()) if len(historical_breadth) else None
    )
    if breadth_percentile is None:
        breadth_state = "样本不足"
    elif breadth_percentile <= 0.25:
        breadth_state = "趋势收缩"
    elif breadth_percentile <= 0.65:
        breadth_state = "局部趋势"
    elif breadth_percentile <= 0.90:
        breadth_state = "趋势扩散"
    else:
        breadth_state = "趋势拥挤"
    setup_counts = current.loc[current["eligible"], "setup"].value_counts().to_dict()
    candidates: list[dict[str, object]] = []
    for _, row in eligible.iterrows():
        stock_history = history[(history["code"] == row["code"]) & history["eligible"]]
        effect = evaluate_rows(stock_history)
        setup = str(row["setup"])
        setup_text = {
            "breakout": "放量接近或突破前60日高点",
            "pullback": "多头结构内缩量回踩MA20",
            "continuation": "多头结构内健康延续",
            "watch": "趋势结构成立，等待触发",
        }.get(setup, "趋势观察")
        theme = row.get("theme", "—")
        if isinstance(theme, list):
            theme = " / ".join(str(value) for value in theme[:2])
        candidates.append(
            {
                "code": str(row["code"]),
                "name": str(row.get("name") or row["code"]),
                "theme": str(theme or "—"),
                "trend_score": round(float(row["trend_score"]), 1),
                "r20": round(float(row["r20"]), 4),
                "r60": round(float(row["r60"]), 4),
                "r120": round(float(row["r120"]), 4),
                "volume_ratio": round(float(row["volume_ratio"]), 3),
                "breakout_distance": round(float(row["breakout_distance"]), 4) if pd.notna(row["breakout_distance"]) else None,
                "setup": setup,
                "first_break": setup == "breakout",
                "pullback": setup == "pullback",
                "note": setup_text,
                "profit_effect": effect,
                "factors": {
                    "structure": round(float(row["structure_score"]), 1),
                    "relative_strength": round(float(row["rs_score"]), 1),
                    "breakout": round(float(row["breakout_score"]), 1) if pd.notna(row["breakout_score"]) else None,
                    "volume": round(float(row["volume_score"]), 1),
                    "quality": round(float(row["quality_score"]), 1),
                    "pullback": round(float(row["pullback_score"]), 1),
                },
            }
        )

    return {
        "data_as_of": str(current["date"].max()) if not current.empty else "",
        "source": source,
        "history_available": not history.empty,
        "stocks_with_history": int(history["code"].nunique()) if not history.empty else 0,
        "profit_effect_available": int(aggregate.get("evaluated") or 0) > 0,
        "profit_effect": aggregate,
        "best_holding": best,
        "trend_contract": {
            "version": CANONICAL_TREND_VERSION,
            "selected_strategy": recommended_strategy,
            "selected_horizon": int(best.get("horizon") or CANONICAL_HORIZON),
            "selection_basis": "同一股票池、信号收盘确认、次日开盘入场、5/10/20日收盘退出",
        },
        "market_gate_validation": gate_validation,
        "decision": decision,
        "gated_strategies": gated_strategies,
        "trend_breadth": {
            "state": breadth_state,
            "eligible_count": current_eligible_count,
            "eligible_ratio": current_eligible_ratio,
            "historical_percentile": breadth_percentile,
            "setup_counts": {str(key): int(value) for key, value in setup_counts.items()},
        },
        "universe": {
            "name": "沪深主板非ST",
            "board": "mainboard",
            "stocks_scanned": int(len(current)),
            "stocks_with_history": int(history["code"].nunique()) if not history.empty else 0,
        },
        "config": {
            "entry": "信号日后第1个交易日开盘",
            "horizons": [5, 10, 20],
            "min_amount": (WencaiTrendConfig()).min_amount,
            "history_dates": sorted(history["date"].dropna().unique().tolist()) if not history.empty else [],
        },
        "candidates": candidates,
    }
