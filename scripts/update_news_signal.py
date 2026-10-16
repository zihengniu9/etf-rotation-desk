"""采集财经快讯并生成消息面信号：outputs/news_signal.json / news_signal.js。

三个公开快讯源各自独立采集，单个失败只在 sources 里记为 error；全部失败时仍写出
status=error 的文件，页面显示“消息面未接入”，不参与进攻/防守判定。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
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
    rows = ((payload.get("data") or {}).get("roll_data")) or []
    items = []
    for row in rows:
        ctime = row.get("ctime")
        if not ctime:
            continue
        level = {"A": 3, "B": 2}.get(str(row.get("level") or "").upper(), 1)
        items.append(NewsItem(
            source="财联社", published_at=datetime.fromtimestamp(int(ctime), TZ),
            title=str(row.get("title") or ""), content=str(row.get("content") or row.get("brief") or ""),
            url=str(row.get("shareurl") or (f"https://www.cls.cn/detail/{row['id']}" if row.get("id") else "")), level=level,
        ))
    return items


def fetch_cls(limit: int) -> list[NewsItem]:
    params = {"app": "CailianpressWeb", "category": "", "os": "web", "refresh_type": "1", "rn": str(limit), "sv": "7.7.5", "last_time": str(int(time.time()))}
    params["sign"] = cls_sign(params)
    return parse_cls(get_json("https://www.cls.cn/nodeapi/telegraphList", params, "https://www.cls.cn/telegraph"))


# ---- 东方财富 7×24 ----
def parse_eastmoney(payload: dict) -> list[NewsItem]:
    rows = ((payload.get("data") or {}).get("fastNewsList")) or []
    items = []
    for row in rows:
        if not row.get("showTime"):
            continue
        code = row.get("code") or ""
        level = 2 if str(row.get("titleColor") or "") in {"1", "2"} else 1
        items.append(NewsItem(
            source="东方财富", published_at=parse_local(str(row["showTime"])),
            title=str(row.get("title") or ""), content=str(row.get("summary") or ""),
            url=f"https://finance.eastmoney.com/a/{code}.html" if code else "", level=level,
        ))
    return items


def fetch_eastmoney(limit: int) -> list[NewsItem]:
    params = {"client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": "", "pageSize": str(limit), "req_trace": str(int(time.time() * 1000))}
    return parse_eastmoney(get_json("https://np-weblist.eastmoney.com/comm/web/getFastNewsList", params, "https://kuaixun.eastmoney.com/"))


# ---- 新浪财经 7×24 ----
def parse_sina(payload: dict) -> list[NewsItem]:
    feed = (((payload.get("result") or {}).get("data") or {}).get("feed") or {})
    items = []
    for row in feed.get("list") or []:
        if not row.get("create_time"):
            continue
        tags = [str(tag.get("name") or "") for tag in row.get("tag") or [] if isinstance(tag, dict)]
        items.append(NewsItem(
            source="新浪财经", published_at=parse_local(str(row["create_time"])),
            title="", content=str(row.get("rich_text") or ""), url=str(row.get("docurl") or ""),
            level=2 if "焦点" in tags else 1,
        ))
    return items


def fetch_sina(limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for page in range(1, max(1, limit // 50) + 1):
        params = {"page": str(page), "page_size": "50", "zhibo_id": "152", "tag_id": "0", "dire": "f", "dpc": "1", "type": "0"}
        batch = parse_sina(get_json("https://zhibo.sina.com.cn/api/zhibo/feed", params, "https://finance.sina.com.cn/7x24/"))
        items.extend(batch)
        if len(batch) < 50:
            break
    return items


FETCHERS = {"cls": ("财联社", fetch_cls), "eastmoney": ("东方财富", fetch_eastmoney), "sina": ("新浪财经", fetch_sina)}


def collect(names: list[str], limit: int) -> tuple[list[NewsItem], list[dict]]:
    items: list[NewsItem] = []
    sources = []
    for name in names:
        label, fetcher = FETCHERS[name]
        started = time.time()
        try:
            batch = fetcher(limit)
            status = "ok" if batch else "empty"
            message = "" if batch else "接口返回 0 条"
            items.extend(batch)
        except Exception as error:  # 网络、格式变化都只影响这一路
            batch, status, message = [], "error", f"{type(error).__name__}: {error}"[:200]
        sources.append({"key": name, "name": label, "status": status, "count": len(batch), "message": message, "seconds": round(time.time() - started, 1)})
    return items, sources


def write_outputs(payload: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    (out_dir / "news_signal.json").write_text(serialized + "\n", encoding="utf-8")
    (out_dir / "news_signal.js").write_text("window.NEWS_SIGNAL = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect market news and build the news gate for market_mode.html")
    parser.add_argument("--sources", default="cls,eastmoney,sina", help="逗号分隔：cls, eastmoney, sina")
    parser.add_argument("--limit", type=int, default=200, help="每个源最多抓取条数")
    parser.add_argument("--lookback-hours", type=int, default=LOOKBACK_HOURS)
    parser.add_argument("--out", type=Path, default=OUTPUTS)
    args = parser.parse_args(argv)
    names = [name.strip() for name in args.sources.split(",") if name.strip()]
    unknown = [name for name in names if name not in FETCHERS]
    if unknown:
        parser.error(f"unknown sources: {unknown}")
    items, sources = collect(names, args.limit)
    payload = aggregate(items, datetime.now(TZ), sources, args.lookback_hours)
    write_outputs(payload, args.out)
    summary = ", ".join(f"{s['name']}={s['status']}({s['count']})" for s in sources)
    print(f"wrote=outputs/news_signal.json gate={payload['gate']['state']} relevant={payload['counts']['relevant']} sources: {summary}")
    for source in sources:
        if source["status"] == "error":
            print(f"WARN {source['name']}: {source['message']}")
    # 全部失败时返回非 0，让流水线日志记一笔；文件仍已写出，页面会显示未接入。
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
