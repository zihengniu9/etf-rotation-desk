import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .etf_data_sources import fetch_all_etfs, fetch_etf_daily_bars, fetch_etf_scales, fetch_realtime_etf_quotes
from .etf_backtest import audit_trade_ledger, run_rotation_backtest
from .etf_hot import fetch_hot_etfs
from .etf_pool import build_theme_pool
from .etf_rotation import rank_etfs_by_momentum


RUN_TZ = ZoneInfo("Asia/Hong_Kong")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a largest-by-theme ETF pool and rank momentum ETFs.")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--momentum-days", type=int, default=20)
    parser.add_argument("--min-total-return", type=float, default=0.01)
    parser.add_argument("--defense-threshold", type=float, default=0.6)
    parser.add_argument("--backtest-days", type=int, default=252)
    parser.add_argument("--ma-window", type=int, default=30)
    parser.add_argument("--below-ma-days-to-sell", type=int, default=2)
    parser.add_argument("--position-fraction", type=float, default=0.5)
    parser.add_argument("--max-daily-buys", type=int, default=2)
    parser.add_argument("--max-theme-positions", type=int, default=1)
    parser.add_argument("--dynamic-exposure", action="store_true")
    parser.add_argument("--theme-cooldown-days", type=int, default=0)
    parser.add_argument("--min-holding-days-before-rebalance", type=int, default=5)
    parser.add_argument("--replacement-score-threshold", type=float, default=1.0)
    parser.add_argument("--loss-cooldown-threshold", type=int, default=2)
    parser.add_argument("--loss-cooldown-days", type=int, default=15)
    parser.add_argument("--hot-top", type=int, default=30)
    parser.add_argument("--money-symbol", default="511880")
    parser.add_argument("--backtest-excluded-fund-types", default="LOF")
    parser.add_argument("--workers", type=int, default=1, help="Use 1 for stability with AKShare/Sina ETF history.")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--sse-scale-date", default="")
    parser.add_argument("--no-realtime-quotes", action="store_true", help="Disable intraday ETF quote patching.")
    parser.add_argument(
        "--preserve-backtest-history",
        action="store_true",
        help="Preserve previous curve and trade rows by date from the configured backtest history start date.",
    )
    parser.set_defaults(preserve_backtest_history=True)
    parser.add_argument("--backtest-history-start-date", default="2025-06-28")
    parser.add_argument("--no-preserve-backtest-history", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    etfs = fetch_all_etfs()
    scale_date = args.sse_scale_date or _latest_query_date(etfs)
    scales = fetch_etf_scales(stat_date=scale_date)
    pool = build_theme_pool(etfs, scales)
    pool_path = output_dir / "etf_theme_pool.csv"
    pool.to_csv(pool_path, index=False, encoding="utf-8-sig")

    histories = _fetch_histories(pool["code"].astype(str).tolist(), workers=args.workers)
    price_mode = "daily_close"
    realtime_quote_count = 0
    realtime_data_date = latest_histories_date(histories)
    if not args.no_realtime_quotes:
        realtime_quotes = fetch_realtime_etf_quotes(pool["code"].astype(str).tolist())
        histories, realtime_quote_count, patched_data_date = apply_realtime_quotes_to_histories(histories, realtime_quotes)
        if realtime_quote_count:
            price_mode = "realtime_quote"
            realtime_data_date = patched_data_date
    rank, pick = rank_etfs_by_momentum(
        pool,
        histories,
        money_symbol=args.money_symbol,
        defense_threshold=args.defense_threshold,
        momentum_days=args.momentum_days,
        min_total_return=args.min_total_return,
    )

    rank_path = output_dir / "etf_rotation_rank.csv"
    pick_path = output_dir / "etf_rotation_pick.csv"
    rank.to_csv(rank_path, index=False, encoding="utf-8-sig")
    pd.DataFrame([pick]).to_csv(pick_path, index=False, encoding="utf-8-sig")

    backtest_pool = filter_backtest_pool(pool, excluded_fund_types=args.backtest_excluded_fund_types)
    curve, trades, positions = run_rotation_backtest(
        backtest_pool,
        histories,
        lookback_days=args.backtest_days,
        momentum_days=args.momentum_days,
        ma_window=args.ma_window,
        buy_threshold=args.defense_threshold,
        below_ma_days_to_sell=args.below_ma_days_to_sell,
        position_fraction=args.position_fraction,
        max_daily_buys=args.max_daily_buys,
        max_theme_positions=args.max_theme_positions or None,
        dynamic_exposure=args.dynamic_exposure,
        theme_cooldown_days=args.theme_cooldown_days,
        min_holding_days_before_rebalance=args.min_holding_days_before_rebalance,
        replacement_score_threshold=args.replacement_score_threshold,
        loss_cooldown_threshold=args.loss_cooldown_threshold,
        loss_cooldown_days=args.loss_cooldown_days,
        min_total_return=args.min_total_return,
    )
    curve_path = output_dir / "etf_backtest_curve.csv"
    trades_path = output_dir / "etf_backtest_trades.csv"
    positions_path = output_dir / "etf_backtest_positions.csv"
    max_positions = max(1, int(1.0 / args.position_fraction)) if args.position_fraction > 0 else 1
    ledger_errors = audit_trade_ledger(trades, positions, max_positions=max_positions)
    if ledger_errors:
        raise ValueError("Invalid backtest trade ledger: " + "; ".join(ledger_errors[:5]))
    if args.preserve_backtest_history and not args.no_preserve_backtest_history:
        curve = merge_existing_csv(curve_path, curve, key_columns=["date"], min_date=args.backtest_history_start_date)
        if trades_path.exists():
            trades = merge_trade_ledger_rows(pd.read_csv(trades_path), trades, min_date=args.backtest_history_start_date)
        else:
            trades = filter_trade_ledger_from_date(trades, args.backtest_history_start_date)
    else:
        curve = filter_rows_from_date(curve, args.backtest_history_start_date)
        trades = filter_trade_ledger_from_date(trades, args.backtest_history_start_date)
    ledger_errors = audit_trade_ledger(trades, positions, max_positions=max_positions)
    if ledger_errors:
        raise ValueError("Invalid merged backtest trade ledger: " + "; ".join(ledger_errors[:5]))
    curve.to_csv(curve_path, index=False, encoding="utf-8-sig")
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    positions.to_csv(positions_path, index=False, encoding="utf-8-sig")

    hot_rank = fetch_hot_etfs(limit=args.hot_top)
    hot_path = output_dir / "etf_hot_rank.csv"
    hot_rank.to_csv(hot_path, index=False, encoding="utf-8-sig")

    status_path = output_dir / "etf_update_status.csv"
    status = pd.DataFrame(
        [
            {
                "updated_at": datetime.now(RUN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "data_date": latest_curve_date(curve),
                "price_mode": price_mode,
                "realtime_quotes": realtime_quote_count,
                "realtime_data_date": realtime_data_date,
                "ranked_count": len(rank),
                "pick_code": pick.get("code", ""),
                "pick_name": pick.get("name", ""),
            }
        ],
    )
    status.to_csv(status_path, index=False, encoding="utf-8-sig")

    print(f"etf_list={len(etfs)} themes={len(pool)} ranked={len(rank)}")
    if not rank.empty:
        columns = ["code", "name", "theme", "score", "total_return", "annual_vol", "fund_size"]
        print(rank.head(args.top)[columns].to_string(index=False))
    print(f"pick={pick.get('code')} {pick.get('name', '')} theme={pick.get('theme', '')}")
    print(f"wrote {pool_path}")
    print(f"wrote {rank_path}")
    print(f"wrote {pick_path}")
    print(f"wrote {curve_path}")
    print(f"wrote {trades_path}")
    print(f"wrote {positions_path}")
    print(f"wrote {hot_path}")
    print(f"wrote {status_path}")
    return 0


def _latest_query_date(etfs: pd.DataFrame) -> str:
    if "query_date" in etfs.columns and not etfs["query_date"].dropna().empty:
        value = str(etfs["query_date"].dropna().iloc[0])
        digits = value.replace("-", "")
        if len(digits) == 8 and digits.isdigit():
            return digits
    return date.today().strftime("%Y%m%d")


def latest_curve_date(curve: pd.DataFrame) -> str:
    if curve.empty or "date" not in curve.columns:
        return ""
    dates = curve["date"].dropna().astype(str)
    if dates.empty:
        return ""
    return dates.iloc[-1]


def latest_histories_date(histories: dict[str, pd.DataFrame]) -> str:
    dates: list[str] = []
    for history in histories.values():
        if history.empty or "date" not in history.columns:
            continue
        parsed = pd.to_datetime(history["date"], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(parsed.max().strftime("%Y-%m-%d"))
    return max(dates) if dates else ""


def apply_realtime_quotes_to_histories(
    histories: dict[str, pd.DataFrame],
    quotes: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], int, str]:
    patched = {str(code).zfill(6): history.copy() for code, history in histories.items()}
    if quotes.empty:
        return patched, 0, latest_histories_date(patched)

    quote_frame = quotes.copy()
    required = {"code", "realtime_price", "realtime_date"}
    if required.difference(quote_frame.columns):
        return patched, 0, latest_histories_date(patched)
    quote_frame["code"] = quote_frame["code"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6).str[-6:]
    quote_frame["realtime_price"] = pd.to_numeric(quote_frame["realtime_price"], errors="coerce")
    quote_frame["realtime_date"] = pd.to_datetime(quote_frame["realtime_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    quote_frame = quote_frame.dropna(subset=["code", "realtime_price", "realtime_date"])
    quote_frame = quote_frame[quote_frame["realtime_price"] > 0]

    patched_count = 0
    patched_dates: list[str] = []
    for _, quote in quote_frame.iterrows():
        code = str(quote["code"])
        history = patched.get(code)
        if history is None or history.empty or "date" not in history.columns or "close" not in history.columns:
            continue
        quote_date = str(quote["realtime_date"])
        quote_price = float(quote["realtime_price"])
        history = history.copy()
        history["date"] = history["date"].astype(str)
        history["close"] = pd.to_numeric(history["close"], errors="coerce")
        history = history.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        if history.empty:
            continue
        latest_date = str(history.iloc[-1]["date"])
        if quote_date < latest_date:
            continue
        if quote_date == latest_date:
            latest_index = history.index[-1]
            history.loc[latest_index, "close"] = quote_price
            if "high" in history.columns:
                history.loc[latest_index, "high"] = max(float(pd.to_numeric(pd.Series([history.loc[latest_index, "high"]]), errors="coerce").fillna(quote_price).iloc[0]), quote_price)
            if "low" in history.columns:
                history.loc[latest_index, "low"] = min(float(pd.to_numeric(pd.Series([history.loc[latest_index, "low"]]), errors="coerce").fillna(quote_price).iloc[0]), quote_price)
        else:
            new_row = {column: pd.NA for column in history.columns}
            new_row["date"] = quote_date
            for column in ["open", "high", "low", "close"]:
                if column in history.columns:
                    new_row[column] = quote_price
            history = pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)
        patched[code] = history.reset_index(drop=True)
        patched_count += 1
        patched_dates.append(quote_date)
    return patched, patched_count, max(patched_dates) if patched_dates else latest_histories_date(patched)


def merge_existing_csv(path: Path, fresh: pd.DataFrame, *, key_columns: list[str], min_date: str | None = None) -> pd.DataFrame:
    if not path.exists():
        return filter_rows_from_date(fresh, min_date).reset_index(drop=True)
    existing = pd.read_csv(path)
    return merge_historical_rows(existing, fresh, key_columns=key_columns, min_date=min_date)


def merge_historical_rows(existing: pd.DataFrame, fresh: pd.DataFrame, *, key_columns: list[str], min_date: str | None = None) -> pd.DataFrame:
    if existing.empty:
        return filter_rows_from_date(fresh, min_date).reset_index(drop=True)
    if fresh.empty:
        return filter_rows_from_date(existing, min_date).reset_index(drop=True)

    columns = list(dict.fromkeys([*fresh.columns.tolist(), *existing.columns.tolist()]))
    key_columns = [column for column in key_columns if column in columns]
    combined = pd.concat(
        [fresh.reindex(columns=columns), existing.reindex(columns=columns)],
        ignore_index=True,
    )
    if key_columns:
        dedupe = combined.copy()
        for column in key_columns:
            dedupe[column] = dedupe[column].astype(str)
        combined = combined.loc[~dedupe.duplicated(subset=key_columns, keep="last")]
        combined = combined.sort_values(key_columns)
    combined = filter_rows_from_date(combined, min_date)
    return combined.reset_index(drop=True).reindex(columns=columns)


def merge_trade_ledger_rows(existing: pd.DataFrame, fresh: pd.DataFrame, *, min_date: str | None = None) -> pd.DataFrame:
    if existing.empty:
        return filter_trade_ledger_from_date(fresh, min_date)
    if fresh.empty:
        return filter_trade_ledger_from_date(existing, min_date)

    columns = list(dict.fromkeys([*fresh.columns.tolist(), *existing.columns.tolist()]))
    existing_filtered = filter_trade_ledger_from_date(existing.reindex(columns=columns), min_date)
    fresh_filtered = filter_trade_ledger_from_date(fresh.reindex(columns=columns), min_date)
    if "date" not in columns or existing_filtered.empty:
        return fresh_filtered.reset_index(drop=True).reindex(columns=columns)

    existing_dates = set(existing_filtered["date"].dropna().astype(str))
    if existing_dates:
        fresh_filtered = fresh_filtered.loc[~fresh_filtered["date"].astype(str).isin(existing_dates)].copy()

    existing_filtered = existing_filtered.copy()
    fresh_filtered = fresh_filtered.copy()
    existing_filtered["_ledger_order"] = range(len(existing_filtered))
    fresh_filtered["_ledger_order"] = range(len(existing_filtered), len(existing_filtered) + len(fresh_filtered))
    combined = pd.concat([existing_filtered, fresh_filtered], ignore_index=True)
    if "date" in combined.columns:
        combined["_ledger_date"] = pd.to_datetime(combined["date"], errors="coerce")
        combined = combined.sort_values(["_ledger_date", "_ledger_order"], na_position="last")
    return combined.drop(columns=["_ledger_order", "_ledger_date"], errors="ignore").reset_index(drop=True).reindex(columns=columns)


def filter_rows_from_date(frame: pd.DataFrame, min_date: str | None) -> pd.DataFrame:
    if not min_date or frame.empty or "date" not in frame.columns:
        return frame.copy()
    dates = pd.to_datetime(frame["date"], errors="coerce")
    start = pd.to_datetime(min_date, errors="coerce")
    if pd.isna(start):
        return frame.copy()
    return frame.loc[dates.isna() | (dates >= start)].copy()


def filter_trade_ledger_from_date(trades: pd.DataFrame, min_date: str | None) -> pd.DataFrame:
    if not min_date or trades.empty or "date" not in trades.columns:
        return trades.copy().reset_index(drop=True)
    required = {"action", "code", "shares"}
    if required.difference(trades.columns):
        return filter_rows_from_date(trades, min_date).reset_index(drop=True)

    frame = trades.copy().reset_index(drop=True)
    dates = pd.to_datetime(frame["date"], errors="coerce")
    start = pd.to_datetime(min_date, errors="coerce")
    if pd.isna(start):
        return frame

    pre_start_holdings: dict[str, float] = {}
    pre_start_indexes_by_code: dict[str, list[int]] = {}
    for index, row in frame.loc[dates < start].iterrows():
        code = str(row.get("code", "")).strip().zfill(6)
        action = str(row.get("action", "")).upper()
        shares = pd.to_numeric(pd.Series([row.get("shares", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
        shares = float(shares)
        if not code:
            continue
        pre_start_indexes_by_code.setdefault(code, []).append(index)
        if action == "BUY":
            pre_start_holdings[code] = pre_start_holdings.get(code, 0.0) + shares
        elif action == "SELL":
            pre_start_holdings[code] = pre_start_holdings.get(code, 0.0) - shares

    carry_codes = {code for code, shares in pre_start_holdings.items() if shares > 0.000001}
    carry_indexes = {
        index
        for code in carry_codes
        for index in pre_start_indexes_by_code.get(code, [])
    }
    keep_mask = (dates >= start) | frame.index.isin(carry_indexes) | dates.isna()
    return frame.loc[keep_mask].reset_index(drop=True)


def filter_backtest_pool(pool: pd.DataFrame, *, excluded_fund_types: str | None = None) -> pd.DataFrame:
    if pool.empty or not excluded_fund_types or "fund_type" not in pool.columns:
        return pool.copy().reset_index(drop=True)
    excluded = {value.strip().upper() for value in excluded_fund_types.split(",") if value.strip()}
    if not excluded:
        return pool.copy().reset_index(drop=True)
    fund_types = pool["fund_type"].fillna("").astype(str).str.strip().str.upper()
    return pool.loc[~fund_types.isin(excluded)].copy().reset_index(drop=True)


def _fetch_histories(codes: list[str], *, workers: int) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    if workers <= 1:
        for code in codes:
            try:
                histories[code] = fetch_etf_daily_bars(code)
            except Exception:
                histories[code] = pd.DataFrame()
        return histories

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {executor.submit(fetch_etf_daily_bars, code): code for code in codes}
        for future in as_completed(future_map):
            code = future_map[future]
            try:
                histories[code] = future.result()
            except Exception:
                histories[code] = pd.DataFrame()
    return histories
