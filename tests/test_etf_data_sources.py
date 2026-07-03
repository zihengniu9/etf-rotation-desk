import unittest

from low_buy_selector.etf_data_sources import parse_sina_realtime_quotes


class ETFDataSourceTests(unittest.TestCase):
    def test_parse_sina_realtime_quotes_extracts_latest_etf_price(self):
        payload = (
            'var hq_str_sz159516="半导设备,1.734,1.794,1.730,1.792,1.683,1.729,1.730,'
            '4837251704,8397479583.232,842800,1.729,1319400,1.728,276600,1.727,'
            '509800,1.726,558200,1.725,5968800,1.730,3953300,1.731,1991700,'
            '1.732,583391,1.733,766400,1.734,2026-07-03,15:00:00,00";\n'
            'var hq_str_sh588200="科创芯片ETF嘉实,4.359,4.416,4.373,4.539,4.277,'
            '4.375,4.376,1474786036,6487649153.000,16900,4.375,2200,4.374,'
            '34700,4.373,20500,4.372,4300,4.371,99600,4.376,343200,'
            '4.377,31700,4.378,134700,4.379,51500,4.380,2026-07-03,15:00:02,00";'
        )

        frame = parse_sina_realtime_quotes(payload)

        self.assertEqual(frame["code"].tolist(), ["159516", "588200"])
        self.assertAlmostEqual(float(frame.iloc[0]["realtime_price"]), 1.730)
        self.assertEqual(frame.iloc[0]["realtime_date"], "2026-07-03")
        self.assertEqual(frame.iloc[0]["realtime_updated_at"], "2026-07-03 15:00:00")


if __name__ == "__main__":
    unittest.main()
