from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MomentumScore:
    passed: bool
    score: float
    total_return: float
    annual_vol: float
    latest_close: float
    mean_close: float
    reason: str


def score_momentum(
    closes: pd.Series,
    *,
    momentum_days: int = 20,
    min_total_return: float = 0.01,
    bonus: float = 0.02,
) -> MomentumScore:
    series = pd.to_numeric(closes, errors="coerce").dropna()
    if len(series) < momentum_days + 1:
        return _fail("not enough history")

    window = series.tail(momentum_days + 1)
    latest = float(window.iloc[-1])
    first = float(window.iloc[0])
    mean_close = float(window.mean())
    if first == 0:
        return _fail("first close is zero", latest_close=latest, mean_close=mean_close)

    returns = window.pct_change().dropna()
    total_return = latest / first - 1.0
    annual_vol = float(returns.std() * np.sqrt(252) + 0.01)
    score = total_return / annual_vol + bonus

    if latest <= mean_close:
        return MomentumScore(False, score, total_return, annual_vol, latest, mean_close, "latest close is below average")
    if total_return <= min_total_return:
        return MomentumScore(False, score, total_return, annual_vol, latest, mean_close, "total return is too low")
    return MomentumScore(True, score, total_return, annual_vol, latest, mean_close, "passed")


def rank_etfs_by_momentum(
    pool: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    *,
    money_symbol: str = "511880",
    defense_threshold: float = 0.6,
    momentum_days: int = 20,
    min_total_return: float = 0.01,
    bonus: float = 0.02,
) -> tuple[pd.DataFrame, dict]:
    rows: list[dict] = []
    for _, etf in pool.iterrows():
        code = str(etf["code"]).zfill(6)
        history = histories.get(code, pd.DataFrame())
        if "close" not in history.columns:
            continue
        score = score_momentum(
            history["close"],
            momentum_days=momentum_days,
            min_total_return=min_total_return,
            bonus=bonus,
        )
        if not score.passed:
            continue
        rows.append(
            {
                "code": code,
                "name": etf.get("name", ""),
                "theme": etf.get("theme", ""),
                "fund_size": etf.get("fund_size", pd.NA),
                "score": round(score.score, 6),
                "total_return": round(score.total_return, 6),
                "annual_vol": round(score.annual_vol, 6),
                "latest_close": score.latest_close,
            }
        )
    rank = pd.DataFrame(rows)
    if not rank.empty:
        rank = rank.sort_values("score", ascending=False).reset_index(drop=True)
        pick = rank.iloc[0].to_dict()
        top_score = float(pick.get("score", 0.0))
        if top_score <= defense_threshold:
            return rank, _defense_pick(money_symbol, top_score, defense_threshold, "top ETF score is weak")
        pick["mode"] = "attack"
        pick["reason"] = "top ETF score is above defense threshold"
        pick["market_strength"] = top_score
        pick["defense_threshold"] = defense_threshold
        return rank, pick
    return rank, _defense_pick(money_symbol, 0.0, defense_threshold, "no ETF passed momentum filters")


def _defense_pick(symbol: str, market_strength: float, defense_threshold: float, reason: str) -> dict:
    return {
        "code": symbol,
        "name": "货币ETF",
        "theme": "防守",
        "score": round(market_strength, 6),
        "total_return": pd.NA,
        "annual_vol": pd.NA,
        "fund_size": pd.NA,
        "latest_close": pd.NA,
        "mode": "defense",
        "market_strength": round(market_strength, 6),
        "defense_threshold": defense_threshold,
        "reason": f"{reason}; switch to defense",
    }


def _fail(reason: str, *, latest_close: float = 0.0, mean_close: float = 0.0) -> MomentumScore:
    return MomentumScore(
        passed=False,
        score=0.0,
        total_return=0.0,
        annual_vol=0.0,
        latest_close=latest_close,
        mean_close=mean_close,
        reason=reason,
    )
