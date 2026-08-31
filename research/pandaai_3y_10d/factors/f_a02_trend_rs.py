class TrendRelativeStrength(Factor):
    def calculate(self, factors):
        close = factors["close"]
        return (
            0.45 * RANK(RETURNS(close, 20))
            + 0.35 * RANK(RETURNS(close, 60))
            + 0.20 * RANK(RETURNS(close, 120))
        )

