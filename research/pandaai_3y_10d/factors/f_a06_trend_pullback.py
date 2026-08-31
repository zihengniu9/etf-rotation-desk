class TrendPullback(Factor):
    def calculate(self, factors):
        close = factors["close"]
        volume = factors["volume"]
        ma20 = MA(close, 20)
        ma60 = MA(close, 60)
        ma120 = MA(close, 120)
        full_alignment = (close > ma20) & (ma20 > ma60) & (ma60 > ma120)
        gap20 = close / ma20 - 1.0
        volume_ratio = volume / MA(volume, 20)
        pullback_distance = MAX(0.0, 1.0 - ABS(gap20 - 0.01) / 0.06)
        low_volume_quality = MAX(0.0, 1.0 - ABS(volume_ratio - 0.85) / 0.85)
        score = 0.65 * pullback_distance + 0.35 * low_volume_quality
        return IF(full_alignment, score, 0.0)

