import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .etf_data_sources import fetch_all_etfs, fetch_etf_daily_bars, fetch_etf_scales, fetch_realtime_etf_quotes
from .etf_backtest import POSITION_COLUMNS, audit_trade_ledger, run_rotation_backtest
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
    previous_positions = pd.DataFrame(columns=POSITION_COLUMNS)
    if args.preserve_backtest_history and not args.no_preserve_backtest_history and positions_path.exists():
        previous_positions = pd.read_csv(positions_path)
    max_positions = max(1, int(1.0 / args.position_fraction)) if args.position_fraction > 0 else 1
    ledger_errors = audit_trade_ledger(trades, positions, max_positions=max_positions)
    if ledger_errors:
        raise ValueError("Invalid backtest trade ledger: " + "; ".join(ledger_errors[:5]))
    if args.preserve_backtest_history and not args.no_preserve_backtest_history:
        curve = merge_existing_csv(curve_path, curve, key_columns=["date"], min_date=args.backtest_history_start_date)
        if trades_path.exists():
            trades = merge_trade_ledger_rows(
                pd.read_csv(trades_path),
                trades,
                min_date=args.backtest_history_start_date,
                max_positions=max_positions,
                max_theme_positions=args.max_theme_positions or None,
            )
        else:
            trades = filter_trade_ledger_from_date(trades, args.backtest_history_start_date)
    else:
        curve = filter_rows_from_date(curve, args.backtest_history_start_date)
        trades = filter_trade_ledger_from_date(trades, args.backtest_history_start_date)
    positions = align_positions_to_trade_ledger(trades, combine_position_metadata(previous_positions, positions))
    curve = align_latest_curve_to_positions(curve, trades, positions)
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


def merge_trade_ledger_rows(
    existing: pd.DataFrame,
    fresh: pd.DataFrame,
    *,
    min_date: str | None = None,
    max_positions: int | None = None,
    max_theme_positions: int | None = None,
) -> pd.DataFrame:
    if existing.empty:
        return filter_trade_ledger_from_date(fresh, min_date)
    if fresh.empty:
        return filter_trade_ledger_from_date(existing, min_date)

    columns = list(dict.fromkeys([*fresh.columns.tolist(), *existing.columns.tolist()]))
    existing_filtered = filter_trade_ledger_from_date(existing.reindex(columns=columns), min_date)
    existing_filtered = normalize_full_exit_trade_rows(existing_filtered)
    fresh_filtered = filter_trade_ledger_from_date(fresh.reindex(columns=columns), min_date)
    if "date" not in columns or existing_filtered.empty:
        return fresh_filtered.reset_index(drop=True).reindex(columns=columns)

    existing_dates_parsed = pd.to_datetime(existing_filtered["date"], errors="coerce")
    latest_existing_date = existing_dates_parsed.max()
    if pd.notna(latest_existing_date):
        fresh_dates_parsed = pd.to_datetime(fresh_filtered["date"], errors="coerce")
        fresh_filtered = fresh_filtered.loc[fresh_dates_parsed > latest_existing_date].copy()

    existing_dates = set(existing_filtered["date"].dropna().astype(str))
    if existing_dates:
        fresh_filtered = fresh_filtered.loc[~fresh_filtered["date"].astype(str).isin(existing_dates)].copy()
    fresh_filtered = filter_appendable_trade_rows(
        existing_filtered,
        fresh_filtered,
        max_positions=max_positions,
        max_theme_positions=max_theme_positions,
    )

    existing_filtered = existing_filtered.copy()
    fresh_filtered = fresh_filtered.copy()
    existing_filtered["_ledger_order"] = range(len(existing_filtered))
    fresh_filtered["_ledger_order"] = range(len(existing_filtered), len(existing_filtered) + len(fresh_filtered))
    combined = pd.concat([existing_filtered, fresh_filtered], ignore_index=True)
    if "date" in combined.columns:
        combined["_ledger_date"] = pd.to_datetime(combined["date"], errors="coerce")
        combined = combined.sort_values(["_ledger_date", "_ledger_order"], na_position="last")
    combined = combined.drop(columns=["_ledger_order", "_ledger_date"], errors="ignore").reset_index(drop=True).reindex(columns=columns)
    return recalculate_trade_cash_after(combined)


def combine_position_metadata(previous: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for frame in [previous, fresh]:
        if frame is not None and not frame.empty:
            frames.append(frame.reindex(columns=POSITION_COLUMNS))
    if not frames:
        return pd.DataFrame(columns=POSITION_COLUMNS)
    return pd.concat(frames, ignore_index=True).reindex(columns=POSITION_COLUMNS)


def recalculate_trade_cash_after(trades: pd.DataFrame, initial_cash: float | None = None) -> pd.DataFrame:
    if trades.empty or {"action", "value", "cash_after"}.difference(trades.columns):
        return trades.copy().reset_index(drop=True)

    frame = trades.copy().reset_index(drop=True)
    cash = _infer_initial_cash(frame) if initial_cash is None else float(initial_cash)
    holdings: dict[str, float] = {}
    for index, row in frame.iterrows():
        action = str(row.get("action", "")).upper()
        code = str(row.get("code", "")).strip().zfill(6)
        shares = _to_float(row.get("shares", 0.0))
        value = _to_float(row.get("value", 0.0))
        fee = _to_float(row.get("fee", 0.0))
        stamp_tax = _to_float(row.get("stamp_tax", 0.0))
        if action == "BUY":
            cash -= value + fee + stamp_tax
            if code and shares > 0:
                holdings[code] = holdings.get(code, 0.0) + shares
        elif action == "SELL":
            cash += value - fee - stamp_tax
            if code and shares > 0:
                remaining = holdings.get(code, 0.0) - shares
                if remaining > 0.000001:
                    holdings[code] = remaining
                else:
                    holdings.pop(code, None)
        else:
            continue
        frame.at[index, "cash_after"] = round(cash, 8)
        if not holdings and "equity_after" in frame.columns:
            frame.at[index, "equity_after"] = round(cash, 8)
    return frame


def _infer_initial_cash(trades: pd.DataFrame) -> float:
    for _, row in trades.iterrows():
        cash_after = pd.to_numeric(pd.Series([row.get("cash_after", pd.NA)]), errors="coerce").iloc[0]
        if pd.isna(cash_after):
            continue
        action = str(row.get("action", "")).upper()
        value = _to_float(row.get("value", 0.0))
        fee = _to_float(row.get("fee", 0.0))
        stamp_tax = _to_float(row.get("stamp_tax", 0.0))
        if action == "BUY":
            return float(cash_after) + value + fee + stamp_tax
        if action == "SELL":
            return float(cash_after) - value + fee + stamp_tax
    return 1.0


def filter_appendable_trade_rows(
    existing: pd.DataFrame,
    fresh: pd.DataFrame,
    *,
    max_positions: int | None = None,
    max_theme_positions: int | None = None,
    tolerance: float = 0.000001,
) -> pd.DataFrame:
    if fresh.empty or {"action", "code", "shares"}.difference(fresh.columns):
        return fresh.copy().reset_index(drop=True)

    holdings: dict[str, float] = {}
    cost_bases: dict[str, float] = {}
    themes: dict[str, str] = {}
    if not existing.empty and not {"action", "code", "shares"}.difference(existing.columns):
        for _, row in existing.reset_index(drop=True).iterrows():
            code = str(row.get("code", "")).strip().zfill(6)
            action = str(row.get("action", "")).upper()
            shares = _to_float(row.get("shares", 0.0))
            if not code or shares <= 0:
                continue
            if action == "BUY":
                holdings[code] = holdings.get(code, 0.0) + shares
                cost_bases[code] = cost_bases.get(code, 0.0) + _row_cost_basis(row)
                themes[code] = _metadata_theme(row)
            elif action == "SELL":
                current = holdings.get(code, 0.0)
                sell_ratio = min(1.0, shares / current) if current > tolerance else 0.0
                holdings[code] = current - shares
                cost_bases[code] = cost_bases.get(code, 0.0) * (1.0 - sell_ratio)
                if abs(holdings[code]) <= tolerance:
                    holdings.pop(code, None)
                    cost_bases.pop(code, None)
                    themes.pop(code, None)

    keep_indexes: list[int] = []
    normalized = fresh.copy()
    fresh_ordered = fresh.reset_index(drop=False).rename(columns={"index": "_source_index"})
    if "date" in fresh_ordered.columns:
        fresh_ordered["_ledger_date"] = pd.to_datetime(fresh_ordered["date"], errors="coerce")
        fresh_ordered = fresh_ordered.sort_values(["_ledger_date", "_source_index"], na_position="last")
    for _, row in fresh_ordered.iterrows():
        source_index = int(row["_source_index"])
        code = str(row.get("code", "")).strip().zfill(6)
        action = str(row.get("action", "")).upper()
        shares = _to_float(row.get("shares", 0.0))
        if not code or shares <= 0:
            keep_indexes.append(source_index)
            continue
        if action == "BUY":
            theme = _metadata_theme(row)
            if code in holdings and holdings.get(code, 0.0) > tolerance:
                continue
            if max_positions and _open_position_count(holdings, tolerance) >= max_positions:
                continue
            if max_theme_positions and theme and _open_theme_count(themes, theme) >= max_theme_positions:
                continue
            keep_indexes.append(source_index)
            holdings[code] = holdings.get(code, 0.0) + shares
            cost_bases[code] = cost_bases.get(code, 0.0) + _row_cost_basis(row)
            themes[code] = theme
        elif action == "SELL":
            current = holdings.get(code, 0.0)
            if current <= tolerance:
                continue
            if abs(shares - current) > tolerance:
                _normalize_exit_row(normalized, source_index, row, current, cost_bases.get(code, 0.0))
            keep_indexes.append(source_index)
            holdings.pop(code, None)
            cost_bases.pop(code, None)
            themes.pop(code, None)
        else:
            keep_indexes.append(source_index)
    return normalized.loc[keep_indexes].copy().reset_index(drop=True)


def normalize_full_exit_trade_rows(trades: pd.DataFrame, tolerance: float = 0.000001) -> pd.DataFrame:
    if trades.empty or {"action", "code", "shares"}.difference(trades.columns):
        return trades.copy().reset_index(drop=True)

    normalized = trades.copy().reset_index(drop=True)
    holdings: dict[str, float] = {}
    cost_bases: dict[str, float] = {}
    for index, row in normalized.iterrows():
        code = str(row.get("code", "")).strip().zfill(6)
        action = str(row.get("action", "")).upper()
        shares = _to_float(row.get("shares", 0.0))
        if not code or shares <= 0:
            continue
        if action == "BUY":
            holdings[code] = holdings.get(code, 0.0) + shares
            cost_bases[code] = cost_bases.get(code, 0.0) + _row_cost_basis(row)
        elif action == "SELL" and holdings.get(code, 0.0) > tolerance:
            if abs(shares - holdings[code]) > tolerance:
                _normalize_exit_row(normalized, index, row, holdings[code], cost_bases.get(code, 0.0))
            holdings.pop(code, None)
            cost_bases.pop(code, None)
    return normalized


def _normalize_exit_row(frame: pd.DataFrame, index: int, row: pd.Series, shares: float, cost_basis: float) -> None:
    original_shares = _to_float(row.get("shares", 0.0))
    price = _to_float(row.get("price", 0.0))
    scale = shares / original_shares if original_shares > 0 else 1.0
    gross_value = shares * price if price > 0 else _to_float(row.get("value", 0.0)) * scale
    fee = _to_float(row.get("fee", 0.0)) * scale
    stamp_tax = _to_float(row.get("stamp_tax", 0.0)) * scale
    if cost_basis <= 0:
        cost_basis = _row_cost_basis(row) * scale
    realized_pnl = gross_value - cost_basis - fee - stamp_tax

    frame.at[index, "shares"] = round(shares, 8)
    if "value" in frame.columns:
        frame.at[index, "value"] = round(gross_value, 8)
    if "fee" in frame.columns:
        frame.at[index, "fee"] = round(fee, 8)
    if "stamp_tax" in frame.columns:
        frame.at[index, "stamp_tax"] = round(stamp_tax, 8)
    if "cost_basis" in frame.columns:
        frame.at[index, "cost_basis"] = round(cost_basis, 8)
    if "realized_pnl" in frame.columns:
        frame.at[index, "realized_pnl"] = round(realized_pnl, 8)
    if "realized_return" in frame.columns:
        frame.at[index, "realized_return"] = round(realized_pnl / cost_basis if cost_basis else 0.0, 6)


def _row_cost_basis(row: pd.Series) -> float:
    cost_basis = _to_float(row.get("cost_basis", 0.0))
    return cost_basis if cost_basis > 0 else _to_float(row.get("value", 0.0))


def _metadata_theme(row: pd.Series) -> str:
    return str(row.get("theme", "") or "").strip()


def _open_position_count(holdings: dict[str, float], tolerance: float) -> int:
    return sum(1 for shares in holdings.values() if shares > tolerance)


def _open_theme_count(themes: dict[str, str], theme: str) -> int:
    return sum(1 for value in themes.values() if value == theme)


def align_positions_to_trade_ledger(trades: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return positions.copy().reset_index(drop=True)

    open_books: dict[str, dict] = {}
    trade_meta: dict[str, dict] = {}
    for _, row in trades.reset_index(drop=True).iterrows():
        code = str(row.get("code", "")).strip().zfill(6)
        if not code:
            continue
        action = str(row.get("action", "")).upper()
        shares = _to_float(row.get("shares", 0.0))
        value = _to_float(row.get("cost_basis", row.get("value", 0.0)))
        price = _to_float(row.get("price", 0.0))
        trade_meta[code] = {
            "code": code,
            "name": row.get("name", ""),
            "theme": row.get("theme", ""),
            "last_price": price,
            "entry_price": price,
            "score": _to_float(row.get("score", 0.0)),
        }
        if shares <= 0:
            continue
        if action == "BUY":
            book = open_books.setdefault(code, {"shares": 0.0, "cost_basis": 0.0})
            book["shares"] += shares
            book["cost_basis"] += value
        elif action == "SELL":
            book = open_books.get(code)
            if not book:
                continue
            current_shares = float(book.get("shares", 0.0))
            if current_shares <= 0:
                continue
            sell_ratio = min(1.0, shares / current_shares)
            book["shares"] = current_shares - shares
            book["cost_basis"] = float(book.get("cost_basis", 0.0)) * (1.0 - sell_ratio)
            if book["shares"] <= 0.000001:
                open_books.pop(code, None)

    if not open_books:
        return pd.DataFrame(columns=POSITION_COLUMNS)

    fresh_by_code = {}
    if not positions.empty and "code" in positions.columns:
        fresh = positions.copy()
        fresh["code"] = fresh["code"].astype(str).str.zfill(6)
        fresh_by_code = {str(row["code"]): row.to_dict() for _, row in fresh.iterrows()}

    rows = []
    for code, book in open_books.items():
        shares = float(book["shares"])
        if shares <= 0:
            continue
        source = {**trade_meta.get(code, {"code": code}), **fresh_by_code.get(code, {})}
        last_price = _to_float(source.get("last_price", source.get("entry_price", 0.0)))
        entry_price = float(book.get("cost_basis", 0.0)) / shares if shares else 0.0
        market_value = shares * last_price
        rows.append(
            {
                "code": code,
                "name": source.get("name", ""),
                "theme": source.get("theme", ""),
                "shares": round(shares, 8),
                "entry_price": round(entry_price, 6),
                "last_price": round(last_price, 6),
                "market_value": round(market_value, 8),
                "weight": 0.0,
                "score": round(_to_float(source.get("score", 0.0)), 6),
                "ma30": round(_to_float(source.get("ma30", 0.0)), 6) if not is_missing_value(source.get("ma30", pd.NA)) else pd.NA,
                "below_ma_days": int(_to_float(source.get("below_ma_days", 0))),
                "unrealized_return": round(last_price / entry_price - 1.0 if entry_price else 0.0, 6),
            }
        )

    frame = pd.DataFrame(rows, columns=POSITION_COLUMNS)
    equity = _latest_trade_cash(trades) + float(pd.to_numeric(frame["market_value"], errors="coerce").fillna(0.0).sum())
    if equity > 0 and not frame.empty:
        frame["weight"] = (pd.to_numeric(frame["market_value"], errors="coerce").fillna(0.0) / equity).round(6)
    return frame.reset_index(drop=True)


def align_latest_curve_to_positions(curve: pd.DataFrame, trades: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    if curve.empty:
        return curve.copy()
    aligned = curve.copy().reset_index(drop=True)
    cash = _latest_trade_cash(trades)
    position_value = 0.0 if positions.empty else float(pd.to_numeric(positions.get("market_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    equity = cash + position_value
    if equity <= 0:
        return aligned
    initial_equity = _to_float(aligned.iloc[0].get("equity", 1.0)) or 1.0

    if positions.empty and not trades.empty and {"date", "action"}.issubset(trades.columns):
        ordered_trades = trades.copy().reset_index(drop=True)
        ordered_trades["_ledger_date"] = pd.to_datetime(ordered_trades["date"], errors="coerce")
        ordered_trades = ordered_trades.sort_values("_ledger_date", na_position="first")
        final_trade = ordered_trades.iloc[-1]
        final_exit_date = final_trade.get("_ledger_date", pd.NaT)
        if str(final_trade.get("action", "")).upper() == "SELL" and pd.notna(final_exit_date):
            curve_dates = pd.to_datetime(aligned["date"], errors="coerce")
            exit_indexes = aligned.index[curve_dates >= final_exit_date]
            if len(exit_indexes):
                aligned.loc[exit_indexes, "cash"] = round(cash, 8)
                aligned.loc[exit_indexes, "position_value"] = 0.0
                aligned.loc[exit_indexes, "equity"] = round(cash, 8)
                aligned.loc[exit_indexes, "exposure"] = 0.0
                aligned.loc[exit_indexes, "total_return"] = round(cash / initial_equity - 1.0, 6)
                if "positions" in aligned.columns:
                    aligned.loc[exit_indexes, "positions"] = ""
                first_exit_index = int(exit_indexes[0])
                prior_equities = pd.to_numeric(aligned.loc[: first_exit_index - 1, "equity"], errors="coerce").dropna()
                running_peak = max(float(prior_equities.max()) if not prior_equities.empty else cash, cash)
                aligned.loc[exit_indexes, "drawdown"] = round(cash / running_peak - 1.0 if running_peak else 0.0, 6)
                return aligned

    latest_index = aligned.index[-1]
    previous_equities = pd.to_numeric(aligned.loc[:latest_index, "equity"], errors="coerce").fillna(equity)
    running_peak = max(float(previous_equities.max()), equity)
    aligned.loc[latest_index, "cash"] = round(cash, 8)
    aligned.loc[latest_index, "position_value"] = round(position_value, 8)
    aligned.loc[latest_index, "equity"] = round(equity, 8)
    aligned.loc[latest_index, "exposure"] = round(position_value / equity if equity else 0.0, 6)
    aligned.loc[latest_index, "total_return"] = round(equity / initial_equity - 1.0, 6)
    aligned.loc[latest_index, "drawdown"] = round(equity / running_peak - 1.0 if running_peak else 0.0, 6)
    if "positions" in aligned.columns:
        aligned.loc[latest_index, "positions"] = "|".join(positions["code"].astype(str).tolist()) if not positions.empty else ""
    return aligned


def is_missing_value(value: object) -> bool:
    try:
        return pd.isna(value)
    except ValueError:
        return False


def _to_float(value: object) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return 0.0 if pd.isna(parsed) else float(parsed)


def _latest_trade_cash(trades: pd.DataFrame) -> float:
    if trades.empty or "cash_after" not in trades.columns:
        return 0.0
    values = pd.to_numeric(trades["cash_after"], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else 0.0


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
