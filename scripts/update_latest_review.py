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


def dated_flag(row: dict, prefixes: tuple[str, ...], date_key: str) -> bool:
    """问财按问法不同会把条件列命名为 涨停[日期] / 曾涨停[日期] / 涨停开板[日期] 等，任一为真即可。"""
    for key, value in row.items():
        if any(key == f"{prefix}[{date_key}]" for prefix in prefixes) and value in (True, 1, "true", "是"):
            return True
    return False


def query_stock_rows(query_function, query: str, flag, *, filter_universe: bool = False) -> list[dict]:
    """Require dated stock predicates and complete pagination, never index statistics.

    ``flag`` is either a full column name such as ``涨停[20261016]`` or a tuple
    ``(prefixes, date_key)``. With ``filter_universe`` the query may return ST /
    北交所 rows (simplified wording), which are dropped locally instead of failing.
    """
    if not os.environ.get("IWENCAI_API_KEY") or not os.environ.get("HTTPS_PROXY"):
        raise RuntimeError("Wencai credentials and authenticated tunnel are required")
    if isinstance(flag, str):
        match = re.fullmatch(r"(.+)\[(\d{8})\]", flag)
        prefixes, date_key = ((match.group(1),), match.group(2)) if match else ((flag,), "")
    else:
        prefixes, date_key = flag
    rows, seen, total, received = [], set(), None, 0
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
        received += len(batch)
        for row in batch:
            code = str(row.get("股票代码") or "")
            in_universe = bool(re.fullmatch(r"(?:0|3|6)\d{5}\.(?:SH|SZ)", code)) and "ST" not in str(row.get("股票简称") or "").upper()
            if not in_universe:
                if filter_universe:
                    continue
                raise RuntimeError("Expected non-ST Shanghai/Shenzhen stocks, not index/component statistics")
            if not dated_flag(row, prefixes, date_key) or code in seen:
                raise RuntimeError(f"Missing dated predicate or duplicate stock: {code} {prefixes[0]}[{date_key}]")
            seen.add(code)
            rows.append(row)
        if received == total:
            return rows
        if not batch or received > total:
            break
    raise RuntimeError(f"Incomplete stock query: received {received} of {total}")


def query_with_fallback(query_function, variants: list[tuple[str, bool]], flag, attempts: list[dict], label: str) -> tuple[list[dict], str]:
    """依次尝试多种问法：报错或返回 0 只都换下一种；全部为 0 时返回空表，全部报错时抛出。"""
    errors = []
    for query, filter_universe in variants:
        try:
            rows = query_stock_rows(query_function, query, flag, filter_universe=filter_universe)
        except Exception as error:  # 问法不被识别、字段改名都只影响这一种问法
            attempts.append({"label": label, "query": query, "rows": None, "error": f"{type(error).__name__}: {error}"[:200]})
            errors.append(error)
            continue
        attempts.append({"label": label, "query": query, "rows": len(rows)})
        if rows:
            return rows, query
    if errors and len(errors) == len(variants):
        raise RuntimeError(f"{label}: all query variants failed: {errors[-1]}")
    return [], variants[0][0]


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
    change = number(row.get(f"涨跌幅[{as_of.replace('-', '')}]"), None)
    return {
        "code": code,
        "name": name.replace("*ST", "").strip(),
        "boards": int(boards),
        "change": round(change, 2) if change is not None else None,
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
    parser.add_argument("--probe", action="store_true", help="只打印每种问法返回的股票数，不写文件")
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
    date_key = as_of.replace("-", "")
    prior_key = prior.replace("-", "")
    # 第一种是原问法；问财口径变化时（2026-10 起原问法返回 0 只涨停），依次退到更简单的问法，
    # 简化问法可能带出 ST / 北交所，本地过滤，不改变“沪深A股 非ST”口径。
    leader_variants = [
        (f"{as_of_query}{universe} 涨停股票 股票简称 股票代码 所属同花顺行业 连续涨停天数 涨停开板次数 涨停原因 近10日涨停次数 几天几板", False),
        (f"{as_of_query}{universe} 涨停的股票 连续涨停天数 涨停开板次数 涨停原因 所属同花顺行业 {as_of_query}涨跌幅", False),
        (f"{as_of_query}涨停的股票 连续涨停天数 涨停开板次数 所属同花顺行业 {as_of_query}涨跌幅", True),
        (f"{as_of_query}涨停的股票 连续涨停天数 {as_of_query}涨跌幅", True),
    ]
    down_variants = [(f"{as_of_query}{universe} 跌停 股票代码 股票简称", False), (f"{as_of_query}跌停的股票", True)]
    opened_variants = [
        (f"{as_of_query}{universe} 曾涨停 股票代码 股票简称", False),
        (f"{as_of_query}曾涨停的股票", True),
        (f"{as_of_query}炸板的股票", True),
    ]
    feedback_variants = [(f"{prior_query}{universe} 涨停股票 {as_of_query}涨跌幅", False), (f"{prior_query}涨停的股票 {as_of_query}涨跌幅", True)]
    attempts: list[dict] = []
    if args.probe:
        for label, variants, flag in (("涨停", leader_variants, (("涨停",), date_key)), ("跌停", down_variants, (("跌停",), date_key)),
                                      ("曾涨停", opened_variants, (("涨停开板", "曾涨停", "炸板"), date_key)), ("隔日反馈", feedback_variants, (("涨停",), prior_key))):
            for query, filter_universe in variants:
                try:
                    rows = query_stock_rows(query_function, query, flag, filter_universe=filter_universe)
                    print(f"{label}\t{len(rows)}\t{query}")
                except Exception as error:
                    print(f"{label}\tERROR {type(error).__name__}: {str(error)[:120]}\t{query}")
        return 0
    leader_rows, leaders_query = query_with_fallback(query_function, leader_variants, (("涨停",), date_key), attempts, "涨停")
    down_rows, down_query = query_with_fallback(query_function, down_variants, (("跌停",), date_key), attempts, "跌停")
    opened_rows, opened_query = query_with_fallback(query_function, opened_variants, (("涨停开板", "曾涨停", "炸板"), date_key), attempts, "曾涨停")
    feedback_rows, feedback_query = query_with_fallback(query_function, feedback_variants, (("涨停",), prior_key), attempts, "隔日反馈")
    leaders = [normalize_leader(row, as_of) for row in leader_rows]
    leaders.sort(key=lambda row: (-row["boards"], row["break_count"], row["final_time"]))
    market = summarize_market(leaders, down_rows, opened_rows)
    limit_up, limit_down = market["limit_up"], market["limit_down"]
    failed_rate = market["failed_rate"]

    feedback_values, missing_feedback = [], []
    for row in feedback_rows:
        value = number(row.get(f"涨跌幅[{date_key}]"), None)
        if value is None:
            missing_feedback.append(str(row.get("股票代码") or ""))
            continue
        feedback_values.append(value)
    positive_ratio = sum(value > 0 for value in feedback_values) / len(feedback_values) if feedback_values else None
    feedback = {
        "count": len(feedback_values),
        "expected_count": len(feedback_rows),
        "missing_codes": missing_feedback,
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

    # 当日 0 只涨停但前一日有涨停、或当日有跌停，几乎一定是取数失败而不是真实行情。
    anomalies = []
    if not leaders and (feedback_rows or down_rows):
        anomalies.append(f"当日涨停查询返回 0 只（昨日涨停 {len(feedback_rows)} 只、当日跌停 {len(down_rows)} 只），判为取数失败")
    if missing_feedback:
        anomalies.append(f"隔日反馈缺少指定日期涨幅：{','.join(missing_feedback)}；不以最新涨幅或0补齐")
    complete = failed_rate is not None and bool(feedback_values) and not anomalies
    if not complete:
        label = "数据不足"
        conclusion = "缺少完整指定日期的炸板或隔日反馈样本，暂不判断短线强弱。"

    payload = {
        "version": "latest-review-v1",
        "updated_at": datetime.now(RUN_TZ).isoformat(timespec="seconds"),
        "data_as_of": as_of,
        "source": "同花顺问财 · hithink-astock-selector",
        "market": market,
        "market_evidence": {
            "complete": complete,
            "anomalies": anomalies,
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
        "query_attempts": attempts,
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
    if not complete and not leaders:
        # 取数失败时不往 30 日涨停活跃度历史里写空的一天，避免把失败记成“当日无涨停”。
        print(f"WARN review incomplete: {'; '.join(anomalies) or 'missing failed-rate or feedback'}")
        print(f"wrote={output} data_as_of={as_of} limit_up=0 limit_down={int(limit_down)} complete=false (history untouched)")
        return 3
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
    print(f"wrote={output} data_as_of={as_of} limit_up={int(limit_up)} limit_down={int(limit_down)} max_boards={max_boards} complete={str(complete).lower()} leaders_query={leaders_query}")
    return 0 if complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
