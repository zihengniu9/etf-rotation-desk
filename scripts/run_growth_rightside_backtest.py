from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from low_buy_selector.growth_backtest import round_for_json
from low_buy_selector.growth_rightside import (
    LEVELS,
    PRIMARY_FACTOR,
    WEIGHT_SPECS,
    build_growth_rightside_panel,
    build_stock_effects,
    evaluate_growth_rightside_backtest,
    select_primary_signals,
)


def percent(value: object) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"


def metrics(result: dict[str, object]) -> dict[str, object]:
    top10 = result["top_n"]["10"]
    return {
        "periods": top10.get("periods", 0),
        "net": (top10.get("net") or {}).get("mean"),
        "excess": (top10.get("net_excess") or {}).get("mean"),
        "win": (top10.get("net") or {}).get("positive_rate"),
        "dd": top10.get("max_drawdown"),
        "ic": result["ic"].get("rank_ic_mean"),
        "mono": result["deciles"].get("monotonicity"),
    }


def build_report(summary: dict[str, object]) -> str:
    decision = summary["decision"]
    horizon = str(decision["selected_horizon"])
    lines = [
        "# 成长右侧统一因子回测",
        "",
        f"- 统一分：{summary['formula']['score']}。",
        f"- 个股门控：{summary['formula']['individual_gate']}。",
        f"- 市场门控：{summary['formula']['market_gate']}。",
        f"- 区间：{summary['window']['start']} 至 {summary['window']['end']}，{summary['window']['signal_dates']} 个按月信号日。",
        f"- 确认段：{summary['window']['confirmation_start']} 起，共 {summary['window']['confirmation_periods']} 期。",
        f"- 市场门控通过：{summary['universe']['market_gate_pass_dates']} 个信号日。",
        f"- 数据来源：{summary['source']}。",
        "- 交易成本：单边0.30%；收盘确认，下一交易日开盘进入。",
        "",
        "## 70/30 主公式分层效果",
        "",
        "| 阶段 | 口径 | 持有 | 有效期 | Top10净收益/期 | 净超额/期 | 胜率 | RankIC | 单调性 | 最大回撤 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    level_labels = {"ranking": "仅统一分", "structure": "右侧结构", "trigger": "个股触发", "execution": "市场门控实盘"}
    for window in ("development", "confirmation", "full"):
        for level in LEVELS:
            result = summary["results"][window][PRIMARY_FACTOR][level][horizon]
            item = metrics(result)
            lines.append(
                "| {window} | {level} | {h}日 | {periods} | {net} | {excess} | {win} | {ic} | {mono} | {dd} |".format(
                    window={"development": "开发段", "confirmation": "确认段", "full": "全区间"}[window],
                    level=level_labels[level],
                    h=horizon,
                    periods=item["periods"],
                    net=percent(item["net"]),
                    excess=percent(item["excess"]),
                    win=percent(item["win"]),
                    ic=percent(item["ic"]),
                    mono=f"{float(item['mono']):.3f}" if item["mono"] is not None else "—",
                    dd=percent(item["dd"]),
                )
            )
    lines.extend(
        [
            "",
            "## 权重敏感性（全区间、个股触发、选定持有期）",
            "",
            "| 公式 | 成长权重 | 趋势权重 | 有效期 | 净收益/期 | 净超额/期 | 胜率 | 最大回撤 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for factor, spec in WEIGHT_SPECS.items():
        item = metrics(summary["results"]["full"][factor]["trigger"][horizon])
        lines.append(
            "| {factor} | {gw:.0%} | {tw:.0%} | {periods} | {net} | {excess} | {win} | {dd} |".format(
                factor=factor,
                gw=float(spec["growth_weight"]),
                tw=float(spec["trend_weight"]),
                periods=item["periods"],
                net=percent(item["net"]),
                excess=percent(item["excess"]),
                win=percent(item["win"]),
                dd=percent(item["dd"]),
            )
        )
    lines.extend(
        [
            "",
            "## 决定",
            "",
            f"- 实验统一因子：`{PRIMARY_FACTOR}`，即 70% 财务综合 + 30% 趋势强度。",
            f"- 持有期：开发段选择 {decision['selected_horizon']} 个交易日。",
            f"- 结论：{decision['status']}。",
            f"- 当前继续使用：`{decision['active_factor']}`；是否替换：{decision['replace_existing_growth_factor']}。",
            f"- 严格实盘门控有效期：{decision['strict_execution'].get('periods', 0)} 期；样本是否够用：{decision['strict_execution_sample_ok']}。",
            "- 事后最优严格变体：{factor}、持有{horizon}日，净超额/期{excess}；该结果不作为选型依据。".format(
                factor=decision["posthoc_best_strict_variant"]["factor"],
                horizon=decision["posthoc_best_strict_variant"]["horizon"],
                excess=percent(decision["posthoc_best_strict_variant"].get("net_excess")),
            ),
            "- 评分与门控必须分离：门控失败时显示高分观察股，但不得产生新开仓。",
            "",
            "## 边界",
            "",
            "组合权重是在既有成长与趋势研究之后提出，历史区间并非全新未见样本。确认段只有6期，严格市场门控样本更少，不能据此宣称统计显著或直接实盘。历史资讯仍不入分。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest the unified growth plus right-side factor.")
    parser.add_argument("--growth-panel", default="outputs/growth_backtest_panel.csv.gz")
    parser.add_argument("--trend-history", default="outputs/trend_history.csv.gz")
    parser.add_argument("--output", default="outputs/growth_rightside_backtest.json")
    parser.add_argument("--panel-output", default="outputs/growth_rightside_panel.csv.gz")
    parser.add_argument("--signals-output", default="outputs/growth_rightside_signals.csv.gz")
    parser.add_argument("--stock-effects-output", default="outputs/growth_rightside_stock_effects.csv")
    parser.add_argument("--report-output", default="docs/growth_rightside_backtest_report.md")
    parser.add_argument("--confirmation-periods", type=int, default=6)
    parser.add_argument("--one-way-cost", type=float, default=0.003)
    args = parser.parse_args()

    growth = pd.read_csv(args.growth_panel, compression="infer", dtype={"code6": str})
    trend = pd.read_csv(args.trend_history, compression="infer", dtype={"code": str})
    panel = build_growth_rightside_panel(growth, trend)
    summary = evaluate_growth_rightside_backtest(
        panel,
        one_way_cost=args.one_way_cost,
        confirmation_periods=args.confirmation_periods,
    )
    summary = round_for_json(summary)
    horizon = int(summary["decision"]["selected_horizon"])
    signals = select_primary_signals(panel, horizon=horizon)
    effects = build_stock_effects(signals, horizon=horizon)
    summary["audit"] = {
        "strict_signals": int(len(signals)),
        "stocks_with_signals": int(signals["code6"].nunique()) if len(signals) else 0,
        "signals_file": args.signals_output,
        "stock_effects_file": args.stock_effects_output,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    panel_columns = [
        "date", "code6", "name", "growth_profile", "financial_score", "trend_score",
        *WEIGHT_SPECS.keys(), "growth_rightside_score", "eligible", "setup",
        "unified_rankable", "rightside_structure", "rightside_trigger", "rightside_tradeable",
        "market_trend_width", "market_positive_r20_ratio", "market_gate_pass",
        "fwd5", "fwd10", "fwd20", "mae5", "mae10", "mae20",
    ]
    Path(args.panel_output).parent.mkdir(parents=True, exist_ok=True)
    panel[[column for column in panel_columns if column in panel.columns]].to_csv(
        args.panel_output, index=False, compression="gzip", encoding="utf-8-sig"
    )
    signal_columns = [
        "date", "code6", "name", "growth_profile", PRIMARY_FACTOR, "financial_score", "trend_score",
        "setup", "market_trend_width", "market_positive_r20_ratio",
        f"fwd{horizon}", f"mae{horizon}",
    ]
    signals[[column for column in signal_columns if column in signals.columns]].to_csv(
        args.signals_output, index=False, compression="gzip", encoding="utf-8-sig"
    )
    effects.to_csv(args.stock_effects_output, index=False, encoding="utf-8-sig")
    Path(args.report_output).write_text(build_report(summary), encoding="utf-8")
    print(
        f"factor={PRIMARY_FACTOR} horizon={horizon} dates={summary['window']['signal_dates']} "
        f"market_gate_dates={summary['universe']['market_gate_pass_dates']} strict_signals={len(signals)}",
        flush=True,
    )
    for path in (args.output, args.panel_output, args.signals_output, args.stock_effects_output, args.report_output):
        print(f"wrote={path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
