import unittest

import pandas as pd

from low_buy_selector.etf_cli import (
    apply_realtime_quotes_to_histories,
    filter_backtest_pool,
    filter_trade_ledger_from_date,
    latest_curve_date,
    align_positions_to_trade_ledger,
    merge_historical_rows,
    merge_trade_ledger_rows,
    recalculate_trade_cash_after,
)


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

    def test_merge_trade_ledger_rows_keeps_existing_dates_atomic(self):
        existing = pd.DataFrame(
            [
                {"date": "2026-04-21", "action": "BUY", "code": "159259", "reason": "score above threshold", "shares": 1.0},
                {"date": "2026-04-21", "action": "BUY", "code": "159543", "reason": "score above threshold", "shares": 1.0},
            ]
        )
        fresh = pd.DataFrame(
            [
                {"date": "2026-04-21", "action": "SELL", "code": "159259", "reason": "replace weaker ETF", "shares": 1.0},
                {"date": "2026-04-21", "action": "BUY", "code": "588200", "reason": "stronger non-theme ETF", "shares": 1.0},
                {"date": "2026-04-22", "action": "SELL", "code": "159543", "reason": "two closes below MA30", "shares": 1.0},
            ]
        )

        merged = merge_trade_ledger_rows(existing, fresh)

        self.assertEqual(merged["date"].tolist(), ["2026-04-21", "2026-04-21", "2026-04-22"])
        self.assertEqual(merged["code"].tolist(), ["159259", "159543", "159543"])
        self.assertEqual(merged["action"].tolist(), ["BUY", "BUY", "SELL"])

    def test_merge_trade_ledger_rows_does_not_backfill_old_recomputed_trades(self):
        existing = pd.DataFrame(
            [
                {"date": "2026-04-21", "action": "BUY", "code": "159259", "reason": "score above threshold", "shares": 1.0},
                {"date": "2026-06-02", "action": "SELL", "code": "588690", "reason": "two closes below MA30", "shares": 1.0},
            ]
        )
        fresh = pd.DataFrame(
            [
                {"date": "2025-12-16", "action": "BUY", "code": "563230", "reason": "score above threshold", "shares": 1.0},
                {"date": "2026-04-21", "action": "BUY", "code": "515880", "reason": "score above threshold", "shares": 1.0},
                {"date": "2026-06-03", "action": "BUY", "code": "588200", "reason": "score above threshold", "shares": 1.0},
            ]
        )

        merged = merge_trade_ledger_rows(existing, fresh)

        self.assertEqual(merged["date"].tolist(), ["2026-04-21", "2026-06-02", "2026-06-03"])
        self.assertEqual(merged["code"].tolist(), ["159259", "588690", "588200"])

    def test_merge_trade_ledger_rows_skips_fresh_sell_for_unpreserved_position(self):
        existing = pd.DataFrame(
            [
                {"date": "2026-05-06", "action": "BUY", "code": "588200", "reason": "score above threshold", "shares": 0.25, "value": 0.5, "cash_after": 0.5},
                {"date": "2026-05-13", "action": "BUY", "code": "588690", "reason": "score above threshold", "shares": 0.6, "value": 0.4, "cash_after": 0.1},
                {"date": "2026-06-02", "action": "SELL", "code": "588690", "reason": "two closes below MA30", "shares": 0.6, "value": 0.42, "cash_after": 0.52},
            ]
        )
        fresh = pd.DataFrame(
            [
                {"date": "2026-05-20", "action": "BUY", "code": "588770", "reason": "score above threshold", "shares": 0.4, "value": 0.45, "cash_after": 0.55},
                {"date": "2026-06-11", "action": "SELL", "code": "588770", "reason": "two closes below MA30", "shares": 0.4, "value": 0.46, "cash_after": 1.01},
                {"date": "2026-06-12", "action": "BUY", "code": "513310", "reason": "score above threshold", "shares": 0.1, "value": 0.3, "cash_after": 0.71},
            ]
        )

        merged = merge_trade_ledger_rows(existing, fresh)

        self.assertEqual(merged["date"].tolist(), ["2026-05-06", "2026-05-13", "2026-06-02", "2026-06-12"])
        self.assertEqual(merged["code"].tolist(), ["588200", "588690", "588690", "513310"])
        self.assertEqual(merged["action"].tolist(), ["BUY", "BUY", "SELL", "BUY"])
        self.assertAlmostEqual(float(merged.iloc[-1]["cash_after"]), 0.22)

    def test_recalculate_trade_cash_after_uses_merged_trade_values(self):
        trades = pd.DataFrame(
            [
                {"date": "2026-06-01", "action": "BUY", "code": "AAA", "value": 0.5, "cash_after": 0.5},
                {"date": "2026-06-02", "action": "SELL", "code": "AAA", "value": 0.55, "cash_after": 0.9},
                {"date": "2026-06-03", "action": "BUY", "code": "BBB", "value": 0.4, "cash_after": 0.6},
            ]
        )

        recalculated = recalculate_trade_cash_after(trades)

        self.assertEqual(recalculated["cash_after"].round(8).tolist(), [0.5, 1.05, 0.65])

    def test_merge_trade_ledger_rows_respects_existing_theme_position_limit(self):
        existing = pd.DataFrame(
            [
                {"date": "2026-05-06", "action": "BUY", "code": "588200", "theme": "科创半导体", "shares": 0.25, "value": 0.5, "cash_after": 0.5},
            ]
        )
        fresh = pd.DataFrame(
            [
                {"date": "2026-07-07", "action": "BUY", "code": "588170", "theme": "科创半导体", "shares": 0.6, "value": 0.4, "cash_after": 0.6},
                {"date": "2026-07-08", "action": "BUY", "code": "159841", "theme": "证券", "shares": 0.3, "value": 0.2, "cash_after": 0.4},
            ]
        )

        merged = merge_trade_ledger_rows(existing, fresh, max_positions=2, max_theme_positions=1)

        self.assertEqual(merged["code"].tolist(), ["588200", "159841"])

    def test_align_positions_to_trade_ledger_uses_preserved_open_shares(self):
        trades = pd.DataFrame(
            [
                {
                    "date": "2026-05-06",
                    "action": "BUY",
                    "code": "588200",
                    "name": "Chip ETF",
                    "theme": "chip",
                    "shares": 0.23346574,
                    "value": 0.76109833,
                    "cost_basis": 0.76109833,
                    "cash_after": 0.0,
                },
                {
                    "date": "2026-06-02",
                    "action": "SELL",
                    "code": "588690",
                    "name": "Other ETF",
                    "theme": "other",
                    "shares": 1.0,
                    "value": 0.78,
                    "cost_basis": 0.84,
                    "cash_after": 0.79209388,
                },
            ]
        )
        positions = pd.DataFrame(
            [
                {
                    "code": "588200",
                    "name": "Chip ETF",
                    "theme": "chip",
                    "shares": 0.24115872,
                    "entry_price": 3.1,
                    "last_price": 4.5,
                    "score": 0.7,
                    "ma30": 4.0,
                    "below_ma_days": 0,
                }
            ]
        )

        aligned = align_positions_to_trade_ledger(trades, positions)

        self.assertAlmostEqual(float(aligned.iloc[0]["shares"]), 0.23346574)
        self.assertAlmostEqual(float(aligned.iloc[0]["entry_price"]), 3.26, places=2)
        self.assertAlmostEqual(float(aligned.iloc[0]["last_price"]), 4.5)
        self.assertAlmostEqual(float(aligned.iloc[0]["market_value"]), 0.23346574 * 4.5)

    def test_latest_curve_date_uses_last_backtest_row(self):
        curve = pd.DataFrame([{"date": "2026-07-01"}, {"date": "2026-07-02"}])

        self.assertEqual(latest_curve_date(curve), "2026-07-02")
        self.assertEqual(latest_curve_date(pd.DataFrame()), "")

    def test_filter_backtest_pool_excludes_lof_from_simulated_trading(self):
        pool = pd.DataFrame(
            [
                {"code": "161226", "name": "国投瑞银白银期货证券投资基金(LOF)", "fund_type": "LOF"},
                {"code": "588200", "name": "嘉实上证科创板芯片ETF", "fund_type": "股票型"},
                {"code": "513310", "name": "华泰柏瑞中韩半导体ETF", "fund_type": "ETF"},
            ]
        )

        filtered = filter_backtest_pool(pool, excluded_fund_types="LOF")

        self.assertNotIn("161226", set(filtered["code"].astype(str)))
        self.assertIn("588200", set(filtered["code"].astype(str)))
        self.assertIn("513310", set(filtered["code"].astype(str)))

    def test_filter_trade_ledger_keeps_opening_trade_before_start_date(self):
        trades = pd.DataFrame(
            [
                {"date": "2025-06-24", "action": "BUY", "code": "512800", "shares": 10.0},
                {"date": "2025-06-25", "action": "BUY", "code": "AAAAAA", "shares": 1.0},
                {"date": "2025-06-26", "action": "SELL", "code": "AAAAAA", "shares": 1.0},
                {"date": "2025-07-25", "action": "SELL", "code": "512800", "shares": 10.0},
            ]
        )

        filtered = filter_trade_ledger_from_date(trades, "2025-06-28")

        self.assertEqual(filtered["code"].tolist(), ["512800", "512800"])
        self.assertEqual(filtered["date"].tolist(), ["2025-06-24", "2025-07-25"])

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
