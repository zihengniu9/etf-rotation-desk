import unittest

import pandas as pd

from low_buy_selector.etf_cli import apply_realtime_quotes_to_histories, latest_curve_date, merge_historical_rows


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

    def test_merge_historical_rows_can_preserve_from_start_date(self):
        existing = pd.DataFrame(
            [
                {"date": "2025-06-24", "action": "BUY", "code": "512800", "value": 0.50},
                {"date": "2025-06-30", "action": "BUY", "code": "515880", "value": 0.49},
            ]
        )
        fresh = pd.DataFrame(
            [
                {"date": "2025-06-30", "action": "BUY", "code": "515880", "value": 0.51},
                {"date": "2026-07-04", "action": "SELL", "code": "588200", "value": 0.62},
            ]
        )

        merged = merge_historical_rows(
            existing,
            fresh,
            key_columns=["date", "action", "code"],
            min_date="2025-06-28",
        )

        self.assertEqual(merged["date"].tolist(), ["2025-06-30", "2026-07-04"])
        self.assertAlmostEqual(float(merged.loc[merged["date"] == "2025-06-30", "value"].iloc[0]), 0.49)

    def test_latest_curve_date_uses_last_backtest_row(self):
        curve = pd.DataFrame([{"date": "2026-07-01"}, {"date": "2026-07-02"}])

        self.assertEqual(latest_curve_date(curve), "2026-07-02")
        self.assertEqual(latest_curve_date(pd.DataFrame()), "")

    def test_realtime_quotes_append_intraday_close_when_daily_history_is_stale(self):
        histories = {
            "159516": pd.DataFrame(
                [
                    {"date": "2026-07-01", "open": 1.9, "high": 2.0, "low": 1.8, "close": 1.99},
                    {"date": "2026-07-02", "open": 1.86, "high": 1.93, "low": 1.79, "close": 1.794},
                ]
            )
        }
        quotes = pd.DataFrame(
            [
                {"code": "159516", "realtime_price": 1.88, "realtime_date": "2026-07-03", "realtime_updated_at": "2026-07-03 14:30:05"},
            ]
        )

        patched, count, data_date = apply_realtime_quotes_to_histories(histories, quotes)

        self.assertEqual(count, 1)
        self.assertEqual(data_date, "2026-07-03")
        self.assertEqual(patched["159516"]["date"].tolist(), ["2026-07-01", "2026-07-02", "2026-07-03"])
        self.assertAlmostEqual(float(patched["159516"].iloc[-1]["close"]), 1.88)
        self.assertAlmostEqual(float(patched["159516"].iloc[-1]["open"]), 1.88)

    def test_realtime_quotes_replace_same_day_close_but_ignore_stale_quotes(self):
        histories = {
            "159516": pd.DataFrame([{"date": "2026-07-03", "open": 1.8, "high": 1.9, "low": 1.7, "close": 1.82}]),
            "588200": pd.DataFrame([{"date": "2026-07-03", "open": 4.0, "high": 4.5, "low": 3.9, "close": 4.1}]),
        }
        quotes = pd.DataFrame(
            [
                {"code": "159516", "realtime_price": 1.86, "realtime_date": "2026-07-03"},
                {"code": "588200", "realtime_price": 4.2, "realtime_date": "2026-07-02"},
            ]
        )

        patched, count, data_date = apply_realtime_quotes_to_histories(histories, quotes)

        self.assertEqual(count, 1)
        self.assertEqual(data_date, "2026-07-03")
        self.assertAlmostEqual(float(patched["159516"].iloc[-1]["close"]), 1.86)
        self.assertAlmostEqual(float(patched["588200"].iloc[-1]["close"]), 4.1)


if __name__ == "__main__":
    unittest.main()
