from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from low_buy_selector.growth_backtest import (
    build_point_in_time_panel,
    combine_report_snapshots,
    evaluate_growth_backtest,
    round_for_json,
)


def load_reports(directory: Path) -> dict[str, pd.DataFrame]:
    snapshots: dict[str, pd.DataFrame] = {}
    for path in sorted(directory.glob("finance_*.json")):
        period = path.stem.rsplit("_", 1)[-1]
        if len(period) != 8 or not period.isdigit():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshots[period] = pd.DataFrame(payload.get("datas") or [])
    return snapshots


def percent(value: object) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"


def build_report(summary: dict[str, object]) -> str:
    window = summary["window"]
    universe = summary["universe"]
    lines = [
        "# 成长股因子点时回测",
        "",
        f"- 数据源：{summary['source']}。",
        f"- 区间：{window['start']} 至 {window['end']}，共 {window['signal_dates']} 个按月信号日。",
        f"- 样本外：{window['out_of_sample_start']} 起，共 {window['out_of_sample_periods']} 期。",
        f"- 股票池：{universe['name']}；有效面板 {universe['financial_valid_rows']} 行，{universe['unique_stocks']} 只股票。",
        "- 执行：收盘确认、下一交易日开盘买入、持有 5/10/20 日；单边成本 0.30%。",
        "- 防未来：只有公告日期早于信号日的财报可用；同日公告因缺少时分秒而保守延后。",
        "- 历史资讯未纳入本轮分数，因为尚未具备全市场、逐时点、可复现的覆盖。",
        "",
        "## 正式 v1 样本外 Top10 结果",
        "",
        "| 因子 | 持有 | 月度RankIC | Top10净收益/期 | Top10净超额/期 | 胜率 | 期数 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    oos = summary["results"]["out_of_sample"]
    labels = {"growth_core": "成长核心", "quality_score": "成长质量", "financial_score": "财务综合"}
    for factor in ("growth_core", "quality_score", "financial_score"):
        horizons = oos[factor]
        for horizon, result in horizons.items():
            top10 = result["top_n"]["10"]
            lines.append(
                "| {factor} | {horizon}日 | {ic} | {net} | {excess} | {win} | {periods} |".format(
                    factor=labels.get(factor, factor),
                    horizon=horizon,
                    ic=percent(result["ic"]["rank_ic_mean"]),
                    net=percent((top10.get("net") or {}).get("mean")),
                    excess=percent((top10.get("net_excess") or {}).get("mean")),
                    win=percent((top10.get("net") or {}).get("positive_rate")),
                    periods=top10.get("periods", 0),
                )
            )
    decision = summary["decision"]
    baseline = decision.get("formal_baseline") or {}
    exploratory = decision.get("exploratory_candidate") or {}
    lines.extend(
        [
            "",
            "## 回测决定",
            "",
            f"- 正式 v1：{baseline.get('factor', '无通过项')}，{decision['formal_status']}。",
            f"- 探索 v2：{exploratory.get('factor', '无通过项')}，{decision['exploratory_status']}。",
            f"- 执行候选：{decision['execution_candidate']}。",
            "",
            "## 探索 v2（20日 Top10）",
            "",
            "| 因子 | 样本内净超额/期 | 样本外净超额/期 | 样本外RankIC | 单调性 | 胜率 | 最大回撤 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for factor in (
        "double_high_min", "growth_quality_geom", "quality_heavy", "balanced_gq",
        "top30_growth_quality", "persistent_quality", "growth_type_quality",
    ):
        ins = summary["results"]["in_sample"][factor]["20"]["top_n"]["10"]
        result = summary["results"]["out_of_sample"][factor]["20"]
        top10 = result["top_n"]["10"]
        lines.append(
            "| {factor} | {ins} | {oos} | {ic} | {mono} | {win} | {dd} |".format(
                factor=factor,
                ins=percent((ins.get("net_excess") or {}).get("mean")),
                oos=percent((top10.get("net_excess") or {}).get("mean")),
                ic=percent(result["ic"].get("rank_ic_mean")),
                mono=f"{float(result['deciles'].get('monotonicity')):.3f}" if result["deciles"].get("monotonicity") is not None else "—",
                win=percent((top10.get("net") or {}).get("positive_rate")),
                dd=percent(top10.get("max_drawdown")),
            )
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "回测结果首先用于决定成长核心、成长质量和财务综合哪一套更值得保留，以及 5/10/20 日哪个持有期更匹配。",
            "月末样本数量仍有限。正式 v1 因子可读取预留样本外；探索 v2 已使用该区间进行选择，不能再把它称为独立样本外。",
            "本报告不把事件复利当作可直接复制的实盘净值，也不构成投资建议。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the point-in-time growth factor backtest.")
    parser.add_argument("--finance-dir", default="temp_download/growth_history")
    parser.add_argument("--market-history", default="outputs/trend_history.csv.gz")
    parser.add_argument("--output", default="outputs/growth_backtest.json")
    parser.add_argument("--panel-output", default="outputs/growth_backtest_panel.csv.gz")
    parser.add_argument("--report-output", default="docs/growth_backtest_report.md")
    parser.add_argument("--min-amount", type=float, default=50_000_000)
    parser.add_argument("--one-way-cost", type=float, default=0.003)
    parser.add_argument("--oos-periods", type=int, default=12)
    args = parser.parse_args()

    snapshots = load_reports(Path(args.finance_dir))
    if len(snapshots) < 3:
        raise RuntimeError(f"at least three report snapshots are required; found {len(snapshots)}")
    reports = combine_report_snapshots(snapshots)
    market = pd.read_csv(Path(args.market_history), compression="infer", dtype={"code": str})
    panel = build_point_in_time_panel(reports, market, min_amount=args.min_amount)
    if panel.empty:
        raise RuntimeError("point-in-time panel is empty")
    summary = evaluate_growth_backtest(panel, one_way_cost=args.one_way_cost, oos_periods=args.oos_periods)
    summary["data_quality"] = {
        "report_files": len(snapshots),
        "report_rows": int(len(reports)),
        "market_rows": int(len(market)),
        "panel_signal_dates": int(panel["date"].nunique()),
    }
    summary = round_for_json(summary)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    panel_output = Path(args.panel_output)
    panel_output.parent.mkdir(parents=True, exist_ok=True)
    audit_columns = [
        "date", "code6", "name", "theme", "amount", "entry",
        "fwd5", "fwd10", "fwd20", "mae5", "mae10", "mae20",
        "label_valid5", "label_valid10", "label_valid20",
        "current_report_period", "current_announce_date",
        "prev_report_period", "prev_announce_date", "prev2_report_period", "prev2_announce_date",
        "current_revenue_growth", "current_profit_growth", "prev_revenue_growth", "prev_profit_growth",
        "prev2_revenue_growth", "prev2_profit_growth", "revenue_acceleration", "profit_acceleration",
        "current_cash_flow", "current_revenue", "current_net_profit", "cash_margin", "cash_to_profit",
        "current_roe", "current_net_margin", "current_debt_ratio", "persistence_score",
        "growth_core", "quality_score", "balance_score", "financial_score",
        "double_high_min", "growth_quality_geom", "quality_heavy", "balanced_gq",
        "top30_growth_quality", "persistent_quality", "growth_type_quality",
        "growth_profile", "financial_valid", "report_history_complete",
    ]
    panel[[column for column in audit_columns if column in panel.columns]].to_csv(
        panel_output, index=False, compression="gzip", encoding="utf-8-sig"
    )
    report_output = Path(args.report_output)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(build_report(summary), encoding="utf-8")
    print(
        f"dates={summary['window']['signal_dates']} stocks={summary['universe']['unique_stocks']} "
        f"valid_rows={summary['universe']['financial_valid_rows']}",
        flush=True,
    )
    print(f"wrote={output}", flush=True)
    print(f"wrote={panel_output}", flush=True)
    print(f"wrote={report_output}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
