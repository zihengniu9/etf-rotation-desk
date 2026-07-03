# ETF Theme Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an ETF selector that expands the pool to all available themes and keeps the largest ETF per theme by estimated fund size.

**Architecture:** Keep live data adapters separate from pure normalization, theme grouping, and rotation scoring. Generate a theme-representative pool first, then score that pool with the 20-day momentum logic from the referenced strategy.

**Tech Stack:** Python 3.13, pandas, requests, AKShare, stdlib unittest.

---

### File Map

- Create `src/low_buy_selector/etf_data_sources.py` for ETF list, scale, and daily bar adapters.
- Create `src/low_buy_selector/etf_pool.py` for theme extraction, size estimation, and representative selection.
- Create `src/low_buy_selector/etf_rotation.py` for 20-day return/volatility scoring.
- Create `src/low_buy_selector/etf_cli.py` and `run_etf_selector.py` for the command line.
- Create `tests/test_etf_pool.py` and `tests/test_etf_rotation.py`.

### Tasks

- [ ] Write failing tests for ETF theme normalization and largest-by-theme selection.
- [ ] Implement `etf_pool.py` pure functions until tests pass.
- [ ] Write failing tests for ETF momentum score and fallback money fund selection.
- [ ] Implement `etf_rotation.py` pure functions until tests pass.
- [ ] Implement live data adapters using Tonghuashun ETF list, SSE/SZSE shares, and Sina ETF daily bars.
- [ ] Add ETF CLI that writes `outputs/etf_theme_pool.csv`, `outputs/etf_rotation_rank.csv`, and `outputs/etf_rotation_pick.csv`.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run live smoke test with `python run_etf_selector.py --output-dir outputs`.
