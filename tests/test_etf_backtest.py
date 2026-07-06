import unittest

import pandas as pd

from low_buy_selector.etf_backtest import audit_trade_ledger, build_daily_strength_signals, simulate_rotation_backtest


class ETFBacktestTests(unittest.TestCase):
    def test_daily_signals_adjust_split_like_etf_price_breaks(self):
        pool = pd.DataFrame([{"code": "512800", "name": "Bank ETF", "theme": "bank"}])
        history = pd.DataFrame(
            [
                {"date": "2025-06-23", "close": 1.721},
                {"date": "2025-06-24", "close": 1.726},
                {"date": "2025-06-25", "close": 1.744},
                {"date": "2025-06-26", "close": 1.762},
                {"date": "2025-06-27", "close": 1.713},
                {"date": "2025-06-30", "close": 1.711},
                {"date": "2025-07-01", "close": 1.737},
                {"date": "2025-07-02", "close": 1.746},
                {"date": "2025-07-03", "close": 1.746},
                {"date": "2025-07-04", "close": 1.777},
                {"date": "2025-07-07", "close": 0.894},
                {"date": "2025-07-08", "close": 0.891},
            ]
        )

        signals = build_daily_strength_signals(
            pool,
            {"512800": history},
            lookback_days=12,
            momentum_days=2,
            ma_window=2,
            min_total_return=-1.0,
        )

        adjusted_pre_split = float(signals[signals["date"] == "2025-07-04"].iloc[0]["close"])
        post_split = float(signals[signals["date"] == "2025-07-07"].iloc[0]["close"])
        self.assertAlmostEqual(adjusted_pre_split, post_split, places=3)
        self.assertLess(adjusted_pre_split, 1.0)

    def test_simulation_defaults_to_two_half_positions(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.90, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-01", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.70, "close": 30.0, "ma30": 29.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.88, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.82, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.81, "close": 25.0, "ma30": 24.0},
            ]
        )

        curve, trades, positions = simulate_rotation_backtest(signals, initial_cash=1.0, buy_threshold=0.6)

        self.assertEqual(trades["action"].tolist(), ["BUY", "BUY"])
        self.assertEqual(trades["date"].tolist(), ["2026-06-01", "2026-06-01"])
        self.assertEqual(trades["code"].tolist(), ["AAA", "BBB"])
        self.assertAlmostEqual(float(trades.iloc[0]["value"]), 0.5)
        self.assertAlmostEqual(float(curve.iloc[0]["cash"]), 0.0)
        self.assertAlmostEqual(float(curve.iloc[1]["exposure"]), 1.0)
        self.assertEqual(set(positions["code"].tolist()), {"AAA", "BBB"})
        self.assertEqual(audit_trade_ledger(trades, positions), [])
        for column in ["shares", "value", "cost_basis", "realized_pnl", "cash_after", "equity_after"]:
            self.assertIn(column, trades.columns)

    def test_trade_ledger_audit_rejects_sell_without_position(self):
        trades = pd.DataFrame(
            [
                {"date": "2026-06-01", "action": "SELL", "code": "AAA", "shares": 1.0},
            ]
        )

        errors = audit_trade_ledger(trades, pd.DataFrame())

        self.assertTrue(errors)
        self.assertIn("SELL 1.00000000 exceeds held 0.00000000", errors[0])

    def test_trade_ledger_audit_rejects_final_position_mismatch(self):
        trades = pd.DataFrame(
            [
                {"date": "2026-06-01", "action": "BUY", "code": "AAA", "shares": 1.0},
                {"date": "2026-06-02", "action": "SELL", "code": "AAA", "shares": 0.4},
            ]
        )
        positions = pd.DataFrame([{"code": "AAA", "shares": 0.5}])

        errors = audit_trade_ledger(trades, positions)

        self.assertEqual(errors, ["AAA: ledger shares 0.60000000 != position shares 0.50000000"])

    def test_trade_ledger_audit_rejects_more_than_two_open_positions(self):
        trades = pd.DataFrame(
            [
                {"date": "2026-06-01", "action": "BUY", "code": "AAA", "shares": 1.0},
                {"date": "2026-06-01", "action": "BUY", "code": "BBB", "shares": 1.0},
                {"date": "2026-06-01", "action": "BUY", "code": "CCC", "shares": 1.0},
            ]
        )

        errors = audit_trade_ledger(trades, max_positions=2)

        self.assertEqual(errors, ["2026-06-01 CCC row 3: open positions 3 exceeds max 2"])

    def test_full_book_can_replace_weakest_with_stronger_different_theme(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.70, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.62, "close": 8.0, "ma30": 7.5},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "DDD", "name": "Delta ETF", "theme": "beta", "score": 1.10, "close": 40.0, "ma30": 39.5},
                {"date": "2026-06-02", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 1.05, "close": 30.0, "ma30": 29.5},
            ]
        )

        _, trades, positions = simulate_rotation_backtest(
            signals,
            initial_cash=1.0,
            buy_threshold=0.6,
            min_holding_days_before_rebalance=0,
        )

        self.assertEqual(trades["action"].tolist(), ["BUY", "BUY", "SELL", "BUY"])
        self.assertEqual(trades["code"].tolist(), ["BBB", "AAA", "AAA", "CCC"])
        self.assertEqual(trades.iloc[2]["reason"], "replace weaker ETF")
        self.assertEqual(trades.iloc[3]["reason"], "stronger non-theme ETF")
        self.assertAlmostEqual(float(trades.iloc[3]["value"]), 0.4)
        self.assertNotIn("DDD", trades["code"].tolist())
        self.assertEqual(set(positions["code"].tolist()), {"BBB", "CCC"})
        self.assertLessEqual(float(positions["market_value"].max()), 0.5)

    def test_replacement_requires_candidate_score_above_one(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.70, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.62, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.95, "close": 30.0, "ma30": 29.5},
                {"date": "2026-06-03", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.62, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-03", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-03", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 1.00, "close": 30.0, "ma30": 29.5},
                {"date": "2026-06-04", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.62, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-04", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-04", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 1.01, "close": 30.0, "ma30": 29.5},
            ]
        )

        _, trades, positions = simulate_rotation_backtest(
            signals,
            initial_cash=1.0,
            buy_threshold=0.6,
            min_holding_days_before_rebalance=0,
        )

        self.assertEqual(trades["action"].tolist(), ["BUY", "BUY", "SELL", "BUY"])
        self.assertEqual(trades.iloc[2]["date"], "2026-06-04")
        self.assertEqual(trades.iloc[2]["reason"], "replace weaker ETF")
        self.assertEqual(trades.iloc[3]["code"], "CCC")
        self.assertEqual(set(positions["code"].tolist()), {"BBB", "CCC"})

    def test_new_positions_are_not_replaced_before_min_holding_days_but_stop_loss_still_applies(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.70, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.62, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.95, "close": 30.0, "ma30": 29.5},
                {"date": "2026-06-03", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.20, "close": 8.0, "ma30": 9.0},
                {"date": "2026-06-03", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-03", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.95, "close": 30.0, "ma30": 29.5},
                {"date": "2026-06-04", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.20, "close": 7.0, "ma30": 9.0},
                {"date": "2026-06-04", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-04", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.95, "close": 30.0, "ma30": 29.5},
            ]
        )

        _, trades, positions = simulate_rotation_backtest(signals, initial_cash=1.0, buy_threshold=0.6)

        self.assertEqual(trades["action"].tolist(), ["BUY", "BUY", "SELL"])
        self.assertNotIn("replace weaker ETF", trades["reason"].tolist())
        self.assertEqual(trades.iloc[-1]["code"], "AAA")
        self.assertEqual(trades.iloc[-1]["reason"], "two closes below MA30")
        self.assertEqual(set(positions["code"].tolist()), {"BBB"})

    def test_replacement_is_allowed_after_min_holding_days(self):
        rows = [
            {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.70, "close": 10.0, "ma30": 9.5},
            {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 20.0, "ma30": 19.5},
        ]
        for date in ["2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06"]:
            rows.extend(
                [
                    {"date": date, "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.62, "close": 10.0, "ma30": 9.5},
                    {"date": date, "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.75, "close": 20.0, "ma30": 19.5},
                    {"date": date, "code": "CCC", "name": "Core ETF", "theme": "core", "score": 1.05, "close": 30.0, "ma30": 29.5},
                ]
            )
        signals = pd.DataFrame(rows)

        _, trades, positions = simulate_rotation_backtest(
            signals,
            initial_cash=1.0,
            buy_threshold=0.6,
            min_holding_days_before_rebalance=5,
        )

        self.assertEqual(trades["action"].tolist(), ["BUY", "BUY", "SELL", "BUY"])
        self.assertEqual(trades.iloc[2]["date"], "2026-06-06")
        self.assertEqual(trades.iloc[2]["reason"], "replace weaker ETF")
        self.assertEqual(trades.iloc[3]["code"], "CCC")
        self.assertEqual(set(positions["code"].tolist()), {"BBB", "CCC"})

    def test_two_consecutive_losses_cool_down_etf_and_theme(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.90, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.10, "close": 9.0, "ma30": 10.0},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-03", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.10, "close": 8.0, "ma30": 10.0},
                {"date": "2026-06-03", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-04", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.90, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-04", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-05", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.10, "close": 9.0, "ma30": 10.0},
                {"date": "2026-06-05", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-06", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.10, "close": 8.0, "ma30": 10.0},
                {"date": "2026-06-06", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-07", "code": "AAC", "name": "Alpha Plus ETF", "theme": "alpha", "score": 0.96, "close": 12.0, "ma30": 11.5},
                {"date": "2026-06-07", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.95, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-07", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.80, "close": 10.0, "ma30": 9.5},
            ]
        )

        _, trades, positions = simulate_rotation_backtest(
            signals,
            initial_cash=1.0,
            buy_threshold=0.6,
            min_holding_days_before_rebalance=999,
            loss_cooldown_threshold=2,
            loss_cooldown_days=10,
        )

        self.assertEqual(trades[(trades["action"] == "BUY") & (trades["code"] == "AAA")].shape[0], 2)
        self.assertFalse(((trades["date"] == "2026-06-07") & (trades["action"] == "BUY") & (trades["code"].isin(["AAA", "AAC"]))).any())
        self.assertEqual(set(positions["code"].tolist()), {"BBB"})

    def test_replacement_treats_related_themes_as_the_same_bucket(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "科创", "score": 0.70, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "半导体", "score": 0.80, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "科创", "score": 0.62, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "半导体", "score": 0.75, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "CCC", "name": "Core ETF", "theme": "双创", "score": 0.95, "close": 30.0, "ma30": 29.5},
            ]
        )

        _, trades, positions = simulate_rotation_backtest(
            signals,
            initial_cash=1.0,
            buy_threshold=0.6,
            min_holding_days_before_rebalance=0,
        )

        self.assertEqual(trades["action"].tolist(), ["BUY", "BUY"])
        self.assertEqual(set(positions["code"].tolist()), {"AAA", "BBB"})

    def test_simulation_can_limit_one_position_per_theme(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "全指电力", "score": 0.90, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta 电力 ETF", "theme": "clean energy", "score": 0.85, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-01", "code": "CCC", "name": "Core ETF", "theme": "chip", "score": 0.80, "close": 30.0, "ma30": 29.5},
            ]
        )

        _, trades, positions = simulate_rotation_backtest(
            signals,
            position_fraction=0.25,
            max_daily_buys=3,
            max_theme_positions=1,
            buy_threshold=0.6,
        )

        self.assertEqual(trades["code"].tolist(), ["AAA", "CCC"])
        self.assertEqual(set(positions["theme"].tolist()), {"全指电力", "chip"})

    def test_simulation_can_apply_dynamic_exposure_and_theme_cooldown(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.70, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.69, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-01", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.68, "close": 30.0, "ma30": 29.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.10, "close": 9.0, "ma30": 10.0},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.69, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-03", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.10, "close": 8.0, "ma30": 10.0},
                {"date": "2026-06-03", "code": "DDD", "name": "Delta ETF", "theme": "alpha", "score": 0.95, "close": 12.0, "ma30": 11.0},
            ]
        )

        curve, trades, _ = simulate_rotation_backtest(
            signals,
            position_fraction=0.25,
            max_daily_buys=4,
            max_theme_positions=1,
            dynamic_exposure=True,
            theme_cooldown_days=3,
            buy_threshold=0.6,
            below_ma_days_to_sell=2,
        )

        first_day_buys = trades[(trades["date"] == "2026-06-01") & (trades["action"] == "BUY")]
        self.assertEqual(first_day_buys["code"].tolist(), ["AAA", "BBB"])
        self.assertAlmostEqual(float(curve.iloc[0]["exposure"]), 0.5)
        self.assertTrue(((trades["date"] == "2026-06-03") & (trades["action"] == "SELL") & (trades["code"] == "AAA")).any())
        self.assertFalse(((trades["date"] == "2026-06-03") & (trades["action"] == "BUY") & (trades["code"] == "DDD")).any())

    def test_simulation_uses_half_positions_skips_full_book_and_sells_after_two_ma30_breaks(self):
        signals = pd.DataFrame(
            [
                {"date": "2026-06-01", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.70, "close": 10.0, "ma30": 9.5},
                {"date": "2026-06-01", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.65, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-01", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.80, "close": 30.0, "ma30": 29.5},
                {"date": "2026-06-02", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.20, "close": 10.5, "ma30": 9.5},
                {"date": "2026-06-02", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.55, "close": 20.0, "ma30": 19.5},
                {"date": "2026-06-02", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.55, "close": 29.0, "ma30": 30.0},
                {"date": "2026-06-03", "code": "AAA", "name": "Alpha ETF", "theme": "alpha", "score": 0.20, "close": 9.0, "ma30": 9.5},
                {"date": "2026-06-03", "code": "BBB", "name": "Beta ETF", "theme": "beta", "score": 0.76, "close": 21.0, "ma30": 19.5},
                {"date": "2026-06-03", "code": "CCC", "name": "Core ETF", "theme": "core", "score": 0.50, "close": 28.0, "ma30": 30.0},
            ]
        )

        curve, trades, positions = simulate_rotation_backtest(
            signals,
            initial_cash=1.0,
            position_fraction=0.5,
            max_daily_buys=2,
            buy_threshold=0.6,
            ma_window=30,
            below_ma_days_to_sell=2,
        )

        self.assertEqual(len(curve), 3)
        self.assertEqual(trades["action"].tolist(), ["BUY", "BUY", "SELL", "BUY"])
        self.assertEqual(trades.iloc[0]["code"], "CCC")
        self.assertEqual(trades.iloc[1]["code"], "AAA")
        self.assertFalse(((trades["date"] == "2026-06-01") & (trades["code"] == "BBB")).any())
        self.assertEqual(trades.iloc[2]["code"], "CCC")
        self.assertEqual(trades.iloc[2]["reason"], "two closes below MA30")
        self.assertEqual(set(positions["code"].tolist()), {"AAA", "BBB"})
        self.assertLessEqual(float(curve.iloc[-1]["exposure"]), 1.0)


if __name__ == "__main__":
    unittest.main()
