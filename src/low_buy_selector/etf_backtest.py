import pandas as pd

from .etf_rotation import score_momentum


CURVE_COLUMNS = ["date", "equity", "cash", "position_value", "exposure", "total_return", "drawdown", "positions"]
TRADE_COLUMNS = [
    "date",
    "action",
    "code",
    "name",
    "theme",
    "price",
    "shares",
    "value",
    "fee",
    "stamp_tax",
    "cost_basis",
    "realized_pnl",
    "realized_return",
    "score",
    "reason",
    "cash_after",
    "equity_after",
]
POSITION_COLUMNS = ["code", "name", "theme", "shares", "entry_price", "last_price", "market_value", "weight", "score", "ma30", "below_ma_days", "unrealized_return"]
SIGNAL_COLUMNS = ["date", "code", "name", "theme", "score", "close", "ma30", "below_ma30", "passed"]
THEME_BUCKET_KEYWORDS = [
    ("电力", ("电力", "绿电")),
    ("半导体", ("半导体", "芯片", "集成电路")),
    ("科创", ("科创", "双创", "科综")),
    ("5G通信", ("5G", "通信", "CPO")),
    ("AI算力", ("AI", "人工智能", "算力", "云计算", "数据")),
    ("新能源车", ("新能源车", "智能车", "汽车")),
    ("光伏储能", ("光伏", "储能", "电池", "锂")),
    ("医药医疗", ("医药", "医疗", "生物")),
    ("军工航天", ("军工", "航天", "卫星", "国防")),
    ("消费", ("消费", "食品", "酒")),
    ("金融证券", ("证券", "金融", "银行", "保险")),
]


def build_daily_strength_signals(
    pool: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    *,
    lookback_days: int = 30,
    momentum_days: int = 20,
    ma_window: int = 30,
    min_total_return: float = 0.01,
    bonus: float = 0.02,
) -> pd.DataFrame:
    normalized = {code: _normalize_history(history) for code, history in histories.items()}
    dates = sorted({date for history in normalized.values() for date in history["date"].tolist()})
    if not dates:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    backtest_dates = dates[-lookback_days:]
    rows: list[dict] = []

    for current_date in backtest_dates:
        for _, etf in pool.iterrows():
            code = _normalize_code(etf["code"])
            history = normalized.get(code, pd.DataFrame(columns=["date", "close"]))
            window = history[history["date"] <= current_date]
            if window.empty:
                continue
            latest_close = float(window.iloc[-1]["close"])
            ma_value = float(window["close"].tail(ma_window).mean()) if len(window) >= ma_window else pd.NA
            below_ma = bool(pd.notna(ma_value) and latest_close < ma_value)
            score = score_momentum(
                window["close"],
                momentum_days=momentum_days,
                min_total_return=min_total_return,
                bonus=bonus,
            )
            rows.append(
                {
                    "date": current_date,
                    "code": code,
                    "name": etf.get("name", ""),
                    "theme": etf.get("theme", ""),
                    "score": round(score.score, 6),
                    "close": latest_close,
                    "ma30": ma_value,
                    "below_ma30": below_ma,
                    "passed": score.passed,
                }
            )

    return pd.DataFrame(rows, columns=SIGNAL_COLUMNS)


def run_rotation_backtest(
    pool: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    *,
    lookback_days: int = 30,
    momentum_days: int = 20,
    ma_window: int = 30,
    buy_threshold: float = 0.6,
    below_ma_days_to_sell: int = 2,
    position_fraction: float = 0.5,
    max_daily_buys: int = 2,
    max_theme_positions: int | None = 1,
    dynamic_exposure: bool = False,
    theme_cooldown_days: int = 0,
    min_holding_days_before_rebalance: int = 5,
    replacement_score_threshold: float = 1.0,
    loss_cooldown_threshold: int = 2,
    loss_cooldown_days: int = 15,
    initial_cash: float = 1.0,
    min_total_return: float = 0.01,
    bonus: float = 0.02,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    signals = build_daily_strength_signals(
        pool,
        histories,
        lookback_days=lookback_days,
        momentum_days=momentum_days,
        ma_window=ma_window,
        min_total_return=min_total_return,
        bonus=bonus,
    )
    return simulate_rotation_backtest(
        signals,
        initial_cash=initial_cash,
        position_fraction=position_fraction,
        max_daily_buys=max_daily_buys,
        max_theme_positions=max_theme_positions,
        dynamic_exposure=dynamic_exposure,
        theme_cooldown_days=theme_cooldown_days,
        min_holding_days_before_rebalance=min_holding_days_before_rebalance,
        replacement_score_threshold=replacement_score_threshold,
        loss_cooldown_threshold=loss_cooldown_threshold,
        loss_cooldown_days=loss_cooldown_days,
        buy_threshold=buy_threshold,
        ma_window=ma_window,
        below_ma_days_to_sell=below_ma_days_to_sell,
    )


def simulate_rotation_backtest(
    signals: pd.DataFrame,
    *,
    initial_cash: float = 1.0,
    position_fraction: float = 0.5,
    max_daily_buys: int = 2,
    max_theme_positions: int | None = 1,
    dynamic_exposure: bool = False,
    theme_cooldown_days: int = 0,
    min_holding_days_before_rebalance: int = 5,
    replacement_score_threshold: float = 1.0,
    loss_cooldown_threshold: int = 2,
    loss_cooldown_days: int = 15,
    buy_threshold: float = 0.6,
    ma_window: int = 30,
    below_ma_days_to_sell: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if signals.empty:
        return (
            pd.DataFrame(columns=CURVE_COLUMNS),
            pd.DataFrame(columns=TRADE_COLUMNS),
            pd.DataFrame(columns=POSITION_COLUMNS),
        )

    frame = signals.copy()
    frame["date"] = frame["date"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce").fillna(0.0)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if "ma30" not in frame.columns:
        frame["ma30"] = pd.NA
    frame["ma30"] = pd.to_numeric(frame["ma30"], errors="coerce")
    frame = frame.dropna(subset=["close"])
    dates = sorted(frame["date"].unique().tolist())

    cash = float(initial_cash)
    positions: dict[str, dict] = {}
    curve_rows: list[dict] = []
    trade_rows: list[dict] = []
    running_peak = float(initial_cash)
    max_positions = max(1, int(1.0 / position_fraction))
    max_daily_buys = max(0, int(max_daily_buys))
    max_theme_positions = max(0, int(max_theme_positions or 0))
    theme_cooldown_days = max(0, int(theme_cooldown_days))
    min_holding_days_before_rebalance = max(0, int(min_holding_days_before_rebalance))
    replacement_score_threshold = float(replacement_score_threshold)
    loss_cooldown_threshold = max(0, int(loss_cooldown_threshold))
    loss_cooldown_days = max(0, int(loss_cooldown_days))
    code_loss_counts: dict[str, int] = {}
    theme_loss_counts: dict[str, int] = {}
    code_cooldowns: dict[str, int] = {}
    theme_cooldowns: dict[str, int] = {}

    for day_index, current_date in enumerate(dates):
        day = frame[frame["date"] == current_date].sort_values(["score", "code"], ascending=[False, True])
        by_code = {_normalize_code(row["code"]): row for _, row in day.iterrows()}
        market_strength = _daily_market_strength(day)
        max_exposure = _dynamic_exposure_cap(market_strength) if dynamic_exposure else 1.0

        for code, position in positions.items():
            row = by_code.get(code)
            if row is not None:
                position["last_price"] = float(row["close"])
                position["score"] = float(row["score"])
                position["ma30"] = float(row["ma30"]) if pd.notna(row.get("ma30")) else pd.NA

        for code in list(positions.keys()):
            position = positions[code]
            score = float(position.get("score", 0.0))
            ma_value = position.get("ma30", pd.NA)
            below_ma = pd.notna(ma_value) and float(position["last_price"]) < float(ma_value)
            if below_ma:
                position["below_ma_days"] = int(position.get("below_ma_days", 0)) + 1
            else:
                position["below_ma_days"] = 0
            if position["below_ma_days"] >= below_ma_days_to_sell:
                value = float(position["shares"]) * float(position["last_price"])
                cash += value
                del positions[code]
                theme = _theme_key(position.get("theme", ""), position.get("name", ""))
                _apply_loss_cooldown(
                    position,
                    value,
                    code_loss_counts,
                    theme_loss_counts,
                    code_cooldowns,
                    theme_cooldowns,
                    loss_cooldown_threshold,
                    loss_cooldown_days,
                )
                if theme and theme_cooldown_days:
                    theme_cooldowns[theme] = max(theme_cooldowns.get(theme, 0), theme_cooldown_days + 1)
                trade_rows.append(
                    _trade_row(current_date, "SELL", position, value, score, f"two closes below MA{ma_window}", cash, _equity(cash, positions))
                )

        daily_buys = 0
        for _, row in day.iterrows():
            code = _normalize_code(row["code"])
            score = float(row["score"])
            passed = bool(row.get("passed", True))
            theme = _theme_key(row.get("theme", ""), row.get("name", ""))
            if daily_buys >= max_daily_buys or score <= buy_threshold or not passed or code in positions:
                continue
            equity = _equity(cash, positions)
            current_exposure = (equity - cash) / equity if equity else 0.0
            if code_cooldowns.get(code, 0) > 0:
                continue
            if theme and theme_cooldowns.get(theme, 0) > 0:
                continue
            price = float(row["close"])
            if price <= 0:
                continue
            replacement_code = ""
            if len(positions) >= max_positions:
                if score <= replacement_score_threshold:
                    continue
                replacement_code = _replacement_position_code(
                    positions,
                    theme,
                    score,
                    current_day_index=day_index,
                    min_holding_days_before_rebalance=min_holding_days_before_rebalance,
                )
                if not replacement_code:
                    continue
                position = positions[replacement_code]
                value = float(position["shares"]) * float(position["last_price"])
                buy_value = min(equity * position_fraction, cash + value)
                if buy_value <= 0:
                    continue
                cash += value
                del positions[replacement_code]
                _apply_loss_cooldown(
                    position,
                    value,
                    code_loss_counts,
                    theme_loss_counts,
                    code_cooldowns,
                    theme_cooldowns,
                    loss_cooldown_threshold,
                    loss_cooldown_days,
                )
                trade_rows.append(
                    _trade_row(current_date, "SELL", position, value, float(position.get("score", 0.0)), "replace weaker ETF", cash, _equity(cash, positions))
                )
            else:
                if current_exposure + position_fraction > max_exposure + 0.000001:
                    continue
                if max_theme_positions and _theme_position_count(positions, theme) >= max_theme_positions:
                    continue
                buy_value = equity * position_fraction
                if cash < buy_value or buy_value <= 0:
                    continue

            position = {
                "code": code,
                "name": row.get("name", ""),
                "theme": row.get("theme", ""),
                "theme_key": theme,
                "shares": buy_value / price,
                "entry_price": price,
                "last_price": price,
                "score": score,
                "ma30": float(row["ma30"]) if pd.notna(row.get("ma30")) else pd.NA,
                "below_ma_days": 0,
                "entry_index": day_index,
            }
            cash -= buy_value
            positions[code] = position
            trade_rows.append(
                _trade_row(
                    current_date,
                    "BUY",
                    position,
                    buy_value,
                    score,
                    "stronger non-theme ETF" if replacement_code else "score above threshold",
                    cash,
                    _equity(cash, positions),
                )
            )
            daily_buys += 1

        equity = _equity(cash, positions)
        running_peak = max(running_peak, equity)
        position_value = equity - cash
        curve_rows.append(
            {
                "date": current_date,
                "equity": round(equity, 8),
                "cash": round(cash, 8),
                "position_value": round(position_value, 8),
                "exposure": round(position_value / equity if equity else 0.0, 6),
                "total_return": round(equity / initial_cash - 1.0, 6),
                "drawdown": round(equity / running_peak - 1.0 if running_peak else 0.0, 6),
                "positions": "|".join(sorted(positions.keys())),
            }
        )
        code_cooldowns = {code: days - 1 for code, days in code_cooldowns.items() if days > 1}
        theme_cooldowns = {theme: days - 1 for theme, days in theme_cooldowns.items() if days > 1}

    final_equity = _equity(cash, positions)
    position_rows = [_position_row(position, final_equity) for position in positions.values()]
    return (
        pd.DataFrame(curve_rows, columns=CURVE_COLUMNS),
        pd.DataFrame(trade_rows, columns=TRADE_COLUMNS),
        pd.DataFrame(position_rows, columns=POSITION_COLUMNS),
    )


def _normalize_history(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty or "close" not in history.columns:
        return pd.DataFrame(columns=["date", "close"])
    frame = history.copy()
    if "date" not in frame.columns:
        frame["date"] = range(len(frame))
    frame["date"] = frame["date"].astype(str)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)[["date", "close"]]
    frame["close"] = _adjust_split_like_price_breaks(frame["close"])
    return frame


def _adjust_split_like_price_breaks(closes: pd.Series) -> pd.Series:
    values = pd.to_numeric(closes, errors="coerce").astype(float).reset_index(drop=True)
    if len(values) < 2:
        return closes
    factors = [1.0] * len(values)
    cumulative_factor = 1.0
    for index in range(len(values) - 1, 0, -1):
        current = float(values.iloc[index])
        previous = float(values.iloc[index - 1])
        if current <= 0 or previous <= 0:
            factors[index - 1] = cumulative_factor
            continue
        ratio = current / previous
        if ratio <= 0.67 or ratio >= 1.5:
            cumulative_factor *= ratio
        factors[index - 1] = cumulative_factor
    return values * pd.Series(factors)


def _normalize_code(code: object) -> str:
    text = str(code)
    return text.zfill(6) if text.isdigit() else text


def _theme_key(theme: object, name: object = "") -> str:
    text = f"{theme or ''} {name or ''}".strip()
    upper_text = text.upper()
    for bucket, keywords in THEME_BUCKET_KEYWORDS:
        if any(keyword.upper() in upper_text for keyword in keywords):
            return bucket
    return str(theme or "").strip()


def _theme_position_count(positions: dict[str, dict], theme: str) -> int:
    if not theme:
        return 0
    return sum(1 for position in positions.values() if position.get("theme_key") == theme or _theme_key(position.get("theme", ""), position.get("name", "")) == theme)


def _replacement_position_code(
    positions: dict[str, dict],
    candidate_theme: str,
    candidate_score: float,
    *,
    current_day_index: int,
    min_holding_days_before_rebalance: int,
) -> str:
    if not positions or not candidate_theme:
        return ""
    if _theme_position_count(positions, candidate_theme) > 0:
        return ""
    eligible_positions = [
        position
        for position in positions.values()
        if current_day_index - int(position.get("entry_index", current_day_index)) >= min_holding_days_before_rebalance
    ]
    if not eligible_positions:
        return ""
    weakest = min(eligible_positions, key=lambda position: (float(position.get("score", 0.0)), str(position.get("code", ""))))
    return str(weakest["code"]) if candidate_score > float(weakest.get("score", 0.0)) else ""


def _apply_loss_cooldown(
    position: dict,
    exit_value: float,
    code_loss_counts: dict[str, int],
    theme_loss_counts: dict[str, int],
    code_cooldowns: dict[str, int],
    theme_cooldowns: dict[str, int],
    loss_cooldown_threshold: int,
    loss_cooldown_days: int,
) -> None:
    if loss_cooldown_threshold <= 0 or loss_cooldown_days <= 0:
        return

    code = str(position.get("code", ""))
    theme = str(position.get("theme_key") or _theme_key(position.get("theme", ""), position.get("name", "")))
    entry_value = float(position.get("shares", 0.0)) * float(position.get("entry_price", 0.0))
    is_loss = float(exit_value) < entry_value

    if not is_loss:
        if code:
            code_loss_counts[code] = 0
        if theme:
            theme_loss_counts[theme] = 0
        return

    if code:
        code_loss_counts[code] = code_loss_counts.get(code, 0) + 1
        if code_loss_counts[code] >= loss_cooldown_threshold:
            code_cooldowns[code] = max(code_cooldowns.get(code, 0), loss_cooldown_days + 1)
            code_loss_counts[code] = 0

    if theme:
        theme_loss_counts[theme] = theme_loss_counts.get(theme, 0) + 1
        if theme_loss_counts[theme] >= loss_cooldown_threshold:
            theme_cooldowns[theme] = max(theme_cooldowns.get(theme, 0), loss_cooldown_days + 1)
            theme_loss_counts[theme] = 0


def _daily_market_strength(day: pd.DataFrame) -> float:
    if day.empty:
        return 0.0
    passed = day[day.get("passed", True).astype(bool)] if "passed" in day.columns else day
    scores = pd.to_numeric(passed["score"] if not passed.empty else day["score"], errors="coerce").dropna()
    return float(scores.max()) if not scores.empty else 0.0


def _dynamic_exposure_cap(strength: float) -> float:
    if strength < 0.6:
        return 0.0
    if strength < 0.75:
        return 0.5
    if strength < 0.9:
        return 0.75
    return 1.0


def _equity(cash: float, positions: dict[str, dict]) -> float:
    return float(cash) + sum(float(position["shares"]) * float(position["last_price"]) for position in positions.values())


def _trade_row(date: str, action: str, position: dict, value: float, score: float, reason: str, cash_after: float, equity_after: float) -> dict:
    shares = float(position["shares"])
    price = float(position["last_price"])
    gross_value = float(value)
    fee = 0.0
    stamp_tax = 0.0
    cost_basis = shares * float(position.get("entry_price", price))
    realized_pnl = gross_value - cost_basis - fee - stamp_tax if action == "SELL" else 0.0
    realized_return = realized_pnl / cost_basis if action == "SELL" and cost_basis else 0.0
    return {
        "date": date,
        "action": action,
        "code": position["code"],
        "name": position.get("name", ""),
        "theme": position.get("theme", ""),
        "price": round(price, 6),
        "shares": round(shares, 8),
        "value": round(gross_value, 8),
        "fee": round(fee, 8),
        "stamp_tax": round(stamp_tax, 8),
        "cost_basis": round(cost_basis, 8),
        "realized_pnl": round(realized_pnl, 8),
        "realized_return": round(realized_return, 6),
        "score": round(float(score), 6),
        "reason": reason,
        "cash_after": round(float(cash_after), 8),
        "equity_after": round(float(equity_after), 8),
    }


def _position_row(position: dict, equity: float) -> dict:
    market_value = float(position["shares"]) * float(position["last_price"])
    entry_price = float(position["entry_price"])
    last_price = float(position["last_price"])
    return {
        "code": position["code"],
        "name": position.get("name", ""),
        "theme": position.get("theme", ""),
        "shares": round(float(position["shares"]), 8),
        "entry_price": round(entry_price, 6),
        "last_price": round(last_price, 6),
        "market_value": round(market_value, 8),
        "weight": round(market_value / equity if equity else 0.0, 6),
        "score": round(float(position.get("score", 0.0)), 6),
        "ma30": round(float(position["ma30"]), 6) if pd.notna(position.get("ma30", pd.NA)) else pd.NA,
        "below_ma_days": int(position.get("below_ma_days", 0)),
        "unrealized_return": round(last_price / entry_price - 1.0 if entry_price else 0.0, 6),
    }


def audit_trade_ledger(
    trades: pd.DataFrame,
    positions: pd.DataFrame | None = None,
    *,
    max_positions: int | None = None,
    tolerance: float = 0.000001,
) -> list[str]:
    if trades.empty:
        return []

    errors: list[str] = []
    holdings: dict[str, float] = {}
    required_columns = {"date", "action", "code", "shares"}
    missing_columns = sorted(required_columns - set(trades.columns))
    if missing_columns:
        return [f"trade ledger missing columns: {', '.join(missing_columns)}"]

    max_positions = max(0, int(max_positions or 0))

    for row_number, row in trades.reset_index(drop=True).iterrows():
        code = _normalize_code(row.get("code", ""))
        action = str(row.get("action", "")).upper()
        date = str(row.get("date", ""))
        shares = pd.to_numeric(pd.Series([row.get("shares", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
        shares = float(shares)
        if shares < -tolerance:
            errors.append(f"{date} {code} row {row_number + 1}: negative shares {shares}")
            continue
        if action == "BUY":
            holdings[code] = holdings.get(code, 0.0) + shares
        elif action == "SELL":
            current_shares = holdings.get(code, 0.0)
            if shares > current_shares + tolerance:
                errors.append(
                    f"{date} {code} row {row_number + 1}: SELL {shares:.8f} exceeds held {current_shares:.8f}"
                )
                holdings[code] = current_shares - shares
            else:
                holdings[code] = current_shares - shares
                if abs(holdings[code]) <= tolerance:
                    holdings.pop(code, None)
        else:
            errors.append(f"{date} {code} row {row_number + 1}: unknown action {action}")
        if max_positions:
            open_positions = sum(1 for held_shares in holdings.values() if held_shares > tolerance)
            if open_positions > max_positions:
                errors.append(f"{date} {code} row {row_number + 1}: open positions {open_positions} exceeds max {max_positions}")

    if positions is not None and not positions.empty:
        expected = {
            _normalize_code(row.get("code", "")): float(
                pd.to_numeric(pd.Series([row.get("shares", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
            )
            for _, row in positions.iterrows()
        }
        for code in sorted(set(holdings) | set(expected)):
            held = holdings.get(code, 0.0)
            expected_shares = expected.get(code, 0.0)
            if abs(held - expected_shares) > tolerance:
                errors.append(f"{code}: ledger shares {held:.8f} != position shares {expected_shares:.8f}")
    elif positions is not None and positions.empty:
        for code, held in sorted(holdings.items()):
            if abs(held) > tolerance:
                errors.append(f"{code}: ledger leaves open shares {held:.8f} but positions are empty")

    return errors
