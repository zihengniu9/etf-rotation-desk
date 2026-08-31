import unittest

import pandas as pd

from low_buy_selector.dividend_engine import build_dividend_factors, build_dividend_snapshot


def sample_frame() -> pd.DataFrame:
    rows = []
    industries = ["公用事业", "公用事业", "公用事业", "公用事业", "公用事业", "汽车", "交通运输"]
    for index, industry in enumerate(industries):
        scale = index + 1
        rows.append(
            {
                "股票代码": f"6000{index:02d}.SH",
                "股票简称": f"样本{index}",
                "所属同花顺行业": industry,
                "股票市场类型": "沪市A股",
                "最新价[20260828]": 10 + index,
                "最新涨跌幅[20260828]": index - 2,
                "总市值[20260828]": 10_000_000_000 + index,
                "股息率[20260828]": 2.5 + index * 0.4,
                "市盈率(pe,ttm)[20260828]": 16 - index,
                "市净率(pb)[20260828]": 2.2 - index * 0.1,
                "现金分红总额[20231231]": 100 * scale,
                "现金分红总额[20241231]": 105 * scale,
                "现金分红总额[20251231]": 110 * scale,
                "经营活动产生的现金流量净额[20231231]": 400 * scale,
                "经营活动产生的现金流量净额[20241231]": 420 * scale,
                "经营活动产生的现金流量净额[20251231]": 450 * scale,
                "归属于母公司股东的净利润[20231231]": 250 * scale,
                "归属于母公司股东的净利润[20241231]": 270 * scale,
                "归属于母公司股东的净利润[20251231]": 300 * scale,
            }
        )
    return pd.DataFrame(rows)


class DividendEngineTests(unittest.TestCase):
    def test_dividend_factor_has_three_independent_subscores(self):
        result = build_dividend_factors(sample_frame())
        self.assertEqual(len(result), 7)
        self.assertTrue(result["financial_valid"].all())
        self.assertTrue(result["dqc_score"].notna().all())
        self.assertTrue(result["valuation_score"].between(0, 100).all())
        self.assertTrue(result["dividend_score"].between(0, 100).all())
        self.assertTrue(result["cashflow_score"].between(0, 100).all())

    def test_dividend_factor_flags_value_trap_without_hiding_score(self):
        frame = sample_frame()
        frame.loc[0, "现金分红总额[20251231]"] = 10
        frame.loc[0, "归属于母公司股东的净利润[20251231]"] = 40
        frame.loc[0, "经营活动产生的现金流量净额[20251231]"] = 20
        result = build_dividend_factors(frame).set_index("code6")
        row = result.loc["600000"]
        self.assertTrue(bool(row["dividend_drop_flag"]))
        self.assertTrue(bool(row["profit_drop_flag"]))
        self.assertGreaterEqual(row["risk_flag_count"], 2)
        self.assertEqual(row["research_status"], "价值陷阱复核")

    def test_snapshot_caps_each_industry_and_marks_backtest_pending(self):
        snapshot, _ = build_dividend_snapshot(
            sample_frame(),
            as_of="2026-08-28",
            source="test",
            query="test query",
            top=6,
            max_per_industry=2,
        )
        industries = [item["industry"] for item in snapshot["candidates"]]
        self.assertLessEqual(industries.count("公用事业"), 2)
        self.assertEqual(snapshot["validation"]["panda_backtest"], "pending_parameter_confirmation")
        self.assertFalse(snapshot["validation"]["backtest_claim_allowed"])


if __name__ == "__main__":
    unittest.main()
