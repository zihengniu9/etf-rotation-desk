class TrendComposite(Factor):
    def calculate(self, factors):
        close = factors["close"]
        high = factors["high"]
        volume = factors["volume"]
        ma20 = MA(close, 20)
        ma60 = MA(close, 60)
        ma120 = MA(close, 120)
        above20 = close > ma20
        mid_alignment = above20 & (ma20 > ma60)
        full_alignment = mid_alignment & (ma60 > ma120)
        structure = IF(full_alignment, 1.0, IF(mid_alignment, 0.70, IF(above20, 0.35, 0.0)))
        r20 = RETURNS(close, 20)
        rs_score = 0.45 * RANK(r20) + 0.35 * RANK(RETURNS(close, 60)) + 0.20 * RANK(RETURNS(close, 120))
        breakout_distance = close / DELAY(TS_MAX(high, 60), 1) - 1.0
        breakout = MAX(0.0, MIN(1.0, (breakout_distance + 0.10) / 0.11))
        volume_ratio = volume / MA(volume, 20)
        volume_score = MAX(0.0, 1.0 - ABS(volume_ratio - 1.40) / 1.40)
        gap20 = close / ma20 - 1.0
        gap_score = MAX(0.0, 1.0 - ABS(gap20 - 0.04) / 0.12)
        momentum_health = MAX(0.0, 1.0 - ABS(r20 - 0.10) / 0.30)
        quality = 0.60 * gap_score + 0.40 * momentum_health
        pullback_distance = MAX(0.0, 1.0 - ABS(gap20 - 0.01) / 0.06)
        low_volume_quality = MAX(0.0, 1.0 - ABS(volume_ratio - 0.85) / 0.85)
        pullback = IF(full_alignment, 0.65 * pullback_distance + 0.35 * low_volume_quality, 0.0)
        heat_r20 = MAX(0.0, MIN(1.0, (r20 - 0.25) / 0.30))
        heat_gap = MAX(0.0, MIN(1.0, (gap20 - 0.10) / 0.15))
        overheat = 0.60 * heat_r20 + 0.40 * heat_gap
        score = (
            0.20 * structure
            + 0.25 * rs_score
            + 0.20 * breakout
            + 0.15 * volume_score
            + 0.10 * quality
            + 0.10 * pullback
            - 0.15 * overheat
        )
        return MAX(0.0, MIN(1.0, score))

