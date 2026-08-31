# PandaAI Factor Research Report

- Candidates: 7; completed: 1; failed: 1
- Settings: 10-day rebalance, 10 groups, 0.30% one-way cost
- Multiple-testing reference: p < 0.0033
- `long_sharpe`, drawdown, and monthly win rate are direction-selected single-factor diagnostics, not official pool-level C metrics.
- Full CLI payloads are retained at the `raw_result` paths in the CSV.

| name | direction | rank_ic | ic_ir | long_excess_pct | turnover_pct | annual_cost_pct | net_excess_pct | long_sharpe | long_max_drawdown_pct | long_monthly_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-B08 | 1 | 0.0275 | 0.4574 | 13.46% | 0.41% | 0.06% | 13.40% | 6.1702 | 0.48% | 66.67% |

## Failures

- `F-B09`: run: 因子分析执行失败（无详细错误信息）
