from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from low_buy_selector.growth_engine import build_growth_snapshot, build_finance_factors, attach_news_evidence


def load_wencai_rows(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame(payload.get("datas") or [])


def load_news_directory(directory: Path) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    if not directory.exists():
        return result
    for path in sorted(directory.glob("news_*.json")):
        match = re.search(r"news_([0-9]{6})", path.stem)
        if not match:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        result[match.group(1)] = list(payload.get("data") or [])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the point-in-time growth-factor research snapshot.")
    parser.add_argument("--current-input", default="temp_download/growth_finance_2026h1.json")
    parser.add_argument("--annual-2025-input", default="temp_download/growth_finance_2025.json")
    parser.add_argument("--annual-2024-input", default="temp_download/growth_finance_2024.json")
    parser.add_argument("--news-dir", default="temp_download")
    parser.add_argument("--as-of", default="2026-08-27")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--output", default="outputs/growth_factor_snapshot.json")
    parser.add_argument("--candidates-output", default="outputs/growth_factor_candidates.csv")
    parser.add_argument("--js-output", default="outputs/growth_factor_snapshot.js")
    args = parser.parse_args()

    current = load_wencai_rows(Path(args.current_input))
    annual_2025 = load_wencai_rows(Path(args.annual_2025_input))
    annual_2024 = load_wencai_rows(Path(args.annual_2024_input))
    news = load_news_directory(Path(args.news_dir))
    snapshot = build_growth_snapshot(current, annual_2025, annual_2024, news, as_of=args.as_of, top=args.top)
    mainboard_count = int(snapshot["universe"]["stocks_mainboard"])
    valid_count = int(snapshot["universe"]["stocks_financial_valid"])
    if valid_count < max(100, int(mainboard_count * 0.5)):
        raise RuntimeError(
            f"growth factor field coverage collapsed: valid={valid_count} mainboard={mainboard_count}"
        )

    finance = build_finance_factors(current, annual_2025, annual_2024)
    ranked = attach_news_evidence(finance, news, as_of=args.as_of)
    csv_columns = [
        "code6", "name", "final_status", "growth_profile", "final_score", "growth_core", "quality_score",
        "balance_score", "news_news_score", "current_revenue_growth", "current_profit_growth",
        "revenue_acceleration", "profit_acceleration", "persistence_score", "cash_margin", "cash_to_profit",
        "current_roe", "current_net_margin", "current_debt_ratio", "news_news_count", "news_positive_articles",
        "news_negative_articles", "news_positive_groups", "news_negative_groups", "low_base_flag",
        "cash_mismatch_flag", "high_debt_flag", "factor_status", "factor_coverage",
    ]
    output_frame = ranked[[column for column in csv_columns if column in ranked.columns]].copy()
    if "code6" in output_frame.columns:
        output_frame["code6"] = output_frame["code6"].astype(str).str.extract(r"([0-9]{6})")[0].str.zfill(6)
    for column in output_frame.select_dtypes(include=["number"]).columns:
        output_frame[column] = output_frame[column].round(4)
    candidates_path = Path(args.candidates_output)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    output_frame.to_csv(candidates_path, index=False, encoding="utf-8-sig")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    output_path.write_text(serialized + "\n", encoding="utf-8")
    js_path = Path(args.js_output)
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text("window.GROWTH_FACTOR_SNAPSHOT = " + serialized + ";\n", encoding="utf-8")
    print(f"growth_rows={mainboard_count} valid={valid_count}")
    print(f"news_queried={snapshot['universe']['news_queried_stocks']} candidates={len(snapshot['candidates'])}")
    print(f"wrote={output_path}")
    print(f"wrote={candidates_path}")
    print(f"wrote={js_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
