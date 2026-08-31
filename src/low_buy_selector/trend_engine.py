"""Trend continuation engine.

The module only uses information available at the end of each bar.  It is
deliberately independent from the short-term sentiment score so that the
dashboard can route between strategies instead of mixing all signals into a
single number.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

import pandas as pd

from .trend_contract import CanonicalTrendConfig, apply_canonical_scores


@dataclass(frozen=True)
class TrendConfig:
    fast_window: int = 20
    trend_window: int = 60
    long_window: int = 120
    breakout_window: int = 60
    volume_window: int = 20
    atr_window: int = 20
    slope_window: int = 5
    pullback_window: int = 10
    breakout_buffer: float = 0.005
    max_breakout_volume_ratio: float = 3.0


def normalize_stock_code(code: object) -> str:
    """Return the six-digit A-share code from a filename or vendor symbol."""

    match = re.search(r"(\d{6})", str(code))
    return match.group(1) if match else str(code).strip().upper()


def is_main_board_code(code: object) -> bool:
    """Keep Shanghai/Shenzhen main-board stocks; exclude STAR/ChiNext/Beijing."""

    normalized = normalize_stock_code(code)
    return normalized.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))


def prepare_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Normalize an OHLCV frame without filling missing prices."""

    if "close" not in bars.columns:
        raise ValueError("bars must contain close")

    frame = bars.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        frame = frame.dropna(subset=["date"]).drop_duplicates("date", keep="last").sort_values("date")
    else:
        frame = frame.reset_index(drop=True)

    for column in ("open", "high", "low", "close", "volume", "amount", "turnover"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["high"] = frame.get("high", frame["close"]).fillna(frame["close"])
    frame["low"] = frame.get("low", frame["close"]).fillna(frame["close"])
    if "amount" in frame.columns:
        frame["turnover_proxy"] = frame["amount"]
    elif "volume" in frame.columns:
        frame["turnover_proxy"] = frame["volume"]
    else:
        frame["turnover_proxy"] = pd.NA
    return frame.dropna(subset=["close"]).reset_index(drop=True)


def _reference_close(reference: pd.DataFrame | pd.Series | None, dates: pd.Series) -> pd.Series | None:
    if reference is None:
        return None
    if isinstance(reference, pd.DataFrame):
        if "close" not in reference.columns:
            return None
        ref = reference.copy()
        if "date" in ref.columns:
            ref["date"] = pd.to_datetime(ref["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            ref = ref.dropna(subset=["date"]).drop_duplicates("date", keep="last").set_index("date")
            values = pd.to_numeric(ref["close"], errors="coerce").reindex(dates)
            return values.reset_index(drop=True)
        values = pd.to_numeric(ref["close"], errors="coerce").reset_index(drop=True)
    else:
        values = pd.to_numeric(reference, errors="coerce").reset_index(drop=True)
    if len(values) != len(dates):
        return None
    return values


def _rolling_percentile(values: pd.Series, window: int) -> pd.Series:
    """Percentile rank of the current value within its trailing window."""

    def percentile(window_values: pd.Series) -> float:
        current = window_values.iloc[-1]
        if pd.isna(current):
            return float("nan")
        valid = window_values.dropna()
        if valid.empty:
            return float("nan")
        return float((valid <= current).mean())

    return values.rolling(window, min_periods=max(5, window // 2)).apply(percentile, raw=False)


def calculate_trend_features(
    bars: pd.DataFrame,
    *,
    benchmark: pd.DataFrame | pd.Series | None = None,
    industry: pd.DataFrame | pd.Series | None = None,
    config: TrendConfig | None = None,
) -> pd.DataFrame:
    """Calculate trend features and two actionable setup flags.

    ``breakout_level`` is based on ``high.shift(1)``.  The current bar never
    participates in its own breakout reference, which is the critical
    anti-lookahead rule for this engine.
    """

    cfg = config or TrendConfig()
    frame = prepare_bars(bars)
    close = frame["close"]
    amount = pd.to_numeric(frame["turnover_proxy"], errors="coerce")

    frame["ma20"] = close.rolling(cfg.fast_window, min_periods=cfg.fast_window).mean()
    frame["ma60"] = close.rolling(cfg.trend_window, min_periods=cfg.trend_window).mean()
    frame["ma120"] = close.rolling(cfg.long_window, min_periods=cfg.long_window).mean()
    frame["ma20_slope"] = frame["ma20"].pct_change(cfg.slope_window)
    frame["ma60_slope"] = frame["ma60"].pct_change(cfg.slope_window)
    frame["r20"] = close.pct_change(cfg.fast_window)
    frame["r60"] = close.pct_change(cfg.trend_window)
    frame["r120"] = close.pct_change(cfg.long_window)

    previous_close = close.shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    frame["atr20"] = true_range.rolling(cfg.atr_window, min_periods=cfg.atr_window).mean()
    frame["atr_pct"] = frame["atr20"] / close

    prior_amount_mean = amount.shift(1).rolling(cfg.volume_window, min_periods=cfg.volume_window).mean()
    frame["volume_ratio"] = amount / prior_amount_mean
    abs_daily_return = close.pct_change().abs()
    frame["efficiency20"] = frame["r20"].abs() / abs_daily_return.rolling(cfg.fast_window, min_periods=cfg.fast_window).sum()

    # The shift is intentional: today's high/close cannot raise today's own
    # historical breakout line.
    frame["breakout_level"] = frame["high"].shift(1).rolling(
        cfg.breakout_window, min_periods=cfg.breakout_window
    ).max()
    frame["breakout_distance"] = close / frame["breakout_level"] - 1.0
    # Keep this feature name for compatibility.  The canonical contract uses
    # the same four-price alignment without a second, adapter-specific slope
    # gate; slopes remain available as descriptive fields.
    frame["trend_alignment"] = (
        (close > frame["ma20"])
        & (frame["ma20"] > frame["ma60"])
        & (frame["ma60"] > frame["ma120"])
    )
    frame["breakout_trigger"] = (
        frame["trend_alignment"]
        & (frame["breakout_distance"] >= -0.005)
        & (frame["volume_ratio"] >= 1.10)
        & (frame["volume_ratio"] <= min(2.80, cfg.max_breakout_volume_ratio))
        & frame["r20"].between(0.03, 0.35, inclusive="both")
    )

    # These are the canonical pullback/continuation definitions.  A prior
    # breakout is useful context, but it is not required: the standard study
    # evaluates the setup visible at the signal close.
    frame["pullback_trigger"] = (
        frame["trend_alignment"]
        & (frame["close"] / frame["ma20"] - 1.0).between(-0.01, 0.035, inclusive="both")
        & (frame["volume_ratio"] <= 1.15)
    )
    frame["continuation_trigger"] = (
        frame["trend_alignment"]
        & (frame["close"] / frame["ma20"] - 1.0).between(0.0, 0.08, inclusive="both")
        & frame["r20"].between(0.0, 0.25, inclusive="both")
        & frame["volume_ratio"].between(0.75, 2.20, inclusive="both")
    )

    for reference, prefix in ((benchmark, "benchmark"), (industry, "industry")):
        reference_close = _reference_close(reference, frame["date"] if "date" in frame else pd.Series(range(len(frame))))
        if reference_close is None:
            continue
        reference_return = reference_close.pct_change(cfg.trend_window)
        frame[f"relative_strength_{prefix}_60"] = frame["r60"] - reference_return

    frame["atr_percentile"] = _rolling_percentile(frame["atr_pct"], cfg.long_window)
    return frame


def score_trend_universe(
    features_by_code: Mapping[str, pd.DataFrame],
    *,
    metadata: Mapping[str, Mapping[str, object]] | None = None,
    as_of: str | None = None,
) -> pd.DataFrame:
    """Score the latest valid row of each stock in a cross-section."""

    rows: list[dict[str, object]] = []
    for code, features in features_by_code.items():
        if features.empty:
            continue
        frame = features if as_of is None else features[features["date"] <= as_of]
        if frame.empty:
            continue
        latest = frame.iloc[-1]
        required = ["r20", "r60", "r120", "ma20", "ma60", "ma120", "breakout_level", "volume_ratio"]
        if any(pd.isna(latest.get(column)) for column in required):
            continue
        item: dict[str, object] = {"code": str(code), "date": str(latest.get("date", ""))}
        item.update(latest.to_dict())
        item.update((metadata or {}).get(str(code), {}))
        rows.append(item)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    # The local adapter calls the point-in-time historical high
    # ``breakout_level``; map it to the shared contract's field name before
    # scoring so both adapters use the same breakout distance.
    result["prior_high60"] = result["breakout_level"]
    result = apply_canonical_scores(
        result,
        config=CanonicalTrendConfig(min_amount=0.0),
        require_turnover=False,
    )
    result["alignment_score"] = result["full_alignment"].astype(bool).astype(int) * 100
    result["efficiency_score"] = result["efficiency20"].clip(0, 1).fillna(0) * 100
    result["setup_score"] = (
        result["breakout_trigger"].astype(bool).astype(int) * 100 * 0.7
        + result["pullback_trigger"].astype(bool).astype(int) * 100 * 0.3
    )
    result["close_pct"] = result["r20"] * 100
    result["volume_ratio"] = result["volume_ratio"].round(3)
    return result.sort_values(["trend_score", "rs_score"], ascending=False).reset_index(drop=True)


def evaluate_profit_effect(
    features: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (5, 10, 20),
    signal_cooldown: int = 5,
) -> dict[str, object]:
    """Evaluate one stock's historical trend signals.

    A signal is observed at the close of day ``t``.  The simulated entry is
    the next trading day's open (falling back to next close when open is not
    available); the exit is the close ``horizon`` trading days after the
    signal.  Thus future bars are used only for the label, never for the
    signal itself.
    """

    frame = features.reset_index(drop=True).copy()
    if frame.empty:
        return {"signals": 0, "evaluated": 0, "horizons": {}, "label": "样本不足"}

    breakout = frame.get("breakout_trigger", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    pullback = frame.get("pullback_trigger", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    continuation = frame.get("continuation_trigger", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    signal = breakout | pullback | continuation
    signal_indices: list[int] = []
    last_signal = -10**9
    for index, is_signal in signal.items():
        if is_signal and index - last_signal > max(0, signal_cooldown):
            signal_indices.append(int(index))
            last_signal = int(index)

    open_price = pd.to_numeric(frame.get("open", frame["close"]), errors="coerce")
    close_price = pd.to_numeric(frame["close"], errors="coerce")
    low_price = pd.to_numeric(frame.get("low", frame["close"]), errors="coerce")
    stats: dict[str, dict[str, object]] = {}
    total_evaluated = 0

    for horizon in horizons:
        returns: list[float] = []
        adverse: list[float] = []
        for signal_index in signal_indices:
            entry_index = signal_index + 1
            exit_index = signal_index + horizon
            if exit_index >= len(frame):
                continue
            entry = open_price.iloc[entry_index]
            if pd.isna(entry) or entry <= 0:
                entry = close_price.iloc[entry_index]
            exit_price = close_price.iloc[exit_index]
            if pd.isna(entry) or pd.isna(exit_price) or entry <= 0:
                continue
            returns.append(float(exit_price / entry - 1.0))
            path_low = low_price.iloc[entry_index : exit_index + 1].min()
            adverse.append(float(path_low / entry - 1.0) if pd.notna(path_low) else 0.0)

        total_evaluated = max(total_evaluated, len(returns))
        values = pd.Series(returns, dtype="float64")
        gains = float(values[values > 0].sum()) if not values.empty else 0.0
        losses = float(values[values < 0].abs().sum()) if not values.empty else 0.0
        stats[str(horizon)] = {
            "count": int(len(returns)),
            "win_rate": float((values > 0).mean()) if not values.empty else None,
            "avg_return": float(values.mean()) if not values.empty else None,
            "median_return": float(values.median()) if not values.empty else None,
            "profit_factor": (gains / losses) if losses > 0 else (None if not gains else None),
            "max_adverse": float(min(adverse)) if adverse else None,
        }

    ten_day = stats.get("10", {})
    ten_avg = ten_day.get("avg_return")
    ten_count = int(ten_day.get("count") or 0)
    if ten_count < 5 or ten_avg is None:
        label = "样本不足"
    elif ten_avg > 0 and float(ten_day.get("win_rate") or 0) >= 0.5:
        label = "历史正向"
    elif ten_avg > 0:
        label = "小幅正向"
    else:
        label = "历史偏弱"
    return {
        "signals": int(len(signal_indices)),
        "evaluated": int(total_evaluated),
        "horizons": stats,
        "label": label,
    }


def aggregate_profit_effects(effects: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate stock-level event results without replacing stock detail."""

    horizons: dict[str, dict[str, object]] = {}
    for horizon in ("5", "10", "20"):
        count = 0
        weighted_return = 0.0
        weighted_wins = 0.0
        profit_factors: list[float] = []
        adverse_values: list[float] = []
        for effect in effects:
            item = (effect.get("horizons") or {}).get(horizon, {})
            item_count = int(item.get("count") or 0)
            if not item_count:
                continue
            count += item_count
            weighted_return += float(item.get("avg_return") or 0.0) * item_count
            weighted_wins += float(item.get("win_rate") or 0.0) * item_count
            if item.get("profit_factor") is not None:
                profit_factors.append(float(item["profit_factor"]))
            if item.get("max_adverse") is not None:
                adverse_values.append(float(item["max_adverse"]))
        horizons[horizon] = {
            "count": count,
            "win_rate": weighted_wins / count if count else None,
            "avg_return": weighted_return / count if count else None,
            "profit_factor": sum(profit_factors) / len(profit_factors) if profit_factors else None,
            "max_adverse": min(adverse_values) if adverse_values else None,
        }

    ten = horizons["10"]
    label = "样本不足" if int(ten["count"] or 0) < 20 else (
        "趋势赚钱效应偏正" if float(ten["avg_return"] or 0) > 0 else "趋势赚钱效应偏弱"
    )
    return {"signals": sum(int(effect.get("signals") or 0) for effect in effects), "horizons": horizons, "label": label}


def build_snapshot(
    stock_bars: Mapping[str, pd.DataFrame],
    *,
    benchmark: pd.DataFrame | pd.Series | None = None,
    metadata: Mapping[str, Mapping[str, object]] | None = None,
    as_of: str | None = None,
    config: TrendConfig | None = None,
    source: str = "local OHLCV",
) -> dict[str, object]:
    """Build the JSON contract consumed by ``web/market_mode.html``."""

    features = {
        str(code): calculate_trend_features(bars, benchmark=benchmark, config=config)
        for code, bars in stock_bars.items()
    }
    scored = score_trend_universe(features, metadata=metadata, as_of=as_of)
    candidates: list[dict[str, object]] = []
    all_effects: list[dict[str, object]] = []
    for code in scored["code"].astype(str).tolist() if not scored.empty else []:
        history = features[code]
        if as_of is not None and "date" in history.columns:
            history = history[history["date"] <= as_of]
        all_effects.append(evaluate_profit_effect(history))
    for _, row in scored.head(20).iterrows():
        history = features[str(row["code"])]
        if as_of is not None and "date" in history.columns:
            history = history[history["date"] <= as_of]
        profit_effect = evaluate_profit_effect(history)
        note = "接近或突破前60日高点" if row["setup"] == "breakout" else (
            "多头结构内缩量回踩MA20" if row["setup"] == "pullback" else (
                "多头结构内健康延续" if row["setup"] == "continuation" else "趋势结构待触发"
            )
        )
        candidates.append({
            "code": row["code"],
            "name": row.get("name", row["code"]),
            "theme": row.get("theme", "—"),
            "trend_score": round(float(row["trend_score"]), 1),
            "r20": round(float(row["r20"]), 4),
            "r60": round(float(row["r60"]), 4),
            "r120": round(float(row.get("r120", float("nan"))), 4) if pd.notna(row.get("r120")) else None,
            "volume_ratio": round(float(row["volume_ratio"]), 3),
            "breakout_distance": round(float(row["breakout_distance"]), 4),
            "setup": row["setup"],
            "first_break": row["setup"] == "breakout",
            "pullback": row["setup"] == "pullback",
            "note": note,
            "profit_effect": profit_effect,
        })

    latest_date = as_of or (str(scored["date"].max()) if not scored.empty and "date" in scored else "")
    return {
        "data_as_of": latest_date,
        "source": source,
        "history_available": bool(not scored.empty),
        "stocks_with_history": int(len(scored)),
        "profit_effect_available": any(int(effect.get("evaluated") or 0) > 0 for effect in all_effects),
        "profit_effect": aggregate_profit_effects(all_effects),
        "config": {
            "breakout_window": (config or TrendConfig()).breakout_window,
            "trend_window": (config or TrendConfig()).trend_window,
            "volume_window": (config or TrendConfig()).volume_window,
        },
        "candidates": candidates,
    }
