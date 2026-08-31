# PandaAI Factor Research Report

- Candidates: 7; completed: 7; failed: 0
- Settings: 10-day rebalance, 10 groups, 0.30% one-way cost
- Multiple-testing reference: p < 0.0023
- `long_sharpe`, drawdown, and monthly win rate are direction-selected single-factor diagnostics, not official pool-level C metrics.
- Full CLI payloads are retained at the `raw_result` paths in the CSV.

| name | direction | rank_ic | ic_ir | long_excess_pct | turnover_pct | annual_cost_pct | net_excess_pct | long_sharpe | long_max_drawdown_pct | long_monthly_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-E16 | 1 | 0.0204 | 0.4069 | 1.87% | 0.63% | 0.10% | 1.77% | 6.1767 | 0.48% | 66.67% |
| F-E20 | 1 | -0.0114 | -0.0956 | -2.71% | 21.58% | 3.26% | -5.97% | 5.2116 | 1.72% | 66.67% |
| F-E18 | 1 | 0.0069 | 0.0111 | -6.88% | 0.59% | 0.09% | -6.97% | 7.8390 | 0.00% | 100.00% |
| F-E17 | 1 | 0.0066 | 0.0081 | -7.02% | 0.63% | 0.10% | -7.12% | 7.6975 | 0.00% | 100.00% |
| F-E21 | 1 | -0.0274 | -0.1937 | -3.47% | 32.89% | 4.97% | -8.44% | 4.8760 | 2.11% | 66.67% |
| F-E19 | 1 | -0.0478 | -0.1726 | -3.48% | 51.93% | 7.85% | -11.33% | 3.7002 | 2.73% | 66.67% |
| F-E22 | 1 | -0.0443 | -0.2435 | -5.85% | 42.61% | 6.44% | -12.29% | 4.7469 | 2.22% | 66.67% |
