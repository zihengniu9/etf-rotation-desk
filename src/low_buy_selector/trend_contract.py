"""Canonical trend-factor contract shared by online and local adapters.

The project has two data adapters: the point-in-time Wencai cross-section and
the optional local OHLCV loader.  They must not silently use different trend
definitions.  This module owns the cross-sectional score, setup labels and
the standard backtest winner used by both adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


CANONICAL_TREND_VERSION = "trend-standard-v1"
CANONICAL_STRATEGY = "健康延续"
CANONICAL_HORIZON = 10
MARKET_GATE_WIDTH_MIN = 0.08
MARKET_GATE_POSITIVE_R20_MIN = 0.50


@dataclass(frozen=True)
class CanonicalTrendConfig:
    """Thresholds used by the canonical trend contract.

    ``require_turnover`` is controlled by the adapter.  Wencai has an
    explicit point-in-time turnover field and uses the strict liquidity gate.
    A local OHLCV file may not contain market-cap turnover, so its adapter can
    still calculate the same score and setups while requiring a valid amount
    and volume ratio instead.
    """

    min_amount: float = 100_000_000.0
    min_turnover: float = 0.5
    max_turnover: float = 15.0
    min_volume_ratio: float = 0.65
    max_volume_ratio: float = 3.0


def _scaled_score(series: pd.Series, low: float, high: float) -> pd.Series:
    return ((series - low) / (high - low) * 100.0).clip(0, 100)


def apply_canonical_scores(
    frame: pd.DataFrame,
    *,
    config: CanonicalTrendConfig | None = None,
    require_turnover: bool = True,
) -> pd.DataFrame:
    """Apply the canonical score and mutually exclusive setup labels.

    The function never reads forward-return or adverse-path columns.  Those
    columns can be present in a historical frame, but are labels only.
    """

    cfg = config or CanonicalTrendConfig()
    result = frame.copy()
    required = [
        "close", "ma20", "ma60", "ma120", "r20", "r60", "r120", "volume_ratio",
    ]
    result = result.dropna(subset=required).reset_index(drop=True)
    if result.empty:
        return result

    for column in ("amount", "turnover", "prior_high60"):
        if column not in result.columns:
            result[column] = pd.NA
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result["gap20"] = result["close"] / result["ma20"] - 1.0
    result["breakout_distance"] = result["close"] / result["prior_high60"] - 1.0
    result["full_alignment"] = (
        (result["close"] > result["ma20"])
        & (result["ma20"] > result["ma60"])
        & (result["ma60"] > result["ma120"])
    )
    result["mid_alignment"] = (result["close"] > result["ma20"]) & (result["ma20"] > result["ma60"])

    amount = result["amount"]
    volume_ratio = result["volume_ratio"]
    if require_turnover:
        result["liquid"] = (
            (amount >= cfg.min_amount)
            & result["turnover"].between(cfg.min_turnover, cfg.max_turnover, inclusive="both")
        )
    else:
        # Local files often lack market-cap turnover.  Do not invent it; use
        # only the fields actually present in the file as the adapter gate.
        result["liquid"] = amount.notna() & (amount > 0)

    result["structure_score"] = 0.0
    result.loc[result["close"] > result["ma20"], "structure_score"] = 35.0
    result.loc[result["mid_alignment"], "structure_score"] = 70.0
    result.loc[result["full_alignment"], "structure_score"] = 100.0

    result["rs_score"] = (
        result["r20"].rank(pct=True) * 100.0 * 0.45
        + result["r60"].rank(pct=True) * 100.0 * 0.35
        + result["r120"].rank(pct=True) * 100.0 * 0.20
    )
    # Missing historical high means missing breakout evidence, not a missing
    # entire score.  Such rows can still be ranked as continuation candidates.
    result["breakout_score"] = _scaled_score(result["breakout_distance"], -0.10, 0.01).fillna(0.0)
    result["volume_score"] = (100.0 - (volume_ratio - 1.4).abs() / 1.4 * 100.0).clip(0, 100)
    gap_score = (100.0 - (result["gap20"] - 0.04).abs() / 0.12 * 100.0).clip(0, 100)
    momentum_health = (100.0 - (result["r20"] - 0.10).abs() / 0.30 * 100.0).clip(0, 100)
    result["quality_score"] = gap_score * 0.60 + momentum_health * 0.40
    pullback_distance = (100.0 - (result["gap20"] - 0.01).abs() / 0.06 * 100.0).clip(0, 100)
    low_volume_quality = (100.0 - (volume_ratio - 0.85).abs() / 0.85 * 100.0).clip(0, 100)
    result["pullback_score"] = (pullback_distance * 0.65 + low_volume_quality * 0.35).where(
        result["full_alignment"], 0.0
    )
    result["overheat_penalty"] = (
        _scaled_score(result["r20"], 0.25, 0.55) * 0.60
        + _scaled_score(result["gap20"], 0.10, 0.25) * 0.40
    )
    result["trend_score"] = (
        result["structure_score"] * 0.20
        + result["rs_score"] * 0.25
        + result["breakout_score"] * 0.20
        + result["volume_score"] * 0.15
        + result["quality_score"] * 0.10
        + result["pullback_score"] * 0.10
        - result["overheat_penalty"] * 0.15
    ).clip(0, 100)

    volume_ok = volume_ratio.between(cfg.min_volume_ratio, cfg.max_volume_ratio, inclusive="both")
    result["eligible"] = result["full_alignment"] & result["liquid"] & (result["r60"] > 0) & volume_ok

    # The setup rules are mutually exclusive by priority.  The priority is
    # deliberate: a current breakout is not also labelled a pullback or a
    # continuation signal.
    breakout = (
        result["eligible"]
        & (result["breakout_distance"] >= -0.005)
        & volume_ratio.between(1.10, 2.80, inclusive="both")
        & result["r20"].between(0.03, 0.35, inclusive="both")
    )
    pullback = (
        result["eligible"]
        & result["gap20"].between(-0.01, 0.035, inclusive="both")
        & (volume_ratio <= 1.15)
    )
    continuation = (
        result["eligible"]
        & result["gap20"].between(0.0, 0.08, inclusive="both")
        & result["r20"].between(0.0, 0.25, inclusive="both")
        & volume_ratio.between(0.75, 2.20, inclusive="both")
    )
    result["breakout_trigger"] = breakout
    result["pullback_trigger"] = pullback
    result["continuation_trigger"] = continuation
    result["setup"] = "watch"
    result.loc[continuation, "setup"] = "continuation"
    result.loc[pullback, "setup"] = "pullback"
    result.loc[breakout, "setup"] = "breakout"
    result["score_percentile"] = result["trend_score"].rank(pct=True)
    result["eligible_score_percentile"] = result["trend_score"].where(result["eligible"]).rank(pct=True)
    return result.sort_values(["trend_score", "rs_score"], ascending=False).reset_index(drop=True)
