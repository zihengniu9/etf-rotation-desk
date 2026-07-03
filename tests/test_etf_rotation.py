import unittest

import pandas as pd

from low_buy_selector.etf_rotation import rank_etfs_by_momentum, score_momentum


class ETFRotationTests(unittest.TestCase):
    def test_score_momentum_passes_positive_etf_above_average(self):
        closes = pd.Series([1.00, 1.01, 1.02, 1.03, 1.04, 1.05])
        score = score_momentum(closes, momentum_days=5, bonus=0.02)

        self.assertTrue(score.passed)
        self.assertGreater(score.total_return, 0.01)
        self.assertGreater(score.score, 0)

    def test_score_momentum_fails_when_return_is_too_low(self):
        closes = pd.Series([1.00, 1.00, 1.00, 1.00, 1.00, 1.005])
        score = score_momentum(closes, momentum_days=5, bonus=0.02)

        self.assertFalse(score.passed)
        self.assertIn("return", score.reason)

    def test_rank_etfs_falls_back_to_money_fund_when_none_pass(self):
        pool = pd.DataFrame(
            [
                {"code": "512480", "name": "半导体ETF", "theme": "半导体"},
                {"code": "159530", "name": "机器人ETF", "theme": "机器人"},
            ]
        )
        histories = {
            "512480": pd.DataFrame({"close": [1, 1, 1, 1, 1, 1]}),
            "159530": pd.DataFrame({"close": [1, 0.99, 0.98, 0.97, 0.96, 0.95]}),
        }

        rank, pick = rank_etfs_by_momentum(pool, histories, money_symbol="511880")

        self.assertEqual(pick["code"], "511880")
        self.assertTrue(rank.empty)

    def test_rank_etfs_switches_to_defense_when_top_score_is_weak(self):
        pool = pd.DataFrame(
            [
                {"code": "512480", "name": "semiconductor ETF", "theme": "semiconductor"},
                {"code": "159530", "name": "robot ETF", "theme": "robot"},
            ]
        )
        histories = {
            "512480": pd.DataFrame({"close": [1.00, 1.05, 0.98, 1.08, 0.99, 1.04]}),
            "159530": pd.DataFrame({"close": [1.00, 1.04, 0.99, 1.07, 1.00, 1.035]}),
        }

        rank, pick = rank_etfs_by_momentum(
            pool,
            histories,
            money_symbol="511880",
            defense_threshold=0.6,
            momentum_days=5,
        )

        self.assertFalse(rank.empty)
        self.assertLessEqual(rank.iloc[0]["score"], 0.6)
        self.assertEqual(pick["code"], "511880")
        self.assertEqual(pick["mode"], "defense")
        self.assertIn("defense", pick["reason"])


if __name__ == "__main__":
    unittest.main()
