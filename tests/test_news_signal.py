import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from low_buy_selector.news_signal import NewsItem, aggregate, classify, dedupe  # noqa: E402
import update_news_signal as collector  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
OK = [{"key": "cls", "name": "财联社", "status": "ok", "count": 1}]


def item(title, hours=1, level=1, source="财联社", content=""):
    return NewsItem(source=source, published_at=NOW - timedelta(hours=hours), title=title, content=content, level=level)


class ClassifyTests(unittest.TestCase):
    def test_policy_easing_is_market_positive(self):
        row = classify(item("央行宣布下调存款准备金率0.5个百分点 降准释放长期资金"), NOW)
        self.assertEqual(row["scope"], "market")
        self.assertEqual(row["sentiment"], 1)
        self.assertEqual(row["weight"], 2, "Authority source raises the weight")
        self.assertIn("降准", row["evidence"]["positive"])

    def test_negation_phrase_does_not_count_as_negative(self):
        row = classify(item("美方宣布暂缓加征关税 市场情绪回暖"), NOW)
        self.assertEqual(row["sentiment"], 1)
        self.assertNotIn("加征", row["evidence"]["negative"])

    def test_theme_news_maps_to_theme(self):
        row = classify(item("多家芯片企业遭列入实体清单 出口管制升级", level=2), NOW)
        self.assertIn("半导体", row["themes"])
        self.assertEqual(row["sentiment"], -1)

    def test_irrelevant_and_recap_items_are_skipped(self):
        self.assertIsNone(classify(item("某地举办马拉松比赛"), NOW))
        self.assertIsNone(classify(item("A股收评：沪指跌1.2% 半导体板块领跌"), NOW), "Price recaps are covered by market modules")

    def test_impact_decays_with_age(self):
        fresh = classify(item("证监会对多家公司立案调查", hours=0), NOW)
        old = classify(item("证监会对多家公司立案调查", hours=12), NOW)
        self.assertAlmostEqual(old["impact"], fresh["impact"] / 2, places=2)


class AggregateTests(unittest.TestCase):
    def test_major_market_negative_blocks(self):
        payload = aggregate([item("美国宣布对华加征关税并扩大出口管制", level=2)], NOW, OK)
        self.assertEqual(payload["gate"]["state"], "block")
        self.assertTrue(payload["gate"]["reasons"][0].startswith("重大利空"))

    def test_moderate_negative_is_caution(self):
        payload = aggregate([item("证监会就减持新规征求意见 收紧大股东减持", level=1)], NOW, OK)
        self.assertEqual(payload["gate"]["state"], "caution")

    def test_positive_news_never_unlocks_attack(self):
        payload = aggregate([item("国务院常务会议部署稳增长 支持资本市场", level=3)], NOW, OK)
        self.assertEqual(payload["gate"]["state"], "clear")

    def test_theme_alert(self):
        news = [item("芯片出口管制升级 多家企业被列入实体清单", level=2, hours=h) for h in (1,)]
        news.append(item("半导体设备进口限制再收紧", level=2, hours=2, source="东方财富"))
        payload = aggregate(news, NOW, OK)
        semi = next(theme for theme in payload["themes"] if theme["theme"] == "半导体")
        self.assertTrue(semi["alert"])
        self.assertIn("芯片", semi["aliases"])

    def test_all_sources_failed_is_unavailable(self):
        payload = aggregate([], NOW, [{"key": "cls", "status": "error"}])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["gate"]["state"], "unavailable")

    def test_window_excludes_old_items(self):
        payload = aggregate([item("央行降准", hours=30)], NOW, OK)
        self.assertEqual(payload["counts"]["fetched"], 0)

    def test_dedupe_merges_same_event_across_sources(self):
        a = item("央行宣布下调存款准备金率0.5个百分点", level=2)
        b = item("央行：下调存款准备金率0.5个百分点", source="新浪财经")
        kept = dedupe([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].source, "财联社")
        self.assertIn("新浪财经", kept[0].tags)


class ParserTests(unittest.TestCase):
    def test_cls(self):
        rows = collector.parse_cls({"data": {"roll_data": [{"id": 1, "ctime": 1792371600, "title": "", "content": "【央行降准】央行宣布降准", "level": "A"}]}})
        self.assertEqual(rows[0].level, 3)
        self.assertEqual(rows[0].url, "https://www.cls.cn/detail/1")

    def test_eastmoney(self):
        rows = collector.parse_eastmoney({"data": {"fastNewsList": [{"code": "202610193", "title": "标题", "summary": "摘要", "showTime": "2026-10-19 08:30:00"}]}})
        self.assertEqual(rows[0].published_at.hour, 8)
        self.assertTrue(rows[0].url.endswith("202610193.html"))

    def test_sina(self):
        rows = collector.parse_sina({"result": {"data": {"feed": {"list": [{"create_time": "2026-10-19 08:00:00", "rich_text": "内容", "tag": [{"name": "焦点"}]}]}}}})
        self.assertEqual(rows[0].level, 2)

    def test_cls_sign_is_stable(self):
        self.assertEqual(collector.cls_sign({"b": "2", "a": "1"}), collector.cls_sign({"a": "1", "b": "2"}))

    def test_one_failed_source_does_not_stop_others(self):
        good = lambda limit: [item("央行降准")]
        def bad(limit):
            raise TimeoutError("timeout")
        with mock.patch.dict(collector.FETCHERS, {"cls": ("财联社", bad), "sina": ("新浪财经", good)}):
            items, sources = collector.collect(["cls", "sina"], 10)
        self.assertEqual(len(items), 1)
        self.assertEqual([s["status"] for s in sources], ["error", "ok"])

    def test_main_writes_files_even_when_all_fail(self):
        def bad(limit):
            raise OSError("blocked")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(collector.FETCHERS, {"cls": ("财联社", bad)}):
            code = collector.main(["--sources", "cls", "--out", directory])
            self.assertEqual(code, 1)
            self.assertTrue((Path(directory) / "news_signal.json").exists())
            self.assertTrue((Path(directory) / "news_signal.js").read_text(encoding="utf-8").startswith("window.NEWS_SIGNAL = "))


if __name__ == "__main__":
    unittest.main()
