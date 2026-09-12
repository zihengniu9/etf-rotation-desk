from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo


RUN_TZ = ZoneInfo("Asia/Hong_Kong")
DATE_RE = re.compile(r"\[(\d{8})\]")


def load_query_function():
    script = Path(r"D:\Codex\CLI\skills\hithink-astock-selector\scripts\cli.py")
    if not script.exists():
        raise FileNotFoundError("hithink-astock-selector/scripts/cli.py not found")
    spec = importlib.util.spec_from_file_location("hithink_astock_selector_cli", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load hithink-astock-selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.query_astock


def number(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "")
        parsed = float(value)
        return parsed if parsed == parsed and abs(parsed) != float("inf") else default
    except (TypeError, ValueError):
        return default


def first_value(row: dict, names: tuple[str, ...], default=None):
    for name in names:
        for key, value in row.items():
            if key == name or str(key).startswith(f"{name}["):
                if value not in (None, ""):
                    return value
    return default


def date_text(value: date) -> str:
    return value.strftime("%Y年%m月%d日")


def previous_business_day(value: date) -> date:
    value -= timedelta(days=1)
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def query_rows(query_function, query: str, *, limit: int = 100) -> list[dict]:
    if not os.environ.get("IWENCAI_API_KEY"):
        raise RuntimeError("IWENCAI_API_KEY is not configured")
    if not os.environ.get("HTTPS_PROXY"):
        raise RuntimeError("HTTPS_PROXY is not configured; refusing direct network access")
    response = query_function(
        query=query,
        page="1",
        limit=str(limit),
        api_key=os.environ["IWENCAI_API_KEY"],
        call_type="normal",
        timeout=60,
    )
    if "datas" not in response:
        raise RuntimeError(f"Wencai response has no datas: {response}")
    return list(response.get("datas") or [])


def query_stock_rows(query_function, query: str, flag: str) -> list[dict]:
    """Require dated stock predicates and complete pagination, never index statistics."""
    if not os.environ.get("IWENCAI_API_KEY") or not os.environ.get("HTTPS_PROXY"):
        raise RuntimeError("Wencai credentials and authenticated tunnel are required")
    rows, seen, total = [], set(), None
    for page in range(1, 101):
        response = query_function(query=query, page=str(page), limit="100",
                                  api_key=os.environ["IWENCAI_API_KEY"], call_type="normal", timeout=60)
        count = number(response.get("code_count"), None)
        if count is None or count < 0 or count != int(count) or not isinstance(response.get("datas"), list):
            raise RuntimeError("Stock query lacks a valid total or rows")
        if total is not None and total != int(count):
            raise RuntimeError("Stock query total changed during pagination")
        total = int(count)
        batch = response["datas"]
        for row in batch:
            code = str(row.get("股票代码") or "")
            if not re.fullmatch(r"(?:0|3|6)\d{5}\.(?:SH|SZ)", code) or "ST" in str(row.get("股票简称") or "").upper():
                raise RuntimeError("Expected non-ST Shanghai/Shenzhen stocks, not index/component statistics")
            if row.get(flag) not in (True, 1, "true") or code in seen:
                raise RuntimeError(f"Missing dated predicate or duplicate stock: {code} {flag}")
            seen.add(code)
            rows.append(row)
        if len(rows) == total:
            return rows
        if not batch or len(rows) > total:
            break
    raise RuntimeError(f"Incomplete stock query: received {len(rows)} of {total}")


def summarize_market(leaders: list[dict], down: list[dict], opened: list[dict]) -> dict:
    closed_codes = {row["code"] for row in leaders}
    opened_codes = {row["股票代码"] for row in opened}
    failed = opened_codes - closed_codes
    touched = opened_codes | closed_codes
    return {
        "index_change": None,
        "limit_up": len(closed_codes), "limit_down": len(down),
        "failed_rate": round(len(failed) / len(touched), 4) if touched else None,
        "failed_count": len(failed), "touched_limit_up": len(touched),
        "max_boards": max((row["boards"] for row in leaders), default=0),
        "board_rows": len(leaders),
        "board_break_rate": round(sum(row["break_count"] > 0 for row in leaders) / len(leaders), 4) if leaders else None,
    }


def industry_list(value) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[;,；，]", str(value or ""))
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def recent_activity(row: dict) -> tuple[int | None, int | None]:
    """Extract an N-day/M-board activity label without treating it as current boards."""

    text = str(first_value(row, ("几天几板", "近期连板描述"), "") or "")
    match = re.search(r"(\d+)\s*天\s*(\d+)\s*板", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    count = first_value(row, ("近10日涨停次数", "近10日涨停天数", "近期涨停次数"), None)
    if count not in (None, ""):
        return 10, int(number(count, 0))
    return None, None


def normalize_leader(row: dict, as_of: str) -> dict:
    name = str(first_value(row, ("股票简称", "股票名称", "名称"), "")).strip()
    code = str(first_value(row, ("股票代码", "证券代码", "代码"), "")).strip()
    boards = number(first_value(row, ("连续涨停天数", "连板数"), 0))
    if boards == 0:
        board_text = str(first_value(row, ("几天几板",), ""))
        match = re.search(r"(\d+)天", board_text)
        boards = number(match.group(1), 0) if match else 0
    recent_days, recent_board_count = recent_activity(row)
    return {
        "code": code,
        "name": name.replace("*ST", "").strip(),
        "boards": int(boards),
        "change": round(number(first_value(row, ("最新涨跌幅", f"涨跌幅[{as_of.replace('-', '')}]"), 0)), 2),
        "break_count": int(number(first_value(row, ("涨停开板次数",), 0))),
        "final_time": str(first_value(row, ("最终涨停时间",), "")),
        "theme": industry_list(first_value(row, ("所属同花顺行业", "所属行业", "行业"), []))[:3],
        "reason": str(first_value(row, ("涨停原因",), "")).strip(),
        "recent_days": recent_days,
        "recent_board_count": recent_board_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the latest Wencai close review snapshot.")
    parser.add_argument("--as-of", default="", help="Latest completed trading date, YYYY-MM-DD")
    parser.add_argument("--output", default="outputs/latest_market_review.json")
    args = parser.parse_args()

    today = datetime.now(RUN_TZ).date()
    as_of_date = date.fromisoformat(args.as_of) if args.as_of else today
    if not args.as_of and datetime.now(RUN_TZ).time() < datetime.strptime("15:30", "%H:%M").time():
        as_of_date = previous_business_day(as_of_date)
    while as_of_date.weekday() >= 5:
        as_of_date -= timedelta(days=1)
    as_of = as_of_date.isoformat()
    prior = previous_business_day(as_of_date).isoformat()
    as_of_query = date_text(as_of_date)
    prior_query = date_text(date.fromisoformat(prior))
    query_function = load_query_function()

    universe = "沪深A股 非ST"
    leaders_query = f"{as_of_query}{universe} 涨停股票 股票简称 股票代码 所属同花顺行业 连续涨停天数 涨停开板次数 涨停原因 近10日涨停次数 几天几板"
    down_query = f"{as_of_query}{universe} 跌停 股票代码 股票简称"
    opened_query = f"{as_of_query}{universe} 曾涨停 股票代码 股票简称"
    feedback_query = f"{prior_query}{universe} 涨停股票 {as_of_query}涨跌幅"
    date_key = as_of.replace("-", "")
    leader_rows = query_stock_rows(query_function, leaders_query, f"涨停[{date_key}]")
    down_rows = query_stock_rows(query_function, down_query, f"跌停[{date_key}]")
    opened_rows = query_stock_rows(query_function, opened_query, f"涨停开板[{date_key}]")
    feedback_rows = query_stock_rows(query_function, feedback_query, f"涨停[{prior.replace('-', '')}]")
    leaders = [normalize_leader(row, as_of) for row in leader_rows]
    leaders.sort(key=lambda row: (-row["boards"], row["break_count"], row["final_time"]))
    market = summarize_market(leaders, down_rows, opened_rows)
    limit_up, limit_down = market["limit_up"], market["limit_down"]
    failed_rate = market["failed_rate"]

    feedback_values = []
    for row in feedback_rows:
        value = number(row.get(f"涨跌幅[{date_key}]"), None)
        if value is None:
            raise RuntimeError(f"Missing dated feedback for {row.get('股票代码')} on {as_of}")
        feedback_values.append(value)
    positive_ratio = sum(value > 0 for value in feedback_values) / len(feedback_values) if feedback_values else None
    feedback = {
        "count": len(feedback_values),
        "avg_return": round(mean(feedback_values), 3) if feedback_values else None,
        "median_return": round(median(feedback_values), 3) if feedback_values else None,
        "positive_ratio": round(positive_ratio, 3) if positive_ratio is not None else None,
        "signal_date": prior,
        "evaluation_date": as_of,
    }

    themes: dict[str, int] = {}
    for row in leaders:
        for theme in row["theme"]:
            themes[theme] = themes.get(theme, 0) + 1
    theme_rank = [{"theme": theme, "count": count} for theme, count in sorted(themes.items(), key=lambda item: (-item[1], item[0]))[:8]]
    max_boards = market["max_boards"]

    if failed_rate is None or feedback["avg_return"] is None:
        label = "数据不足"
        conclusion = "缺少完整炸板或隔日反馈样本，暂不判断短线强弱。"
    elif limit_up >= 60 and limit_down <= 8 and failed_rate < 0.25 and feedback["avg_return"] > 0:
        label = "短线核心观察"
        conclusion = "涨停扩散、连板高度和隔日反馈同时偏强，优先研究高辨识度核心；仍需等次日竞价确认。"
    elif limit_down >= 20 or failed_rate >= 0.35 or feedback["avg_return"] < 0:
        label = "防守等待"
        conclusion = "涨停结构的延续性不足或风险释放明显，先降低暴露，等待核心反馈重新修复。"
    else:
        label = "结构性观察"
        conclusion = "市场存在局部强势，但尚未形成足够一致的短线环境，优先做分层观察。"

    payload = {
        "version": "latest-review-v1",
        "updated_at": datetime.now(RUN_TZ).isoformat(timespec="seconds"),
        "data_as_of": as_of,
        "source": "同花顺问财 · hithink-astock-selector",
        "market": market,
        "market_evidence": {
            "complete": failed_rate is not None and bool(feedback_values),
            "universe": "沪深A股（非ST，含创业板与科创板）",
            "data_as_of": as_of,
            "limit_up_codes": sorted(row["code"] for row in leaders),
            "limit_down_codes": sorted(row["股票代码"] for row in down_rows),
            "opened_codes": sorted(row["股票代码"] for row in opened_rows),
            "feedback_codes": sorted(row["股票代码"] for row in feedback_rows),
            "failed_rate_definition": "收盘未封住的曾涨停股票数 / 当日触及涨停股票总数；不等于封板股票的盘中开板比例",
        },
        "previous_limit_up_feedback": feedback,
        "leader_board": leaders[:12],
        "leader_pool": leaders,
        "theme_rank": theme_rank,
        "review": {
            "label": label,
            "conclusion": conclusion,
            "suitable": ["只研究高辨识度核心及其同梯队竞争关系", "次日竞价不恶化且板块仍有扩散时再复核", "把隔日反馈作为环境确认，不把涨停数量当买点"],
            "avoid": ["中后排补涨与末端加速", "仅凭单日涨停数量追逐题材", "忽略炸板率和核心竞价的主动交易"],
            "next_day_checks": ["最高板是否继续晋级或出现负反馈", "昨日涨停股溢价是否继续为正", "炸板率、跌停家数和板块扩散是否同步改善"],
            "note": "这是收盘复盘快照，不等于次日自动交易指令。",
        },
        "queries": [leaders_query, down_query, opened_query, feedback_query],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Keep the close review as an auditable daily evidence point for the
    # 30-calendar-day leader activity score. This is a replace-by-date write,
    # so rerunning the updater remains idempotent and never double-counts a day.
    history_path = output.parent / "daily_seal_history.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        history = {}
    history[as_of.replace("-", "")] = [
        {
            "name": row["name"],
            "code": row["code"],
            "boards": max(1, int(row.get("boards") or 1)),
            "amount": None,
            "concepts": row.get("theme") or [],
        }
        for row in leaders
        if row.get("code")
    ]
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote={output} data_as_of={as_of} limit_up={int(limit_up)} limit_down={int(limit_down)} max_boards={max_boards}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
