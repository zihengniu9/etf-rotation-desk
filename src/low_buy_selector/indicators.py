from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MA5Setup:
    passed: bool
    latest_date: str
    close: float
    ma5: float
    prev_ma5: float
    distance_pct: float
    ma5_up_days: int
    recent_drawdown_pct: float
    technical_score: float
    reason: str


def evaluate_ma5_setup(
    bars: pd.DataFrame,
    *,
    min_distance_pct: float = -0.5,
    max_distance_pct: float = 3.0,
    ma5_trend_window: int = 5,
    min_ma5_up_days: int | None = None,
    max_recent_drawdown_pct: float = -5.0,
    drawdown_window: int = 10,
) -> MA5Setup:
    if "close" not in bars.columns:
        return _fail("missing close column")

    frame = bars.copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"])
    if len(frame) < 6:
        return _fail("not enough bars for MA5 comparison")

    closes = frame["close"].astype(float)
    latest_close = float(closes.iloc[-1])
    ma5 = float(closes.iloc[-5:].mean())
    prev_ma5 = float(closes.iloc[-6:-1].mean())
    latest_date = str(frame.iloc[-1].get("date", ""))
    rolling_ma5 = closes.rolling(5).mean().dropna()
    trend_window = max(2, int(ma5_trend_window))
    ma5_tail = rolling_ma5.tail(trend_window)
    ma5_changes = ma5_tail.diff().dropna()
    ma5_up_days = int((ma5_changes > 0).sum())
    required_up_days = len(ma5_changes) if min_ma5_up_days is None else int(min_ma5_up_days)
    recent_high = float(closes.tail(max(1, int(drawdown_window))).max())
    recent_drawdown_pct = (latest_close / recent_high - 1.0) * 100.0 if recent_high else 0.0

    if ma5 == 0:
        return _fail("MA5 is zero", latest_date=latest_date, close=latest_close, ma5=ma5, prev_ma5=prev_ma5)

    distance_pct = (latest_close / ma5 - 1.0) * 100.0
    if ma5 <= prev_ma5:
        return MA5Setup(
            passed=False,
            latest_date=latest_date,
            close=latest_close,
            ma5=ma5,
            prev_ma5=prev_ma5,
            distance_pct=distance_pct,
            ma5_up_days=ma5_up_days,
            recent_drawdown_pct=recent_drawdown_pct,
            technical_score=0.0,
            reason="MA5 is not rising",
        )

    if distance_pct < min_distance_pct or distance_pct > max_distance_pct:
        return MA5Setup(
            passed=False,
            latest_date=latest_date,
            close=latest_close,
            ma5=ma5,
            prev_ma5=prev_ma5,
            distance_pct=distance_pct,
            ma5_up_days=ma5_up_days,
            recent_drawdown_pct=recent_drawdown_pct,
            technical_score=0.0,
            reason=f"close-to-MA5 distance {distance_pct:.2f}% outside range",
        )

    if len(ma5_tail) < trend_window:
        return MA5Setup(
            passed=False,
            latest_date=latest_date,
            close=latest_close,
            ma5=ma5,
            prev_ma5=prev_ma5,
            distance_pct=distance_pct,
            ma5_up_days=ma5_up_days,
            recent_drawdown_pct=recent_drawdown_pct,
            technical_score=0.0,
            reason="not enough MA5 values for trend check",
        )

    if ma5_up_days < required_up_days:
        return MA5Setup(
            passed=False,
            latest_date=latest_date,
            close=latest_close,
            ma5=ma5,
            prev_ma5=prev_ma5,
            distance_pct=distance_pct,
            ma5_up_days=ma5_up_days,
            recent_drawdown_pct=recent_drawdown_pct,
            technical_score=0.0,
            reason=f"MA5 trend is not consistently rising ({ma5_up_days}/{len(ma5_changes)} up days)",
        )

    if recent_drawdown_pct < max_recent_drawdown_pct:
        return MA5Setup(
            passed=False,
            latest_date=latest_date,
            close=latest_close,
            ma5=ma5,
            prev_ma5=prev_ma5,
            distance_pct=distance_pct,
            ma5_up_days=ma5_up_days,
            recent_drawdown_pct=recent_drawdown_pct,
            technical_score=0.0,
            reason=f"recent drawdown {recent_drawdown_pct:.2f}% below limit",
        )

    distance_score = max(0.0, min(100.0, 100.0 - abs(distance_pct) * 20.0))
    drawdown_score = max(0.0, min(100.0, 100.0 + recent_drawdown_pct * 8.0))
    trend_score = max(0.0, min(100.0, ma5_up_days / max(1, len(ma5_changes)) * 100.0))
    technical_score = distance_score * 0.55 + trend_score * 0.30 + drawdown_score * 0.15
    return MA5Setup(
        passed=True,
        latest_date=latest_date,
        close=latest_close,
        ma5=ma5,
        prev_ma5=prev_ma5,
        distance_pct=distance_pct,
        ma5_up_days=ma5_up_days,
        recent_drawdown_pct=recent_drawdown_pct,
        technical_score=technical_score,
        reason="passed",
    )


def _fail(
    reason: str,
    *,
    latest_date: str = "",
    close: float = 0.0,
    ma5: float = 0.0,
    prev_ma5: float = 0.0,
    distance_pct: float = 0.0,
    ma5_up_days: int = 0,
    recent_drawdown_pct: float = 0.0,
) -> MA5Setup:
    return MA5Setup(
        passed=False,
        latest_date=latest_date,
        close=close,
        ma5=ma5,
        prev_ma5=prev_ma5,
        distance_pct=distance_pct,
        ma5_up_days=ma5_up_days,
        recent_drawdown_pct=recent_drawdown_pct,
        technical_score=0.0,
        reason=reason,
    )
