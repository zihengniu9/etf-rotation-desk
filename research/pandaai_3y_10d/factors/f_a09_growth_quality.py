class GrowthQuality(Factor):
    def calculate(self, factors):
        ocf = factors["cash_flow_from_operating_activities_ttm"]
        revenue = factors["operating_revenue_ttm"]
        parent_profit = factors["net_profit_parent_company_ttm"]
        roe = factors["oper_roe_ttm"]
        net_margin = factors["oper_net_margin_ttm"]
        cash_margin = ocf / MAX(revenue, 1.0)
        cash_to_profit = ocf / MAX(parent_profit, 1.0)
        score = (
            0.35 * RANK(MAX(-0.50, MIN(1.00, cash_margin)))
            + 0.25 * RANK(MAX(-1.00, MIN(3.00, cash_to_profit)))
            + 0.20 * RANK(MAX(-5.00, MIN(30.00, roe)))
            + 0.20 * RANK(MAX(-20.00, MIN(60.00, net_margin)))
        )
        return IF((revenue > 0) & (parent_profit > 0), score, 0.0)

