class GrowthCore(Factor):
    def calculate(self, factors):
        rev_growth = factors["gr_oper_rev_ttm"]
        prev_rev_growth = factors["gr_oper_rev_lyr"]
        profit_growth = factors["gr_np_parent_ttm"]
        prev_profit_growth = factors["gr_np_parent_lyr"]
        revenue = factors["operating_revenue_ttm"]
        parent_profit = factors["net_profit_parent_company_ttm"]
        rev_score = RANK(MAX(-50.0, MIN(200.0, rev_growth)))
        profit_score = RANK(MAX(-80.0, MIN(500.0, profit_growth)))
        rev_accel = RANK(MAX(-100.0, MIN(150.0, rev_growth - prev_rev_growth)))
        profit_accel = RANK(MAX(-300.0, MIN(500.0, profit_growth - prev_profit_growth)))
        persistence = (
            AS_FLOAT(rev_growth > 0)
            + AS_FLOAT(prev_rev_growth > 0)
            + AS_FLOAT(profit_growth > 0)
            + AS_FLOAT(prev_profit_growth > 0)
        ) / 4.0
        score = 0.25 * rev_score + 0.35 * profit_score + 0.15 * rev_accel + 0.15 * profit_accel + 0.10 * persistence
        return IF((revenue > 0) & (parent_profit > 0), score, 0.0)

