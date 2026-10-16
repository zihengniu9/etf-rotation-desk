"""采集财经快讯并生成消息面信号：outputs/news_signal.json / news_signal.js。

三个公开快讯源各自独立采集，单个失败只在 sources 里记为 error；全部失败时仍写出
status=error 的文件，页面显示“消息面未接入”，不参与进攻/防守判定。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from low_buy_selector.news_signal import LOOKBACK_HOURS, NewsItem, aggregate  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
OUTPUTS = ROOT / "outputs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: object) -> str:
    parser = PlainText()
    parser.feed(str(value or ""))
    return "".join(parser.parts).strip()


def get_json(url: str, params: dict, referer: str, timeout: float = 15) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full, headers={**HEADERS, "Referer": referer})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def parse_local(value: str) -> datetime:
    return datetime.strptime(value.strip()[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)


# ---- 财联社电报 ----
def cls_sign(params: dict) -> str:
    query = urllib.parse.urlencode(sorted(params.items()))
    return hashlib.md5(hashlib.sha1(query.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()


def parse_cls(payload: dict) -> list[NewsItem]:
    if str(payload.get("errno", 0)) != "0" or not isinstance(payload.get("data"), dict):
        raise ValueError(f"CLS response rejected: {payload.get('msg', 'missing data')}")
    rows = ((payload.get("data") or {}).get("roll_data")) or []
    items = []
    for row in rows:
        ctime = row.get("ctime")
        if not ctime:
            continue
        level = {"A": 3, "B": 2}.get(str(row.get("level") or "").upper(), 1)
        items.append(NewsItem(
            source="财联社", published_at=datetime.fromtimestamp(int(ctime), TZ),
            title=clean_text(row.get("title")), content=clean_text(row.get("content") or row.get("brief")),
            url=str(row.get("shareurl") or (f"https://www.cls.cn/detail/{row['id']}" if row.get("id") else "")), level=level,
        ))
    return items


def fetch_cls(limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    cursor = int(time.time())
    cutoff = datetime.now(TZ) - timedelta(hours=LOOKBACK_HOURS)
    while len(items) < limit:
        size = min(50, limit - len(items))
        params = {"app": "CailianpressWeb", "category": "", "os": "web", "refresh_type": "1", "rn": str(size), "sv": "7.7.5", "last_time": str(cursor)}
        params["sign"] = cls_sign(params)
        batch = parse_cls(get_json("https://www.cls.cn/v1/roll/get_roll_list", params, "https://www.cls.cn/telegraph"))
        if not batch:
            break
        items.extend(batch)
        oldest = min(item.published_at for item in batch)
        next_cursor = int(oldest.timestamp()) - 1
        if oldest <= cutoff or len(batch) < size or next_cursor >= cursor:
            break
        cursor = next_cursor
    return items[:limit]


# ---- 东方财富 7×24 ----
def parse_eastmoney(payload: dict) -> list[NewsItem]:
    if not isinstance(payload.get("data"), dict):
        raise ValueError(f"Eastmoney response rejected: {payload.get('message', 'missing data')}")
    rows = ((payload.get("data") or {}).get("fastNewsList")) or []
    items = []
    for row in rows:
        if not row.get("showTime"):
            continue
        code = row.get("code") or ""
        level = 2 if str(row.get("titleColor") or "") in {"1", "2"} else 1
        items.append(NewsItem(
            source="东方财富", published_at=parse_local(str(row["showTime"])),
            title=clean_text(row.get("title")), content=clean_text(row.get("summary")),
            url=f"https://finance.eastmoney.com/a/{code}.html" if code else "", level=level,
        ))
    return items


def fetch_eastmoney(limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    cursor = ""
    cutoff = datetime.now(TZ) - timedelta(hours=LOOKBACK_HOURS)
    while len(items) < limit:
        size = min(100, limit - len(items))
        params = {"client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": cursor, "pageSize": str(size), "req_trace": str(int(time.time() * 1000))}
        payload = get_json("https://np-weblist.eastmoney.com/comm/web/getFastNewsList", params, "https://kuaixun.eastmoney.com/")
        batch = parse_eastmoney(payload)
        if not batch:
            break
        items.extend(batch)
        next_cursor = str((payload.get("data") or {}).get("sortEnd") or "")
        if min(item.published_at for item in batch) <= cutoff or len(batch) < size or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return items[:limit]


# ---- 新浪财经 7×24 ----
def parse_sina(payload: dict) -> list[NewsItem]:
    if not isinstance((payload.get("result") or {}).get("data"), dict):
        raise ValueError("Sina response missing feed data")
    feed = (((payload.get("result") or {}).get("data") or {}).get("feed") or {})
    items = []
    for row in feed.get("list") or []:
        if not row.get("create_time"):
            continue
        tags = [str(tag.get("name") or "") for tag in row.get("tag") or [] if isinstance(tag, dict)]
        items.append(NewsItem(
            source="新浪财经", published_at=parse_local(str(row["create_time"])),
            title="", content=clean_text(row.get("rich_text")), url=str(row.get("docurl") or ""),
            level=2 if "焦点" in tags else 1,
        ))
    return items


def fetch_sina(limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    cutoff = datetime.now(TZ) - timedelta(hours=LOOKBACK_HOURS)
    for page in range(1, (limit + 49) // 50 + 1):
        size = 50
        params = {"page": str(page), "page_size": str(size), "zhibo_id": "152", "tag_id": "0", "dire": "f", "dpc": "1", "type": "0"}
        batch = parse_sina(get_json("https://zhibo.sina.com.cn/api/zhibo/feed", params, "https://finance.sina.com.cn/7x24/"))
        items.extend(batch)
        if not batch or len(batch) < size or min(item.published_at for item in batch) <= cutoff:
            break
    return items[:limit]


FETCHERS = {"cls": ("财联社", fetch_cls), "eastmoney": ("东方财富", fetch_eastmoney), "sina": ("新浪财经", fetch_sina)}


def collect(names: list[str], limit: int, lookback_hours: int = LOOKBACK_HOURS, now: datetime | None = None) -> tuple[list[NewsItem], list[dict]]:
    items: list[NewsItem] = []
    sources = []
    now = now or datetime.now(TZ)
    cutoff = now - timedelta(hours=lookback_hours)
    for name in names:
        label, fetcher = FETCHERS[name]
        started = time.time()
        try:
            fetched = fetcher(limit)
            batch = [item for item in fetched if cutoff <= item.published_at <= now + timedelta(minutes=5)]
            status = "ok" if batch else "empty"
            message = "" if batch else "最近窗口内无有效快讯"
            items.extend(batch)
        except Exception as error:  # 网络、格式变化都只影响这一路
            fetched, batch, status, message = [], [], "error", f"{type(error).__name__}: {error}"[:200]
        oldest = min((item.published_at for item in fetched), default=None)
        latest = max((item.published_at for item in batch), default=None)
        sources.append({"key": name, "name": label, "status": status, "count": len(batch), "fetched": len(fetched), "oldest_at": oldest.isoformat(timespec="seconds") if oldest else None, "latest_at": latest.isoformat(timespec="seconds") if latest else None, "window_covered": bool(oldest and oldest <= cutoff and batch), "message": message, "seconds": round(time.time() - started, 1)})
    return items, sources


def write_outputs(payload: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    (out_dir / "news_signal.json").write_text(serialized + "\n", encoding="utf-8")
    (out_dir / "news_signal.js").write_text("window.NEWS_SIGNAL = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect market news and build the news gate for market_mode.html")
    parser.add_argument("--sources", default="cls,eastmoney,sina", help="逗号分隔：cls, eastmoney, sina")
    parser.add_argument("--limit", type=int, default=2500, help="每源分页抓取上限；达到24小时边界后停止")
    parser.add_argument("--lookback-hours", type=int, default=LOOKBACK_HOURS)
    parser.add_argument("--out", type=Path, default=OUTPUTS)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 5000 or not 1 <= args.lookback_hours <= LOOKBACK_HOURS:
        parser.error("limit must be 1..5000 and lookback-hours must be 1..24")
    names = [name.strip() for name in args.sources.split(",") if name.strip()]
    unknown = [name for name in names if name not in FETCHERS]
    if unknown:
        parser.error(f"unknown sources: {unknown}")
    items, sources = collect(names, args.limit, args.lookback_hours)
    payload = aggregate(items, datetime.now(TZ), sources, args.lookback_hours)
    write_outputs(payload, args.out)
    summary = ", ".join(f"{s['name']}={s['status']}({s['count']})" for s in sources)
    print(f"wrote=outputs/news_signal.json gate={payload['gate']['state']} relevant={payload['counts']['relevant']} sources: {summary}")
    for source in sources:
        print(f"SOURCE {source['name']}: {source['status']} recent={source['count']} fetched={source['fetched']} oldest={source['oldest_at']} full_window={source['window_covered']}")
        if source["status"] == "error":
            print(f"WARN {source['name']}: {source['message']}")
    # 全部失败时返回非 0，让流水线日志记一笔；文件仍已写出，页面会显示未接入。
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
