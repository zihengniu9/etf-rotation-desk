from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from low_buy_selector.trend_engine import build_snapshot, is_main_board_code, normalize_stock_code


RUN_TZ = ZoneInfo("Asia/Hong_Kong")


def load_metadata(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    frame = pd.read_csv(path, dtype=str).fillna("")
    if "code" not in frame.columns:
        raise ValueError(f"metadata must contain code: {path}")
    return {
        str(row["code"]): {key: row[key] for key in frame.columns if key != "code" and row[key] != ""}
        for _, row in frame.iterrows()
    }


def load_bars(directory: Path, *, main_board_only: bool = True) -> dict[str, pd.DataFrame]:
    if not directory.exists():
        raise FileNotFoundError(f"bars directory not found: {directory}")
    result: dict[str, pd.DataFrame] = {}
    for path in sorted(directory.glob("*.csv")):
        frame = pd.read_csv(path)
        if "close" not in frame.columns:
            continue
        code = normalize_stock_code(path.stem)
        if main_board_only and not is_main_board_code(code):
            continue
        result[code] = frame
    if not result:
        raise ValueError(f"no CSV with close column found in {directory}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the point-in-time trend engine snapshot from local OHLCV CSVs.")
    parser.add_argument("--bars-dir", default="data/trend_bars")
    parser.add_argument("--metadata", default="data/trend_metadata.csv")
    parser.add_argument("--output", default="outputs/trend_engine.json")
    parser.add_argument("--as-of", default=None, help="Optional YYYY-MM-DD cutoff; defaults to the latest available bar.")
    parser.add_argument("--include-non-mainboard", action="store_true", help="Include STAR, ChiNext and Beijing stocks; disabled by default.")
    args = parser.parse_args()

    bars = load_bars(Path(args.bars_dir), main_board_only=not args.include_non_mainboard)
    snapshot = build_snapshot(
        bars,
        metadata=load_metadata(Path(args.metadata)),
        as_of=args.as_of,
        source=f"本地OHLCV · {len(bars)}只样本",
    )
    snapshot["universe"] = {
        "name": "沪深主板" if not args.include_non_mainboard else "全A（含非主板）",
        "board": "mainboard" if not args.include_non_mainboard else "all_a",
        "stocks_scanned": len(bars),
        "stocks_with_history": snapshot.get("stocks_with_history", 0),
    }
    snapshot["updated_at"] = datetime.now(RUN_TZ).isoformat(timespec="seconds")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"trend_snapshot={snapshot['data_as_of']} candidates={len(snapshot['candidates'])}")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
