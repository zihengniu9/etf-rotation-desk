class TrendQuality(Factor):
    def calculate(self, factors):
        close = factors["close"]
        gap20 = close / MA(close, 20) - 1.0
        r20 = RETURNS(close, 20)
        gap_score = MAX(0.0, 1.0 - ABS(gap20 - 0.04) / 0.12)
        momentum_health = MAX(0.0, 1.0 - ABS(r20 - 0.10) / 0.30)
        return 0.60 * gap_score + 0.40 * momentum_health

