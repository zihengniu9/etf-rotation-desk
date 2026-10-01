import json
import io
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import scripts.build_dashboard_status as status_builder
from scripts.build_dashboard_status import (
    MARKET_HOLIDAYS,
    RUN_TZ,
    build_latest_industry_snapshot,
    collection_day_status,
    file_state,
    latest_completed_trading_day,
    review_is_complete,
)

ROOT = Path(__file__).resolve().parents[1]


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=RUN_TZ)


class TradingCalendarTests(unittest.TestCase):
    def test_collection_skips_exchange_holidays_and_weekends(self):
        from datetime import date

        for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-07"):
            self.assertEqual(collection_day_status(date.fromisoformat(day)), "closed")
        self.assertEqual(collection_day_status(date.fromisoformat("2026-10-08")), "trading")
        with self.assertRaises(ValueError):
            collection_day_status(date.fromisoformat("2027-01-04"))

    def test_calendar_cli_does_not_write_snapshots(self):
        with mock.patch.object(status_builder, "main") as build, mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(status_builder.cli(["--check-trading-day", "2026-10-01"]), 0)
            self.assertEqual(out.getvalue().strip(), "closed")
            build.assert_not_called()

    def test_close_data_counts_only_after_close(self):
        self.assertEqual(latest_completed_trading_day(at("2026-09-30T16:20")).isoformat(), "2026-09-30")
        self.assertEqual(latest_completed_trading_day(at("2026-09-30T10:00")).isoformat(), "2026-09-29")

    def test_cutoff_uses_exchange_timezone(self):
        self.assertEqual(latest_completed_trading_day(datetime.fromisoformat("2026-09-30T08:00:00+00:00")).isoformat(), "2026-09-30")
        self.assertEqual(latest_completed_trading_day(datetime.fromisoformat("2026-09-30T07:29:00+00:00")).isoformat(), "2026-09-29")

    def test_holidays_and_weekends_roll_back_to_last_session(self):
        # 国庆休市 10/1-10/7：节中任何时刻的最新完成交易日都是 9/30。
        self.assertEqual(latest_completed_trading_day(at("2026-10-01T12:00")).isoformat(), "2026-09-30")
        self.assertEqual(latest_completed_trading_day(at("2026-10-08T09:00")).isoformat(), "2026-09-30")
        self.assertEqual(latest_completed_trading_day(at("2026-10-08T16:00")).isoformat(), "2026-10-08")
        self.assertEqual(latest_completed_trading_day(at("2026-09-27T12:00")).isoformat(), "2026-09-24")

    def test_frontend_calendar_matches_backend(self):
        script = (ROOT / "web" / "trading_calendar.js").read_text(encoding="utf-8")
        frontend = set(re.findall(r'"(\d{4}-\d{2}-\d{2})"', script))
        self.assertEqual(frontend, set(MARKET_HOLIDAYS))


class DashboardStatusTests(unittest.TestCase):
    def test_incomplete_review_is_not_complete(self):
        self.assertFalse(review_is_complete({"market_evidence": {"complete": False}}))
        self.assertTrue(review_is_complete({"market_evidence": {"complete": True}}))
        self.assertTrue(review_is_complete({"data_as_of": "2026-09-30"}), "Older reviews without the flag stay valid")

    def test_newer_data_is_never_stale(self):
        self.assertEqual(file_state("2026-09-30", "2026-09-29", exists=True), "current")
        self.assertEqual(file_state("2026-09-29", "2026-09-30", exists=True), "stale")
        self.assertEqual(file_state("2026-09-30", "2026-09-30", exists=True, source_status="incomplete"), "error")

    def test_failed_review_does_not_anchor_or_pass_as_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            day = "2026-09-30"
            files = {
                "latest_market_review.json": {"data_as_of": "2026-09-29", "market_evidence": {"complete": False}},
                "shortterm_signal.json": {"date": day, "status": "ok"},
                "shortterm_factor_preview.json": {"data_as_of": day, "status": "ok", "phase": "close"},
                "industry_update_status.json": {"data_as_of": day, "status": "success"},
                "trend_engine.json": {"data_as_of": day},
                "growth_factor_snapshot.json": {"data_as_of": day},
                "dividend_factor_snapshot.json": {"data_as_of": day},
            }
            for name, payload in files.items():
                (outputs / name).write_text(json.dumps(payload), encoding="utf-8")
            (outputs / "etf_update_status.csv").write_text(f"data_date\n{day}\n", encoding="utf-8")
            with mock.patch.object(status_builder, "OUTPUTS", outputs):
                status_builder.main(now=at("2026-09-30T16:32"))
            payload = json.loads((outputs / "dashboard_status.json").read_text(encoding="utf-8"))
        states = {item["key"]: item["state"] for item in payload["modules"]}
        self.assertEqual(payload["reference_date"], day)
        self.assertEqual(states.pop("review"), "error")
        self.assertEqual(set(states.values()), {"current"}, "Fresher modules must not be marked stale by a lagging review")
        self.assertEqual(payload["summary"]["error"], 1)

    def test_latest_industry_snapshot_drops_historical_rows(self):
        payload = {
            "updated_at": "2026-08-28T16:20:00+08:00",
            "data_as_of": "2026-08-28",
            "history_days": 2,
            "rows": [
                {"date": "2026-08-27", "industry": "医药"},
                {"date": "2026-08-28", "industry": "半导体"},
                {"date": "2026-08-28", "industry": "汽车"},
            ],
        }
        result = build_latest_industry_snapshot(payload)
        self.assertEqual(result["data_as_of"], "2026-08-28")
        self.assertEqual([row["industry"] for row in result["rows"]], ["半导体", "汽车"])

    def test_weekly_factor_can_have_bounded_lag(self):
        self.assertEqual(file_state("2026-08-27", "2026-08-28", exists=True, max_lag_days=5), "current")
        self.assertEqual(file_state("2026-08-20", "2026-08-28", exists=True, max_lag_days=5), "stale")


if __name__ == "__main__":
    unittest.main()
