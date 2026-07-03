import unittest

from low_buy_selector.etf_hot import parse_hot_etf_response


class ETFHotTests(unittest.TestCase):
    def test_parse_hot_etf_response_keeps_rank_and_hot_value(self):
        payload = {
            "data": {
                "list": [
                    {"code": "588170", "market": "20", "name": "科创半导体ETF华夏", "rate": 12177850.0, "sdate": "20260701", "stime": "14"},
                    {"code": "159558", "market": "36", "name": "半导体设备ETF易方达", "rate": 5694307.5, "sdate": "20260701", "stime": "14"},
                ]
            }
        }

        frame = parse_hot_etf_response(payload, limit=1)

        self.assertEqual(frame.columns.tolist(), ["rank", "code", "name", "market", "heat", "sdate", "stime"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["rank"], 1)
        self.assertEqual(frame.iloc[0]["code"], "588170")
        self.assertEqual(frame.iloc[0]["heat"], 12177850.0)


if __name__ == "__main__":
    unittest.main()
