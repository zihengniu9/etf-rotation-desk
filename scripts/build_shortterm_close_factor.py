from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


RUN_TZ = ZoneInfo("Asia/Hong_Kong")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def close_time_score(value: object) -> float:
    text = str(value or "")
    clock = text[-8:] if len(text) >= 8 else text
    if clock and clock < "10:00:00":
        return 100.0
    if clock and clock < "11:00:00":
        return 82.0
    if clock and clock < "14:00:00":
        return 60.0
    return 35.0


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def is_main_board(code: object) -> bool:
    text = str(code or "").upper().split(".", 1)[0].zfill(6)
    return text.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))


def code_key(code: object) -> str:
    return str(code or "").upper().split(".", 1)[0].zfill(6)


def split_theme(value: object) -> list[str]:
    text = str(value or "").replace("；", "-").replace("/", "-")
    return [item.strip() for item in text.split("-") if item.strip()][:3]


def load_trend_rows(path: Path, as_of: str) -> list[dict[str, str]]:
    """Load the same-day main-board trend cross-section without using forward labels."""

    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            row
            for row in rows
            if str(row.get("date") or "") == as_of
            and is_main_board(row.get("code"))
            and not str(row.get("name") or "").upper().startswith("ST")
        ]


def percentile_score(value: float | None, values: list[float]) -> float | None:
    if value is None or not values:
        return None
    below_or_equal = sum(item <= value for item in values)
    return round(clamp(below_or_equal / len(values) * 100.0), 1)


def load_heat_rows(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[str, dict[str, float]] = {}

    def merge(row: dict) -> None:
        key = code_key(row.get("code"))
        if not key:
            return
        current = result.setdefault(key, {})
        heat = number(row.get("heat"), None)
        change = number(row.get("change"), None)
        amount = number(row.get("amount"), None)
        turnover = number(row.get("turnover_rate"), None)
        if heat is not None:
            current["heat"] = max(heat, current.get("heat", 0.0))
        if change is not None:
            current["change"] = change
        if amount is not None:
            current["amount"] = amount
        if turnover is not None:
            current["turnover"] = turnover

    # The detailed industry blocks cover selected hot industries. The compact
    # hot-industry index contains another useful layer: the leading stock for
    # each of the broader hot-industry ranks. Merge both without double-counting.
    for industry in (payload.get("industries") or {}).values():
        for row in industry.get("rows") or []:
            merge(row)
    for industry in (payload.get("hot_industries") or {}).values():
        leader = industry.get("leader") if isinstance(industry, dict) else None
        if leader:
            merge(leader)
    return result


def load_recent_limitup_counts(
    path: Path,
    as_of: str,
    current_rows: list[dict],
) -> tuple[dict[str, int], int, str | None]:
    """Count unique limit-up days in the trailing 30 calendar days.

    The history is an evidence layer. If its latest date lags the signal date,
    the returned coverage count makes that limitation visible in the snapshot.
    """

    try:
        target = date.fromisoformat(as_of)
    except ValueError:
        return {}, 0, None
    start = target - timedelta(days=30)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        payload = {}
    counts: dict[str, int] = Counter()
    covered_dates: set[date] = set()
    max_date: date | None = None
    for key, rows in (payload or {}).items():
        try:
            stamp = date.fromisoformat(str(key)[:4] + "-" + str(key)[4:6] + "-" + str(key)[6:8])
        except ValueError:
            continue
        if not start <= stamp <= target:
            continue
        covered_dates.add(stamp)
        max_date = max(max_date, stamp) if max_date else stamp
        seen: set[str] = set()
        for row in rows or []:
            key_code = code_key(row.get("code"))
            if key_code and key_code not in seen:
                counts[key_code] += 1
                seen.add(key_code)
    current_key = target.strftime("%Y%m%d")
    if current_rows and current_key not in (payload or {}):
        covered_dates.add(target)
        max_date = max(max_date, target) if max_date else target
        for row in current_rows:
            key_code = code_key(row.get("code"))
            if key_code:
                counts[key_code] += 1
    return dict(counts), len(covered_dates), max_date.isoformat() if max_date else None


def leader_reasons(item: dict) -> list[str]:
    reasons: list[str] = []
    if item.get("r60_pct") is not None:
        reasons.append(f"60日涨幅 {item['r60_pct']:+.1f}%")
    if item.get("recent_limitup_days", 0) > 0:
        reasons.append(f"近30日涨停 {item['recent_limitup_days']}次")
    if item.get("heat") is not None:
        reasons.append(f"热度 {item['heat']:.0f}")
    return reasons or ["龙头证据待补齐"]


def build_leader_candidates(
    rows: list[dict[str, str]],
    core_codes: set[str],
    current_leaders: list[dict],
    score_m: float,
    roles_path: Path,
    seal_history_path: Path,
    limit: int,
) -> tuple[list[dict], dict[str, object]]:
    """Build a leader pool from 60d return, recent limit-ups and stock heat."""

    heat_rows = load_heat_rows(roles_path)
    heat_values = [item["heat"] for item in heat_rows.values() if item.get("heat") is not None]
    r60_values = [number(row.get("r60"), None) for row in rows]
    r60_values = [item for item in r60_values if item is not None]
    recent_counts, covered_days, history_max_date = load_recent_limitup_counts(
        seal_history_path, str(rows[0].get("date") if rows else ""), current_leaders
    )

    result: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "")
        key = code_key(code)
        if not code or key in {code_key(item) for item in core_codes}:
            continue
        r60 = number(row.get("r60"), None)
        r60_pct = r60 * 100.0 if r60 is not None else None
        r60_score = percentile_score(r60, r60_values)
        recent_days = int(recent_counts.get(key, 0))
        recent_score = 0.0 if recent_days == 0 else min(100.0, 25.0 + (recent_days - 1) * 15.0)
        heat = heat_rows.get(key, {}).get("heat")
        heat_score = percentile_score(heat, heat_values)
        # The current hot-stock source is a ranked sample, not a full-market
        # heat series. Keep the 25% slot in the score with a neutral midpoint
        # when a stock is outside that sample; never treat an absent value as
        # a high score or silently renormalize the factor.
        heat_score = 50.0 if heat_score is None else heat_score
        components = [(0.40, r60_score), (0.35, recent_score), (0.25, heat_score)]
        available = [(weight, value) for weight, value in components if value is not None]
        if not available:
            continue
        leader_score = round(sum(weight * value for weight, value in available) / sum(weight for weight, _ in available), 1)
        if leader_score < 45.0 or not (recent_days > 0 or (r60_score or 0) >= 65 or (heat_score or 0) >= 65):
            continue
        roles = heat_rows.get(key, {})
        r60_display = "—" if r60_pct is None else f"{r60_pct:+.1f}%"
        current_change = roles.get("change")
        themes = split_theme(row.get("theme"))
        item = {
            "name": str(row.get("name") or ""),
            "code": code,
            "pool": "leader",
            "pool_label": "龙头观察",
            "lane": "leader",
            "lane_label": "龙头观察",
            "theme": themes[0] if themes else "未分组",
            "themes": themes,
            "boards": 0,
            "recent_days": 30,
            "recent_board_count": recent_days,
            "theme_breadth": None,
            "gap": None,
            "daily_change": current_change,
            "opens": None,
            "amount_yi": round(roles["amount"] / 1e8, 2) if roles.get("amount") is not None else (round(number(row.get("amount")) / 1e8, 2) if row.get("amount") else None),
            "turnover": roles.get("turnover", number(row.get("turnover"), None)),
            "volume_ratio": number(row.get("volume_ratio"), None),
            "pop": heat_score,
            "heat": heat,
            "heat_score": heat_score,
            "r60": r60,
            "r60_pct": r60_pct,
            "r60_score": r60_score,
            "recent_limitup_days": recent_days,
            "recent_limitup_score": round(recent_score, 1),
            "note": "、".join(leader_reasons({"r60_pct": r60_pct, "recent_limitup_days": recent_days, "heat": heat})),
            "why": leader_reasons({"r60_pct": r60_pct, "recent_limitup_days": recent_days, "heat": heat}),
            "market": score_m,
            "strength": r60_score,
            "position": round(recent_score, 1),
            "quality": heat_score,
            "total": leader_score,
            "action": "放弃：市场门控" if score_m <= 0 else ("龙头重点" if leader_score >= 75 else "龙头观察"),
            "yizi": False,
            "lanban": False,
            "theme_rank": None,
            "theme_delta": None,
            "higher_dead": "不适用：龙头观察池",
            "high60": None,
            "first_break": False,
            "missing": ["09:25竞价"] + ([] if r60 is not None else ["近60日涨幅"]) + ([] if recent_days > 0 or covered_days >= 20 else ["近30日涨停历史覆盖不足"]) + ([] if heat is not None else ["股票热度样本未覆盖"]),
            "break_count": None,
            "final_time": None,
            "trend_score": None,
            "trend_setup": None,
            "trend_eligible": None,
            "overheat_penalty": None,
            "leader_source": "60日涨幅 + 近30日涨停 + 同花顺个股热度",
            "history_max_date": history_max_date,
            "history_covered_days": covered_days,
        }
        result.append(item)
    result.sort(key=lambda item: (-item["total"], -item["recent_limitup_days"], -(item["heat_score"] or 0), item["code"]))
    selected = result[:limit]
    for index, item in enumerate(selected, 1):
        item["rank"] = index
        item["rank_label"] = f"龙头{index}"
    return selected, {"scanned": len(rows), "history_covered_days": covered_days, "history_max_date": history_max_date, "heat_covered": len(heat_rows)}
def market_score(market: dict, feedback: dict) -> float:
    required = [(market, key) for key in ("limit_up", "limit_down", "failed_rate", "max_boards")]
    required += [(feedback, key) for key in ("avg_return", "positive_ratio")]
    for source, key in required:
        value = number(source.get(key), None)
        if value is None or not math.isfinite(value):
            raise ValueError(f"Incomplete short-term market evidence: {key}")
    if not 0 <= float(market["failed_rate"]) <= 1 or not 0 <= float(feedback["positive_ratio"]) <= 1:
        raise ValueError("Market ratios must be fractions in [0, 1]")
    limit_up = number(market.get("limit_up"))
    limit_down = number(market.get("limit_down"))
    failed_rate = number(market.get("failed_rate"))
    max_boards = number(market.get("max_boards"))
    avg_return = number(feedback.get("avg_return"))
    positive_ratio = number(feedback.get("positive_ratio"))
    score = (
        clamp((limit_up - 20.0) / 70.0 * 25.0, 0, 25)
        + clamp((30.0 - limit_down) / 30.0 * 20.0, 0, 20)
        + clamp((0.45 - failed_rate) / 0.35 * 20.0, 0, 20)
        + clamp(max_boards / 7.0 * 15.0, 0, 15)
        + clamp((avg_return + 2.0) / 5.0 * 12.0, 0, 12)
        + clamp(positive_ratio / 0.65 * 8.0, 0, 8)
    )
    return round(clamp(score), 1)


def market_risks(market: dict, feedback: dict) -> list[str]:
    # Same risk vetoes as the close review, before candidate ranking.
    reasons = []
    if number(market.get("limit_down")) >= 20:
        reasons.append("跌停不少于20家")
    if number(market.get("failed_rate")) >= 0.35:
        reasons.append("炸板率不低于35%")
    if number(feedback.get("avg_return")) < 0:
        reasons.append("昨日涨停反馈为负")
    return reasons


def market_gate(score: float, risks: list[str] | None = None) -> tuple[str, int, str]:
    if risks:
        return "空仓", 0, "防守等待 · " + "、".join(risks)
    if score >= 75:
        return "可做", 70, "修复/主升 · 允许研究核心"
    if score >= 60:
        return "轻仓试错", 40, "结构观察 · 只保留最高辨识度"
    if score >= 45:
        return "观望", 20, "分歧偏大 · 等次日确认"
    return "空仓", 0, "退潮/风险释放 · 暂停个股"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a close-only M/S/E/Q factor snapshot.")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--review", default="outputs/latest_market_review.json")
    parser.add_argument("--preview-output", default="outputs/shortterm_factor_preview.json")
    parser.add_argument("--preview-js", default="outputs/shortterm_factor_preview.js")
    parser.add_argument("--factor-output", default="outputs/shortterm_factors.json")
    parser.add_argument("--factor-js", default="outputs/shortterm_factors.js")
    parser.add_argument("--trend-current", default="outputs/trend_current.csv.gz")
    parser.add_argument("--stock-roles", default="outputs/industry_stock_roles.json")
    parser.add_argument("--seal-history", default="outputs/daily_seal_history.json")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--leader-top", "--anomaly-top", dest="leader_top", type=int, default=20)
    args = parser.parse_args()

    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    review_date = str(review.get("data_as_of") or "")
    if review_date != args.as_of:
        raise RuntimeError(f"close review date mismatch: review={review_date} expected={args.as_of}")

    market = review.get("market") or {}
    feedback = review.get("previous_limit_up_feedback") or {}
    leaders = list(review.get("leader_pool") or review.get("leader_board") or [])
    if not leaders:
        raise RuntimeError("close review has no leader pool")
    score_m = market_score(market, feedback)
    risks = market_risks(market, feedback)

    theme_counter: Counter[str] = Counter()
    theme_rows: dict[str, list[dict]] = defaultdict(list)
    for row in leaders:
        for theme in row.get("theme") or []:
            theme_counter[str(theme)] += 1
            theme_rows[str(theme)].append(row)
    max_theme = max(theme_counter.values(), default=1)
    max_boards = max(int(number(row.get("boards"), 1)) for row in leaders)

    raw_candidates = []
    for row in leaders:
        boards = max(1, int(number(row.get("boards"), 1)))
        breaks = max(0, int(number(row.get("break_count"), 0)))
        themes = [str(item) for item in (row.get("theme") or []) if str(item)]
        primary_theme = max(themes, key=lambda item: theme_counter[item], default="未分组")
        breadth = theme_counter.get(primary_theme, 0)
        peers = sorted(
            theme_rows.get(primary_theme, [row]),
            key=lambda item: (-int(number(item.get("boards"), 1)), int(number(item.get("break_count"), 0))),
        )
        theme_rank = next((index for index, item in enumerate(peers, 1) if item.get("code") == row.get("code")), 1)
        board_values = [int(number(item.get("boards"), 1)) for item in peers]
        theme_delta = board_values[0] - board_values[1] if len(board_values) > 1 and theme_rank == 1 else None

        seal_score = close_time_score(row.get("final_time"))
        activity_value = row.get("recent_board_count")
        if activity_value in (None, ""):
            activity_value = row.get("l10")
        activity_available = activity_value not in (None, "")
        activity_count = max(boards, int(number(activity_value, boards)))
        recent_days_value = row.get("recent_days")
        recent_days = int(number(recent_days_value, 10)) if recent_days_value not in (None, "") else None
        activity_bonus = min(8.0, activity_count / 10.0 * 8.0) if activity_available else 0.0
        strength = round(clamp(boards / max(max_boards, 1) * 48 + max(0, 28 - breaks * 4) + seal_score * 0.24 + activity_bonus), 1)
        position = round(
            clamp(boards / max(max_boards, 1) * 50 + breadth / max_theme * 25 + (25 if theme_rank == 1 else 15 if theme_rank == 2 else 8) + activity_bonus * 0.6),
            1,
        )
        quality = round(clamp(100 - min(48, breaks * 8) - (12 if seal_score < 50 else 0)), 1)
        total = round(0.40 * strength + 0.35 * position + 0.25 * quality, 1)
        raw_candidates.append(
            {
                "name": str(row.get("name") or ""),
                "code": str(row.get("code") or ""),
                "pool": "core",
                "pool_label": "短线核心",
                "lane": "relay" if boards >= 2 else "discovery",
                "lane_label": "连板接力" if boards >= 2 else "新晋龙头",
                "theme": primary_theme,
                "boards": boards,
                "recent_days": recent_days,
                "recent_board_count": activity_count,
                "activity_score": round(activity_count / 10.0 * 100.0, 1) if activity_available else None,
                "activity_available": activity_available,
                "theme_breadth": breadth,
                "gap": None,
                "daily_change": number(row.get("change"), None),
                "opens": breaks,
                "amount_yi": None,
                "pop": round(0.55 * strength + 0.45 * position, 1),
                "note": str(row.get("reason") or ""),
                "market": market_score(market, feedback),
                "strength": strength,
                "position": position,
                "quality": quality,
                "total": total,
                "action": "",
                "yizi": bool(breaks == 0 and str(row.get("final_time") or "").endswith("09:25:00")),
                "lanban": breaks >= 5,
                "theme_rank": theme_rank,
                "theme_delta": theme_delta,
                "higher_dead": "盘后未确认",
                "high60": None,
                "first_break": None,
                "missing": ["09:25竞价", "首封与封单"] + ([] if activity_available else ["近10日活跃度"]),
                "break_count": breaks,
                "final_time": row.get("final_time"),
                "trend_score": None,
                "trend_setup": None,
                "trend_eligible": None,
                "overheat_penalty": None,
            }
        )

    verdict, position_cap, state = market_gate(score_m, risks)
    for item in raw_candidates:
        if position_cap == 0:
            item["action"] = "放弃：市场门控"
        elif item["lanban"] or item["quality"] < 55:
            item["action"] = "放弃：封板质量"
        elif item["total"] >= 75:
            item["action"] = "重点观察"
        elif item["total"] >= 62:
            item["action"] = "观察"
        else:
            item["action"] = "放弃：同梯队偏弱"
    raw_candidates.sort(key=lambda item: (-item["total"], -item["boards"], item["break_count"]))
    core_candidates = raw_candidates[: args.top]
    for index, item in enumerate(core_candidates, 1):
        item["rank"] = index
        item["rank_label"] = str(index)

    trend_rows = load_trend_rows(Path(args.trend_current), args.as_of)
    leader_candidates, leader_coverage = build_leader_candidates(
        trend_rows,
        {str(item.get("code") or "") for item in leaders},
        leaders,
        score_m,
        Path(args.stock_roles),
        Path(args.seal_history),
        args.leader_top,
    )
    candidates = core_candidates + leader_candidates
    if position_cap == 0:
        for item in candidates:
            item["action"] = "放弃：市场门控"

    now = datetime.now(RUN_TZ).isoformat(timespec="seconds")
    preview = {
        "schema_version": 2,
        "status": "ok",
        "data_as_of": args.as_of,
        "factor_as_of": args.as_of,
        "phase": "close",
        "basis": "close_review",
        "factor_evidence": {"usable": True, "reason": "same_day_close", "as_of": args.as_of},
        "pool": {
            "relay_count": sum(item["lane"] == "relay" for item in core_candidates),
            "discovery_count": sum(item["lane"] == "discovery" for item in core_candidates),
            "core_count": len(core_candidates),
            "leader_count": len(leader_candidates),
            "total_count": len(candidates),
            "relay_label": "连板接力",
            "discovery_label": "新晋龙头",
            "leader_label": "龙头观察",
            "trend_scanned": len(trend_rows),
            "leader_scanned": leader_coverage["scanned"],
            "leader_history_covered_days": leader_coverage["history_covered_days"],
            "leader_history_max_date": leader_coverage["history_max_date"],
            "leader_heat_covered": leader_coverage["heat_covered"],
        },
        "market": {
            "score": score_m,
            "risk_reasons": risks,
            "allow_research": position_cap > 0,
            "state": state,
            "verdict": verdict,
            "position_cap": position_cap,
            "eco_score": score_m,
            "auction_score": None,
            "leader_score": round(clamp(number(market.get("max_boards")) / 7 * 100), 1),
            "notes": ["盘后口径：使用当日涨跌停、炸板、连板高度与隔日反馈；09:25竞价留待次日重新确认。"] + risks,
        },
        "candidates": candidates,
        "coverage": {
            "M": {"value": 100, "label": "收盘生态完整"},
            "S": {"value": 82, "label": "连板/量价强度；龙头看60日涨幅"},
            "E": {"value": 80, "label": "梯队、题材与30日涨停活跃度"},
            "Q": {"value": 72, "label": "封板质量与个股热度"},
            "AI": {"value": 0, "label": "未启用"},
        },
        "notes": [
            "这是盘后候选排序，不包含次日竞价确认。",
            "短线核心池研究涨停/连板梯队；龙头观察池用60日涨幅、近30日涨停活跃度和股票热度补充辨识度。",
            "M控制是否允许研究个股，S/E/Q只负责各自候选池内排序；龙头观察仍需次日竞价和盘中触发确认。",
        ] + (["trend_current 未找到同日主板横截面，龙头观察池未生成。"] if not trend_rows else []) + ([f"近30日涨停历史当前覆盖 {leader_coverage['history_covered_days']} 个交易日，未覆盖部分不以旧数据补齐；待每日收盘追加。"] if leader_coverage["history_covered_days"] < 20 else []),
        "generated_at": now,
    }

    hot_board = []
    for theme, count in theme_counter.most_common(10):
        hot_board.append(
            {
                "concept": theme,
                "count": count,
                "stocks": [
                    {"name": str(row.get("name") or ""), "code": str(row.get("code") or ""), "boards": int(number(row.get("boards"), 1))}
                    for row in theme_rows[theme][:8]
                ],
            }
        )
    factors = {
        "generated_at": now,
        "for_date": args.as_of,
        "basis": "close_review",
        "rules": "双池盘后口径：核心池 40%S + 35%E + 25%Q；龙头池 40%60日涨幅 + 35%近30日涨停 + 25%股票热度；M仅作市场门控",
        "candidate_pools": preview["pool"],
        "high_candidates": [],
        "hot_board": hot_board,
        "watch_hot": [
            {
                "name": item["name"], "code": item["code"], "boards": item["boards"], "lane": item["lane"],
                "hot": number(item.get("theme_breadth")) >= 3, "best_concept": item["theme"], "concept_count": item.get("theme_breadth"), "pop": item["pop"],
            }
            for item in candidates
        ],
        "popularity_top": [
            {
                "name": item["name"], "code": item["code"], "boards": item["boards"], "amount_yi": item["amount_yi"],
                "theme": item["theme"], "theme_n": item["theme_breadth"], "pop": item["pop"],
            }
            for item in candidates[:10]
        ],
        "data_source": "同花顺问财收盘复盘 + trend-standard-v1 同日主板横截面",
    }

    preview_text = json.dumps(preview, ensure_ascii=False, indent=2)
    Path(args.preview_output).write_text(preview_text + "\n", encoding="utf-8")
    Path(args.preview_js).write_text("window.SHORT_FACTOR_PREVIEW = " + preview_text + ";\n", encoding="utf-8")
    factor_text = json.dumps(factors, ensure_ascii=False, indent=2)
    Path(args.factor_output).write_text(factor_text + "\n", encoding="utf-8")
    Path(args.factor_js).write_text("window.SHORT_FACTORS = " + factor_text + ";\n", encoding="utf-8")
    print(f"wrote={args.preview_output} data_as_of={args.as_of} candidates={len(candidates)} market={score_m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
