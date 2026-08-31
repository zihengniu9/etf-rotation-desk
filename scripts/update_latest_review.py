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


def industry_list(value) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[;,；，]", str(value or ""))
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def normalize_leader(row: dict, as_of: str) -> dict:
    name = str(first_value(row, ("股票简称", "股票名称", "名称"), "")).strip()
    code = str(first_value(row, ("股票代码", "证券代码", "代码"), "")).strip()
    boards = number(first_value(row, ("连续涨停天数", "连板数"), 0))
    if boards == 0:
        board_text = str(first_value(row, ("几天几板",), ""))
        match = re.search(r"(\d+)天", board_text)
        boards = number(match.group(1), 0) if match else 0
    return {
        "code": code,
        "name": name.replace("*ST", "").strip(),
        "boards": int(boards),
        "change": round(number(first_value(row, ("最新涨跌幅", f"涨跌幅[{as_of.replace('-', '')}]"), 0)), 2),
        "break_count": int(number(first_value(row, ("涨停开板次数",), 0))),
        "final_time": str(first_value(row, ("最终涨停时间",), "")),
        "theme": industry_list(first_value(row, ("所属同花顺行业", "所属行业", "行业"), []))[:3],
        "reason": str(first_value(row, ("涨停原因",), "")).strip(),
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

    # 统计类问句不拼接日期，问财会在返回字段名中带上最近完整交易日；
    # 指定日期只用于清单和隔日反馈，避免盘中/周末把统计列解析成空值。
    stats_query = "涨停家数 跌停家数 炸板率 最高连板数"
    leaders_query = f"{as_of_query}涨停股票 股票简称 股票代码 所属同花顺行业 连续涨停天数 涨停开板次数 涨停原因"
    feedback_query = f"{prior_query}涨停股票 {as_of_query}涨跌幅"
    stats_rows = query_rows(query_function, stats_query, limit=10)
    leader_rows = query_rows(query_function, leaders_query, limit=100)
    feedback_rows = query_rows(query_function, feedback_query, limit=100)
    if not stats_rows or not leader_rows:
        raise RuntimeError(f"No completed close review returned for {as_of}")

    stats = stats_rows[0] if stats_rows else {}
    limit_up = number(first_value(stats, ("涨停家数",), len(leader_rows)))
    limit_down = number(first_value(stats, ("跌停家数",), 0))
    failed_rate = number(first_value(stats, ("炸板率",), 0))
    index_change = number(first_value(stats, ("最新涨跌幅:前复权", "最新涨跌幅"), 0))
    leaders = [normalize_leader(row, as_of) for row in leader_rows]
    leaders = [row for row in leaders if row["name"] and not row["name"].upper().startswith("ST")]
    leaders.sort(key=lambda row: (-row["boards"], row["break_count"], row["final_time"]))

    feedback_values = []
    for row in feedback_rows:
        value = first_value(row, (f"涨跌幅[{as_of.replace('-', '')}]", "最新涨跌幅"), None)
        if value not in (None, ""):
            feedback_values.append(number(value))
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
    max_boards = leaders[0]["boards"] if leaders else int(number(first_value(stats, ("最高连板数",), 0)))
    closed_count = sum(row["break_count"] == 0 for row in leaders)
    break_rate = 1 - closed_count / len(leaders) if leaders else None

    if limit_up >= 60 and limit_down <= 8 and failed_rate < 25 and (feedback["avg_return"] or 0) > 0:
        label = "短线核心观察"
        conclusion = "涨停扩散、连板高度和隔日反馈同时偏强，优先研究高辨识度核心；仍需等次日竞价确认。"
    elif limit_down >= 20 or failed_rate >= 35 or (feedback["avg_return"] or 0) < 0:
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
        "market": {
            "index_change": round(index_change, 3),
            "limit_up": int(limit_up),
            "limit_down": int(limit_down),
            "failed_rate": round(failed_rate / 100, 4),
            "max_boards": max_boards,
            "board_rows": len(leaders),
            "board_break_rate": round(break_rate, 4) if break_rate is not None else None,
        },
        "previous_limit_up_feedback": feedback,
        "leader_board": leaders[:12],
        "theme_rank": theme_rank,
        "review": {
            "label": label,
            "conclusion": conclusion,
            "suitable": ["只研究高辨识度核心及其同梯队竞争关系", "次日竞价不恶化且板块仍有扩散时再复核", "把隔日反馈作为环境确认，不把涨停数量当买点"],
            "avoid": ["中后排补涨与末端加速", "仅凭单日涨停数量追逐题材", "忽略炸板率和核心竞价的主动交易"],
            "next_day_checks": ["最高板是否继续晋级或出现负反馈", "昨日涨停股溢价是否继续为正", "炸板率、跌停家数和板块扩散是否同步改善"],
            "note": "这是收盘复盘快照，不等于次日自动交易指令。",
        },
        "queries": [stats_query, leaders_query, feedback_query],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote={output} data_as_of={as_of} limit_up={int(limit_up)} limit_down={int(limit_down)} max_boards={max_boards}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
