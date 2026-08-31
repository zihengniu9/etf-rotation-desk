from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


RUN_TZ = ZoneInfo("Asia/Hong_Kong")


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    review = load("outputs/latest_market_review.json")
    signal = load("outputs/shortterm_signal.json")
    factors = load("outputs/shortterm_factor_preview.json")
    review_date = str(review.get("data_as_of") or "")
    signal_date = str(signal.get("date") or "")
    if not review_date or review_date != signal_date:
        raise RuntimeError(f"short-term live inputs are not aligned: review={review_date} signal={signal_date}")

    change_by_name = {
        str(row.get("name") or ""): row.get("change")
        for row in review.get("leader_board") or []
    }
    code_by_name = {
        str(row.get("name") or ""): str(row.get("code") or "")
        for row in review.get("leader_board") or []
    }
    stocks = []
    for candidate in (factors.get("candidates") or [])[:16]:
        name = str(candidate.get("name") or "")
        stocks.append(
            {
                "code": str(candidate.get("code") or code_by_name.get(name) or ""),
                "name": name,
                "price": None,
                "pct": change_by_name.get(name),
                "high": None,
                "low": None,
                "open": None,
                "research_status": candidate.get("action") or "观察",
            }
        )

    market = review.get("market") or {}
    payload = {
        "version": "shortterm-live-v2",
        "updated_at": datetime.now(RUN_TZ).isoformat(timespec="seconds"),
        "date": review_date,
        "source": "最新收盘复盘 + 当日 M/S/E/Q 候选",
        "stocks": stocks,
        "sentiment": {
            "date": review_date,
            "limit_up_count": market.get("limit_up"),
            "limit_down_count": market.get("limit_down"),
        },
        "coverage": {
            "stock_price": "未在复盘快照返回时明确留空",
            "stock_change": "仅涨停复盘清单可取得收盘涨跌幅",
            "candidate_count": len(stocks),
        },
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    Path("outputs/shortterm_live.json").write_text(serialized + "\n", encoding="utf-8")
    Path("outputs/shortterm_live.js").write_text("window.SHORT_TERM_LIVE = " + serialized + ";\n", encoding="utf-8")
    print(f"wrote=outputs/shortterm_live.json date={review_date} candidates={len(stocks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
