import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


WORKBUDDY = Path(r"C:\Users\69449\WorkBuddy\2026-08-22-20-19-58")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MSEQ = load_module("build_mseq", WORKBUDDY / "dashboard" / "research" / "build_mseq.py")
SIGNAL = load_module("signal_0925", WORKBUDDY / "dashboard" / "signal_0925.py")
FACTORS = load_module("build_factors", WORKBUDDY / "dashboard" / "research" / "build_factors.py")


class MseqTests(unittest.TestCase):
    def test_market_gate_is_not_in_stock_rank(self):
        self.assertNotIn("M", MSEQ.W_TOTAL)
        self.assertAlmostEqual(sum(MSEQ.W_TOTAL.values()), 1.0)
        self.assertEqual(MSEQ.W_TOTAL, {"S": 0.40, "E": 0.35, "Q": 0.25})

    def test_factor_time_gate(self):
        self.assertEqual(MSEQ.factor_usage("2026-08-26", "2026-08-25", "open"), (True, "prior_close"))
        self.assertEqual(MSEQ.factor_usage("2026-08-26", "2026-08-26", "open"), (False, "same_day_blocked"))
        self.assertEqual(MSEQ.factor_usage("2026-08-26", "2026-08-26", "close"), (True, "same_day_close"))
        self.assertEqual(MSEQ.factor_usage("2026-08-26", "2026-08-25", "close"), (False, "stale"))

    def test_signal_parser_keeps_code_and_prefers_target_date(self):
        rows = [{
            "股票代码": "000001.SZ",
            "股票简称": "测试",
            "竞价涨幅[20260825]": 1.0,
            "竞价涨幅[20260826]": 5.0,
            "连续涨停天数": 2,
            "涨停开板次数": 0,
            "成交额": 100000000,
            "所属概念": "人工智能;融资融券",
        }]
        parsed = SIGNAL.parse_rows(rows, SIGNAL.parse_date("2026-08-26"))[0]
        self.assertEqual(parsed["code"], "000001.SZ")
        self.assertEqual(parsed["gap"], 5.0)
        self.assertEqual(parsed["concepts"], ["人工智能"])

    def test_discovery_pool_keeps_repeated_first_board_leader(self):
        rows = [
            {"name": "连板票", "code": "600001.SH", "gap": 5.0, "boards": 3,
             "opens": 0, "jitian": "3天3板", "amount": 2e8,
             "concepts": ["旧题材"], "pop_auction": 70},
            {"name": "神奇制药", "code": "600613.SH", "gap": 7.6, "boards": 1,
             "opens": 1, "jitian": "8天6板", "amount": 1.5e8,
             "concepts": ["医药"], "pop_auction": 48},
            {"name": "普通首板", "code": "600002.SH", "gap": 4.0, "boards": 1,
             "opens": 0, "jitian": "首板涨停", "amount": 1e8,
             "concepts": ["普通题材"], "pop_auction": 35},
        ]
        pool = SIGNAL.discovery_pool(rows, rows[:1])
        self.assertEqual(SIGNAL.parse_board_activity("8天6板", 1), (8, 6))
        self.assertIn("神奇制药", [x["name"] for x in pool])
        magic = next(x for x in pool if x["name"] == "神奇制药")
        self.assertEqual(magic["lane"], "discovery")
        self.assertEqual(magic["recent_board_count"], 6)
        self.assertNotIn("普通首板", [x["name"] for x in pool])

    def test_factor_parser_uses_dated_board_activity_fields(self):
        rows = [{
            "股票代码": "600613.SH", "股票简称": "神奇制药",
            "连续涨停天数[20260824]": 1, "几天几板[20260824]": "8天6板",
            "所属概念[20260824]": "抗肿瘤;医药", "成交额[20260824]": 150000000,
        }]
        _, info = FACTORS.build_hot_board(rows, SIGNAL.parse_date("2026-08-24"))
        self.assertEqual(info["神奇制药"]["boards"], 1)
        self.assertEqual(info["神奇制药"]["recent_board_count"], 6)

    def test_build_blocks_same_day_close_evidence_in_open_phase(self):
        signal = {
            "date": "2026-08-26", "status": "ok", "score": 78, "verdict": "可做",
            "eco": {"points": 24, "limit_up": 70, "limit_down": 4, "failed_rate": 0.2},
            "auction": {"points": 34, "mean_premium": 0.7},
            "leader": {"points": 20},
            "ladder": [
                {"name": "甲", "code": "600001.SH", "gap": 5.0, "boards": 3, "opens": 0,
                 "amount": 100000000, "concepts": ["主题"], "pop_auction": 80, "theme": "主题", "note": ""},
                {"name": "乙", "code": "600002.SH", "gap": 2.0, "boards": 2, "opens": 0,
                 "amount": 90000000, "concepts": ["主题"], "pop_auction": 60, "theme": "主题", "note": ""},
            ],
        }
        factors = {
            "for_date": "2026-08-26",
            "hot_board": [{"concept": "主题", "count": 4, "stocks": [{"name": "甲", "boards": 3}]}],
            "high_candidates": [{"name": "甲", "code": "600001.SH", "r60": 1.1, "first_break": True}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sig_dir = tmp_path / "signals"
            sig_dir.mkdir()
            (sig_dir / "signal_20260826.json").write_text(json.dumps(signal), encoding="utf-8")
            factors_path = tmp_path / "factors.json"
            factors_path.write_text(json.dumps(factors), encoding="utf-8")
            old = MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR
            MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR = str(sig_dir), str(factors_path), str(tmp_path / "out")
            try:
                self.assertEqual(MSEQ.build("2026-08-26", "open"), 0)
                out = json.loads((tmp_path / "out" / "shortterm_factor_preview.json").read_text(encoding="utf-8"))
            finally:
                MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR = old
        self.assertEqual(out["phase"], "open")
        self.assertFalse(out["factor_evidence"]["usable"])
        self.assertEqual(out["factor_evidence"]["reason"], "same_day_blocked")
        self.assertTrue(all(x["code"] for x in out["candidates"]))
        for row in out["candidates"]:
            self.assertAlmostEqual(row["total"], round(0.40 * row["strength"] + 0.35 * row["position"] + 0.25 * row["quality"], 1))

    def test_empty_signal_clears_old_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sig_dir = tmp_path / "signals"
            sig_dir.mkdir()
            (sig_dir / "signal_20260826.json").write_text(
                json.dumps({"date": "2026-08-26", "status": "no_auction", "ladder": []}),
                encoding="utf-8",
            )
            old = MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR
            MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR = str(sig_dir), str(tmp_path / "none.json"), str(tmp_path / "out")
            try:
                self.assertEqual(MSEQ.build("2026-08-26", "open"), 0)
                out = json.loads((tmp_path / "out" / "shortterm_factor_preview.json").read_text(encoding="utf-8"))
            finally:
                MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR = old
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["market"]["position_cap"], 0)

    def test_build_includes_discovery_lane_without_mixing_input(self):
        signal = {
            "date": "2026-08-26", "status": "ok", "score": 78, "verdict": "可做",
            "eco": {"points": 24, "limit_up": 70, "limit_down": 4, "failed_rate": 0.2},
            "auction": {"points": 34, "mean_premium": 0.7},
            "leader": {"points": 20},
            "ladder": [{"name": "连板票", "code": "600001.SH", "gap": 5.0,
                        "boards": 3, "opens": 0, "amount": 100000000,
                        "concepts": ["主题"], "pop_auction": 80, "theme": "主题",
                        "note": "", "lane": "relay"}],
            "discovery": [{"name": "神奇制药", "code": "600613.SH", "gap": 7.6,
                           "boards": 1, "opens": 1, "amount": 150000000,
                           "concepts": ["医药"], "pop_auction": 48, "theme": "医药",
                           "note": "", "lane": "discovery", "recent_days": 8,
                           "recent_board_count": 6, "theme_breadth": 3,
                           "discovery_score": 72.0}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sig_dir = tmp_path / "signals"
            sig_dir.mkdir()
            (sig_dir / "signal_20260826.json").write_text(json.dumps(signal), encoding="utf-8")
            old = MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR
            MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR = str(sig_dir), str(tmp_path / "none.json"), str(tmp_path / "out")
            try:
                self.assertEqual(MSEQ.build("2026-08-26", "open"), 0)
                out = json.loads((tmp_path / "out" / "shortterm_factor_preview.json").read_text(encoding="utf-8"))
            finally:
                MSEQ.SIG_DIR, MSEQ.FACTORS_JSON, MSEQ.OUT_DIR = old
        self.assertEqual(out["pool"]["relay_count"], 1)
        self.assertEqual(out["pool"]["discovery_count"], 1)
        row = next(x for x in out["candidates"] if x["name"] == "神奇制药")
        self.assertEqual(row["lane"], "discovery")
        self.assertEqual(row["recent_board_count"], 6)
        self.assertAlmostEqual(row["total"], round(0.40 * row["strength"] + 0.35 * row["position"] + 0.25 * row["quality"], 1))


if __name__ == "__main__":
    unittest.main()
