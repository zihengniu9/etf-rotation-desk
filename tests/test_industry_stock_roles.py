import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_industry_stock_roles.py"
SPEC = importlib.util.spec_from_file_location("industry_stock_roles", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IndustryStockRolesTests(unittest.TestCase):
    def test_normalize_dated_market_columns(self):
        rows = MODULE.normalize_stock_rows(
            [
                {
                    "股票代码": "000001.SZ",
                    "股票简称": "示例股份",
                    "最新价": "10.2",
                    "涨跌幅[20260814]": 3.5,
                    "成交额[20260814]": 125000000,
                    "换手率[20260814]": 6.2,
                    "个股热度[20260816]": 900000,
                    "所属同花顺行业": ["小金属"],
                }
            ],
            "小金属",
        )
        self.assertEqual(rows[0]["code"], "000001")
        self.assertEqual(rows[0]["change"], 3.5)
        self.assertEqual(rows[0]["amount"], 125000000)
        self.assertEqual(rows[0]["heat"], 900000)

    def test_roles_are_distinct_stock_records(self):
        rows = [
            {"code": "000001", "name": "情绪股", "change": 10, "amount": 100, "heat": 100, "turnover_rate": 8},
            {"code": "000002", "name": "中军股", "change": 2, "amount": 500, "heat": 70, "turnover_rate": 4},
            {"code": "000003", "name": "扩散股", "change": 5, "amount": 80, "heat": 40, "turnover_rate": 12},
        ]
        roles = MODULE.score_roles(rows)
        self.assertIsNotNone(roles)
        self.assertEqual(roles["leader"]["code"], "000001")
        self.assertEqual(roles["center"]["code"], "000002")
        self.assertEqual(roles["spread"]["code"], "000003")

    def test_hot_rank_is_aggregated_by_industry(self):
        rows = [
            {"code": "000001", "name": "热度一", "heat": 100, "hot_rank": 1, "industries": ["医药生物", "化学制药"]},
            {"code": "000002", "name": "热度二", "heat": 80, "hot_rank": 4, "industries": ["医药生物", "化学制药"]},
            {"code": "000003", "name": "热度三", "heat": 60, "hot_rank": 8, "industries": ["电子", "半导体"]},
        ]
        stats = MODULE.build_hot_industry_stats(rows, {"化学制药", "半导体"})
        self.assertEqual(stats["化学制药"]["count"], 2)
        self.assertEqual(stats["化学制药"]["leader"]["code"], "000001")
        self.assertEqual(stats["半导体"]["top_rank"], 8)


if __name__ == "__main__":
    unittest.main()
