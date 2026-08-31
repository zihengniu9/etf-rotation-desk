# PandaAI Factor Research Report

- Candidates: 6; completed: 6; failed: 0
- Settings: 10-day rebalance, 10 groups, 0.30% one-way cost
- Multiple-testing reference: p < 0.0033
- `long_sharpe`, drawdown, and monthly win rate are direction-selected single-factor diagnostics, not official pool-level C metrics.
- Full CLI payloads are retained at the `raw_result` paths in the CSV.

| name | direction | rank_ic | ic_ir | long_excess_pct | turnover_pct | annual_cost_pct | net_excess_pct | long_sharpe | long_max_drawdown_pct | long_monthly_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-C11 | 1 | 0.0157 | 0.2027 | -1.19% | 0.33% | 0.05% | -1.24% | 5.6743 | 0.92% | 66.67% |
| F-C15 | 1 | 0.0069 | 0.0279 | -5.19% | 0.31% | 0.05% | -5.24% | 5.5970 | 0.86% | 66.67% |
| F-C12 | 1 | 0.0079 | 0.0456 | -5.77% | 0.51% | 0.08% | -5.85% | 6.4317 | 0.12% | 66.67% |
| F-C13 | 1 | 0.0033 | -0.0188 | -8.71% | 0.42% | 0.06% | -8.77% | 6.2602 | 0.00% | 100.00% |
| F-C14 | 1 | -0.0004 | -0.0842 | -9.22% | 0.44% | 0.07% | -9.29% | 5.9815 | 0.44% | 66.67% |
| F-C09 | 1 | -0.0285 | -0.3262 | -24.25% | 0.34% | 0.05% | -24.30% | 6.7293 | 0.00% | 100.00% |
