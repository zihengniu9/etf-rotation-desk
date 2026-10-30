"""Shared completeness and dated-quote checks for financial collectors."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path

from build_dashboard_status import RUN_TZ, latest_completed_trading_day


def fetch_all(query_function, query: str, *, page_size: int = 10000, timeout: int = 90) -> dict:
    rows, seen, expected = [], set(), None
    for page in range(1, 101):
        response = query_function(query=query, page=str(page), limit=str(page_size),
                                  api_key=os.environ["IWENCAI_API_KEY"], call_type="normal", timeout=timeout)
        count = response.get("code_count", response.get("row_count"))
        try:
            count = float(count)
            if not math.isfinite(count) or count < 0 or int(count) != count:
                raise ValueError
        except (TypeError, ValueError):
            raise RuntimeError("Financial query lacks a valid total; snapshot kept intact") from None
        count = int(count)
        batch = response.get("datas")
        if not isinstance(batch, list) or (expected is not None and count != expected):
            raise RuntimeError("Financial query changed or has invalid rows; snapshot kept intact")
        expected = count
        for row in batch:
            code = str(row.get("股票代码") or "")
            if not code or code in seen:
                raise RuntimeError(f"Financial query has missing/duplicate code {code!r} on page {page}, rows={len(rows)}, total={expected}")
            seen.add(code)
            rows.append(row)
        if len(rows) == expected:
            return {"datas": rows, "code_count": expected, "query": query}
        if not batch or len(rows) > expected:
            break
    raise RuntimeError(f"Incomplete financial query: {len(rows)}/{expected}; snapshot kept intact")


def quote_query(as_of: str) -> str:
    day = datetime.fromisoformat(as_of).strftime("%Y年%m月%d日")
    return ("沪深A股非ST，股票代码，股票简称，所属同花顺行业，上市日期，股息率，"
            + "，".join(day + field for field in ("市盈率TTM", "市净率", "收盘价", "涨跌幅", "总市值")))


def dated_quotes(rows: list[dict], as_of: str) -> dict[str, dict]:
    key = as_of.replace("-", "")
    fields = {
        "最新价": ("收盘价", "收盘价:不复权", "收盘价_不复权"),
        "最新涨跌幅": ("涨跌幅", "涨跌幅:前复权"),
        "总市值": ("总市值",),
        "市盈率TTM": ("市盈率(pe,ttm)", "市盈率TTM"),
        "市净率": ("市净率(pb)", "市净率"),
        "动态市盈率": ("动态市盈率",),
    }
    for name, labels in fields.items():
        if name == "动态市盈率":
            continue
        if not any(f"{label}[{key}]" in row for row in rows for label in labels):
            raise RuntimeError(f"Missing dated quote field {labels[0]}[{key}]; snapshot kept intact")
    result = {}
    for row in rows:
        mapped = {name: next((row[f"{label}[{key}]"] for label in labels if row.get(f"{label}[{key}]") not in (None, "")), None)
                  for name, labels in fields.items()}
        # These are the dividend normalizer's preferred vendor labels.
        mapped["市盈率(pe,ttm)"] = mapped["市盈率TTM"]
        mapped["市净率(pb)"] = mapped["市净率"]
        result[str(row["股票代码"])] = mapped
    return result


def needs_refresh(module: str, as_of: str, outputs: Path = Path("outputs")) -> bool:
    try:
        payload = json.loads((outputs / f"{module}_factor_snapshot.json").read_text(encoding="utf-8"))
        snapshot_day = datetime.fromisoformat(str(payload.get("data_as_of") or "")).date()
        universe = payload.get("universe") or {}
        valid = universe.get("valid" if module == "dividend" else "stocks_financial_valid")
        return snapshot_day < datetime.fromisoformat(as_of).date() or (payload.get("collection") or {}).get("complete") is False or (valid is not None and int(valid) < 30)
    except (OSError, ValueError):
        return True


def record_attempt(module: str, as_of: str, result: str, outputs: Path = Path("outputs")) -> None:
    path = outputs / "financial_update_status.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        records = {}
    records[module] = {"target_date": as_of, "result": result, "updated_at": datetime.now(RUN_TZ).isoformat(timespec="seconds")}
    outputs.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--needed", choices=("growth", "dividend"))
    parser.add_argument("--as-of")
    parser.add_argument("--record", choices=("growth", "dividend"))
    parser.add_argument("--result", choices=("ok", "error"))
    args = parser.parse_args()
    as_of = args.as_of or latest_completed_trading_day(datetime.now(RUN_TZ)).isoformat()
    if args.record:
        if not args.result:
            parser.error("record requires result")
        record_attempt(args.record, as_of, args.result)
        return 0
    print(("yes" if needs_refresh(args.needed, as_of) else "no") if args.needed else as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
