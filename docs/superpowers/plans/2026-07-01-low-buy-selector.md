# Low Buy Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a runnable CLI that screens Tonghuashun hot stocks for rising MA5 low-buy candidates.

**Architecture:** Keep pure calculations in small modules so they can be tested without network access. Put live data adapters behind thin functions and keep CLI orchestration separate.

**Tech Stack:** Python 3.13, pandas, requests, AKShare, stdlib unittest.

---

### File Map

- `src/low_buy_selector/indicators.py`: moving-average calculations and technical pass/fail logic.
- `src/low_buy_selector/scoring.py`: topic heat normalization and business-logic scoring.
- `src/low_buy_selector/ths.py`: Tonghuashun board page parsing and pagination.
- `src/low_buy_selector/data_sources.py`: AKShare daily bars, hot keywords, and business descriptions.
- `src/low_buy_selector/selector.py`: orchestration for one stock and for the full board.
- `src/low_buy_selector/cli.py`: command-line interface and CSV output.
- `tests/`: unittest coverage for pure logic and HTML parsing.

### Tasks

- [ ] Write failing tests for MA5 uptrend and distance filtering.
- [ ] Implement `indicators.py` and rerun indicator tests.
- [ ] Write failing tests for topic and legitimacy scoring.
- [ ] Implement `scoring.py` and rerun scoring tests.
- [ ] Write failing tests for Tonghuashun table parsing.
- [ ] Implement `ths.py` and rerun parser tests.
- [ ] Implement live data adapters and selector orchestration.
- [ ] Add CLI entry point.
- [ ] Run all unit tests with `python -m unittest discover -s tests -v`.
- [ ] Run a real-data smoke test against board `883910`.
