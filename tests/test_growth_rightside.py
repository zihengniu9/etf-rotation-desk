import unittest

import pandas as pd

from low_buy_selector.growth_rightside import (
    build_growth_rightside_panel,
    build_market_gate_table,
)


class GrowthRightSideTests(unittest.TestCase):
    def test_market_gate_uses_canonical_eight_and_fifty_percent_thresholds(self):
        trend = pd.DataFrame(
            {
                "date": ["2026-01-31"] * 100,
                "eligible": [True] * 8 + [False] * 92,
                "r20": [0.1] * 50 + [-0.1] * 50,
            }
        )
        gate = build_market_gate_table(trend)
        self.assertTrue(bool(gate.loc[0, "market_gate_pass"]))
        trend.loc[7, "eligible"] = False
        gate = build_market_gate_table(trend)
        self.assertFalse(bool(gate.loc[0, "market_gate_pass"]))

    def test_unified_score_is_separate_from_execution_gate(self):
        growth = pd.DataFrame(
            [
                {
                    "date": "2026-01-31", "code6": "600001", "name": "样本",
                    "financial_score": 80.0, "financial_valid": True,
                    "fwd5": 0.01, "fwd10": 0.02, "fwd20": 0.03,
                    "label_valid5": True, "label_valid10": True, "label_valid20": True,
                }
            ]
        )
        trend_rows = []
        for index in range(100):
            trend_rows.append(
                {
                    "date": "2026-01-31", "code": f"60{index:04d}.SH",
                    "trend_score": 60.0, "eligible": index < 8,
                    "setup": "continuation" if index == 1 else "watch",
                    "r20": 0.1 if index < 50 else -0.1,
                }
            )
        trend = pd.DataFrame(trend_rows)
        panel = build_growth_rightside_panel(growth, trend)
        self.assertAlmostEqual(panel.loc[0, "gr_7030"], 74.0)
        self.assertTrue(bool(panel.loc[0, "market_gate_pass"]))
        self.assertTrue(bool(panel.loc[0, "rightside_tradeable"]))
        panel.loc[0, "market_gate_pass"] = False
        self.assertAlmostEqual(panel.loc[0, "gr_7030"], 74.0)

    def test_breakout_is_not_a_preferred_growth_entry(self):
        growth = pd.DataFrame(
            [{"date": "2026-01-31", "code6": "600001", "name": "样本", "financial_score": 80, "financial_valid": True}]
        )
        trend_rows = [
            {
                "date": "2026-01-31", "code": f"60{index:04d}.SH", "trend_score": 60,
                "eligible": index < 8, "setup": "breakout" if index == 1 else "watch",
                "r20": 0.1 if index < 50 else -0.1,
            }
            for index in range(100)
        ]
        panel = build_growth_rightside_panel(growth, pd.DataFrame(trend_rows))
        self.assertTrue(bool(panel.loc[0, "rightside_structure"]))
        self.assertFalse(bool(panel.loc[0, "rightside_trigger"]))


if __name__ == "__main__":
    unittest.main()

