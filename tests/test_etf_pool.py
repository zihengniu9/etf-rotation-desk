import unittest

import pandas as pd

from low_buy_selector.etf_data_sources import append_supplemental_funds, get_supplemental_funds
from low_buy_selector.etf_pool import (
    build_theme_pool,
    extract_theme,
    normalize_etf_code,
)


class ETFPoolTests(unittest.TestCase):
    def test_normalize_etf_code_removes_market_suffix(self):
        self.assertEqual(normalize_etf_code("512480.XSHG"), "512480")
        self.assertEqual(normalize_etf_code("159509.XSHE"), "159509")

    def test_extract_theme_groups_synonyms(self):
        self.assertEqual(extract_theme("国联安中证全指半导体ETF"), "半导体")
        self.assertEqual(extract_theme("华夏国证芯片ETF"), "半导体")
        self.assertEqual(extract_theme("华夏上证科创板半导体材料设备主题ETF"), "科创半导体")
        self.assertEqual(extract_theme("华泰柏瑞中韩半导体ETF"), "中韩半导体")
        self.assertEqual(extract_theme("易方达国证机器人产业ETF"), "机器人")
        self.assertEqual(extract_theme("华夏沪深300ETF"), "沪深300")
        self.assertEqual(extract_theme("易方达上证科创板50ETF"), "科创")
        self.assertEqual(extract_theme("科创综指ETF东财"), "科创")
        self.assertEqual(extract_theme("华安中证数字经济主题ETF"), "科技成长")
        self.assertEqual(extract_theme("科创债ETF银华"), "债券")

    def test_extract_theme_recognizes_silver_lof(self):
        self.assertEqual(extract_theme("国投瑞银白银期货证券投资基金(LOF)"), "白银")
        self.assertEqual(extract_theme("南方原油证券投资基金(LOF)"), "原油")

    def test_build_theme_pool_keeps_largest_fund_size_per_theme(self):
        etfs = pd.DataFrame(
            [
                {"code": "512480", "name": "国联安中证全指半导体ETF", "latest_nav": 3.0},
                {"code": "159995", "name": "华夏国证芯片ETF", "latest_nav": 2.0},
                {"code": "588170", "name": "华夏上证科创板半导体材料设备主题ETF", "latest_nav": 1.0},
                {"code": "513310", "name": "华泰柏瑞中韩半导体ETF", "latest_nav": 1.0},
                {"code": "159530", "name": "易方达国证机器人产业ETF", "latest_nav": 1.5},
            ]
        )
        scales = pd.DataFrame(
            [
                {"code": "512480", "shares": 100.0},
                {"code": "159995", "shares": 300.0},
                {"code": "588170", "shares": 500.0},
                {"code": "513310", "shares": 400.0},
                {"code": "159530", "shares": 200.0},
            ]
        )

        pool = build_theme_pool(etfs, scales)

        semiconductor = pool[pool["theme"] == "半导体"].iloc[0]
        self.assertEqual(semiconductor["code"], "159995")
        self.assertEqual(semiconductor["fund_size"], 600.0)
        self.assertIn("科创半导体", set(pool["theme"]))
        self.assertIn("中韩半导体", set(pool["theme"]))
        self.assertIn("机器人", set(pool["theme"]))

    def test_supplemental_funds_add_specialty_lof_candidates(self):
        base = pd.DataFrame([{"code": "512480", "name": "国联安半导体ETF", "latest_nav": 3.0}])

        supplemented = append_supplemental_funds(base)
        supplemental = get_supplemental_funds()

        self.assertIn("161226", set(supplemental["code"].astype(str)))
        self.assertIn("513310", set(supplemental["code"].astype(str)))
        self.assertIn("161226", set(supplemented["code"].astype(str)))
        silver = supplemented[supplemented["code"].astype(str) == "161226"].iloc[0]
        self.assertIn("白银", silver["name"])


if __name__ == "__main__":
    unittest.main()
