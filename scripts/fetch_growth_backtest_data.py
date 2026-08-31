from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse


REPORT_SPECS = (
    ("20221231", "2022年年报"),
    ("20230331", "2023年一季报"),
    ("20230630", "2023年中报"),
    ("20230930", "2023年三季报"),
    ("20231231", "2023年年报"),
    ("20240331", "2024年一季报"),
    ("20240630", "2024年中报"),
    ("20240930", "2024年三季报"),
    ("20241231", "2024年年报"),
    ("20250331", "2025年一季报"),
    ("20250630", "2025年中报"),
    ("20250930", "2025年三季报"),
    ("20251231", "2025年年报"),
    ("20260331", "2026年一季报"),
    ("20260630", "2026年中报"),
)


def load_query_function():
    script = Path(r"D:\Codex\CLI\skills\hithink-astock-selector\scripts\cli.py")
    if not script.exists():
        raise FileNotFoundError(f"hithink-astock-selector CLI not found: {script}")
    spec = importlib.util.spec_from_file_location("hithink_astock_selector_cli", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.query_astock


def verify_https_tunnel() -> str:
    proxy = os.environ.get("HTTPS_PROXY", "").strip()
    if not proxy:
        raise RuntimeError("HTTPS_PROXY is not configured; refusing direct network access")
    parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise RuntimeError("HTTPS_PROXY is invalid")
    with socket.create_connection((host, port), timeout=5):
        pass
    return f"{host}:{port}"


def chinese_period_end(period: str) -> str:
    return f"{int(period[:4])}年{int(period[4:6])}月{int(period[6:8])}日"


def build_query(period: str, label: str) -> str:
    fields = [
        f"{chinese_period_end(period)}沪深主板非ST股票",
        "股票代码",
        "股票简称",
        f"{label}营业收入同比增长率",
        f"{label}归母净利润同比增长率",
        f"{label}经营活动产生的现金流量净额",
        f"{label}净资产收益率",
        f"{label}销售净利率",
        f"{label}资产负债率",
        f"{label}营业收入",
        f"{label}归母净利润",
        f"{label}实际披露日期",
    ]
    return "，".join(fields)


def fetch_all(query_function, query: str, *, limit: int, timeout: int) -> dict[str, object]:
    api_key = os.environ.get("IWENCAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("IWENCAI_API_KEY is not configured")
    first = query_function(
        query=query,
        page="1",
        limit=str(limit),
        api_key=api_key,
        call_type="normal",
        timeout=timeout,
    )
    rows = list(first.get("datas") or [])
    expected = int(float(first.get("code_count") or first.get("row_count") or len(rows)))
    page = 2
    while len(rows) < expected:
        response = query_function(
            query=query,
            page=str(page),
            limit=str(limit),
            api_key=api_key,
            call_type="normal",
            timeout=timeout,
        )
        page_rows = list(response.get("datas") or [])
        if not page_rows:
            break
        rows.extend(page_rows)
        page += 1
    first["datas"] = rows
    first["research_query"] = query
    return first


def valid_cache(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("datas"))


def sanitize_payload(payload: dict[str, object]) -> dict[str, object]:
    """Remove response metadata that is unnecessary for reproducible research."""

    cleaned = dict(payload)
    cleaned.pop("token", None)
    cleaned.pop("claw_headers", None)
    return cleaned


def sanitize_cached_file(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cleaned = sanitize_payload(payload)
    if cleaned.keys() != payload.keys():
        path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch point-in-time growth financial reports from Wencai.")
    parser.add_argument("--output-dir", default="temp_download/growth_history")
    parser.add_argument("--limit", type=int, default=4000)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    tunnel = verify_https_tunnel()
    print(f"https_tunnel={tunnel}", flush=True)
    query_function = load_query_function()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for period, label in REPORT_SPECS:
        path = output_dir / f"finance_{period}.json"
        if valid_cache(path) and not args.refresh:
            sanitize_cached_file(path)
            print(f"cache={period} path={path}", flush=True)
            continue
        query = build_query(period, label)
        print(f"fetch={period} label={label}", flush=True)
        payload = fetch_all(query_function, query, limit=args.limit, timeout=args.timeout)
        payload = sanitize_payload(payload)
        payload["research_meta"] = {
            "report_period": period,
            "report_label": label,
            "source": "同花顺问财 hithink-astock-selector",
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"rows={len(payload.get('datas') or [])} path={path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
