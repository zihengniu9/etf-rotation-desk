class TrendStructure(Factor):
    def calculate(self, factors):
        close = factors["close"]
        ma20 = MA(close, 20)
        ma60 = MA(close, 60)
        ma120 = MA(close, 120)
        above20 = close > ma20
        mid_alignment = above20 & (ma20 > ma60)
        full_alignment = mid_alignment & (ma60 > ma120)
        return IF(full_alignment, 1.0, IF(mid_alignment, 0.70, IF(above20, 0.35, 0.0)))

