import json
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_latest_review as review  # noqa: E402

DAY, PRIOR = "20261016", "20261015"


def stock(code, name, **flags):
    return {"股票代码": code, "股票简称": name, **flags}


def fake_wencai(answers):
    """answers: list of (substring, rows). The first substring found in the query wins; unknown queries return 0 rows."""
    def query(query, page, limit, **_):
        for needle, rows in answers:
            if needle in query:
                if isinstance(rows, Exception):
                    raise rows
                return {"code_count": len(rows), "datas": rows if page == "1" else []}
        return {"code_count": 0, "datas": []}
    return query


LEADERS = [stock("600001.SH", "甲", **{f"涨停[{DAY}]": True, "连续涨停天数": 3}), stock("000002.SZ", "乙", **{f"涨停[{DAY}]": True, "连续涨停天数": 1})]
DOWN = [stock("600003.SH", "丙", **{f"跌停[{DAY}]": True})]
OPENED = [stock("600001.SH", "甲", **{f"曾涨停[{DAY}]": True}), stock("600004.SH", "丁", **{f"曾涨停[{DAY}]": True})]
FEEDBACK = [stock("600005.SH", "戊", **{f"涨停[{PRIOR}]": True, f"涨跌幅[{DAY}]": 2.5})]


def run(answers):
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.dict(os.environ, {"IWENCAI_API_KEY": "k", "HTTPS_PROXY": "http://127.0.0.1:1"}), \
            mock.patch.object(review, "load_query_function", return_value=fake_wencai(answers)):
        out = Path(tmp) / "latest_market_review.json"
        history = Path(tmp) / "daily_seal_history.json"
        history.write_text(json.dumps({PRIOR: [{"code": "600005.SH"}]}), encoding="utf-8")
        with mock.patch.object(sys, "argv", ["x", "--as-of", "2026-10-16", "--output", str(out)]):
            code = review.main()
        return code, json.loads(out.read_text(encoding="utf-8")), json.loads(history.read_text(encoding="utf-8"))


class LatestReviewFallbackTests(unittest.TestCase):
    def test_historical_price_never_uses_latest_quote(self):
        row = stock("600001.SH", "甲", **{"最新涨跌幅": -5, f"涨跌幅[{DAY}]": 10})
        self.assertEqual(review.normalize_leader(row, "2026-10-16")["change"], 10)
        del row[f"涨跌幅[{DAY}]"]
        self.assertIsNone(review.normalize_leader(row, "2026-10-16")["change"])

    def test_predicate_does_not_accept_a_numeric_break_count(self):
        self.assertFalse(review.dated_flag({f"涨停开板次数[{DAY}]": 1}, ("涨停", "涨停开板"), DAY))

    def test_missing_feedback_stays_missing_but_valid_seals_are_saved(self):
        missing = stock("600006.SH", "己", **{f"涨停[{PRIOR}]": True, "最新涨跌幅": 10})
        code, payload, history = run([("涨停股票 股票简称", LEADERS), ("跌停 股票代码", DOWN), ("曾涨停 股票代码", OPENED), ("涨停股票 2026年10月16日涨跌幅", FEEDBACK + [missing])])
        self.assertEqual(code, 3)
        self.assertFalse(payload["market_evidence"]["complete"])
        self.assertEqual(payload["previous_limit_up_feedback"]["missing_codes"], ["600006.SH"])
        self.assertEqual(payload["previous_limit_up_feedback"]["count"], 1)
        self.assertEqual(payload["previous_limit_up_feedback"]["expected_count"], 2)
        self.assertEqual(len(history[DAY]), 2)

    def test_probe_writes_no_output_or_history(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"IWENCAI_API_KEY": "k", "HTTPS_PROXY": "http://127.0.0.1:1"}), mock.patch.object(review, "load_query_function", return_value=fake_wencai([])), mock.patch("sys.stdout", new_callable=io.StringIO):
            out = Path(tmp) / "latest_market_review.json"
            with mock.patch.object(sys, "argv", ["x", "--as-of", "2026-10-16", "--probe", "--output", str(out)]):
                self.assertEqual(review.main(), 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_original_wording_returning_zero_falls_back(self):
        code, payload, history = run([
            ("涨停股票 股票简称", []),            # 原问法：返回 0 只（2026-10 起的实际现象）
            ("涨停的股票 连续涨停天数 涨停开板次数 涨停原因", LEADERS),
            ("跌停 股票代码", DOWN),
            ("曾涨停 股票代码", OPENED),
            (f"涨停股票 2026年10月16日涨跌幅", FEEDBACK),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["market"]["limit_up"], 2)
        self.assertEqual(payload["market"]["failed_count"], 1)
        self.assertTrue(payload["market_evidence"]["complete"])
        self.assertIn("涨停的股票", payload["queries"][0])
        self.assertEqual([a["rows"] for a in payload["query_attempts"] if a["label"] == "涨停"], [0, 2])
        self.assertEqual(len(history[DAY]), 2)

    def test_simplified_wording_filters_st_and_bse_locally(self):
        mixed = LEADERS + [stock("600006.SH", "*ST己", **{f"涨停[{DAY}]": True}), stock("830001.BJ", "北", **{f"涨停[{DAY}]": True})]
        code, payload, _ = run([
            ("涨停的股票 连续涨停天数 涨停开板次数 所属同花顺行业", mixed),
            ("跌停 股票代码", DOWN), ("曾涨停 股票代码", OPENED), ("涨停股票 2026年10月16日涨跌幅", FEEDBACK),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["market_evidence"]["limit_up_codes"], ["000002.SZ", "600001.SH"])

    def test_opened_accepts_other_dated_column_names(self):
        opened = [stock("600004.SH", "丁", **{f"涨停开板[{DAY}]": True})]
        _, payload, _ = run([("涨停股票 股票简称", LEADERS), ("跌停 股票代码", DOWN), ("曾涨停 股票代码", opened), ("涨停股票 2026年10月16日涨跌幅", FEEDBACK)])
        self.assertEqual(payload["market"]["failed_count"], 1)

    def test_zero_limit_up_with_feedback_is_failure_and_keeps_history(self):
        code, payload, history = run([("跌停 股票代码", DOWN), ("曾涨停 股票代码", OPENED), ("涨停股票 2026年10月16日涨跌幅", FEEDBACK)])
        self.assertEqual(code, 3, "Incomplete review must fail the pipeline step")
        self.assertFalse(payload["market_evidence"]["complete"])
        self.assertTrue(payload["market_evidence"]["anomalies"])
        self.assertNotIn(DAY, history, "A failed day must not be written as an empty limit-up day")
        self.assertEqual(len([a for a in payload["query_attempts"] if a["label"] == "涨停"]), 4)

    def test_wrong_predicate_moves_to_next_wording(self):
        undated = [stock("600001.SH", "甲", **{"涨停[20261015]": True})]
        code, payload, _ = run([
            ("涨停股票 股票简称", undated),
            ("涨停的股票 连续涨停天数 涨停开板次数 涨停原因", LEADERS),
            ("跌停 股票代码", DOWN), ("曾涨停 股票代码", OPENED), ("涨停股票 2026年10月16日涨跌幅", FEEDBACK),
        ])
        self.assertEqual(code, 0)
        first = payload["query_attempts"][0]
        self.assertIsNone(first["rows"])
        self.assertIn("Missing dated predicate", first["error"])


if __name__ == "__main__":
    unittest.main()
