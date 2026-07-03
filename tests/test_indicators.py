import unittest

import pandas as pd

from low_buy_selector.indicators import evaluate_ma5_setup


class IndicatorTests(unittest.TestCase):
    def test_passes_when_ma5_rises_and_close_is_near_ma5(self):
        bars = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=10),
                "close": [10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4, 11.6, 11.7],
            }
        )

        result = evaluate_ma5_setup(bars, min_distance_pct=-1.0, max_distance_pct=3.0)

        self.assertTrue(result.passed)
        self.assertGreater(result.ma5, result.prev_ma5)
        self.assertGreaterEqual(result.distance_pct, -1.0)
        self.assertLessEqual(result.distance_pct, 3.0)

    def test_fails_when_ma5_is_not_rising(self):
        bars = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=6),
                "close": [11.0, 10.8, 10.6, 10.4, 10.2, 10.1],
            }
        )

        result = evaluate_ma5_setup(bars, min_distance_pct=-1.0, max_distance_pct=3.0)

        self.assertFalse(result.passed)
        self.assertIn("MA5 is not rising", result.reason)

    def test_fails_when_close_is_too_far_above_ma5(self):
        bars = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=6),
                "close": [10.0, 10.1, 10.2, 10.3, 10.4, 12.0],
            }
        )

        result = evaluate_ma5_setup(bars, min_distance_pct=-1.0, max_distance_pct=3.0)

        self.assertFalse(result.passed)
        self.assertIn("outside range", result.reason)

    def test_fails_when_latest_ma5_rises_but_recent_ma5_trend_has_pullback(self):
        bars = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=9),
                "close": [10.0, 10.0, 10.0, 10.0, 10.0, 12.0, 8.0, 12.0, 12.0],
            }
        )

        result = evaluate_ma5_setup(
            bars,
            min_distance_pct=-1.0,
            max_distance_pct=20.0,
            ma5_trend_window=5,
        )

        self.assertFalse(result.passed)
        self.assertIn("MA5 trend is not consistently rising", result.reason)

    def test_fails_when_latest_close_has_obvious_recent_drawdown(self):
        bars = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=10),
                "close": [10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 14.0, 13.0, 13.0],
            }
        )

        result = evaluate_ma5_setup(
            bars,
            min_distance_pct=-1.0,
            max_distance_pct=10.0,
            max_recent_drawdown_pct=-5.0,
            drawdown_window=10,
        )

        self.assertFalse(result.passed)
        self.assertIn("recent drawdown", result.reason)


if __name__ == "__main__":
    unittest.main()
