# PandaAI Factor Research Report

- Candidates: 2; completed: 2; failed: 0
- Settings: 10-day rebalance, 10 groups, 0.30% one-way cost
- Multiple-testing reference: p < 0.0033
- `long_sharpe`, drawdown, and monthly win rate are direction-selected single-factor diagnostics, not official pool-level C metrics.
- Full CLI payloads are retained at the `raw_result` paths in the CSV.

| name | direction | rank_ic | ic_ir | long_excess_pct | turnover_pct | annual_cost_pct | net_excess_pct | long_sharpe | long_max_drawdown_pct | long_monthly_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-D10 | 1 | 0.0040 | 0.0399 | -1.40% | 2.03% | 0.31% | -1.71% | 0.5135 | 35.68% | 55.17% |
| F-D07 | 1 | -0.0562 | -0.2353 | -10.66% | 62.47% | 9.45% | -20.11% | 0.3251 | 34.95% | 55.17% |
