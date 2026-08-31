class BalanceQuality(Factor):
    def calculate(self, factors):
        debt_to_asset = factors["fin_debt_to_asset_ttm"]
        return 1.0 - RANK(debt_to_asset)

