import unittest

import pandas as pd

from low_buy_selector.etf_cli import merge_historical_rows


class ETFCLITests(unittest.TestCase):
    def test_merge_historical_rows_preserves_old_dates_and_appends_new_dates(self):
        existing = pd.DataFrame(
            [
                {"date": "2026-06-01", "equity": 1.00, "cash": 1.00},
                {"date": "2026-06-02", "equity": 1.02, "cash": 0.75},
            ]
        )
        fresh = pd.DataFrame(
            [
                {"date": "2026-06-02", "equity": 1.03, "cash": 0.80},
                {"date": "2026-06-03", "equity": 1.04, "cash": 0.70},
            ]
        )

        merged = merge_historical_rows(existing, fresh, key_columns=["date"])

        self.assertEqual(merged["date"].tolist(), ["2026-06-01", "2026-06-02", "2026-06-03"])
        self.assertAlmostEqual(float(merged.loc[merged["date"] == "2026-06-02", "equity"].iloc[0]), 1.02)
        self.assertAlmostEqual(float(merged.loc[merged["date"] == "2026-06-01", "equity"].iloc[0]), 1.00)

    def test_merge_historical_rows_keeps_fresh_columns_when_existing_is_empty(self):
        fresh = pd.DataFrame([{"date": "2026-06-03", "equity": 1.04, "cash": 0.70}])

        merged = merge_historical_rows(pd.DataFrame(), fresh, key_columns=["date"])

        self.assertEqual(merged.columns.tolist(), ["date", "equity", "cash"])
        self.assertEqual(len(merged), 1)

    def test_merge_historical_rows_matches_numeric_and_text_key_values(self):
        existing = pd.DataFrame(
            [
                {"date": "2026-05-20", "action": "BUY", "code": 159516, "reason": "stronger non-theme ETF", "value": 0.83},
            ]
        )
        fresh = pd.DataFrame(
            [
                {"date": "2026-05-20", "action": "BUY", "code": "159516", "reason": "stronger non-theme ETF", "value": 0.84},
            ]
        )

        merged = merge_historical_rows(existing, fresh, key_columns=["date", "action", "code", "reason"])

        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(float(merged.iloc[0]["value"]), 0.83)


if __name__ == "__main__":
    unittest.main()
