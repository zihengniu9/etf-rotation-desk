# Low Buy Selector Design

## Goal

Build a minimal command-line selector that starts from the Tonghuashun hot stock board `883910`, filters stocks whose 5-day moving average is rising and whose latest close is close to that average, then ranks survivors by automatic topic heat and business-logic fit.

## Data Sources

- Board constituents: `https://q.10jqka.com.cn/thshy/detail/code/883910/page/{page}/`, parsed from the constituent table.
- Daily bars: `akshare.stock_zh_a_hist_tx`, using Tencent-style symbols such as `sz002167` and `sh600667`.
- Topic heat: `akshare.stock_hot_keyword_em`, using symbols such as `SZ002167`.
- Business description: `akshare.stock_zyjs_ths`, using plain six-digit stock codes.

## Selection Rules

- Technical pass: latest MA5 is greater than the previous MA5, the latest MA5 trend window is consistently rising, the latest close is within the configured MA5 distance range, and the latest close has not obviously pulled back from the recent high. Defaults: `-0.5%` to `+3%` from MA5, 5 MA5 points all rising, and no worse than `-5%` from the recent 10-day high.
- Topic score: use the highest available per-stock hot concept heat, normalized to `0-100`.
- Logic score: compare hot concept names and simplified tokens against main business, product name, and business scope text.
- Final rank: combine technical closeness, topic score, and logic score, then sort descending.

## Output

The CLI prints a compact table and optionally writes CSV. Each result includes stock code, name, close, MA5, MA5 distance, top concepts, score fields, and a short logic reason.

## Scope

This first version is a smoke-testable research tool, not trading advice or an automated trading system. It favors transparent heuristics and robust failure handling over perfect topic reasoning.
