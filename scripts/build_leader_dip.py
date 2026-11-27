"""生成“短线观察 · 龙头低吸”看板数据。

读取本地缓存的 AKShare 日线和东方财富人气榜（默认 data/leader_dip/），计算：
  - 下一交易日信号（热度前50 · 高度≥50%）
  - 全区间、前半年、后半年回测和净值曲线
  - 仓位方案对比、策略变体对比
  - 回测交易明细和按个股汇总的历史赚钱效应
输出 outputs/leader_dip.json、outputs/leader_dip.js（file:// 打开时的兜底）和
outputs/leader_dip_trades.csv。

用法（项目根目录）：
  $env:PYTHONPATH='src'            # Windows PowerShell
  export PYTHONPATH=src            # macOS / Linux
  python scripts/build_leader_dip.py --data-dir data/leader_dip
  python scripts/build_leader_dip.py --update     # 先联网增量更新数据再生成

数据源不是同花顺问财，页面会明确标注来源和覆盖范围。仅供研究复盘，不构成投资建议。
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from low_buy_selector import leader_dip as ld  # noqa: E402

RUN_TZ = ZoneInfo("Asia/Shanghai")
VERSION = "leader-dip-v2"
MIN_HISTORY = 60  # 有效历史：至少 60 个交易日

PARAM_SETS = {
    "main": {"label": "龙头低吸", "desc": "热度前50 · 高度≥50%", "overrides": {}},
}

SIZING = [
    ("分散：前5只，单票1成，上限3成", {}),
    ("龙一龙二：各3成，上限6成", {"leader_topk": 2, "pos_size": 0.3, "max_pos": 0.6}),
    ("龙一龙二：各半仓，最多满仓", {"leader_topk": 2, "pos_size": 0.5, "max_pos": 1.0}),
    ("只做龙一：半仓", {"leader_topk": 1, "pos_size": 0.5, "max_pos": 0.5}),
]

VARIANTS = [
    ("基准：热度前50 + 高度≥50%", {}),
    ("旧参数：热度前30 + 高度≥20%", {"hot_topn": 30, "height_min": 0.20}),
    ("热度前30", {"hot_topn": 30}),
    ("热度前100", {"hot_topn": 100}),
    ("高度≥30%", {"height_min": 0.30}),
    ("高度≥80%", {"height_min": 0.80}),
    ("不等冰点", {"use_ice": False}),
    ("开盘直接买", {"buy_mode": "open"}),
    ("挂 -1%", {"dip": -0.01}),
    ("挂 -5%", {"dip": -0.05}),
    ("退潮过滤（前2天跌停>涨停不开）", {"retreat_days": 2}),
    ("只吸冰点日收红的", {"min_prev_pct": 0.0}),
    ("热度在升温", {"hot_rising": True}),
    ("卖法：先卖半 + 破前日低点走", {"exit_mode": "trail"}),
    ("卖法：最多拿5天", {"max_hold": 5}),
    ("异动回避（10日≥90% / 30日≥190%）", {"halt10_cap": 90, "halt30_cap": 190}),
]


def clean(value):
    """把 numpy / NaN 转成 JSON 友好的值。"""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    return value


def periods_for(dates: pd.DatetimeIndex, start: str) -> dict:
    """全区间 + 按交易日数对半切分的前后两段（用于样本外检验）。"""
    window = dates[dates >= pd.Timestamp(start)]
    if len(window) < 2:
        raise RuntimeError("回测区间内交易日不足")
    mid = window[len(window) // 2]
    prev = window[window < mid][-1]
    return {
        "全区间": (window[0], window[-1]),
        "前半段": (window[0], prev),
        "后半段": (mid, window[-1]),
    }


def slice_upto(obj: dict, end: pd.Timestamp) -> dict:
    out = {}
    for key, value in obj.items():
        out[key] = value.loc[:end] if isinstance(value, (pd.DataFrame, pd.Series)) else value
    return out


class Runner:
    def __init__(self, panel: dict, names: dict, hot, base: ld.Config):
        self.panel, self.names, self.hot, self.base = panel, names, hot, base
        self.cache: dict = {}

    def cfg(self, **overrides) -> ld.Config:
        cfg = copy.deepcopy(self.base)
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def signals(self, cfg: ld.Config) -> dict:
        key = (cfg.hot_topn, cfg.height_min, cfg.leader_topk, cfg.leader_mode)
        if key not in self.cache:
            self.cache[key] = ld.build_signals(self.panel, self.names, cfg, self.hot)
        return self.cache[key]

    def backtest(self, cfg: ld.Config, start: pd.Timestamp, end: pd.Timestamp):
        c2 = copy.deepcopy(cfg)
        c2.start = start.strftime("%Y%m%d")
        return ld.run_backtest(slice_upto(self.panel, end), self.names,
                               slice_upto(self.signals(cfg), end), c2)


def summarize(eq: pd.DataFrame, tr: pd.DataFrame, cfg: ld.Config) -> dict:
    nav = eq["总资产"] / cfg.init_cash
    total = float(nav.iloc[-1] - 1)
    days = len(nav)
    out = {
        "start": eq.index[0], "end": eq.index[-1], "trading_days": days,
        "total_return_pct": round(total * 100, 2),
        "annual_return_pct": round(((1 + total) ** (252 / max(days, 1)) - 1) * 100, 2),
        "max_drawdown_pct": round(float((nav / nav.cummax() - 1).min()) * 100, 2),
        "avg_position_pct": round(float(eq["仓位"].mean()) * 100, 1),
        "trades": int(len(tr)),
    }
    if len(tr):
        win = tr["收益率%"] > 0
        top3 = tr["盈亏"].sort_values(ascending=False).head(3).sum()
        out.update({
            "win_rate_pct": round(float(win.mean()) * 100, 1),
            "avg_trade_pct": round(float(tr["收益率%"].mean()), 2),
            "median_trade_pct": round(float(tr["收益率%"].median()), 2),
            "avg_win_pct": round(float(tr.loc[win, "收益率%"].mean()), 2) if win.any() else None,
            "avg_loss_pct": round(float(tr.loc[~win, "收益率%"].mean()), 2) if (~win).any() else None,
            "avg_hold_days": round(float(tr["持有天数"].mean()), 2),
            "pnl_ex_top3": round(float(tr["盈亏"].sum() - top3), 0),
        })
    return out


def trade_rows(tr: pd.DataFrame) -> list:
    fly_col = next((c for c in tr.columns if c.startswith("卖后")), None)
    rows = []
    for _, r in tr.iterrows():
        rows.append({
            "code": r["代码"], "name": r["名称"], "buy_date": str(r["买入日"]), "sell_date": str(r["卖出日"]),
            "buy_price": r["买入价"], "exit_price": r["清仓价"], "hold_days": int(r["持有天数"]),
            "hot_rank": None if r["买入前热度排名"] in ("", None) or pd.isna(r["买入前热度排名"]) else int(r["买入前热度排名"]),
            "height_pct": r["买入前高度%"], "return_pct": r["收益率%"], "pnl": r["盈亏"],
            "exit_reason": r["卖出原因"],
            "after_exit_max_pct": None if fly_col is None else r[fly_col],
        })
    return rows


def stock_effects(tr: pd.DataFrame) -> list:
    if not len(tr):
        return []
    g = tr.groupby(["代码", "名称"])
    out = []
    for (code, name), grp in g:
        r = grp["收益率%"]
        out.append({
            "code": code, "name": name, "signals": int(len(grp)),
            "win_rate_pct": round(float((r > 0).mean()) * 100, 1),
            "avg_return_pct": round(float(r.mean()), 2), "median_return_pct": round(float(r.median()), 2),
            "best_pct": round(float(r.max()), 2), "worst_pct": round(float(r.min()), 2),
            "pnl": round(float(grp["盈亏"].sum()), 0),
            "last_buy": str(grp["买入日"].max()),
        })
    return sorted(out, key=lambda x: (-x["signals"], -x["pnl"]))


def coverage(panel: dict, hot, cfg: ld.Config, data_dir: Path) -> dict:
    close = panel["close"]
    last = close.index[-1]
    uni = pd.read_csv(data_dir / "_universe.csv", dtype={"code": str})
    hist = close.notna().sum()
    hot_cover = 0 if hot is None else int(hot.loc[last].notna().sum())
    hot_start = None
    if hot is not None:
        any_hot = hot.notna().any(axis=1)
        hot_start = any_hot[any_hot].index[0] if any_hot.any() else None
    return {
        "universe": "沪深主板（000/001/002/003/600/601/603/605），剔除 ST/退市",
        "universe_note": "股票名单为当前名单，已退市股票不在其中，回测存在幸存者偏差",
        "scanned": int(len(uni)),
        "with_daily_file": int(close.shape[1]),
        "valid_history": int((hist >= MIN_HISTORY).sum()),
        "min_history_days": MIN_HISTORY,
        "updated_today": int(close.loc[last].notna().sum()),
        "daily_first_date": close.index[0],
        "data_as_of": last,
        "hot_stocks_cached": 0 if hot is None else int(hot.notna().any().sum()),
        "hot_ranked_on_last_day": hot_cover,
        "hot_history_start": hot_start,
        "sources": {
            "daily": "AKShare stock_zh_a_hist_tx（腾讯证券日线，前复权；失败时退回东方财富）",
            "popularity": "AKShare stock_hot_rank_detail_em（东方财富股吧个股人气榜，日度排名）",
            "universe": "AKShare stock_info_a_code_name（上交所/深交所官网名单）",
            "is_wencai": False,
        },
    }


def build(data_dir: Path, out_dir: Path, start: str) -> dict:
    base = ld.Config()
    base.data_dir = str(data_dir)
    base.start = start
    panel, names = ld.load_panel(base)
    hot = ld.load_hot(base, panel["close"])
    if hot is None:
        raise RuntimeError(f"{data_dir}/hot 下没有人气榜缓存：龙头定义依赖热度，不能在缺数据时出结论")
    runner = Runner(panel, names, hot, base)
    per = periods_for(panel["close"].index, start)

    strategies = {}
    trades_out = None
    for key, spec in PARAM_SETS.items():
        cfg = runner.cfg(**spec["overrides"])
        sig = runner.signals(cfg)
        result = {"label": spec["label"], "desc": spec["desc"],
                  "signal": ld.signal_payload(panel, names, hot, sig, cfg), "periods": {}}
        for pname, (s, e) in per.items():
            eq, tr = runner.backtest(cfg, s, e)
            result["periods"][pname] = summarize(eq, tr, cfg)
            if pname == "全区间":
                nav = (eq["总资产"] / cfg.init_cash).round(4)
                result["nav"] = [[d.date().isoformat(), float(v)] for d, v in nav.items()]
                result["position"] = [[d.date().isoformat(), round(float(v), 3)] for d, v in eq["仓位"].items()]
                result["trades"] = trade_rows(tr)
                result["stock_effects"] = stock_effects(tr)
                reasons = tr.assign(r=tr["卖出原因"].str.replace("（此前已卖一半）", "", regex=False)) \
                    .groupby("r")["收益率%"].agg(["count", "mean"]) if len(tr) else pd.DataFrame()
                result["exit_reasons"] = [{"reason": k, "count": int(v["count"]), "avg_return_pct": round(float(v["mean"]), 2)}
                                          for k, v in reasons.iterrows()]
                if key == "main":
                    trades_out = tr
        strategies[key] = result

    def table(rows_spec, base_over):
        rows = []
        for label, over in rows_spec:
            cfg = runner.cfg(**{**base_over, **over})
            row = {"label": label, "overrides": over}
            for pname, (s, e) in per.items():
                eq, tr = runner.backtest(cfg, s, e)
                sm = summarize(eq, tr, cfg)
                row[pname] = {k: sm.get(k) for k in ("total_return_pct", "max_drawdown_pct", "trades",
                                                     "win_rate_pct", "avg_trade_pct", "pnl_ex_top3")}
            rows.append(row)
        return rows

    sizing = {key: table(SIZING, spec["overrides"]) for key, spec in PARAM_SETS.items()}
    variants = table(VARIANTS, {})
    base_row = variants[0]
    for row in variants:
        better = [row[p]["total_return_pct"] > base_row[p]["total_return_pct"] for p in ("前半段", "后半段")]
        row["beats_baseline_both_halves"] = all(better)

    emo = runner.signals(runner.cfg())["emotion"].loc[per["全区间"][0]:]
    emotion = [{"date": d.date().isoformat(), "limit_up": int(r["涨停家数"]), "limit_down": int(r["跌停家数"]),
                "max_boards": int(r["最高连板"]),
                "premium_pct": None if pd.isna(r["昨日涨停溢价%"]) else round(float(r["昨日涨停溢价%"]), 2),
                "ice": bool(r["冰点"]), "can_open": bool(r["可开仓"])} for d, r in emo.iterrows()]

    cov = coverage(panel, hot, base, data_dir)
    payload = {
        "version": VERSION,
        "generated_at": datetime.now(RUN_TZ).isoformat(timespec="seconds"),
        "data_as_of": cov["data_as_of"],
        "for_date_note": "信号基于 data_as_of 收盘，用于下一个交易日",
        "status": "ok",
        "coverage": cov,
        "periods": {k: [s.date().isoformat(), e.date().isoformat()] for k, (s, e) in per.items()},
        "strategies": strategies,
        "sizing": sizing,
        "variants": variants,
        "emotion": emotion,
        "assumptions": [
            "信号只用前一交易日及以前的数据；买入为当日盘中触及挂单价成交（成交价取开盘价与挂单价的较低者）",
            "卖出按收盘价近似；跌停当日视为卖不出，停牌日不交易",
            "佣金万2.5双边、印花税万5（卖出）、滑点千1双边；闲置资金按年化1.5%逆回购计息",
            "人气榜只能回溯约一年，回测区间以热度数据起点为准；用的是全天汇总排名，不是竞价前热度",
            "股票池为当前沪深主板名单，存在幸存者偏差",
            "策略变体是在同一段数据上比较，存在过拟合风险；前后两段都优于基准才视为有效改进",
        ],
        "disclaimer": "仅供研究复盘，不构成投资建议。",
    }
    payload = clean(payload)

    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (out_dir / "leader_dip.json").write_text(text, encoding="utf-8")
    (out_dir / "leader_dip.js").write_text(f"window.LEADER_DIP_DATA = {text};\n", encoding="utf-8")
    if trades_out is not None:
        trades_out.to_csv(out_dir / "leader_dip_trades.csv", index=False, encoding="utf-8-sig")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="生成龙头低吸看板数据")
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "leader_dip"))
    ap.add_argument("--out-dir", default=str(ROOT / "outputs"))
    ap.add_argument("--start", default="20251201", help="回测起点（人气榜大约只能回溯一年）")
    ap.add_argument("--update", action="store_true", help="先联网增量更新日线和人气榜")
    a = ap.parse_args()
    data_dir = Path(a.data_dir)
    if a.update:
        cfg = ld.Config()
        cfg.data_dir = str(data_dir)
        cfg.start = a.start
        ld.update_data(cfg)
    payload = build(data_dir, Path(a.out_dir), a.start)
    cov = payload["coverage"]
    print(f"数据日期 {payload['data_as_of']}；扫描 {cov['scanned']} 只，有效历史 {cov['valid_history']} 只，"
          f"当日人气榜覆盖 {cov['hot_ranked_on_last_day']} 只")
    for key, st in payload["strategies"].items():
        p = st["periods"]["全区间"]
        print(f"{st['label']}：全区间 {p['total_return_pct']:+.2f}%，回撤 {p['max_drawdown_pct']:.2f}%，"
              f"{p['trades']} 笔；下一交易日{'可开仓' if st['signal']['can_open_next_day'] else '不开仓'}")
    print(f"已写入 {a.out_dir}/leader_dip.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
