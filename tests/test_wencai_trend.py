import unittest

import pandas as pd

from low_buy_selector.wencai_trend import (
    build_wencai_label_query,
    build_wencai_query,
    build_market_decision,
    merge_wencai_responses,
    normalize_wencai_response,
    score_wencai_cross_section,
)


class WencaiTrendTests(unittest.TestCase):
    def test_query_separates_signal_and_forward_labels(self):
        query = build_wencai_query("2026-06-30", include_forward=True)
        self.assertIn("2026年6月30日前60个交易日最高价", query)
        self.assertIn("2026年6月30日后第1个交易日开盘价（前复权）", query)
        self.assertIn("2026年6月30日后第1个交易日最低价（前复权）", query)
        self.assertIn("2026年6月30日后第20个交易日收盘价（前复权）", query)
        labels = build_wencai_label_query("2026-06-30")
        self.assertNotIn("20日均线", labels)
        self.assertIn("后第10个交易日收盘价（前复权）", labels)

    def test_parser_uses_dated_columns_and_forward_returns(self):
        response = {
            "columns": [
                {"index_name": "股票代码", "key": "股票代码"},
                {"index_name": "股票简称", "key": "股票简称"},
                {"index_name": "收盘价:前复权", "key": "收盘价[20260630]", "timestamp": "20260630"},
                {"index_name": "均线", "key": "20日均线[20260630]", "timestamp": "20260630"},
                {"index_name": "均线", "key": "60日均线[20260630]", "timestamp": "20260630"},
                {"index_name": "均线", "key": "120日均线[20260630]", "timestamp": "20260630"},
                {"index_name": "涨跌幅", "key": "r20", "timestamp": "20260601-20260629"},
                {"index_name": "涨跌幅", "key": "r60", "timestamp": "20260331-20260629"},
                {"index_name": "涨跌幅", "key": "r120", "timestamp": "20251225-20260629"},
                {"index_name": "最高价最大值", "key": "high60", "timestamp": "20260331-20260629"},
                {"index_name": "量比", "key": "vr", "timestamp": "20260630"},
                {"index_name": "成交额", "key": "amount", "timestamp": "20260630"},
                {"index_name": "换手率", "key": "turnover", "timestamp": "20260630"},
                {"index_name": "开盘价:前复权", "key": "entry", "timestamp": "20260701"},
                {"index_name": "最低价:前复权", "key": "entry_low", "timestamp": "20260701"},
                {"index_name": "收盘价:前复权", "key": "exit5", "timestamp": "20260707"},
                {"index_name": "收盘价:前复权", "key": "exit10", "timestamp": "20260714"},
                {"index_name": "收盘价:前复权", "key": "exit20", "timestamp": "20260728"},
                {"index_name": "区间最低价:前复权", "key": "low5", "timestamp": "20260702-20260707"},
                {"index_name": "区间最低价:前复权", "key": "low10", "timestamp": "20260702-20260714"},
                {"index_name": "区间最低价:前复权", "key": "low20", "timestamp": "20260702-20260728"},
            ],
            "datas": [{
                "股票代码": "600001.SH", "股票简称": "测试", "收盘价[20260630]": 10,
                "20日均线[20260630]": 9.5, "60日均线[20260630]": 9, "120日均线[20260630]": 8,
                "r20": 10, "r60": 20, "r120": 30, "high60": 10.1, "vr": 1.4,
                "amount": 200000000, "turnover": 3, "entry": 10, "exit5": 11, "exit10": 12, "exit20": 13,
                "entry_low": 9.9, "low5": 9.8, "low10": 9.7, "low20": 9.5,
            }],
        }
        frame = normalize_wencai_response(response, "2026-06-30")
        self.assertAlmostEqual(float(frame.iloc[0]["r20"]), 0.10)
        self.assertAlmostEqual(float(frame.iloc[0]["fwd10"]), 0.20)
        self.assertAlmostEqual(float(frame.iloc[0]["mae20"]), -0.05)

    def test_score_requires_liquid_full_alignment(self):
        frame = pd.DataFrame({
            "date": ["2026-06-30"], "code": ["600001.SH"], "name": ["测试"], "theme": ["行业"],
            "close": [10.0], "ma20": [9.5], "ma60": [9.0], "ma120": [8.0],
            "r20": [0.10], "r60": [0.20], "r120": [0.30], "prior_high60": [10.05],
            "volume_ratio": [1.4], "amount": [200_000_000], "turnover": [3.0],
            "entry": [10.0], "exit5": [10.5], "exit10": [11.0], "exit20": [11.5],
            "low5": [9.8], "low10": [9.7], "low20": [9.5],
            "fwd5": [0.05], "fwd10": [0.10], "fwd20": [0.15],
            "mae5": [-0.02], "mae10": [-0.03], "mae20": [-0.05],
        })
        scored = score_wencai_cross_section(frame)
        self.assertTrue(bool(scored.iloc[0]["eligible"]))
        self.assertEqual(scored.iloc[0]["setup"], "breakout")

    def test_missing_range_high_does_not_poison_composite_score(self):
        frame = pd.DataFrame({
            "date": ["2026-06-30"], "code": ["600001.SH"], "name": ["测试"], "theme": ["行业"],
            "close": [10.0], "ma20": [9.5], "ma60": [9.0], "ma120": [8.0],
            "r20": [0.10], "r60": [0.20], "r120": [0.30], "prior_high60": [float("nan")],
            "volume_ratio": [1.4], "amount": [200_000_000], "turnover": [3.0],
        })
        scored = score_wencai_cross_section(frame)
        self.assertTrue(pd.notna(scored.iloc[0]["trend_score"]))
        self.assertEqual(float(scored.iloc[0]["breakout_score"]), 0.0)

    def test_parser_prefers_front_adjusted_fields_and_skips_entry_day_close(self):
        response = {
            "columns": [
                {"index_name": "股票代码", "key": "股票代码"},
                {"index_name": "股票简称", "key": "股票简称"},
                {"index_name": "开盘价:不复权", "key": "entry_raw", "timestamp": "20260701"},
                {"index_name": "开盘价_前复权", "key": "entry_adj", "timestamp": "20260701"},
                {"index_name": "收盘价_前复权", "key": "entry_close", "timestamp": "20260701"},
                {"index_name": "收盘价:不复权", "key": "exit5_raw", "timestamp": "20260707"},
                {"index_name": "收盘价_前复权", "key": "exit5_adj", "timestamp": "20260707"},
                {"index_name": "收盘价_前复权", "key": "exit10_adj", "timestamp": "20260714"},
                {"index_name": "收盘价_前复权", "key": "exit20_adj", "timestamp": "20260728"},
            ],
            "datas": [{
                "股票代码": "600001.SH", "股票简称": "测试", "entry_raw": 20,
                "entry_adj": 10, "entry_close": 10.2, "exit5_raw": 30,
                "exit5_adj": 11, "exit10_adj": 12, "exit20_adj": 13,
            }],
        }
        frame = normalize_wencai_response(response, "2026-06-30")
        self.assertAlmostEqual(float(frame.iloc[0]["entry"]), 10.0)
        self.assertAlmostEqual(float(frame.iloc[0]["fwd5"]), 0.10)

    def test_feature_and_label_responses_merge_by_code(self):
        features = {
            "columns": [
                {"index_name": "股票代码", "key": "股票代码"},
                {"index_name": "收盘价:前复权", "key": "close", "timestamp": "20260630"},
            ],
            "datas": [{"股票代码": "600001.SH", "close": 10}],
        }
        labels = {
            "columns": [
                {"index_name": "股票代码", "key": "股票代码"},
                {"index_name": "开盘价:前复权", "key": "entry", "timestamp": "20260701"},
            ],
            "datas": [{"股票代码": "600001.SH", "entry": 10.2}],
        }
        merged = merge_wencai_responses(features, labels)
        self.assertEqual(len(merged["datas"]), 1)
        self.assertEqual(merged["datas"][0]["close"], 10)
        self.assertEqual(merged["datas"][0]["entry"], 10.2)

    def test_market_gate_requires_eight_percent_established_trends(self):
        current = pd.DataFrame({
            "eligible": [True, True] + [False] * 98,
            "r20": [0.05] * 80 + [-0.05] * 20,
            "full_alignment": [True] * 5 + [False] * 95,
        })
        decision = build_market_decision(current)
        self.assertFalse(decision["allow_new_entries"])
        self.assertEqual(decision["mode"], "趋势模式关闭")

        current.loc[:9, "eligible"] = True
        decision = build_market_decision(current)
        self.assertTrue(decision["allow_new_entries"])
        self.assertEqual(decision["default_holding_days"], 10)


if __name__ == "__main__":
    unittest.main()
