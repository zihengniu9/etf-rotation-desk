import argparse
from pathlib import Path

from .selector import SelectorConfig, screen_board


DISPLAY_COLUMNS = [
    "code",
    "name",
    "latest_date",
    "close",
    "ma5",
    "distance_pct",
    "ma5_up_days",
    "recent_drawdown_pct",
    "total_score",
    "top_concept",
    "top_heat",
    "matched_keywords",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen Tonghuashun hot stocks for MA5 low-buy setups.")
    parser.add_argument("--board-code", default="883910")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--min-distance-pct", type=float, default=-0.5)
    parser.add_argument("--max-distance-pct", type=float, default=3.0)
    parser.add_argument("--ma5-trend-window", type=int, default=5)
    parser.add_argument("--min-ma5-up-days", type=int, default=0, help="0 means all MA5 comparisons in the trend window must rise.")
    parser.add_argument("--max-recent-drawdown-pct", type=float, default=-5.0)
    parser.add_argument("--drawdown-window", type=int, default=10)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit-board", type=int, default=0, help="Only evaluate the first N board constituents.")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    frame, summary = screen_board(
        SelectorConfig(
            board_code=args.board_code,
            start_date=args.start_date,
            end_date=args.end_date,
            min_distance_pct=args.min_distance_pct,
            max_distance_pct=args.max_distance_pct,
            ma5_trend_window=args.ma5_trend_window,
            min_ma5_up_days=args.min_ma5_up_days,
            max_recent_drawdown_pct=args.max_recent_drawdown_pct,
            drawdown_window=args.drawdown_window,
            max_workers=args.workers,
            board_limit=args.limit_board,
        )
    )

    print(
        f"board={args.board_code} total={summary.total_constituents} "
        f"evaluated={summary.evaluated} selected={summary.selected} errors={summary.errors}"
    )
    if frame.empty:
        print("No candidates matched the current filters.")
    else:
        columns = [column for column in DISPLAY_COLUMNS if column in frame.columns]
        print(frame.head(args.top)[columns].to_string(index=False))

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False, encoding="utf-8-sig")
        print(f"wrote {output}")

    return 0 if summary.errors == 0 else 2
