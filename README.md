# AI Low-Buy Stock Selector

Minimal research CLI for screening Tonghuashun hot stocks (`883910`) whose MA5 is consistently rising, whose latest close is close to MA5, and whose recent pullback is not obvious.

Run tests:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

Run a live smoke test:

```powershell
python run_selector.py --board-code 883910 --top 20 --output outputs/picks.csv
```

This is a research filter, not investment advice.

## Trend engine

The trend engine is deliberately separated from the short-term sentiment
score. It reads point-in-time OHLCV CSV files from `data/trend_bars/`, where
each file is named by stock code and contains at least `date` and `close`;
`high`, `low`, and `amount`/`volume` are recommended. Optional stock labels
can be supplied in `data/trend_metadata.csv` with `code`, `name`, and `theme`.

Build the dashboard contract with:

```powershell
$env:PYTHONPATH='src'
python scripts/update_trend_data.py --bars-dir data/trend_bars
```

The output is `outputs/trend_engine.json`. The dashboard only treats the
canonical `trend-standard-v1` setup flags (`健康延续`, `缩量回踩`, and the
research-only `放量突破`) as trend triggers when this file is present, marked
as `universe.board=mainboard`, and backed by historical daily data. If the
full main-board dataset is unavailable, the factor page stays in an explicit
data-missing state instead of presenting a small sample as a market-wide
conclusion. The current standard-backtest winner is `健康延续`, held for 10
trading days; `缩量回踩` is the secondary setup and `放量突破` is not enabled
by default.

For routine data refreshes, use the installed 同花顺问财
`hithink-astock-selector` Skill as the primary source. The CSV command below
is retained for offline backtests or an explicitly labelled fallback only.

The dashboard entry point is `web/market_mode.html`: identify the current market
regime first, then route to the strategy page that matches it. The dashboard
routing is:

- `web/market_mode.html`: primary market-regime decision page and strategy router.
- `web/market_overview.html`: secondary reference page for cross-module context.
- `web/trend_engine.html`: trend factor subpage for all Shanghai/Shenzhen
  main-board stocks and stock-level profit-effect analysis.
- `web/growth_factor.html`: growth-quality candidates and historical tests.
- `web/dividend_factor.html`: valuation, dividend quality, and cash-flow
  coverage candidates.
- ETF, industry-mainline, short-term, trend, growth, and dividend pages remain
  independent modules under one market-regime router.

## Dashboard automation

All market-data collection runs on the local Windows machine because the
project requires an authenticated tun tunnel. GitHub-hosted runners only
validate and deploy the generated static files; they never collect Wencai
market data.

Before installing the tasks, configure these **user-level** environment
variables without writing the API key into the repository:

```powershell
[Environment]::SetEnvironmentVariable('IWENCAI_BASE_URL', 'https://openapi.iwencai.com', 'User')
[Environment]::SetEnvironmentVariable('IWENCAI_API_KEY', '<your-api-key>', 'User')
```

Start the tun proxy expected at `http://127.0.0.1:7897`, then install the
unified weekday tasks:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_dashboard_tasks.ps1
```

The installer creates three tasks:

- `09:28` morning short-term signal;
- `10:00`, `11:30`, and `14:00` intraday ETF/industry refreshes;
- `16:20` close review plus short-term, trend, dividend, ETF, and industry
  snapshots.

Every run verifies the tun endpoint through HTTPS first, makes one initial
network attempt, rebuilds dashboard status and the static bundle, commits only
generated `outputs/` changes, rebases on `origin/main`, and pushes to GitHub.
Run a complete update manually with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\update_dashboard_daily.ps1 -Mode Full -Push
```

For online deployment, enable GitHub Pages with the GitHub Actions source.
`.github/workflows/validate-dashboard.yml` checks the factor and dashboard
contracts, while `.github/workflows/deploy-pages.yml` publishes `index.html`,
`web/`, and the generated `outputs/` bundle whenever `main` changes.

## Growth-factor research

The first growth-factor engine is separate from the trend and short-term
engines. It uses the Shanghai/Shenzhen main board, excludes ST names, and
keeps a 5-billion-yuan market-cap floor. The research command consumes raw
point-in-time Wencai finance responses plus optional historical news responses:

```powershell
$env:PYTHONPATH='src'
python scripts/run_growth_factor_analysis.py
```

It writes `outputs/growth_factor_snapshot.json` and
`outputs/growth_factor_candidates.csv`. Financial growth and quality are the
primary score; historical news is only a 10% evidence layer. The current
snapshot is exploratory until disclosure-date history and forward-return
labels are connected for a genuine backtest.

Run the disclosure-date-aware growth backtest with:

```powershell
$env:PYTHONPATH='src'
python scripts/fetch_growth_backtest_data.py
python scripts/run_growth_backtest.py
```

The fetch command uses 同花顺问财 through the project-required HTTPS tun
tunnel. The backtest writes `outputs/growth_backtest.json`,
`outputs/growth_backtest_panel.csv.gz`, and
`docs/growth_backtest_report.md`. Reports become usable only after their
announcement date; same-day announcements are conservatively deferred because
the source does not expose an intraday timestamp. Historical news is not yet
part of the backtest score.

The experimental unified growth/right-side study can be reproduced with:

```powershell
$env:PYTHONPATH='src'
python scripts/run_growth_rightside_backtest.py
```

It evaluates `70% financial growth score + 30% canonical trend score` while
keeping the individual right-side trigger and market trend gate separate from
the stock rank. The current monthly-history result does **not** replace
`financial_score`: the confirmation window and strict market-gated execution
both failed. Outputs are written to `outputs/growth_rightside_backtest.json`,
the stock-level signal/effect CSV files, and
`docs/growth_rightside_backtest_report.md`.

## Dividend-quality factor

The dividend factor combines 30% valuation, 35% dividend quality, and 35%
cash-flow quality. Ranking blends the full universe with secondary-industry
peers, excludes financial companies, caps displayed candidates at two per
secondary industry, and flags dividend cuts, profit deterioration, unsafe
payout ratios, and weak cash conversion.

Refresh the latest point-in-time cross-section with:

```powershell
$env:PYTHONPATH='src'
python scripts/update_dividend_factor.py
```

The command writes `outputs/dividend_factor_snapshot.json`, its `file://`
JavaScript fallback, and `outputs/dividend_factor_candidates.csv`. The page
labels this as a current cross-section; it does not claim historical Alpha
until a disclosure-date-aware backtest is connected.
