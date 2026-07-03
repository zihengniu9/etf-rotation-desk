import unittest

from low_buy_selector.ths import parse_board_constituents, parse_total_pages


SAMPLE_HTML = """
<html><body>
<table class="m-table m-pager-table">
  <thead>
    <tr>
      <th>序号</th><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅(%)</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>1</td><td><a>002167</a></td><td><a>东方锆业</a></td><td>24.28</td><td>10.01</td></tr>
    <tr><td>2</td><td><a>600667</a></td><td><a>太极实业</a></td><td>32.10</td><td>10.01</td></tr>
  </tbody>
</table>
<span class="page_info">1/3</span>
</body></html>
"""


class TonghuashunParserTests(unittest.TestCase):
    def test_parses_constituents_and_preserves_leading_zeroes(self):
        frame = parse_board_constituents(SAMPLE_HTML)

        self.assertEqual(list(frame["代码"]), ["002167", "600667"])
        self.assertEqual(list(frame["名称"]), ["东方锆业", "太极实业"])

    def test_parses_total_pages(self):
        self.assertEqual(parse_total_pages(SAMPLE_HTML), 3)


if __name__ == "__main__":
    unittest.main()
