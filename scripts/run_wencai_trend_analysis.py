from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from low_buy_selector.wencai_trend import (
    build_dashboard_snapshot,
    build_wencai_label_query,
    build_wencai_query,
    evaluate_strategies,
    merge_wencai_responses,
    normalize_wencai_response,
    score_wencai_cross_section,
    select_best_holding,
)
from low_buy_selector.trend_contract import CANONICAL_HORIZON, CANONICAL_TREND_VERSION


RUN_TZ = ZoneInfo("Asia/Hong_Kong")


def load_query_function():
    override = os.environ.get("IWENCAI_SELECTOR_SKILL_DIR", "").strip()
    candidates = [
        Path(override) if override else None,
        Path(r"D:\Codex\CLI\skills\hithink-astock-selector"),
        Path.home() / ".codex" / "skills" / "hithink-astock-selector",
    ]
    for directory in candidates:
        if directory is None:
            continue
        script = directory / "scripts" / "cli.py"
        if not script.exists():
            continue
        spec = importlib.util.spec_from_file_location("hithink_astock_selector_cli", script)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.query_astock
    raise FileNotFoundError("hithink-astock-selector/scripts/cli.py not found")


def fetch_all(query_function, query: str, *, limit: int, timeout: int) -> dict[str, object]:
    api_key = os.environ.get("IWENCAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("IWENCAI_API_KEY is not configured")
    first = query_function(
        query=query,
        page="1",
        limit=str(limit),
        api_key=api_key,
        call_type="normal",
        timeout=timeout,
    )
    if "datas" not in first:
        raise RuntimeError(f"Wencai response has no datas: {first}")
    expected = int(float(first.get("code_count") or first.get("row_count") or len(first["datas"])))
    all_rows = list(first["datas"])
    page = 2
    while len(all_rows) < expected:
        response = query_function(
            query=query,
            page=str(page),
            limit=str(limit),
            api_key=api_key,
            call_type="normal",
            timeout=timeout,
        )
        rows = list(response.get("datas") or [])
        if not rows:
            break
        all_rows.extend(rows)
        page += 1
    first["datas"] = all_rows
    return first


def default_history_dates(as_of: str) -> list[str]:
    latest = pd.Timestamp(as_of) - pd.offsets.BDay(22)
    month_ends = pd.date_range(end=latest - pd.offsets.MonthBegin(1), periods=11, freq="BME")
    dates = [stamp.strftime("%Y-%m-%d") for stamp in month_ends]
    dates.append(latest.strftime("%Y-%m-%d"))
    return sorted(dict.fromkeys(dates))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full-mainboard Wencai trend factor and holding-period study.")
    parser.add_argument("--as-of", default=datetime.now(RUN_TZ).strftime("%Y-%m-%d"))
    parser.add_argument("--history-dates", default="", help="Comma-separated signal dates; default is 12 non-overlapping monthly samples.")
    parser.add_argument("--limit", type=int, default=4000)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", default="outputs/trend_engine.json")
    parser.add_argument("--backtest-output", default="outputs/trend_backtest.json")
    parser.add_argument("--history-output", default="outputs/trend_history.csv.gz")
    parser.add_argument("--current-output", default="outputs/trend_current.csv.gz")
    parser.add_argument("--history-input", default="", help="Optional prior history CSV/CSV.GZ used as a date cache.")
    parser.add_argument("--current-input", default="", help="Optional current cross-section CSV/CSV.GZ cache.")
    args = parser.parse_args()

    if not os.environ.get("HTTPS_PROXY"):
        raise RuntimeError("HTTPS_PROXY is not configured; refusing direct network access")
    query_function = load_query_function()
    explicit_dates = [value.strip() for value in args.history_dates.split(",") if value.strip()]
    cached_frame: pd.DataFrame | None = None
    cache_path = Path(args.history_input) if args.history_input else None
    if cache_path is not None and cache_path.exists():
        cached_frame = pd.read_csv(cache_path, dtype={"code": str})
        cached_frame["date"] = cached_frame["date"].astype(str)
    if explicit_dates:
        dates = explicit_dates
    elif cached_frame is not None and not cached_frame.empty:
        # Preserve every previously validated historical cross-section.  The
        # cache should not silently collapse from 36 dates to the 12-date
        # default merely because the current snapshot is being refreshed.
        dates = sorted(cached_frame["date"].dropna().unique().tolist())
    else:
        dates = default_history_dates(args.as_of)
    history_frames: list[pd.DataFrame] = []
    requested_dates = set(dates)
    cached_dates: set[str] = set()
    if cached_frame is not None:
        for signal_date, group in cached_frame[cached_frame["date"].isin(requested_dates)].groupby("date", sort=True):
            rescored = score_wencai_cross_section(group.reset_index(drop=True))
            if not rescored.empty:
                history_frames.append(rescored)
                cached_dates.add(str(signal_date))
                print(
                    f"history_cache={signal_date} rows={len(rescored)} eligible={int(rescored['eligible'].sum())}",
                    flush=True,
                )
    for signal_date in dates:
        if signal_date in cached_dates:
            continue
        print(f"history_features={signal_date}", flush=True)
        feature_response = fetch_all(
            query_function,
            build_wencai_query(signal_date, include_forward=False),
            limit=args.limit,
            timeout=args.timeout,
        )
        print(f"history_labels={signal_date}", flush=True)
        label_response = fetch_all(
            query_function,
            build_wencai_label_query(signal_date),
            limit=args.limit,
            timeout=args.timeout,
        )
        response = merge_wencai_responses(feature_response, label_response)
        normalized = normalize_wencai_response(response, signal_date)
        scored = score_wencai_cross_section(normalized)
        if not scored.empty:
            history_frames.append(scored)
        print(f"history_rows={len(scored)} eligible={int(scored['eligible'].sum()) if not scored.empty else 0}", flush=True)

    if not history_frames:
        raise RuntimeError("No valid historical Wencai samples were returned")
    history = pd.concat(history_frames, ignore_index=True)
    summary = evaluate_strategies(history)
    best = select_best_holding(summary)
    history_coverage = []
    for signal_date, group in history.groupby("date", sort=True):
        eligible = group[group["eligible"]]
        history_coverage.append(
            {
                "date": str(signal_date),
                "rows": int(len(group)),
                "eligible": int(len(eligible)),
                "eligible_ratio": float(len(eligible) / len(group)) if len(group) else 0.0,
                "evaluated5": int(eligible["fwd5"].notna().sum()),
                "evaluated10": int(eligible["fwd10"].notna().sum()),
                "evaluated20": int(eligible["fwd20"].notna().sum()),
            }
        )

    current_cache = Path(args.current_input) if args.current_input else None
    if current_cache is not None and current_cache.exists():
        current = score_wencai_cross_section(pd.read_csv(current_cache, dtype={"code": str}))
        print(f"current_cache={current_cache} rows={len(current)}", flush=True)
    else:
        print(f"current_query={args.as_of}", flush=True)
        current_response = fetch_all(
            query_function,
            build_wencai_query(args.as_of, include_forward=False),
            limit=args.limit,
            timeout=args.timeout,
        )
        current = score_wencai_cross_section(normalize_wencai_response(current_response, args.as_of))
    if current.empty:
        raise RuntimeError("No valid current Wencai trend rows were returned")

    source = f"同花顺问财 · hithink-astock-selector · {len(history_frames)}个历史时点"
    snapshot = build_dashboard_snapshot(current, history, summary, source=source, top=args.top)
    snapshot["updated_at"] = datetime.now(RUN_TZ).isoformat(timespec="seconds")

    backtest = {
        "data_as_of": args.as_of,
        "source": source,
        "engine_selection": {
            "selected_adapter": "wencai_cross_section",
            "canonical_contract": CANONICAL_TREND_VERSION,
            "reason": "当前可复核的标准历史样本来自36个问财主板截面；本地data/trend_bars未提供完整全市场历史，因此不对本地适配器宣称独立回测优胜",
            "local_adapter_status": "已统一评分与触发契约，待接入完整本地全市场OHLCV后做独立交叉复核",
        },
        "signal_dates": sorted(history["date"].unique().tolist()),
        "stocks": int(history["code"].nunique()),
        "rows": int(len(history)),
        "history_coverage": history_coverage,
        "best_holding": best,
        "strategies": summary,
        "market_decision": snapshot.get("decision"),
        "market_gate_validation": snapshot.get("market_gate_validation"),
        "gated_strategies": snapshot.get("gated_strategies"),
        "factor_rule": {
            "version": CANONICAL_TREND_VERSION,
            "signal": "收盘确认；仅使用信号日及之前数据",
            "entry": "下一交易日开盘",
            "exit": "第5/10/20个交易日收盘",
            "universe": "沪深主板非ST；成交额>=1亿元；换手率0.5%-15%",
            "setups": ["健康延续", "放量突破", "缩量回踩", "综合分位"],
            "selected_strategy": best.get("strategy"),
            "selected_horizon": best.get("horizon", CANONICAL_HORIZON),
            "selection_rule": best.get("selection_rule"),
            "costs": "当前输出为毛收益，未计佣金、印花税和滑点；后续净收益复核必须沿用同一信号口径",
        },
    }

    for path_text, frame in ((args.history_output, history), (args.current_output, current)):
        path = Path(path_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, compression="gzip")
        print(f"wrote={path}", flush=True)

    for path_text, payload in ((args.output, snapshot), (args.backtest_output, backtest)):
        path = Path(path_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote={path}", flush=True)
    print(f"current_rows={len(current)} candidates={len(snapshot['candidates'])}", flush=True)
    print(f"best={best.get('label', '样本不足')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
