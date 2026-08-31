class TrendBreakout(Factor):
    def calculate(self, factors):
        close = factors["close"]
        high = factors["high"]
        prior_high60 = DELAY(TS_MAX(high, 60), 1)
        breakout_distance = close / prior_high60 - 1.0
        return MAX(0.0, MIN(1.0, (breakout_distance + 0.10) / 0.11))

