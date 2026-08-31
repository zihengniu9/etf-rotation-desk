from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


RUN_TZ = ZoneInfo("Asia/Hong_Kong")


def load(path: str, default):
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


def next_business_day(value: date) -> date:
    value += timedelta(days=1)
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def candidate_role(item: dict) -> str:
    lane = item.get("lane_label") or ("新晋龙头" if item.get("lane") == "discovery" else "连板接力")
    return f"{lane} · M/S/E/Q {item.get('total', '—')}分 · {item.get('action', '观察')}"


def main() -> int:
    review = load("outputs/latest_market_review.json", {})
    signal = load("outputs/shortterm_signal.json", {})
    mseq = load("outputs/shortterm_factor_preview.json", {})
    samples = load("outputs/shortterm_samples.json", [])
    as_of = str(review.get("data_as_of") or signal.get("date") or "")
    if not as_of or str(mseq.get("data_as_of") or "") != as_of:
        raise RuntimeError(
            f"short-term plan inputs are not aligned: review={review.get('data_as_of')} "
            f"signal={signal.get('date')} mseq={mseq.get('data_as_of')}"
        )
    for_date = next_business_day(date.fromisoformat(as_of)).isoformat()
    candidates = list(mseq.get("candidates") or [])
    actionable = [item for item in candidates if not str(item.get("action") or "").startswith("放弃")]
    relay = [item for item in actionable if item.get("lane") != "discovery"]
    discovery = [item for item in actionable if item.get("lane") == "discovery"]
    primary = (relay or actionable or candidates or [{}])[0]
    discovery_names = "、".join(str(item.get("name")) for item in discovery[:3]) or "新晋龙头候选"
    market = review.get("market") or {}
    feedback = review.get("previous_limit_up_feedback") or {}
    latest_sample = next((item for item in reversed(samples) if str(item.get("date")) == as_of), {})
    close_effect = (latest_sample.get("act") or {}).get("oc_avg_pct")
    close_text = "开盘至收盘效果待取得" if close_effect is None else f"开盘至收盘均值{close_effect:+.2f}%"
    primary_name = str(primary.get("name") or "最高辨识度核心")
    gate_score = (mseq.get("market") or {}).get("score", signal.get("score", "—"))
    headline = (
        f"{as_of} 收盘：盘后市场门控 {gate_score} 分，{close_text}；"
        f"{for_date} 先确认 {primary_name} 的核心反馈，再观察 {discovery_names} 的新晋龙头竞争。"
    )
    market_review = (
        f"收盘涨停 {market.get('limit_up', '—')} 家、跌停 {market.get('limit_down', '—')} 家、"
        f"炸板率 {float(market.get('failed_rate') or 0) * 100:.1f}%，最高 {market.get('max_boards', '—')} 板；"
        f"昨日涨停次日均值 {feedback.get('avg_return', '—')}%。"
        f"当前计划由固定规则生成，不使用盘后信息反推次日必涨。"
    )
    branches = [
        {
            "key": "A",
            "title": "核心超预期 · 只保留最高身份",
            "condition": f"{primary_name} 竞价不低于预期，非无法成交的一字加速；所属方向至少2只同步转强，开盘后承接不破关键均价。",
            "action": "只进入触发观察，不在竞价前预设成交；M门控继续允许且首次分歧承接确认后，再按既定仓位上限执行。",
        },
        {
            "key": "B",
            "title": "新晋龙头竞争 · 等市场选赢家",
            "condition": f"{discovery_names} 中出现竞价与板块扩散同时占优者，且第一名相对第二名形成明确分差。",
            "action": "只保留唯一性最强的一只；未形成明显赢家时全部降级为观察，不替市场提前选龙头。",
        },
        {
            "key": "C",
            "title": "低于预期 · 取消个股剧本",
            "condition": "最高板负反馈、昨日强势股集体低开，或跌停/炸板明显扩张；竞价分跌破30时直接触发熔断。",
            "action": "停止新增个股操作，回到ETF独立策略或现金；等待下一次生态、竞价与核心反馈重新共振。",
        },
    ]
    watchlist = []
    for item in (actionable or candidates)[:6]:
        watchlist.append(
            {
                "name": f"{item.get('name', '')}({str(item.get('code') or '').split('.')[0]})",
                "role": candidate_role(item),
                "trigger": "竞价不弱、非一字难成交，所属题材有同步扩散；S/E/Q状态不恶化",
                "action": "满足条件后进入观察；否则取消，不按静态排名直接买入",
            }
        )
    payload = {
        "version": "shortterm-plan-rules-v1",
        "generated_at": datetime.now(RUN_TZ).isoformat(timespec="seconds"),
        "data_as_of": as_of,
        "for_date": for_date,
        "headline": headline,
        "market_review": market_review,
        "branches": branches,
        "watchlist": watchlist,
        "rules": [
            "M 市场门控优先于所有个股排名；竞价分低于30自动降档。",
            "S/E/Q 只在同一候选池内比较，第一名与第二名差距不明显时不确认龙头。",
            "一字难成交、烂板、同题材更高板压制或价值不明的候选直接降级。",
            "次日实际触发必须使用当时可见数据，盘后计划不是自动交易指令。",
        ],
        "note": "规则版每日预案：来源为当日收盘复盘与盘后 M/S/E/Q；09:25 信号若缺失则留待次日竞价重新确认，不包含未经核验的新闻叙事。",
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    Path("outputs/shortterm_plan.json").write_text(serialized + "\n", encoding="utf-8")
    Path("outputs/shortterm_plan.js").write_text("window.SHORT_PLAN = " + serialized + ";\n", encoding="utf-8")
    print(f"wrote=outputs/shortterm_plan.json data_as_of={as_of} for_date={for_date} watchlist={len(watchlist)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
