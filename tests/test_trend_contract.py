import unittest

import pandas as pd

from low_buy_selector.trend_contract import (
    CANONICAL_HORIZON,
    CANONICAL_STRATEGY,
    CANONICAL_TREND_VERSION,
    apply_canonical_scores,
)


def contract_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["600000.SH", "600001.SH"],
            "close": [10.0, 10.0],
            "ma20": [9.8, 9.8],
            "ma60": [9.5, 9.5],
            "ma120": [9.0, 9.0],
            "r20": [0.10, 0.08],
            "r60": [0.20, 0.18],
            "r120": [0.30, 0.28],
            "prior_high60": [10.05, 9.95],
            "volume_ratio": [1.4, 0.9],
            "amount": [200_000_000, 200_000_000],
            "turnover": [3.0, 3.0],
            "fwd10": [0.90, -0.90],
        }
    )


class TrendContractTests(unittest.TestCase):
    def test_contract_metadata_is_explicit(self):
        self.assertEqual(CANONICAL_TREND_VERSION, "trend-standard-v1")
        self.assertEqual(CANONICAL_STRATEGY, "健康延续")
        self.assertEqual(CANONICAL_HORIZON, 10)

    def test_forward_labels_do_not_change_score_or_setup(self):
        first = apply_canonical_scores(contract_frame())
        changed = contract_frame()
        changed["fwd10"] = [-0.99, 0.99]
        second = apply_canonical_scores(changed)
        columns = ["code", "trend_score", "eligible", "setup", "breakout_trigger", "pullback_trigger"]
        pd.testing.assert_frame_equal(first[columns], second[columns])

    def test_setup_priority_is_breakout_then_pullback_then_continuation(self):
        scored = apply_canonical_scores(contract_frame())
        self.assertEqual(scored.loc[scored["code"] == "600000.SH", "setup"].iloc[0], "breakout")
        self.assertEqual(scored.loc[scored["code"] == "600001.SH", "setup"].iloc[0], "pullback")


if __name__ == "__main__":
    unittest.main()
