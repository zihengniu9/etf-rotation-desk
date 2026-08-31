import unittest

import pandas as pd

from low_buy_selector.growth_backtest import (
    build_point_in_time_panel,
    evaluate_factor,
    normalize_report_snapshot,
)


def report_frame(period: str, announce_date: str, profit_growth: float, code: str = "600001.SH") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "股票代码": code,
                "股票简称": "成长样本",
                f"公告日期[{period}]": announce_date,
                f"营业收入同比增长率[{period}]": 20 + profit_growth / 10,
                f"归母净利润同比增长率[{period}]": profit_growth,
                f"经营活动产生的现金流量净额[{period}]": 20,
                f"净资产收益率[{period}]": 12,
                f"销售净利率[{period}]": 10,
                f"资产负债率[{period}]": 35,
                f"营业收入[{period}]": 100,
                f"归母净利润[{period}]": 10,
            }
        ]
    )


class GrowthBacktestTests(unittest.TestCase):
    def test_normalize_report_keeps_announcement_date(self):
        frame = normalize_report_snapshot(report_frame("20241231", "20250423", 30), "20241231")
        self.assertEqual(frame.loc[0, "code6"], "600001")
        self.assertEqual(frame.loc[0, "announce_date"], pd.Timestamp("2025-04-23"))

    def test_same_day_announcement_is_not_available_at_signal_close(self):
        reports = pd.concat(
            [
                normalize_report_snapshot(report_frame("20230930", "20231020", 10), "20230930"),
                normalize_report_snapshot(report_frame("20231231", "20240320", 20), "20231231"),
                normalize_report_snapshot(report_frame("20240331", "20240430", 80), "20240331"),
            ],
            ignore_index=True,
        )
        market = pd.DataFrame(
            [
                {
                    "date": "2024-04-30", "code": "600001.SH", "name": "成长样本",
                    "amount": 100_000_000, "fwd5": 0.05, "fwd10": 0.06, "fwd20": 0.08,
                    "label_valid5": True, "label_valid10": True, "label_valid20": True,
                }
            ]
        )
        panel = build_point_in_time_panel(reports, market)
        self.assertEqual(panel.loc[0, "current_report_period"], pd.Timestamp("2023-12-31"))
        self.assertEqual(panel.loc[0, "current_profit_growth"], 20)
        self.assertIn("balanced_gq", panel.columns)

    def test_factor_evaluation_uses_high_score_as_long_side(self):
        rows = []
        for date in ("2025-01-31", "2025-02-28"):
            for index in range(100):
                rows.append(
                    {
                        "date": date,
                        "code6": f"60{index:04d}",
                        "financial_valid": True,
                        "factor": index,
                        "fwd5": index / 10000,
                        "label_valid5": True,
                    }
                )
        result = evaluate_factor(pd.DataFrame(rows), "factor", 5, one_way_cost=0.0)
        self.assertGreater(result["ic"]["rank_ic_mean"], 0.99)
        self.assertGreater(result["top_n"]["10"]["raw"]["mean"], 0.009)
        self.assertGreater(result["deciles"]["monotonicity"], 0.99)


if __name__ == "__main__":
    unittest.main()
