import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


REVIEW = module("update_latest_review")
FACTOR = module("build_shortterm_close_factor")


class ShorttermMarketTests(unittest.TestCase):
    def stock(self, code, flag="跌停[20260911]"):
        return {"股票代码": code, "股票简称": "样本", flag: True}

    def query(self, responses, flag="跌停[20260911]"):
        iterator = iter(responses)
        with patch.dict(os.environ, {"IWENCAI_API_KEY": "test", "HTTPS_PROXY": "http://localhost"}):
            return REVIEW.query_stock_rows(lambda **kwargs: next(iterator), "query", flag)

    def test_rejects_index_statistics(self):
        with self.assertRaises(RuntimeError):
            self.query([{"code_count": 1, "datas": [{"指数代码": "000171.CSI", "指数@跌停家数[20260911]": 0}]}])

    def test_requires_complete_unique_dated_pool(self):
        a, b = self.stock("600001.SH"), self.stock("000001.SZ")
        self.assertEqual(len(self.query([{"code_count": 2, "datas": [a]}, {"code_count": 2, "datas": [b]}])), 2)
        for batches in [
            [{"code_count": 2, "datas": [a]}, {"code_count": 2, "datas": []}],
            [{"code_count": 2, "datas": [a, a]}],
            [{"code_count": 1, "datas": [self.stock("600001.SH", "跌停[20260910]")]}],
            [{"datas": [a]}],
        ]:
            with self.subTest(batches=batches), self.assertRaises(RuntimeError):
                self.query(batches)
        self.assertEqual(self.query([{"code_count": 0, "datas": []}]), [])

    def test_failed_boards_exclude_resealed_stocks(self):
        market = REVIEW.summarize_market(
            [{"code": "600001.SH", "boards": 2, "break_count": 1}, {"code": "600002.SH", "boards": 1, "break_count": 0}],
            [self.stock("000001.SZ")],
            [self.stock("600001.SH"), self.stock("600003.SH")],
        )
        self.assertEqual(market["failed_count"], 1)
        self.assertEqual(market["touched_limit_up"], 3)
        self.assertEqual(market["failed_rate"], 0.3333)
        self.assertEqual(market["board_break_rate"], 0.5)
        self.assertIsNone(market["index_change"])

    def test_missing_values_never_earn_zero_risk_bonus(self):
        market = {"limit_up": 40, "limit_down": 0, "failed_rate": 0, "max_boards": 4}
        feedback = {"avg_return": 1.025, "positive_ratio": 0.5}
        self.assertEqual(FACTOR.market_score(market, feedback), 69.1)
        for key in market:
            with self.subTest(key=key), self.assertRaises(ValueError):
                FACTOR.market_score({**market, key: None}, feedback)
        with self.assertRaises(ValueError):
            FACTOR.market_score(market, {})
        with self.assertRaises(ValueError):
            FACTOR.market_score({**market, "failed_rate": 31}, feedback)

    def test_existing_risk_veto_precedes_high_rank(self):
        for market, feedback in [({"limit_down": 21}, {}), ({"failed_rate": 0.35}, {}), ({}, {"avg_return": -1})]:
            risks = FACTOR.market_risks(market, feedback)
            self.assertTrue(risks)
            self.assertEqual(FACTOR.market_gate(90, risks)[1], 0)


if __name__ == "__main__":
    unittest.main()
