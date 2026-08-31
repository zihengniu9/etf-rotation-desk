class TrendVolumeHealth(Factor):
    def calculate(self, factors):
        volume = factors["volume"]
        volume_ratio = volume / MA(volume, 20)
        return MAX(0.0, 1.0 - ABS(volume_ratio - 1.40) / 1.40)

