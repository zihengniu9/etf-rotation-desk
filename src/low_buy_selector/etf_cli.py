import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd

from .etf_data_sources import fetch_all_etfs, fetch_etf_daily_bars, fetch_etf_scales
from .etf_backtest import audit_trade_ledger, run_rotation_backtest
from .etf_hot import fetch_hot_etfs
from .etf_pool import build_theme_pool
from .etf_rotation import rank_etfs_by_momentum


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
    parser.add_argument("--workers", type=int, default=1, help="Use 1 for stability with AKShare/Sina ETF history.")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--sse-scale-date", default="")
    parser.add_argument(
        "--preserve-backtest-history",
        action="store_true",
        help="Preserve previous curve rows by date. Trades and positions are always overwritten with a coherent fresh ledger.",
    )
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

    curve, trades, positions = run_rotation_backtest(
        pool,
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
    ledger_errors = audit_trade_ledger(trades, positions)
    if ledger_errors:
        raise ValueError("Invalid backtest trade ledger: " + "; ".join(ledger_errors[:5]))
    if args.preserve_backtest_history and not args.no_preserve_backtest_history:
        curve = merge_existing_csv(curve_path, curve, key_columns=["date"])
    curve.to_csv(curve_path, index=False, encoding="utf-8-sig")
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    positions.to_csv(positions_path, index=False, encoding="utf-8-sig")

    hot_rank = fetch_hot_etfs(limit=args.hot_top)
    hot_path = output_dir / "etf_hot_rank.csv"
    hot_rank.to_csv(hot_path, index=False, encoding="utf-8-sig")

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
    return 0


def _latest_query_date(etfs: pd.DataFrame) -> str:
    if "query_date" in etfs.columns and not etfs["query_date"].dropna().empty:
        value = str(etfs["query_date"].dropna().iloc[0])
        digits = value.replace("-", "")
        if len(digits) == 8 and digits.isdigit():
            return digits
    return date.today().strftime("%Y%m%d")


def merge_existing_csv(path: Path, fresh: pd.DataFrame, *, key_columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return fresh.copy().reset_index(drop=True)
    existing = pd.read_csv(path)
    return merge_historical_rows(existing, fresh, key_columns=key_columns)


def merge_historical_rows(existing: pd.DataFrame, fresh: pd.DataFrame, *, key_columns: list[str]) -> pd.DataFrame:
    if existing.empty:
        return fresh.copy().reset_index(drop=True)
    if fresh.empty:
        return existing.copy().reset_index(drop=True)

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
    return combined.reset_index(drop=True).reindex(columns=columns)


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
