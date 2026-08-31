from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
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


def market_score(market: dict, feedback: dict) -> float:
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


def market_gate(score: float) -> tuple[str, int, str]:
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
    parser.add_argument("--top", type=int, default=20)
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
        strength = round(clamp(boards / max(max_boards, 1) * 48 + max(0, 28 - breaks * 4) + seal_score * 0.24), 1)
        position = round(
            clamp(boards / max(max_boards, 1) * 50 + breadth / max_theme * 25 + (25 if theme_rank == 1 else 15 if theme_rank == 2 else 8)),
            1,
        )
        quality = round(clamp(100 - min(48, breaks * 8) - (12 if seal_score < 50 else 0)), 1)
        total = round(0.40 * strength + 0.35 * position + 0.25 * quality, 1)
        raw_candidates.append(
            {
                "name": str(row.get("name") or ""),
                "code": str(row.get("code") or ""),
                "lane": "relay" if boards >= 2 else "discovery",
                "lane_label": "连板接力" if boards >= 2 else "新晋龙头",
                "theme": primary_theme,
                "boards": boards,
                "recent_days": None,
                "recent_board_count": boards,
                "theme_breadth": breadth,
                "gap": None,
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
                "missing": ["09:25竞价", "L10/动量", "首封与封单"],
                "break_count": breaks,
                "final_time": row.get("final_time"),
            }
        )

    score_m = market_score(market, feedback)
    verdict, position_cap, state = market_gate(score_m)
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
    candidates = raw_candidates[: args.top]
    for index, item in enumerate(candidates, 1):
        item["rank"] = index

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
            "relay_count": sum(item["lane"] == "relay" for item in candidates),
            "discovery_count": sum(item["lane"] == "discovery" for item in candidates),
            "total_count": len(candidates),
            "relay_label": "连板接力",
            "discovery_label": "新晋龙头",
        },
        "market": {
            "score": score_m,
            "state": state,
            "verdict": verdict,
            "position_cap": position_cap,
            "eco_score": score_m,
            "auction_score": None,
            "leader_score": round(clamp(number(market.get("max_boards")) / 7 * 100), 1),
            "notes": ["盘后口径：使用当日涨跌停、炸板、连板高度与隔日反馈；09:25竞价留待次日重新确认。"],
        },
        "candidates": candidates,
        "coverage": {
            "M": {"value": 100, "label": "收盘生态完整"},
            "S": {"value": 78, "label": "连板/回封/封板时间"},
            "E": {"value": 78, "label": "梯队与题材地位"},
            "Q": {"value": 70, "label": "炸板与封板质量"},
            "AI": {"value": 0, "label": "未启用"},
        },
        "notes": ["这是盘后候选排序，不包含次日竞价确认。", "M控制是否允许研究个股，S/E/Q只负责候选池内排序。"],
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
        "rules": "盘后涨停池：40%强度S + 35%地位E + 25%质量Q；M仅作市场门控",
        "candidate_pools": preview["pool"],
        "high_candidates": [],
        "hot_board": hot_board,
        "watch_hot": [
            {
                "name": item["name"], "code": item["code"], "boards": item["boards"], "lane": item["lane"],
                "hot": item["theme_breadth"] >= 3, "best_concept": item["theme"], "concept_count": item["theme_breadth"], "pop": item["pop"],
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
        "data_source": "同花顺问财收盘复盘",
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
