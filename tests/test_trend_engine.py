import unittest

import pandas as pd

from low_buy_selector.trend_engine import (
    calculate_trend_features,
    evaluate_profit_effect,
    is_main_board_code,
    normalize_stock_code,
    score_trend_universe,
)


def synthetic_bars(final_close: float = 110.0, final_amount: float = 150.0) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=141, freq="D")
    close = [100.0] * 140 + [final_close]
    amount = [100.0] * 140 + [final_amount]
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "amount": amount,
        }
    )


class TrendEngineTests(unittest.TestCase):
    def test_mainboard_universe_filter_is_explicit(self):
        self.assertEqual(normalize_stock_code("000001.SZ"), "000001")
        self.assertEqual(normalize_stock_code("600000.SH"), "600000")
        self.assertTrue(is_main_board_code("000001.SZ"))
        self.assertTrue(is_main_board_code("600000.SH"))
        self.assertFalse(is_main_board_code("300001.SZ"))
        self.assertFalse(is_main_board_code("688001.SH"))
        self.assertFalse(is_main_board_code("830001.BJ"))

    def test_breakout_level_excludes_current_bar(self):
        features = calculate_trend_features(synthetic_bars())
        latest = features.iloc[-1]

        self.assertAlmostEqual(float(latest["breakout_level"]), 100.0)
        self.assertTrue(bool(latest["breakout_trigger"]))

    def test_universe_score_returns_breakout_candidate(self):
        features = calculate_trend_features(synthetic_bars())
        scored = score_trend_universe({"000001.SZ": features}, metadata={"000001.SZ": {"name": "测试股"}})

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored.iloc[0]["setup"], "breakout")
        self.assertGreater(float(scored.iloc[0]["trend_score"]), 50)

    def test_missing_history_is_not_silently_filled(self):
        short = synthetic_bars().head(40)
        features = calculate_trend_features(short)
        scored = score_trend_universe({"000001.SZ": features})

        self.assertTrue(scored.empty)

    def test_profit_effect_enters_next_open_and_uses_future_only_for_label(self):
        features = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=8, freq="D"),
                "open": [100, 100, 102, 103, 104, 105, 106, 107],
                "low": [99, 99, 101, 102, 103, 104, 105, 106],
                "close": [100, 100, 102, 105, 106, 108, 109, 110],
                "breakout_trigger": [False, True, False, False, False, False, False, False],
                "pullback_trigger": [False] * 8,
            }
        )
        effect = evaluate_profit_effect(features, horizons=(2,), signal_cooldown=0)

        self.assertEqual(effect["signals"], 1)
        self.assertEqual(effect["horizons"]["2"]["count"], 1)
        self.assertAlmostEqual(effect["horizons"]["2"]["avg_return"], 0.0294117647, places=6)


if __name__ == "__main__":
    unittest.main()
