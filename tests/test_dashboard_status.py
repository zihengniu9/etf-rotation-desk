import unittest

from scripts.build_dashboard_status import build_latest_industry_snapshot, file_state


class DashboardStatusTests(unittest.TestCase):
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
