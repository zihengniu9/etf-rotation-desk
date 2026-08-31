class QualityHeavy(Factor):
    def calculate(self, factors):
        rev_growth = factors["gr_oper_rev_ttm"]
        prev_rev_growth = factors["gr_oper_rev_lyr"]
        profit_growth = factors["gr_np_parent_ttm"]
        prev_profit_growth = factors["gr_np_parent_lyr"]
        revenue = factors["operating_revenue_ttm"]
        parent_profit = factors["net_profit_parent_company_ttm"]
        ocf = factors["cash_flow_from_operating_activities_ttm"]
        roe = factors["oper_roe_ttm"]
        net_margin = factors["oper_net_margin_ttm"]
        debt_to_asset = factors["fin_debt_to_asset_ttm"]
        persistence = (AS_FLOAT(rev_growth > 0) + AS_FLOAT(prev_rev_growth > 0) + AS_FLOAT(profit_growth > 0) + AS_FLOAT(prev_profit_growth > 0)) / 4.0
        growth = 0.25 * RANK(MAX(-50.0, MIN(200.0, rev_growth))) + 0.35 * RANK(MAX(-80.0, MIN(500.0, profit_growth))) + 0.15 * RANK(MAX(-100.0, MIN(150.0, rev_growth - prev_rev_growth))) + 0.15 * RANK(MAX(-300.0, MIN(500.0, profit_growth - prev_profit_growth))) + 0.10 * persistence
        quality = 0.35 * RANK(MAX(-0.50, MIN(1.00, ocf / MAX(revenue, 1.0)))) + 0.25 * RANK(MAX(-1.00, MIN(3.00, ocf / MAX(parent_profit, 1.0)))) + 0.20 * RANK(MAX(-5.00, MIN(30.00, roe))) + 0.20 * RANK(MAX(-20.00, MIN(60.00, net_margin)))
        balance = 1.0 - RANK(debt_to_asset)
        score = 0.30 * growth + 0.55 * quality + 0.15 * balance
        return IF((revenue > 0) & (parent_profit > 0), score, 0.0)

