from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


RUN_TZ = ZoneInfo("Asia/Hong_Kong")
OUTPUTS = Path("outputs")


def load_json(name: str) -> dict:
    path = OUTPUTS / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_csv_first(name: str) -> dict[str, str]:
    path = OUTPUTS / name
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.DictReader(handle), {})
    except OSError:
        return {}


def write_global_snapshot(name: str, payload: dict, global_name: str) -> None:
    if not payload:
        return
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (OUTPUTS / name).write_text(f"window.{global_name} = {serialized};\n", encoding="utf-8")


def build_latest_industry_snapshot(payload: dict) -> dict:
    if not payload:
        return {}
    data_as_of = iso_date(payload.get("data_as_of"))
    rows = [
        row for row in (payload.get("rows") or [])
        if iso_date(row.get("date")) == data_as_of
    ]
    return {
        "updated_at": payload.get("updated_at"),
        "data_as_of": data_as_of,
        "history_days": payload.get("history_days"),
        "rows": rows,
    }


def iso_date(value: object) -> str | None:
    match = re.search(r"(20[0-9]{2})[-/]?([01][0-9])[-/]?([0-3][0-9])", str(value or ""))
    return "-".join(match.groups()) if match else None


def file_state(
    data_date: str | None,
    reference_date: str | None,
    *,
    exists: bool,
    source_status: str = "",
    max_lag_days: int = 0,
) -> str:
    if not exists or not data_date:
        return "missing"
    if source_status and source_status.lower() not in {"success", "ok"}:
        return "error"
    if reference_date and data_date < reference_date:
        lag = (datetime.fromisoformat(reference_date).date() - datetime.fromisoformat(data_date).date()).days
        if lag > max_lag_days:
            return "stale"
    return "current"


def main() -> int:
    review = load_json("latest_market_review.json")
    short = load_json("shortterm_signal.json")
    short_factor = load_json("shortterm_factor_preview.json")
    industry_flow = load_json("industry_flow.json")
    industry = load_json("industry_update_status.json")
    etf = load_csv_first("etf_update_status.csv")
    trend = load_json("trend_engine.json")
    growth = load_json("growth_factor_snapshot.json")
    dividend = load_json("dividend_factor_snapshot.json")
    reference = iso_date(review.get("data_as_of"))
    industry_latest = build_latest_industry_snapshot(industry_flow)

    definitions = [
        {
            "key": "review", "title": "行情复盘", "href": "./market_mode.html#daily-review",
            "date": iso_date(review.get("data_as_of")), "exists": bool(review), "source_status": "ok",
            "coverage": f"涨停板清单 {len(review.get('leader_board') or [])} 只",
            "source": review.get("source") or "同花顺问财",
            "note": "最新完成交易日的收盘复盘",
            "cadence": "每个交易日收盘", "max_lag_days": 0,
        },
        {
            "key": "short", "title": "短线观察", "href": "./shortterm_dashboard.html",
            "date": iso_date(short.get("date")), "exists": bool(short), "source_status": short.get("status") or "",
            "coverage": f"梯队 {len(short.get('ladder') or [])} 只 · 因子候选 {len(short_factor.get('candidates') or [])} 只",
            "source": "短线 M/S/E/Q 本地生成器",
            "note": "信号日期早于复盘日期时仅作历史快照",
            "cadence": "每个交易日09:25与收盘", "max_lag_days": 0,
        },
        {
            "key": "industry", "title": "行业主线", "href": "./industry_mainline_dashboard.html",
            "date": iso_date(industry.get("data_as_of")), "exists": bool(industry), "source_status": industry.get("status") or "",
            "coverage": f"{industry.get('history_days', '—')} 个历史日 · {industry.get('rows', '—')} 行",
            "source": "行业成分股行情与资金承载",
            "note": industry.get("message") or "行业主线独立于短线题材",
            "cadence": "每个交易日收盘", "max_lag_days": 0,
        },
        {
            "key": "etf", "title": "ETF轮动", "href": "./index.html",
            "date": iso_date(etf.get("data_date")), "exists": bool(etf), "source_status": "ok" if etf else "",
            "coverage": f"排名 {etf.get('ranked_count', '—')} 只 · 实时报价 {etf.get('realtime_quotes', '—')} 只",
            "source": "ETF策略池与行情报价",
            "note": "策略首选与热榜保持双口径",
            "cadence": "交易时段与收盘", "max_lag_days": 0,
        },
        {
            "key": "trend", "title": "趋势因子", "href": "./trend_engine.html",
            "date": iso_date(trend.get("data_as_of")), "exists": bool(trend), "source_status": "ok",
            "coverage": f"历史股票 {trend.get('stocks_with_history', '—')} 只 · 信号 {(trend.get('profit_effect') or {}).get('signals', '—')} 个",
            "source": trend.get("source") or "同花顺问财日线",
            "note": "全主板趋势赚钱效应",
            "cadence": "每个交易日收盘", "max_lag_days": 0,
        },
        {
            "key": "growth", "title": "成长因子", "href": "./growth_factor.html",
            "date": iso_date(growth.get("data_as_of")), "exists": bool(growth), "source_status": "ok",
            "coverage": f"主板 {(growth.get('universe') or {}).get('stocks_mainboard', '—')} 只 · 有效 {(growth.get('universe') or {}).get('stocks_financial_valid', '—')} 只",
            "source": growth.get("source") or "问财财务与历史资讯",
            "note": "当前财报截面，逐股披露日回溯仍待完善",
            "cadence": "每周/财报披露后", "max_lag_days": 5,
        },
        {
            "key": "dividend", "title": "红利因子", "href": "./dividend_factor.html",
            "date": iso_date(dividend.get("data_as_of")), "exists": bool(dividend), "source_status": "ok",
            "coverage": f"匹配 {(dividend.get('universe') or {}).get('matched', '—')} 只 · 有效 {(dividend.get('universe') or {}).get('valid', '—')} 只",
            "source": dividend.get("source") or "同花顺问财",
            "note": "当前截面已更新；PandaAI 历史回测待参数确认",
            "cadence": "每周/分红方案更新后", "max_lag_days": 5,
        },
    ]

    modules = []
    for item in definitions:
        state = file_state(
            item["date"], reference, exists=item["exists"], source_status=item["source_status"],
            max_lag_days=int(item.get("max_lag_days", 0)),
        )
        modules.append({
            "key": item["key"], "title": item["title"], "href": item["href"], "state": state,
            "data_as_of": item["date"], "coverage": item["coverage"], "source": item["source"], "note": item["note"],
            "cadence": item.get("cadence", ""),
        })

    counts = {state: sum(item["state"] == state for item in modules) for state in ("current", "stale", "missing", "error")}
    payload = {
        "version": "dashboard-status-v1",
        "updated_at": datetime.now(RUN_TZ).isoformat(timespec="seconds"),
        "reference_date": reference,
        "reference_rule": "以最新完成交易日的行情复盘日期为新鲜度基准",
        "summary": counts,
        "modules": modules,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    (OUTPUTS / "dashboard_status.json").write_text(serialized + "\n", encoding="utf-8")
    (OUTPUTS / "dashboard_status.js").write_text("window.DASHBOARD_STATUS = " + serialized + ";\n", encoding="utf-8")
    write_global_snapshot("shortterm_signal.js", short, "SHORT_SIGNAL")
    if industry_latest:
        industry_latest_serialized = json.dumps(industry_latest, ensure_ascii=False, separators=(",", ":"))
        (OUTPUTS / "industry_flow_latest.json").write_text(industry_latest_serialized + "\n", encoding="utf-8")
    write_global_snapshot("industry_flow_latest.js", industry_latest, "INDUSTRY_FLOW")
    write_global_snapshot("trend_engine_snapshot.js", trend, "TREND_ENGINE_SNAPSHOT")
    write_global_snapshot("latest_market_review.js", review, "LATEST_MARKET_REVIEW")
    print(f"wrote=outputs/dashboard_status.json reference={reference} current={counts['current']} stale={counts['stale']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
