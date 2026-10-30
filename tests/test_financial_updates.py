import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import financial_data as financial
import update_dividend_factor as dividend
import run_growth_factor_analysis as growth
import build_dashboard_status as status_builder
from datetime import datetime
from tests.test_dividend_engine import sample_frame


class FinancialCollectionTests(unittest.TestCase):
    def test_pagination_is_complete_and_preserves_zero_total(self):
        pages = [{"code_count": 3, "datas": [{"股票代码": "600001.SH"}, {"股票代码": "600002.SH"}]},
                 {"code_count": 3, "datas": [{"股票代码": "600003.SH"}]}]
        with mock.patch.dict(os.environ, {"IWENCAI_API_KEY": "test"}):
            query = mock.Mock(side_effect=pages)
            self.assertEqual(len(financial.fetch_all(query, "test", page_size=2)["datas"]), 3)
            self.assertEqual(query.call_args.kwargs["page"], "2")
            self.assertEqual(query.call_args.kwargs["query"], "test")

    def test_partial_and_duplicate_responses_are_rejected(self):
        for second in ([], [{"股票代码": "600001.SH"}]):
            query = mock.Mock(side_effect=[{"code_count": 2, "datas": [{"股票代码": "600001.SH"}]}, {"code_count": 2, "datas": second}])
            with mock.patch.dict(os.environ, {"IWENCAI_API_KEY": "test"}), self.assertRaises(RuntimeError):
                financial.fetch_all(query, "test", page_size=1)

    def test_dated_quotes_never_use_latest_values(self):
        row = {"股票代码": "600001.SH", "最新价": 999, "收盘价[20261029]": 10, "涨跌幅[20261029]": 1,
               "总市值[20261029]": 100, "市盈率(pe,ttm)[20261029]": 20, "市净率[20261029]": 2, "动态市盈率[20261029]": 18}
        self.assertEqual(financial.dated_quotes([row], "2026-10-29")["600001.SH"]["最新价"], 10)
        row.update({"市盈率(pe,ttm)[20261030]": 999, "市净率(pb)[20261030]": 999})
        row.update(financial.dated_quotes([row], "2026-10-29")["600001.SH"])
        normalized = dividend.normalize_dividend_snapshot(pd.DataFrame([row]))
        self.assertEqual(normalized.iloc[0]["pe_ttm"], 20)
        self.assertEqual(normalized.iloc[0]["pb"], 2)
        with self.assertRaises(RuntimeError):
            financial.dated_quotes([row], "2026-10-28")

    def test_pending_date_and_attempt_record_do_not_relabel_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            snapshot = outputs / "growth_factor_snapshot.json"
            snapshot.write_text(json.dumps({"data_as_of": "2026-10-27"}), encoding="utf-8")
            financial.record_attempt("growth", "2026-10-29", "error", outputs)
            self.assertTrue(financial.needs_refresh("growth", "2026-10-29", outputs))
            self.assertEqual(json.loads(snapshot.read_text())["data_as_of"], "2026-10-27")

    def test_bad_date_or_collapsed_pool_requires_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            path = outputs / "dividend_factor_snapshot.json"
            for payload in ({"data_as_of": "invalid"}, {"data_as_of": "2026-10-29", "universe": {"valid": 3}}, {"data_as_of": "2026-10-29", "collection": {"complete": False}}):
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertTrue(financial.needs_refresh("dividend", "2026-10-29", outputs))

    def test_local_dividend_filters_keep_original_rules(self):
        rows = sample_frame().to_dict(orient="records")
        for row in rows:
            row["上市日期"] = "20100101"
        rows[0]["现金分红总额[20241231]"] = 0
        rows[1]["上市日期"] = "20250101"
        rows[2]["股票代码"] = "830001.BJ"
        accepted = dividend.eligible_rows(rows, "2026-10-29")
        self.assertEqual(len(accepted), 4)

    def test_failed_growth_refresh_cannot_stamp_old_input_with_new_date(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "old.json"
            source.write_text(json.dumps({"research_meta": {"data_as_of": "2026-10-27", "complete": True}, "datas": [{}]}), encoding="utf-8")
            with mock.patch.object(sys, "argv", ["x", "--as-of", "2026-10-29", "--current-input", str(source)]), self.assertRaises(RuntimeError):
                growth.main()

    def test_dividend_small_sample_cannot_replace_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = sample_frame().head(3).to_dict(orient="records")
            for row in rows:
                row["上市日期"] = "20100101"
            source, output = root / "source.json", root / "snapshot.json"
            source.write_text(json.dumps({"datas": rows, "research_meta": {"data_as_of": "2026-10-29"}}), encoding="utf-8")
            output.write_text('{"data_as_of":"2026-10-22"}', encoding="utf-8")
            with mock.patch.dict(os.environ, {"IWENCAI_API_KEY": "test", "HTTPS_PROXY": "http://127.0.0.1:1"}), mock.patch.object(sys, "argv", ["x", "--as-of", "2026-10-29", "--input", str(source), "--output", str(output)]), self.assertRaises(RuntimeError):
                dividend.main()
            self.assertEqual(json.loads(output.read_text())["data_as_of"], "2026-10-22")

    def test_latest_failed_attempt_is_visible_without_changing_snapshot_date(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory)
            (outputs / "growth_factor_snapshot.json").write_text(json.dumps({"data_as_of": "2026-10-27"}), encoding="utf-8")
            financial.record_attempt("growth", "2026-10-29", "error", outputs)
            now = datetime.fromisoformat("2026-10-30T10:00:00+08:00")
            with mock.patch.object(status_builder, "OUTPUTS", outputs):
                status_builder.main(now=now)
            report = json.loads((outputs / "dashboard_status.json").read_text(encoding="utf-8"))
            module = next(item for item in report["modules"] if item["key"] == "growth")
            self.assertEqual(module["state"], "error")
            self.assertEqual(module["data_as_of"], "2026-10-27")


if __name__ == "__main__":
    unittest.main()
