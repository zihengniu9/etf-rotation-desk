# PandaAI Factor Research Report

- Candidates: 15; completed: 8; failed: 7
- Settings: 10-day rebalance, 10 groups, 0.30% one-way cost
- Multiple-testing reference: p < 0.0033
- `long_sharpe`, drawdown, and monthly win rate are direction-selected single-factor diagnostics, not official pool-level C metrics.
- Full CLI payloads are retained at the `raw_result` paths in the CSV.

| name | direction | rank_ic | ic_ir | long_excess_pct | turnover_pct | annual_cost_pct | net_excess_pct | long_sharpe | long_max_drawdown_pct | long_monthly_win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-A10 | 1 | 0.0367 | 0.3818 | 1.67% | 0.88% | 0.13% | 1.54% | 3.9538 | 3.03% | 66.67% |
| F-A06 | 1 | -0.0462 | -0.2852 | 1.51% | 70.03% | 10.59% | -9.08% | 4.5907 | 1.94% | 66.67% |
| F-A07 | 1 | -0.1032 | -0.3090 | -2.62% | 57.82% | 8.74% | -11.36% | 4.3788 | 1.41% | 66.67% |
| F-A01 | 1 | -0.0643 | -0.2318 | -10.12% | 67.74% | 10.24% | -20.36% | 3.2397 | 3.21% | 66.67% |
| F-A02 | 1 | -0.1062 | -0.2425 | -16.53% | 50.96% | 7.71% | -24.24% | 2.2067 | 5.56% | 66.67% |
| F-A03 | 1 | -0.0372 | -0.2159 | -18.55% | 60.73% | 9.18% | -27.73% | 3.6410 | 1.73% | 66.67% |
| F-A04 | 1 | -0.0410 | -0.4282 | -16.14% | 89.91% | 13.59% | -29.73% | 5.1318 | 0.92% | 66.67% |
| F-A05 | 1 | -0.0717 | -0.5805 | -21.54% | 82.44% | 12.46% | -34.00% | 4.8309 | 1.39% | 66.67% |

## Failures

- `F-A08`: run: 因子分析执行失败（无详细错误信息）
- `F-A09`: run: 因子分析执行失败（无详细错误信息）
- `F-A11`: run: 因子分析执行失败（无详细错误信息）
- `F-A12`: run: 因子分析执行失败（无详细错误信息）
- `F-A13`: run: 因子分析执行失败（无详细错误信息）
- `F-A14`: run: 因子分析执行失败（无详细错误信息）
- `F-A15`: run: 因子分析执行失败（无详细错误信息）
