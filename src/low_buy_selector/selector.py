from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .data_sources import fetch_business_description, fetch_daily_bars, fetch_hot_keywords
from .indicators import evaluate_ma5_setup
from .scoring import score_hot_topics, score_legitimacy
from .ths import fetch_board_constituents


@dataclass(frozen=True)
class SelectorConfig:
    board_code: str = "883910"
    start_date: str = ""
    end_date: str = ""
    min_distance_pct: float = -0.5
    max_distance_pct: float = 3.0
    ma5_trend_window: int = 5
    min_ma5_up_days: int = 0
    max_recent_drawdown_pct: float = -5.0
    drawdown_window: int = 10
    max_workers: int = 6
    board_limit: int = 0


@dataclass(frozen=True)
class ScreenSummary:
    total_constituents: int
    evaluated: int
    selected: int
    errors: int


def screen_board(config: SelectorConfig) -> tuple[pd.DataFrame, ScreenSummary]:
    config = _with_default_dates(config)
    constituents = fetch_board_constituents(config.board_code)
    if config.board_limit > 0:
        constituents = constituents.head(config.board_limit)

    records: list[dict] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, config.max_workers)) as executor:
        futures = [
            executor.submit(_evaluate_row, row, config)
            for _, row in constituents.iterrows()
        ]
        for future in as_completed(futures):
            record, error = future.result()
            if error:
                errors += 1
            if record:
                records.append(record)

    frame = pd.DataFrame(records)
    if not frame.empty:
        frame = frame.sort_values("total_score", ascending=False).reset_index(drop=True)

    summary = ScreenSummary(
        total_constituents=len(constituents),
        evaluated=len(constituents),
        selected=len(frame),
        errors=errors,
    )
    return frame, summary


def _evaluate_row(row: pd.Series, config: SelectorConfig) -> tuple[dict | None, bool]:
    code = str(row["代码"]).zfill(6)
    name = str(row["名称"])
    try:
        bars = fetch_daily_bars(code, start_date=config.start_date, end_date=config.end_date)
        setup = evaluate_ma5_setup(
            bars,
            min_distance_pct=config.min_distance_pct,
            max_distance_pct=config.max_distance_pct,
            ma5_trend_window=config.ma5_trend_window,
            min_ma5_up_days=config.min_ma5_up_days or None,
            max_recent_drawdown_pct=config.max_recent_drawdown_pct,
            drawdown_window=config.drawdown_window,
        )
        if not setup.passed:
            return None, False

        keywords = fetch_hot_keywords(code)
        business = fetch_business_description(code)
        hot_score = score_hot_topics(keywords)
        logic_score = score_legitimacy(keywords, business)
        total_score = (
            setup.technical_score * 0.45
            + hot_score.score * 0.35
            + logic_score.score * 0.20
        )
        return {
            "code": code,
            "name": name,
            "latest_date": setup.latest_date,
            "close": round(setup.close, 3),
            "ma5": round(setup.ma5, 3),
            "prev_ma5": round(setup.prev_ma5, 3),
            "distance_pct": round(setup.distance_pct, 3),
            "ma5_up_days": setup.ma5_up_days,
            "recent_drawdown_pct": round(setup.recent_drawdown_pct, 3),
            "technical_score": round(setup.technical_score, 2),
            "hot_score": round(hot_score.score, 2),
            "logic_score": round(logic_score.score, 2),
            "total_score": round(total_score, 2),
            "top_concept": hot_score.top_concept,
            "top_heat": hot_score.top_heat,
            "concepts": hot_score.concepts_text,
            "matched_keywords": logic_score.matched_keywords,
            "logic_reason": logic_score.reason,
        }, False
    except Exception as exc:
        return {
            "code": code,
            "name": name,
            "error": f"{type(exc).__name__}: {exc}",
        }, True


def _with_default_dates(config: SelectorConfig) -> SelectorConfig:
    if config.start_date and config.end_date:
        return config
    today = date.today()
    start = today - timedelta(days=220)
    return SelectorConfig(
        board_code=config.board_code,
        start_date=config.start_date or start.strftime("%Y%m%d"),
        end_date=config.end_date or today.strftime("%Y%m%d"),
        min_distance_pct=config.min_distance_pct,
        max_distance_pct=config.max_distance_pct,
        ma5_trend_window=config.ma5_trend_window,
        min_ma5_up_days=config.min_ma5_up_days,
        max_recent_drawdown_pct=config.max_recent_drawdown_pct,
        drawdown_window=config.drawdown_window,
        max_workers=config.max_workers,
        board_limit=config.board_limit,
    )
