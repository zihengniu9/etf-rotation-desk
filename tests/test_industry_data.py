import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.update_industry_data import build_daily_snapshot, extract_embedded_data, merge_snapshot


class IndustryDataTests(unittest.TestCase):
    def test_extract_embedded_data_stops_at_live_data_array(self):
        with TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "dashboard.html"
            html_path.write_text(
                """<script>
                const LIVE_DATA = [{"date":"2026-08-11","industry":"工业金属","turnover":123}];
                const fallbackData = LIVE_DATA.length ? LIVE_DATA : [];
                let data = [];
                </script>""",
                encoding="utf-8",
            )

            rows = extract_embedded_data(html_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0]["date"], "2026-08-11")
        self.assertEqual(rows.iloc[0]["industry"], "工业金属")

    def test_build_daily_snapshot_aligns_yuan_history_with_yuan_unit_live_values(self):
        summary = pd.DataFrame(
            [
                {"序号": 1, "板块": "半导体", "涨跌幅": 3.0, "总成交额": 200.0, "上涨家数": 8, "下跌家数": 2},
                {"序号": 2, "板块": "证券", "涨跌幅": -1.0, "总成交额": 100.0, "上涨家数": 3, "下跌家数": 7},
            ]
        )
        previous = pd.DataFrame(
            [
                {"date": "2026-08-05", "industry": "半导体", "turnover": 10_000_000_000.0},
                {"date": "2026-08-05", "industry": "证券", "turnover": 5_000_000_000.0},
            ]
        )

        snapshot = build_daily_snapshot(summary, "2026-08-06", previous)

        semiconductor = snapshot.loc[snapshot["industry"] == "半导体"].iloc[0]
        self.assertAlmostEqual(float(semiconductor["turnover"]), 20_000_000_000.0)
        self.assertAlmostEqual(float(semiconductor["turnover_ratio"]), 2.0)

    def test_build_daily_snapshot_calculates_share_benchmark_and_ratio(self):
        summary = pd.DataFrame(
            [
                {"序号": 1, "板块": "半导体", "涨跌幅": 3.0, "总成交额": 200.0, "上涨家数": 8, "下跌家数": 2},
                {"序号": 2, "板块": "证券", "涨跌幅": -1.0, "总成交额": 100.0, "上涨家数": 3, "下跌家数": 7},
            ]
        )
        previous = pd.DataFrame(
            [
                {"date": "2026-08-05", "industry": "半导体", "turnover": 100.0},
                {"date": "2026-08-05", "industry": "证券", "turnover": 50.0},
            ]
        )

        snapshot = build_daily_snapshot(summary, "2026-08-06", previous)

        semiconductor = snapshot.loc[snapshot["industry"] == "半导体"].iloc[0]
        securities = snapshot.loc[snapshot["industry"] == "证券"].iloc[0]
        self.assertAlmostEqual(float(semiconductor["turnover_share"]), 66.666666, places=4)
        self.assertAlmostEqual(float(securities["turnover_share"]), 33.333333, places=4)
        self.assertAlmostEqual(float(semiconductor["benchmark_1d"]), 1.666666, places=4)
        self.assertAlmostEqual(float(semiconductor["turnover_ratio"]), 2.0)
        self.assertEqual(int(semiconductor["total_count"]), 10)

    def test_merge_snapshot_replaces_same_day_and_keeps_latest_days(self):
        previous = pd.DataFrame(
            [
                {"date": "2026-08-05", "industry": "半导体", "turnover": 100.0},
                {"date": "2026-08-06", "industry": "半导体", "turnover": 110.0},
            ]
        )
        snapshot = pd.DataFrame(
            [
                {"date": "2026-08-06", "industry": "半导体", "turnover": 130.0},
                {"date": "2026-08-06", "industry": "证券", "turnover": 80.0},
            ]
        )

        merged = merge_snapshot(previous, snapshot, max_days=2)

        self.assertEqual(len(merged), 3)
        self.assertEqual(merged.groupby(["date", "industry"]).size().max(), 1)
        self.assertEqual(sorted(merged.loc[merged["date"] == "2026-08-06", "industry"].tolist()), ["半导体", "证券"])
        self.assertAlmostEqual(
            float(merged.loc[(merged["date"] == "2026-08-06") & (merged["industry"] == "半导体"), "turnover"].iloc[0]),
            130.0,
        )


if __name__ == "__main__":
    unittest.main()
