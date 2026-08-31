# PandaAI Factor Research Report

- Candidates: 3; completed: 3; failed: 0
- Settings: 10-day rebalance, 10 groups, 0.30% one-way cost
- Multiple-testing reference: p < 0.0033
- `long_sharpe`, drawdown, and monthly win rate are direction-selected single-factor diagnostics, not official pool-level C metrics.
- Full CLI payloads are retained at the `raw_result` paths in the CSV.

| name | direction | rank_ic | ic_ir | long_excess_pct | turnover_pct | annual_cost_pct | net_excess_pct | long_sharpe | long_max_drawdown_pct | long_monthly_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-D08 | 1 | 0.0103 | 0.0071 | 1.90% | 7.20% | 1.09% | 0.81% | 0.8055 | 21.13% | 58.62% |
| F-D11 | 1 | 0.0110 | -0.0101 | -0.22% | 5.70% | 0.86% | -1.08% | 0.7758 | 19.65% | 58.62% |
| F-D15 | 1 | 0.0107 | -0.0183 | -0.83% | 5.25% | 0.79% | -1.62% | 0.7754 | 18.52% | 58.62% |
