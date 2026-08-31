import unittest

import pandas as pd

from low_buy_selector.growth_engine import (
    attach_news_evidence,
    build_finance_factors,
    is_main_board_name,
    score_news_records,
)


def finance_rows() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    current = pd.DataFrame(
        [
            {
                "股票代码": "600001.SH", "股票简称": "成长样本",
                "营业收入同比增长率[20260630]": 35, "归母净利润同比增长率[20260630]": 48,
                "经营活动产生的现金流量净额[20260630]": 50, "净资产收益率[20260630]": 15,
                "销售净利率[20260630]": 12, "资产负债率[20260630]": 35,
                "营业收入[20260630]": 100, "归母净利润[20260630]": 10, "总市值[20260827]": 10_000_000_000,
                "动态市盈率[20260827]": 20,
            },
            {
                "股票代码": "300001.SZ", "股票简称": "非主板",
                "营业收入同比增长率[20260630]": 90, "归母净利润同比增长率[20260630]": 90,
                "经营活动产生的现金流量净额[20260630]": 10, "净资产收益率[20260630]": 15,
                "销售净利率[20260630]": 12, "资产负债率[20260630]": 35,
                "营业收入[20260630]": 100, "归母净利润[20260630]": 10, "总市值[20260827]": 10_000_000_000,
                "动态市盈率[20260827]": 20,
            },
        ]
    )
    annual_2025 = pd.DataFrame(
        [{
            "股票代码": "600001.SH", "股票简称": "成长样本",
            "营业收入同比增长率[20251231]": 25, "归母净利润同比增长率[20251231]": 30,
            "经营活动产生的现金流量净额[20251231]": 40, "净资产收益率[20251231]": 12,
            "销售净利率[20251231]": 10, "资产负债率[20251231]": 38,
            "营业收入[20251231]": 80, "归母净利润[20251231]": 8,
        }]
    )
    annual_2024 = pd.DataFrame(
        [{
            "股票代码": "600001.SH", "股票简称": "成长样本",
            "营业收入同比增长率[20241231]": 20, "归母净利润同比增长率[20241231]": 22,
            "经营活动产生的现金流量净额[20241231]": 30, "净资产收益率[20241231]": 10,
            "销售净利率[20241231]": 9, "资产负债率[20241231]": 40,
            "营业收入[20241231]": 60, "归母净利润[20241231]": 6,
        }]
    )
    return current, annual_2025, annual_2024


class GrowthEngineTests(unittest.TestCase):
    def test_main_board_filter(self):
        self.assertTrue(is_main_board_name("600001.SH", "成长样本"))
        self.assertFalse(is_main_board_name("300001.SZ", "创业板"))
        self.assertFalse(is_main_board_name("600002.SH", "ST样本"))

    def test_finance_factors_keep_only_main_board_and_classify_persistence(self):
        current, annual_2025, annual_2024 = finance_rows()
        result = build_finance_factors(current, annual_2025, annual_2024)
        self.assertEqual(list(result["code6"]), ["600001"])
        self.assertEqual(result.loc[0, "growth_profile"], "持续成长")
        self.assertGreater(result.loc[0, "cash_to_profit"], 1)

    def test_finance_factors_apply_explicit_market_cap_floor(self):
        current, annual_2025, annual_2024 = finance_rows()
        current.loc[0, "总市值[20260827]"] = 4_900_000_000
        result = build_finance_factors(current, annual_2025, annual_2024)
        self.assertTrue(result.empty)

    def test_finance_factors_accept_current_wencai_field_aliases(self):
        current, annual_2025, annual_2024 = finance_rows()
        current = current.rename(
            columns={
                "营业收入同比增长率[20260630]": "营业收入(同比增长率)[20260630]",
                "归母净利润同比增长率[20260630]": "归属于母公司所有者的净利润同比增长率[20260630]",
                "净资产收益率[20260630]": "净资产收益率roe(加权,公布值)[20260630]",
                "归母净利润[20260630]": "归属于母公司所有者的净利润[20260630]",
                "动态市盈率[20260827]": "市盈率(pe)[20260827]",
            }
        )
        result = build_finance_factors(current, annual_2025, annual_2024)
        self.assertEqual(int(result["financial_valid"].sum()), 1)
        self.assertEqual(result.loc[0, "current_profit_growth"], 48)
        self.assertEqual(result.loc[0, "current_net_profit"], 10)

    def test_news_excludes_future_and_keeps_negative_evidence(self):
        score = score_news_records(
            [
                {"title": "订单与产能投产", "summary": "客户订单放量", "publish_date": "2026-08-20", "url": "a"},
                {"title": "监管问询与减持", "summary": "风险提示", "publish_date": "2026-08-21", "url": "b"},
                {"title": "未来新闻", "summary": "订单", "publish_date": "2026-09-01", "url": "c"},
            ],
            as_of="2026-08-27",
        )
        self.assertEqual(score["future_news_excluded"], 1)
        self.assertIn("需求订单", score["positive_groups"])
        self.assertIn("治理监管", score["negative_groups"])
        self.assertLess(score["risk_penalty"], 100)

    def test_news_is_only_a_ten_percent_evidence_layer(self):
        current, annual_2025, annual_2024 = finance_rows()
        finance = build_finance_factors(current, annual_2025, annual_2024)
        enriched = attach_news_evidence(
            finance,
            {"600001": [{"title": "订单放量与产能投产", "publish_date": "2026-08-20", "url": "a"}]},
            as_of="2026-08-27",
        )
        self.assertTrue(bool(enriched.loc[0, "news_available"]))
        self.assertGreaterEqual(enriched.loc[0, "final_score"], enriched.loc[0, "growth_core"] - 10)


if __name__ == "__main__":
    unittest.main()
