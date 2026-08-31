from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


RUN_TZ = ZoneInfo("Asia/Hong_Kong")
CURRENT_QUERY = (
    "沪深主板非ST股票，股票代码，股票简称，股票市场类型，最新价，最新涨跌幅，"
    "2026年中报营业收入同比增长率，2026年中报归母净利润同比增长率，"
    "2026年中报经营活动产生的现金流量净额，2026年中报净资产收益率，"
    "2026年中报销售净利率，2026年中报资产负债率，2026年中报营业收入，"
    "2026年中报归母净利润，总市值，动态市盈率"
)


def load_query_function():
    candidates = [Path(r"D:\Codex\CLI\skills\hithink-astock-selector\scripts\cli.py")]
    override = os.environ.get("HITHINK_ASTOCK_CLI", "").strip()
    if override:
        candidates.insert(0, Path(override))
    candidates.append(Path.home() / ".codex" / "skills" / "hithink-astock-selector" / "scripts" / "cli.py")
    script = next((path for path in candidates if path.is_file()), None)
    if script is None:
        raise FileNotFoundError("hithink-astock-selector/scripts/cli.py not found")
    spec = importlib.util.spec_from_file_location("hithink_astock_selector_cli", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load hithink-astock-selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.query_astock


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the current growth financial cross-section.")
    parser.add_argument("--as-of", required=True, help="Latest completed trading day, YYYY-MM-DD")
    parser.add_argument("--output", default="temp_download/growth_finance_2026h1.json")
    parser.add_argument("--limit", type=int, default=4000)
    args = parser.parse_args()

    if not os.environ.get("IWENCAI_API_KEY"):
        raise RuntimeError("IWENCAI_API_KEY is not configured")
    if not os.environ.get("HTTPS_PROXY"):
        raise RuntimeError("HTTPS_PROXY is not configured; refusing direct network access")

    query_function = load_query_function()
    payload = query_function(
        query=CURRENT_QUERY,
        page="1",
        limit=str(args.limit),
        api_key=os.environ["IWENCAI_API_KEY"],
        call_type="normal",
        timeout=90,
    )
    rows = list(payload.get("datas") or [])
    expected = int(float(payload.get("code_count") or len(rows)))
    if not rows:
        raise RuntimeError(f"Wencai returned no growth rows: {payload}")
    if expected and len(rows) < min(expected, 2500):
        raise RuntimeError(f"Growth cross-section is incomplete: rows={len(rows)} expected={expected}")

    payload.pop("token", None)
    payload.pop("claw_headers", None)
    payload["research_meta"] = {
        "data_as_of": args.as_of,
        "financial_period": "20260630",
        "retrieved_at": datetime.now(RUN_TZ).isoformat(timespec="seconds"),
        "source": "同花顺问财 · hithink-astock-selector",
        "query": CURRENT_QUERY,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote={output} data_as_of={args.as_of} rows={len(rows)} expected={expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
