from __future__ import annotations

import argparse
import json
from csv import DictReader
from pathlib import Path
from typing import Dict, List


ETF_FILES = (
    "etf_rotation_pick.csv",
    "etf_rotation_rank.csv",
    "etf_theme_pool.csv",
    "etf_backtest_curve.csv",
    "etf_backtest_trades.csv",
    "etf_backtest_positions.csv",
    "etf_hot_rank.csv",
    "etf_update_status.csv",
)


def read_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(DictReader(handle))


def build_payload(output_dir: Path) -> Dict[str, List[dict]]:
    payload: Dict[str, List[dict]] = {}
    for filename in ETF_FILES:
        path = output_dir / filename
        if path.exists():
            payload[path.stem] = read_rows(path)
    return payload


def write_payload(path: Path, payload: Dict[str, List[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    path.write_text("window.ETF_LOCAL_DATA = " + serialized + ";\n", encoding="utf-8")


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build the ETF dashboard file:// data fallback.")
    parser.add_argument("--output-dir", type=Path, default=project_root / "outputs")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_path = (args.output or output_dir / "etf_local_data.js").resolve()
    write_payload(output_path, build_payload(output_dir))
    print(f"ETF local fallback written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
