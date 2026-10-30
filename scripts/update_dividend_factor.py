from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from low_buy_selector.dividend_engine import build_dividend_snapshot, normalize_dividend_snapshot
from financial_data import fetch_all, quote_query, dated_quotes


RUN_TZ = ZoneInfo("Asia/Hong_Kong")


def previous_business_day(value: date) -> date:
    value -= timedelta(days=1)
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def completed_trading_day() -> date:
    now = datetime.now(RUN_TZ)
    candidate = now.date()
    if candidate.weekday() >= 5 or now.time() < datetime.strptime("15:30", "%H:%M").time():
        candidate = previous_business_day(candidate)
    return candidate


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


def build_query(as_of_date: date) -> str:
    as_of_cn = f"{as_of_date.year}年{as_of_date.month}月{as_of_date.day}日"
    return (
        f"{as_of_cn}沪深A股非ST且非金融，上市满3年，"
        "股息率大于2%，市盈率TTM大于0，市净率大于0，"
        "2023年、2024年、2025年经营活动现金流量净额均为正，"
        "2023年、2024年、2025年归属于母公司股东的净利润均为正，"
        "显示股票代码、股票简称、股票市场类型、所属同花顺行业、最新价、最新涨跌幅、总市值、"
        "股息率、市盈率TTM、市净率、2023年现金分红总额、2024年现金分红总额、2025年现金分红总额、"
        "2023年经营活动现金流量净额、2024年经营活动现金流量净额、2025年经营活动现金流量净额、"
        "2023年归属于母公司股东的净利润、2024年归属于母公司股东的净利润、"
        "2025年归属于母公司股东的净利润"
    )


def matched_count(payload: dict, default: int) -> int:
    candidates = [
        payload.get("total"),
        payload.get("row_count"),
        (payload.get("meta") or {}).get("row_count") if isinstance(payload.get("meta"), dict) else None,
    ]
    for value in candidates:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def eligible_rows(rows: list[dict], as_of: str) -> list[dict]:
    cutoff = pd.Timestamp(as_of) - pd.DateOffset(years=3)
    allowed = []
    for row in rows:
        if not re.fullmatch(r"[036]\d{5}\.(SH|SZ)", str(row.get("股票代码") or "")):
            continue
        listing = next((value for key, value in row.items() if key.startswith(("上市日期", "新股上市日期"))), None)
        listing = pd.to_datetime(str(listing), format="mixed", errors="coerce")
        if pd.isna(listing) or listing > cutoff:
            continue
        allowed.append(row)
    normalized = normalize_dividend_snapshot(pd.DataFrame(allowed))
    required = [f"{field}_{year}" for field in ("dividend", "cfo", "profit") for year in (2023, 2024, 2025)]
    if normalized.empty or any(not normalized[column].notna().any() for column in required):
        raise RuntimeError("Dividend annual fields/universe are missing; existing snapshot kept intact")
    valid = normalized[normalized[required].gt(0).all(axis=1) & normalized["dividend_yield"].gt(2) & normalized["pe_ttm"].gt(0) & normalized["pb"].gt(0)]
    codes = set(valid["code6"])
    return [row for row in allowed if str(row["股票代码"]).split(".")[0] in codes]


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the current dividend-quality factor snapshot.")
    parser.add_argument("--as-of", default="", help="Latest completed trading day, YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--max-per-industry", type=int, default=2)
    parser.add_argument("--input", default="", help="Use a saved Wencai response instead of making a network request")
    parser.add_argument("--raw-output", default="temp_download/dividend_factor_raw.json")
    parser.add_argument("--output", default="outputs/dividend_factor_snapshot.json")
    parser.add_argument("--js-output", default="outputs/dividend_factor_snapshot.js")
    parser.add_argument("--csv-output", default="outputs/dividend_factor_candidates.csv")
    args = parser.parse_args()

    if not os.environ.get("IWENCAI_API_KEY"):
        raise RuntimeError("IWENCAI_API_KEY is not configured")
    if not os.environ.get("HTTPS_PROXY"):
        raise RuntimeError("HTTPS_PROXY is not configured; refusing direct network access")

    as_of_date = date.fromisoformat(args.as_of) if args.as_of else completed_trading_day()
    query = build_query(as_of_date)
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        query_function = load_query_function()
        payload = fetch_all(query_function, query)
        quotes_payload = fetch_all(query_function, quote_query(as_of_date.isoformat()))
        quotes = dated_quotes(quotes_payload["datas"], as_of_date.isoformat())
        for row in payload["datas"]:
            row.update(quotes.get(str(row["股票代码"]), {key: None for key in ("最新价", "最新涨跌幅", "总市值", "市盈率TTM", "市净率", "动态市盈率")}))
        payload["research_meta"] = {"data_as_of": as_of_date.isoformat(), "complete": True, "quote_query": quotes_payload["query"]}
    rows = list(payload.get("datas") or [])
    if not rows:
        raise RuntimeError("Wencai returned no dividend rows; existing snapshot kept intact")

    if (payload.get("research_meta") or {}).get("data_as_of") != as_of_date.isoformat():
        raise RuntimeError("Dividend source date is not verified; existing snapshot kept intact")
    frame = pd.DataFrame(rows)
    rows = eligible_rows(rows, as_of_date.isoformat())
    if len(rows) < max(30, args.top):
        raise RuntimeError(f"Dividend cross-section unexpectedly small: {len(rows)}; existing snapshot kept intact")

    raw_path = Path(args.raw_output)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    snapshot, scored = build_dividend_snapshot(
        pd.DataFrame(rows),
        as_of=as_of_date.isoformat(),
        source="同花顺问财 · hithink-astock-selector",
        query=query,
        matched_count=int(payload.get("code_count") or matched_count(payload, len(rows))),
        top=args.top,
        max_per_industry=args.max_per_industry,
    )
    snapshot["updated_at"] = datetime.now(RUN_TZ).isoformat(timespec="seconds")
    snapshot["collection"] = {"complete": True, "source_rows": int(payload.get("code_count") or len(frame)), "eligible_rows": len(rows), "quote_date": as_of_date.isoformat(), "local_filter": "近三年分红、经营现金流与利润均为正，股息率>2%，PE/PB>0"}
    serialized = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")
    js_output = Path(args.js_output)
    js_output.parent.mkdir(parents=True, exist_ok=True)
    js_output.write_text("window.DIVIDEND_FACTOR_SNAPSHOT = " + serialized + ";\n", encoding="utf-8")

    csv_columns = [
        "code6", "name", "industry", "market_type", "research_status", "dqc_score",
        "valuation_score", "dividend_score", "cashflow_score", "dividend_yield", "pe_ttm", "pb",
        "average_payout", "cash_conversion", "cash_coverage", "dividend_stability", "dividend_cagr",
        "risk_flag_count", "factor_status", "factor_coverage",
    ]
    csv_frame = scored[[column for column in csv_columns if column in scored.columns]].copy()
    if "code6" in csv_frame.columns:
        csv_frame["code6"] = csv_frame["code6"].astype(str).str.extract(r"([0-9]{6})")[0].str.zfill(6)
    csv_output = Path(args.csv_output)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    csv_frame.to_csv(csv_output, index=False, encoding="utf-8-sig", float_format="%.4f")
    print(
        f"wrote={output} data_as_of={snapshot['data_as_of']} matched={snapshot['universe']['matched']} "
        f"valid={snapshot['universe']['valid']} candidates={len(snapshot['candidates'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
