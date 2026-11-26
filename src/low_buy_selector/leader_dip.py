"""
龙头低吸（短线观察）：情绪冰点 + 热度/高度龙头低吸 —— 日线因子、信号与回测

数据来源：AKShare（腾讯日线前复权；东方财富个股人气榜）。这是本项目中明确标注的
非问财数据源，由用户在 Mac 上收盘后运行并发布；页面必须展示该来源。

规则（默认参数）：
  1. 节点：昨日涨停股今日平均收跌，且涨停家数处于近 60 日最低 25%（或跌停家数不少于涨停家数）
     视为冰点；冰点后 3 个交易日内才允许开仓（信号只用前一交易日及以前的数据）。
  2. 龙头：前一交易日人气榜排名在前 50 且“高度”（收盘 / 近 20 日最低价 - 1）≥ 50%，
     按“热度排名 + 高度排名”综合排序；旧版连板评分保留为 leader_mode="boards"。
  3. 买点：只做低吸，挂前收 -3% 的限价单，当日最低价触及才成交；单票 1 成，总仓位上限 3 成。
  4. 卖点：浮盈 8% 先卖一半、15% 清仓、曾浮盈 3% 回到成本离场、最多持有 3 天、-5% 止损；
     按收盘价成交，跌停当日卖不出，停牌日不交易。
另外统计“卖飞”：清仓后 10 个交易日内的最高价比卖出价高多少。

用法（在项目根目录，PYTHONPATH=src）：
  python -m low_buy_selector.leader_dip --download          # 第一次：下载并缓存日线和人气榜
  python -m low_buy_selector.leader_dip --update --signal   # 每日：增量更新并输出下一交易日信号
  python scripts/build_leader_dip.py                        # 生成看板数据 outputs/leader_dip.json
  python -m low_buy_selector.leader_dip --demo              # 不联网，用模拟数据检查代码能跑

所有阈值都在下面的 Config 里，也可以用命令行参数覆盖（见 --help）。
仅用于研究和复盘，不构成投资建议；程序不会下单。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ───────────────────────────── 参数 ─────────────────────────────
@dataclass
class Config:
    # 数据
    start: str = "20251201"           # 热度数据大约只能回溯一年
    end: str = ""                     # 留空 = 到今天
    data_dir: str = "data/leader_dip"
    out_dir: str = "outputs/leader_dip_bt"

    # 1) 节点（冰点）
    limit_pct: float = 9.8            # 主板涨跌停判定阈值（%）
    ice_lookback: int = 60            # 涨停家数分位数的回看天数
    ice_quantile: float = 0.25        # 涨停家数处于近 60 日最低 25% 视为低迷
    ice_premium: float = 0.0          # 昨日涨停股今日平均涨幅 < 该值（%）视为亏钱效应
    ice_window: int = 3               # 冰点后几个交易日内允许开仓

    # 2) 龙头池
    leader_window: int = 10           # 统计连板/涨停次数的窗口
    leader_min_zt: int = 2            # 窗口内至少涨停几次
    leader_topk: int = 5              # 取前几只
    name_keywords: list = field(default_factory=list)   # 可选：只做名字含这些字的，如 ["阳"]

    # 2a) 龙头定义：hot_height = 热度 + 高度（默认）；boards = 旧版按连板评分
    leader_mode: str = "hot_height"
    height_window: int = 20           # 高度 = 收盘价 / 近 20 日最低价 - 1（这一波涨了多少）
    height_min: float = 0.50          # 高度至少 50% 才算有空间
    height_pool: int = 50             # 下载热度时：每天高度前 50 名的并集

    # 2b) 热度（东方财富人气榜排名，数字越小越热）
    use_hot: bool = True              # 有热度数据就用
    hot_topn: int = 50                # 前一交易日人气排名在前 N 才算有热度
    hot_strict: bool = False          # True = 没有热度数据的日期一律不开仓；False = 那些日期不做热度过滤

    # 3) 买点与仓位
    dip: float = -0.03                # 挂单价 = 昨收 * (1 + dip)，例如 -0.05 就是“挂 -5”
    pos_size: float = 0.10            # 单票仓位（占总资产）
    max_pos: float = 0.30             # 总仓位上限
    repo_rate: float = 0.015          # 闲置资金逆回购年化

    # 3b) 策略变体开关（默认值 = 原策略）
    use_ice: bool = True              # False = 不等冰点，天天可开仓
    buy_mode: str = "dip"             # dip = 挂低吸单；open = 开盘直接买
    retreat_days: int = 0             # >0：前 N 天每天都“跌停家数 > 涨停家数”时不开仓（退潮过滤）
    min_prev_pct: float = -99.0       # 候选股前一天涨幅至少多少（%），如 0 = 冰点日收红（抗跌）
    pullback_min: float = 0.0         # 距近 10 日最高收盘的回撤至少多少（如 0.10 = 回调 10% 才吸）
    pullback_max: float = 1.0         # 回撤最多多少（太深说明走坏了）
    hot_rising: bool = False          # 要求热度排名比 3 天前更靠前（热度在升温）
    exit_mode: str = "fixed"          # fixed = 原卖法；trail = 先卖一半后，剩下的跌破前一日最低价才走
    trail_max_hold: int = 10          # trail 模式最多拿几天
    # 严重异动回避（主板：10 日偏离累计 +100%、30 日 +200% 会停牌核查）
    halt10_cap: float = 0.0           # >0：近 9 日偏离累计 ≥ 该值（%）就不吸，如 90 = 明天再涨停就可能触发 100%
    halt30_cap: float = 0.0           # >0：近 29 日偏离累计 ≥ 该值（%）就不吸，如 190

    # 4) 卖点（还原现在的卖法）
    tp1: float = 0.08                 # 浮盈到这一档，先卖一半
    tp2: float = 0.15                 # 浮盈到这一档，清仓（“赚够了就走”）
    be_trigger: float = 0.03          # 曾经浮盈超过这一档 ……
    be_exit: float = 0.005            # …… 又回落到成本附近就走（“不亏就行”）
    stop_loss: float = -0.05          # 止损
    max_hold: int = 3                 # 最多拿几个交易日
    hold_on_limit_up: bool = True     # 收盘封涨停当天不卖

    # 成本
    commission: float = 0.00025       # 佣金（双边）
    stamp_tax: float = 0.0005         # 印花税（卖出）
    slippage: float = 0.001           # 滑点（双边）

    # 卖飞统计
    fly_window: int = 10

    init_cash: float = 1_000_000.0


# ───────────────────────────── 数据 ─────────────────────────────
MAIN_BOARD_PREFIX = ("600", "601", "603", "605", "000", "001", "002", "003")
COLMAP = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
          "最低": "low", "成交额": "amount", "涨跌幅": "pct"}


def fetch_universe() -> pd.DataFrame:
    """沪深主板、剔除 ST/退市。名单来自上交所/深交所官网，不走东方财富 push2。
    注意：用的是当前名单，存在幸存者偏差。"""
    import akshare as ak
    try:
        uni = ak.stock_info_a_code_name()
        uni = uni.rename(columns={"证券代码": "code", "证券简称": "name"})[["code", "name"]]
    except Exception as e:
        print(f"交易所名单获取失败（{e}），改用东方财富", file=sys.stderr)
        uni = ak.stock_zh_a_spot_em()[["代码", "名称"]]
        uni.columns = ["code", "name"]
    uni["code"] = uni["code"].astype(str).str.zfill(6)
    uni = uni[uni["code"].str.startswith(MAIN_BOARD_PREFIX)]
    uni = uni[~uni["name"].astype(str).str.contains("ST|退", regex=True)]
    return uni.drop_duplicates("code").reset_index(drop=True)


def fetch_daily(code: str, start: str, end: str) -> pd.DataFrame:
    """先用腾讯日线（前复权），失败再用东方财富。返回 date/open/close/high/low/amount/pct。"""
    import akshare as ak
    err = None
    try:
        df = ak.stock_zh_a_hist_tx(symbol=code, start_date=start, end_date=end, adjust="qfq")
        if df is not None and len(df):
            df = df[["date", "open", "close", "high", "low", "amount"]].copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df["pct"] = (df["close"].pct_change() * 100).round(2)
            return df
    except Exception as e:
        err = e
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
        if df is not None and len(df):
            return df.rename(columns=COLMAP)[list(COLMAP.values())]
    except Exception as e:
        err = e
    if err:
        raise err
    return pd.DataFrame()


def download(cfg: Config, limit: int = 0, workers: int = 4) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    os.makedirs(cfg.data_dir, exist_ok=True)
    upath = os.path.join(cfg.data_dir, "_universe.csv")
    if os.path.exists(upath):
        uni = pd.read_csv(upath, dtype={"code": str})
    else:
        uni = fetch_universe()
        uni.to_csv(upath, index=False)
    print(f"股票池：沪深主板（剔除 ST）共 {len(uni)} 只")
    if limit:
        uni = uni.head(limit)
    # 多拉 40 个交易日左右的数据给 20 日涨幅、60 日分位数预热
    start = (pd.Timestamp(cfg.start) - pd.Timedelta(days=90)).strftime("%Y%m%d")
    end = cfg.end or pd.Timestamp.today().strftime("%Y%m%d")
    todo = [c for c in uni["code"] if not os.path.exists(os.path.join(cfg.data_dir, f"{c}.csv"))]
    print(f"需要下载 {len(todo)} 只（已缓存 {len(uni) - len(todo)} 只）")

    def job(code):
        for attempt in range(3):
            try:
                df = fetch_daily(code, start, end)
                if len(df):
                    df.to_csv(os.path.join(cfg.data_dir, f"{code}.csv"), index=False)
                return code, None
            except Exception as e:
                last = e
                time.sleep(2 + attempt * 3)
        return code, last

    failed = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(job, c) for c in todo]
        for k, f in enumerate(as_completed(futs), 1):
            code, e = f.result()
            if e is not None:
                failed.append(code)
                if len(failed) <= 5:
                    print(f"  失败 {code}: {e}", file=sys.stderr)
            if k % 200 == 0 or k == len(todo):
                print(f"  日线 {k}/{len(todo)}，失败 {len(failed)}", flush=True)
    if failed:
        print(f"共 {len(failed)} 只下载失败，重新运行会自动补下。")


def download_hot(cfg: Config, workers: int = 4) -> None:
    """只给真正可能被选进龙头池的股票下载人气榜历史排名（每天评分前 3×K 名的并集）。"""
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor, as_completed
    panel, names = load_panel(cfg)
    if cfg.leader_mode == "hot_height":
        c, lo = panel["close"], panel["low"]
        hgt = (c / lo.rolling(cfg.height_window, min_periods=5).min() - 1).loc[pd.Timestamp(cfg.start):]
        top = hgt.rank(axis=1, ascending=False, method="first") <= cfg.height_pool
    else:
        sig = build_signals(panel, names, cfg, hot=None)
        sc = sig["score"].loc[pd.Timestamp(cfg.start):]
        top = sc.rank(axis=1, ascending=False, method="first") <= cfg.leader_topk * 3
    codes = list(top.columns[top.any()])
    hdir = os.path.join(cfg.data_dir, "hot")
    os.makedirs(hdir, exist_ok=True)
    todo = [c for c in codes if not os.path.exists(os.path.join(hdir, f"{c}.csv"))]
    print(f"热度：需要 {len(codes)} 只（已缓存 {len(codes) - len(todo)} 只，待下载 {len(todo)} 只）", flush=True)

    def job(code):
        sym = ("SH" if code.startswith("6") else "SZ") + code
        for attempt in range(3):
            try:
                df = ak.stock_hot_rank_detail_em(symbol=sym)
                out = pd.DataFrame({"date": pd.to_datetime(df["时间"]).dt.normalize(),
                                    "rank": pd.to_numeric(df["排名"], errors="coerce")})
                out.dropna().to_csv(os.path.join(hdir, f"{code}.csv"), index=False)
                return None
            except Exception as e:
                last = e
                time.sleep(2 + attempt * 3)
        return last

    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(job, c): c for c in todo}
        for k, f in enumerate(as_completed(futs), 1):
            if f.result() is not None:
                failed += 1
            if k % 50 == 0 or k == len(todo):
                print(f"  热度 {k}/{len(todo)}，失败 {failed}", flush=True)


def update_data(cfg: Config, workers: int = 4) -> None:
    """每日增量更新：补齐每只股票最近的日线（遇到除权导致前复权价变化就整只重下），再刷新活跃股的热度。"""
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor, as_completed
    upath = os.path.join(cfg.data_dir, "_universe.csv")
    if not os.path.exists(upath):
        sys.exit("还没有历史数据，请先运行 --download")
    uni = pd.read_csv(upath, dtype={"code": str})
    today = pd.Timestamp.today().strftime("%Y%m%d")

    def job(code):
        path = os.path.join(cfg.data_dir, f"{code}.csv")
        try:
            old = pd.read_csv(path, parse_dates=["date"]) if os.path.exists(path) else None
            if old is None or not len(old):
                start = (pd.Timestamp(cfg.start) - pd.Timedelta(days=90)).strftime("%Y%m%d")
                new = fetch_daily(code, start, today)
                if len(new):
                    new.to_csv(path, index=False)
                return "new"
            last = old["date"].max()
            new = fetch_daily(code, (last - pd.Timedelta(days=20)).strftime("%Y%m%d"), today)
            if not len(new):
                return "same"
            new["date"] = pd.to_datetime(new["date"])
            ov = old.merge(new[["date", "close"]], on="date", suffixes=("", "_n"))
            if len(ov) and (ov["close"] / ov["close_n"] - 1).abs().max() > 0.003:
                full = fetch_daily(code, old["date"].min().strftime("%Y%m%d"), today)   # 除权了，整只重下
                if len(full):
                    full.to_csv(path, index=False)
                return "refetch"
            add = new[new["date"] > last]
            if not len(add):
                return "same"
            m = pd.concat([old, add[old.columns.intersection(add.columns)]], ignore_index=True)
            m = m.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
            m["pct"] = (m["close"].pct_change() * 100).round(2).fillna(m["pct"])
            m.to_csv(path, index=False)
            return "add"
        except Exception as e:
            return f"err:{e}"

    stat = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(job, c) for c in uni["code"]]
        for k, f in enumerate(as_completed(futs), 1):
            r = f.result()
            key = "err" if r.startswith("err") else r
            stat[key] = stat.get(key, 0) + 1
            if k % 500 == 0 or k == len(futs):
                print(f"  日线更新 {k}/{len(futs)}  {stat}", flush=True)

    # 热度：近 20 个交易日高度前 100 的股票 + 之前热度进过前 50 的股票，整段历史重拉
    panel, names = load_panel(cfg)
    c, lo = panel["close"], panel["low"]
    hgt = (c / lo.rolling(cfg.height_window, min_periods=5).min() - 1).iloc[-20:]
    codes = set(hgt.columns[(hgt.rank(axis=1, ascending=False, method="first") <= 100).any()])
    hdir = os.path.join(cfg.data_dir, "hot")
    os.makedirs(hdir, exist_ok=True)
    for fn in os.listdir(hdir):
        try:
            h = pd.read_csv(os.path.join(hdir, fn))
            if len(h) and h["rank"].tail(20).min() <= 50:
                codes.add(fn[:-4])
        except Exception:
            pass

    def hjob(code):
        sym = ("SH" if code.startswith("6") else "SZ") + code
        for attempt in range(3):
            try:
                df = ak.stock_hot_rank_detail_em(symbol=sym)
                out = pd.DataFrame({"date": pd.to_datetime(df["时间"]).dt.normalize(),
                                    "rank": pd.to_numeric(df["排名"], errors="coerce")})
                out.dropna().to_csv(os.path.join(hdir, f"{code}.csv"), index=False)
                return True
            except Exception:
                time.sleep(2 + attempt * 3)
        return False

    print(f"热度更新：{len(codes)} 只", flush=True)
    ok = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, f in enumerate(as_completed([ex.submit(hjob, c) for c in codes]), 1):
            ok += f.result()
            if k % 100 == 0 or k == len(codes):
                print(f"  热度 {k}/{len(codes)}，成功 {ok}", flush=True)
    print(f"数据已更新到 {panel['close'].index[-1].date()}", flush=True)


def signal_payload(panel: dict, names: dict, hot, sig: dict, cfg: Config, top_n: int = 5) -> dict:
    """最新一个收盘日的冰点判断和龙头清单（给下一个交易日用），返回可直接写成 JSON 的字典。"""
    emo, sc = sig["emotion"], sig["score"]
    d = emo.index[-1]
    recent = emo.iloc[-cfg.ice_window:]
    can_open = bool(recent["冰点"].any()) if cfg.use_ice else True
    retreat = False
    if cfg.retreat_days > 0:
        w = emo.iloc[-cfg.retreat_days:]
        retreat = bool((w["跌停家数"] > w["涨停家数"]).all())
    row = emo.iloc[-1]
    mkt = panel["pct"].loc[d].median()
    leaders = []
    for k, code in enumerate(sc.loc[d].dropna().sort_values(ascending=False).head(max(cfg.leader_topk, top_n)).index, 1):
        cl = float(panel["close"].loc[d, code])
        hr = hot.loc[d, code] if hot is not None else np.nan
        pc = float(panel["pct"].loc[d, code])
        leaders.append({
            "rank": k, "code": code, "name": names.get(code, ""),
            "hot_rank": None if np.isnan(hr) else int(hr),
            "height_pct": round(float(sig["height"].loc[d, code]) * 100, 1),
            "pct": round(pc, 2), "close": round(cl, 2), "dip_price": round(cl * (1 + cfg.dip), 2),
            "dev10_pct": round(float(sig["dev9"].loc[d, code]) + pc - mkt, 1),
            "dev30_pct": round(float(sig["dev29"].loc[d, code]) + pc - mkt, 1),
        })
    return {
        "data_as_of": d.date().isoformat(),
        "limit_up": int(row["涨停家数"]), "limit_down": int(row["跌停家数"]),
        "max_boards": int(row["最高连板"]), "prev_limit_up_premium_pct": None if pd.isna(row["昨日涨停溢价%"]) else float(row["昨日涨停溢价%"]),
        "is_ice_today": bool(row["冰点"]), "ice_in_window": bool(recent["冰点"].any()),
        "ice_window": cfg.ice_window, "retreat_blocked": retreat,
        "can_open_next_day": bool(can_open and not retreat),
        "leaders": leaders,
        "rules": {"hot_topn": cfg.hot_topn, "height_min_pct": round(cfg.height_min * 100), "dip_pct": round(cfg.dip * 100, 1),
                  "pos_size_pct": round(cfg.pos_size * 100), "max_pos_pct": round(cfg.max_pos * 100)},
    }


def daily_signal(cfg: Config, tag: str = "原策略") -> None:
    """用最新收盘数据，给出下一个交易日的冰点判断和龙头低吸清单。"""
    panel, names = load_panel(cfg)
    hot = load_hot(cfg, panel["close"])
    sig = build_signals(panel, names, cfg, hot)
    p = signal_payload(panel, names, hot, sig, cfg)
    prem = p["prev_limit_up_premium_pct"]
    lines = [f"# 龙头低吸信号【{tag}】（基于 {p['data_as_of']} 收盘，用于下一个交易日）", "",
             f"- 涨停 {p['limit_up']} 家，跌停 {p['limit_down']} 家，最高连板 {p['max_boards']}，"
             f"昨日涨停今日平均 {'—' if prem is None else f'{prem:+.2f}%'}",
             f"- 今天是否冰点：{'是' if p['is_ice_today'] else '否'}；近 {cfg.ice_window} 天出现过冰点：{'是' if p['ice_in_window'] else '否'}",
             f"- 下一交易日：**{'可以开仓' if p['can_open_next_day'] else '不开仓'}**"
             + ("（退潮过滤触发）" if p["retreat_blocked"] else ""), "",
             "| 排名 | 代码 | 名称 | 热度排名 | 高度 | 今日涨跌 | 收盘价 | 低吸挂单价 | 10日偏离 | 30日偏离 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for x in p["leaders"]:
        lines.append(f"| {x['rank']} | {x['code']} | {x['name']} | {x['hot_rank'] or ''} | {x['height_pct']:.0f}% | "
                     f"{x['pct']:+.2f}% | {x['close']:.2f} | {x['dip_price']:.2f} | {x['dev10_pct']:.0f}% | {x['dev30_pct']:.0f}% |")
    if not p["leaders"]:
        lines.append("| - | - | 没有同时满足热度和高度的股票 | | | | | | | |")
    lines += ["", f"规则：热度前 {cfg.hot_topn} 且高度≥{cfg.height_min:.0%}；低吸价 = 收盘价 × (1{cfg.dip:+.0%})；"
              f"单票 {cfg.pos_size:.0%}，总仓位上限 {cfg.max_pos:.0%}。", "",
              "仅供研究复盘，不构成投资建议。"]
    os.makedirs("信号", exist_ok=True)
    path = os.path.join("信号", f"信号_{p['data_as_of'].replace('-', '')}_{tag}.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print(f"\n已保存到 {path}")


def load_hot(cfg: Config, like: pd.DataFrame):
    """读热度缓存，返回与行情同形状的宽表（没数据的位置是 NaN）；没有缓存返回 None。"""
    hdir = os.path.join(cfg.data_dir, "hot")
    if not cfg.use_hot or not os.path.isdir(hdir):
        return None
    cols = {}
    for fn in os.listdir(hdir):
        code = fn[:-4]
        if fn.endswith(".csv") and code in like.columns:
            df = pd.read_csv(os.path.join(hdir, fn), parse_dates=["date"])
            if len(df):
                cols[code] = df.groupby("date")["rank"].last()
    if not cols:
        return None
    return pd.DataFrame(cols).reindex(index=like.index, columns=like.columns)


def load_panel(cfg: Config) -> tuple[dict, dict]:
    """读缓存，返回 {字段: 宽表(日期 × 代码)} 和 {代码: 名称}。"""
    upath = os.path.join(cfg.data_dir, "_universe.csv")
    if not os.path.exists(upath):
        sys.exit(f"没找到 {upath}，请先运行：python {os.path.basename(__file__)} --download")
    uni = pd.read_csv(upath, dtype={"code": str})
    names = dict(zip(uni["code"], uni["name"]))
    frames = []
    for code in uni["code"]:
        path = os.path.join(cfg.data_dir, f"{code}.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, parse_dates=["date"])
        df["code"] = code
        frames.append(df)
    if not frames:
        sys.exit("缓存目录里没有行情文件，请先 --download")
    long = pd.concat(frames, ignore_index=True)
    panel = {c: long.pivot(index="date", columns="code", values=c).sort_index()
             for c in ("open", "high", "low", "close", "pct")}
    end = pd.Timestamp(cfg.end) if cfg.end else panel["close"].index[-1]
    panel = {k: v.loc[:end] for k, v in panel.items()}       # 保留 start 之前的预热数据
    return panel, names


def demo_panel(n_days: int = 420, n_stocks: int = 300, seed: int = 7) -> tuple[dict, dict]:
    """模拟数据：只用来检查代码逻辑能跑通，结果没有任何参考意义。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n_days)
    codes = [f"{600000 + i}" for i in range(n_stocks)]
    mood = np.sin(np.arange(n_days) / 9.0) * 0.6 + rng.normal(0, 0.3, n_days)   # 市场情绪波动
    hot = rng.random((n_days, n_stocks)) < (0.02 + 0.02 * (mood[:, None] > 0.3))
    ret = rng.normal(0.0003, 0.022, (n_days, n_stocks)) + mood[:, None] * 0.004
    for t in range(1, n_days):                       # 涨停有一定延续性
        was_zt = ret[t - 1] >= 0.098
        if mood[t] < -0.3:                           # 退潮日：昨日涨停股挨揍，部分跌停
            ret[t] = np.where(was_zt, rng.normal(-0.045, 0.04, n_stocks), ret[t])
            ret[t] = np.where(was_zt & (rng.random(n_stocks) < 0.15), -0.1, ret[t])
            ret[t] = np.where(hot[t] & ~was_zt & (rng.random(n_stocks) < 0.3), 0.1, ret[t])
        else:
            cont = was_zt & (rng.random(n_stocks) < 0.35 + 0.2 * (mood[t] > 0.3))
            ret[t] = np.where(cont | hot[t], 0.1, ret[t])
    ret = np.clip(ret, -0.1, 0.1)
    close = 10 * np.cumprod(1 + ret, axis=0)
    prev = np.vstack([np.full(n_stocks, 10.0), close[:-1]])
    gap = np.clip(rng.normal(0, 0.012, ret.shape), -0.09, 0.09)
    open_ = prev * (1 + gap)
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, ret.shape)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.012, ret.shape)))
    hi = np.minimum(hi, prev * 1.1)
    lo = np.maximum(lo, prev * 0.9)
    zt = ret >= 0.098
    hi = np.where(zt, close, hi)
    lo = np.where(ret <= -0.098, close, lo)
    mk = lambda a: pd.DataFrame(a, index=dates, columns=codes)
    panel = {"open": mk(open_), "high": mk(hi), "low": mk(lo), "close": mk(close), "pct": mk(ret * 100)}
    return panel, {c: f"模拟{c[-3:]}" for c in codes}


# ───────────────────────────── 指标 ─────────────────────────────
def build_signals(panel: dict, names: dict, cfg: Config, hot=None) -> dict:
    close, high, low, pct = panel["close"], panel["high"], panel["low"], panel["pct"]
    eps = 1e-6
    zt = (pct >= cfg.limit_pct) & (close >= high - eps)          # 收盘封涨停
    dt = (pct <= -cfg.limit_pct) & (close <= low + eps)          # 收盘封跌停

    # 连板数
    boards = np.zeros(zt.shape, dtype=int)
    z = zt.to_numpy()
    for t in range(z.shape[0]):
        boards[t] = np.where(z[t], (boards[t - 1] if t else 0) + 1, 0)
    boards = pd.DataFrame(boards, index=zt.index, columns=zt.columns)

    # 市场情绪
    zt_count = zt.sum(axis=1)
    dt_count = dt.sum(axis=1)
    prev_zt = zt.shift(1, fill_value=False)
    premium = pct.where(prev_zt).mean(axis=1)                    # 昨日涨停今日平均涨幅(%)
    q = zt_count.rolling(cfg.ice_lookback, min_periods=20).quantile(cfg.ice_quantile)
    ice = (premium < cfg.ice_premium) & ((zt_count <= q) | (dt_count >= zt_count))
    ice = ice.fillna(False)
    # 第 t 天能否开仓：前 ice_window 天内出现过冰点（不含当天，避免用到未来数据）
    node_ok = ice.shift(1, fill_value=False).astype(int).rolling(cfg.ice_window, min_periods=1).max() > 0

    emotion = pd.DataFrame({"涨停家数": zt_count, "跌停家数": dt_count, "最高连板": boards.max(axis=1),
                            "昨日涨停溢价%": premium.round(2), "冰点": ice, "可开仓": node_ok})

    # 龙头评分（收盘后计算，第二天使用）
    w = cfg.leader_window
    max_boards = boards.rolling(w, min_periods=1).max()
    zt_times = zt.astype(int).rolling(w, min_periods=1).sum()
    ret20 = close / close.shift(20) - 1
    score = max_boards * 100 + zt_times * 10 + ret20.fillna(0).clip(-1, 5)
    score = score.where(zt_times >= cfg.leader_min_zt)
    if cfg.name_keywords:
        ok = [c for c in score.columns if any(k in str(names.get(c, "")) for k in cfg.name_keywords)]
        score = score[ok].reindex(columns=score.columns)
    height = close / low.rolling(cfg.height_window, min_periods=5).min() - 1
    # 偏离值 = 个股涨跌幅 - 市场基准；这里用主板全体个股涨跌幅的中位数近似指数（没有单独下载指数）
    dev = pct.sub(pct.median(axis=1), axis=0)
    dev9 = dev.rolling(9, min_periods=1).sum()
    dev29 = dev.rolling(29, min_periods=1).sum()
    emotion["有热度数据"] = False
    if cfg.leader_mode == "hot_height":
        # 龙头 = 热度前 N 且高度达标，按“热度排名 + 高度排名”综合排序（两者都靠前的排最前）
        if hot is None:
            score = pd.DataFrame(np.nan, index=score.index, columns=score.columns)   # 没有热度数据就不出龙头
        else:
            h = hot.reindex(index=score.index, columns=score.columns)
            emotion["有热度数据"] = h.notna().any(axis=1)
            ok = (h <= cfg.hot_topn) & (height >= cfg.height_min)
            hot_r = h.where(ok).rank(axis=1, method="min")
            hgt_r = height.where(ok).rank(axis=1, ascending=False, method="min")
            score = -(hot_r + hgt_r) - h.where(ok) / 1000          # 并列时热度高的优先
        return {"zt": zt, "dt": dt, "boards": boards, "emotion": emotion, "score": score,
                "hot": hot, "height": height, "dd10": close / close.rolling(10, min_periods=1).max() - 1,
                "dev9": dev9, "dev29": dev29}
    if hot is not None:
        h = hot.reindex(index=score.index, columns=score.columns)
        covered = h.notna().any(axis=1)                       # 当天有没有热度数据
        emotion["有热度数据"] = covered
        ok = h <= cfg.hot_topn
        if not cfg.hot_strict:
            ok = ok.where(covered, True)                      # 没数据的日期不做热度过滤
        score = score.where(ok)
    return {"zt": zt, "dt": dt, "boards": boards, "emotion": emotion, "score": score, "hot": hot,
            "height": height, "dd10": close / close.rolling(10, min_periods=1).max() - 1,
                "dev9": dev9, "dev29": dev29}


# ───────────────────────────── 回测 ─────────────────────────────
def run_backtest(panel: dict, names: dict, sig: dict, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    O, H, L, C = (panel[k] for k in ("open", "high", "low", "close"))
    zt, dt, emo, score = sig["zt"], sig["dt"], sig["emotion"], sig["score"]
    hot = sig.get("hot")
    dates = C.index
    buy_cost = cfg.commission + cfg.slippage
    sell_cost = cfg.commission + cfg.stamp_tax + cfg.slippage

    cash = cfg.init_cash
    pos: dict[str, dict] = {}      # code -> {shares, cost, buy_i, half, peak, cost_amt, proceeds}
    trades, equity = [], []

    def sell(code: str, i: int, frac: float, reason: str) -> None:
        nonlocal cash
        p = pos[code]
        price = C.iat[i, C.columns.get_loc(code)]
        sh = p["shares"] * frac
        cash += sh * price * (1 - sell_cost)
        p["proceeds"] += sh * price * (1 - sell_cost)
        p["shares"] -= sh
        if frac >= 1 or p["shares"] <= 1e-9:
            trades.append({"代码": code, "名称": names.get(code, ""),
                           "买入日": dates[p["buy_i"]].date(), "卖出日": dates[i].date(),
                           "买入价": round(p["cost"], 3), "清仓价": round(price, 3),
                           "持有天数": i - p["buy_i"], "买入前热度排名": p["hot"],
                           "买入前高度%": p["hgt"],
                           "收益率%": round((p["proceeds"] / p["cost_amt"] - 1) * 100, 2),
                           "盈亏": round(p["proceeds"] - p["cost_amt"], 0),
                           "卖出原因": reason + ("（此前已卖一半）" if p["half"] else ""),
                           "_exit_i": i})
            del pos[code]

    i0 = max(1, int(dates.searchsorted(pd.Timestamp(cfg.start))))
    for i in range(i0, len(dates)):
        cash *= 1 + cfg.repo_rate / 252                      # 闲钱做逆回购

        # ── 卖出（T+1：今天买的今天不能卖），按收盘价近似 ──
        for code in list(pos):
            p = pos[code]
            if i <= p["buy_i"]:
                continue
            j = C.columns.get_loc(code)
            c = C.iat[i, j]
            if np.isnan(c):                                   # 停牌
                continue
            if dt.iat[i, j]:                                  # 跌停卖不掉
                continue
            gain = c / p["cost"] - 1
            p["peak"] = max(p["peak"], H.iat[i, j] / p["cost"] - 1)
            held = i - p["buy_i"]
            if gain <= cfg.stop_loss:
                sell(code, i, 1.0, "止损")
            elif cfg.hold_on_limit_up and zt.iat[i, j]:
                continue
            elif cfg.exit_mode == "trail":
                if not p["half"] and gain >= cfg.tp1:
                    sell(code, i, 0.5, "先卖一半")
                    p["half"] = True
                elif held >= 2 and c < L.iat[i - 1, j]:
                    sell(code, i, 1.0, "跌破前日低点")
                elif not p["half"] and p["peak"] >= cfg.be_trigger and gain <= cfg.be_exit:
                    sell(code, i, 1.0, "回吐到成本，不亏就行")
                elif held >= cfg.trail_max_hold:
                    sell(code, i, 1.0, "到期离场")
            elif gain >= cfg.tp2:
                sell(code, i, 1.0, "赚够清仓")
            elif not p["half"] and gain >= cfg.tp1:
                sell(code, i, 0.5, "先卖一半")
                p["half"] = True
            elif p["peak"] >= cfg.be_trigger and gain <= cfg.be_exit:
                sell(code, i, 1.0, "回吐到成本，不亏就行")
            elif held >= cfg.max_hold:
                sell(code, i, 1.0, "到期离场")

        # ── 买入：冰点窗口内，低吸昨天收盘选出的龙头 ──
        can_open = bool(emo["可开仓"].iat[i]) if cfg.use_ice else True
        if can_open and cfg.retreat_days > 0 and i > cfg.retreat_days:
            w = emo.iloc[i - cfg.retreat_days:i]
            if (w["跌停家数"] > w["涨停家数"]).all():
                can_open = False
        if can_open:
            mv = sum(p["shares"] * C.iat[i, C.columns.get_loc(k)] for k, p in pos.items()
                     if not np.isnan(C.iat[i, C.columns.get_loc(k)]))
            total = cash + mv
            sc_prev = score.iloc[i - 1].dropna()
            if cfg.min_prev_pct > -99:
                sc_prev = sc_prev[panel["pct"].iloc[i - 1].reindex(sc_prev.index) >= cfg.min_prev_pct]
            if cfg.pullback_min > 0 or cfg.pullback_max < 1:
                dd = -sig["dd10"].iloc[i - 1].reindex(sc_prev.index)
                sc_prev = sc_prev[(dd >= cfg.pullback_min) & (dd <= cfg.pullback_max)]
            if cfg.hot_rising and hot is not None and i >= 4:
                sc_prev = sc_prev[hot.iloc[i - 1].reindex(sc_prev.index) < hot.iloc[i - 4].reindex(sc_prev.index)]
            if cfg.halt10_cap > 0:
                sc_prev = sc_prev[sig["dev9"].iloc[i - 1].reindex(sc_prev.index) < cfg.halt10_cap]
            if cfg.halt30_cap > 0:
                sc_prev = sc_prev[sig["dev29"].iloc[i - 1].reindex(sc_prev.index) < cfg.halt30_cap]
            pool = sc_prev.sort_values(ascending=False).head(cfg.leader_topk)
            for code in pool.index:
                if code in pos:
                    continue
                if (mv + cfg.pos_size * total) / total > cfg.max_pos + 1e-9:
                    break
                j = C.columns.get_loc(code)
                pc, o, lo, hi = C.iat[i - 1, j], O.iat[i, j], L.iat[i, j], H.iat[i, j]
                if np.isnan([pc, o, lo, hi]).any():
                    continue
                order = o if cfg.buy_mode == "open" else pc * (1 + cfg.dip)
                if lo > order:                                # 没跌到挂单价 → 没买到
                    continue
                if cfg.buy_mode == "open" and o >= pc * 1.098:  # 开盘涨停买不到
                    continue
                if hi - lo < 1e-6 and dt.iat[i, j]:           # 一字跌停不接
                    continue
                fill = min(o, order) * (1 + buy_cost)
                amt = min(cfg.pos_size * total, cash)
                if amt <= 0:
                    break
                hr = hot.iat[i - 1, j] if hot is not None else np.nan
                hg = sig["height"].iat[i - 1, j]
                pos[code] = {"shares": amt / fill, "cost": fill, "buy_i": i, "half": False,
                             "peak": 0.0, "cost_amt": amt, "proceeds": 0.0,
                             "hot": "" if np.isnan(hr) else int(hr),
                             "hgt": round(hg * 100, 1)}
                cash -= amt
                mv += amt

        mv = 0.0
        for k, p in pos.items():
            c = C.iat[i, C.columns.get_loc(k)]
            if np.isnan(c):
                c = C[k].iloc[:i].ffill().iloc[-1]
            mv += p["shares"] * c
        equity.append({"日期": dates[i], "总资产": cash + mv, "仓位": mv / (cash + mv)})

    eq = pd.DataFrame(equity).set_index("日期")
    tr = pd.DataFrame(trades)
    if len(tr):                                               # 卖飞：清仓后 N 日最高价 / 清仓价 - 1
        fly = []
        for _, r in tr.iterrows():
            j, e = H.columns.get_loc(r["代码"]), int(r["_exit_i"])
            win = H.iloc[e + 1:e + 1 + cfg.fly_window, j]
            fly.append(round((win.max() / r["清仓价"] - 1) * 100, 2) if len(win) else np.nan)
        tr[f"卖后{cfg.fly_window}日最高涨幅%"] = fly
        tr = tr.drop(columns="_exit_i")
    return eq, tr


# ───────────────────────────── 报告 ─────────────────────────────
def report(eq: pd.DataFrame, tr: pd.DataFrame, emo: pd.DataFrame, cfg: Config) -> None:
    os.makedirs(cfg.out_dir, exist_ok=True)
    nav = eq["总资产"] / cfg.init_cash
    days = len(nav)
    total = nav.iloc[-1] - 1
    ann = (1 + total) ** (252 / max(days, 1)) - 1
    mdd = (nav / nav.cummax() - 1).min()
    print("\n══════════ 回测结果 ══════════")
    print(f"区间          {eq.index[0].date()} ~ {eq.index[-1].date()}（{days} 个交易日）")
    print(f"总收益        {total:+.2%}    年化 {ann:+.2%}    最大回撤 {mdd:.2%}")
    ew = emo.loc[eq.index[0]:eq.index[-1]]
    print(f"平均仓位      {eq['仓位'].mean():.1%}    冰点天数 {int(ew['冰点'].sum())}    可开仓天数 {int(ew['可开仓'].sum())}")
    hc = int(ew["有热度数据"].sum())
    mode = (f"热度+高度：热度前 {cfg.hot_topn}、高度≥{cfg.height_min:.0%}，取综合前 {cfg.leader_topk}"
            if cfg.leader_mode == "hot_height" else f"连板评分前 {cfg.leader_topk}")
    print(f"龙头定义      {mode}")
    print(f"热度数据      " + (f"覆盖 {hc}/{len(ew)} 个交易日" if hc else "没有"))
    if len(tr):
        win = tr["收益率%"] > 0
        fcol = [c for c in tr.columns if c.startswith("卖后")][0]
        f = tr[fcol].dropna()
        print(f"交易笔数      {len(tr)}    胜率 {win.mean():.1%}    平均持有 {tr['持有天数'].mean():.1f} 天")
        print(f"单笔平均      {tr['收益率%'].mean():+.2f}%    盈利单平均 {tr.loc[win, '收益率%'].mean():+.2f}%"
              f"    亏损单平均 {tr.loc[~win, '收益率%'].mean():+.2f}%")
        if len(f):
            print(f"卖飞统计      {fcol[:-1]} 平均 {f.mean():+.2f}%，中位 {f.median():+.2f}%，"
                  f"超过 10% 的占 {(f > 10).mean():.1%}")
        print("\n按卖出原因：")
        g = tr.assign(原因=tr["卖出原因"].str.replace("（此前已卖一半）", "", regex=False)).groupby("原因")
        print(g["收益率%"].agg(笔数="count", 平均收益="mean").round(2).to_string())
    else:
        print("没有产生交易：可以放宽 --dip 或冰点条件再试。")

    eq.assign(净值=nav).to_csv(os.path.join(cfg.out_dir, "净值.csv"), encoding="utf-8-sig")
    tr.to_csv(os.path.join(cfg.out_dir, "交易明细.csv"), index=False, encoding="utf-8-sig")
    emo.to_csv(os.path.join(cfg.out_dir, "情绪指标.csv"), encoding="utf-8-sig")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        ax[0].plot(nav.index, nav.values, lw=1.4)
        for d in emo.index[emo["冰点"]]:
            ax[0].axvline(d, color="tab:blue", alpha=0.12, lw=1)
        ax[0].set_title("NAV (vertical lines = ice-point days)")
        ax[0].grid(alpha=0.3)
        ax[1].fill_between(eq.index, eq["仓位"].values, step="post", alpha=0.5)
        ax[1].set_ylabel("position")
        ax[1].grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(cfg.out_dir, "nav.png"), dpi=130)
    except Exception as e:
        print(f"（没画图：{e}）")
    print(f"\n明细已保存到 {cfg.out_dir}/：净值.csv、交易明细.csv、情绪指标.csv、nav.png")


# ───────────────────────────── 入口 ─────────────────────────────
def main() -> None:
    cfg = Config()
    ap = argparse.ArgumentParser(description="情绪冰点 + 龙头低吸 日线回测")
    ap.add_argument("--download", action="store_true", help="用 AKShare 下载并缓存日线后退出")
    ap.add_argument("--limit", type=int, default=0, help="只下载前 N 只（试跑用）")
    ap.add_argument("--demo", action="store_true", help="不联网，用模拟数据检查代码")
    ap.add_argument("--selftest", action="store_true", help="联网测试三个数据接口各取一只股票")
    ap.add_argument("--update", action="store_true", help="每日增量更新日线和热度")
    ap.add_argument("--signal", action="store_true", help="输出下一个交易日的冰点判断和龙头清单")
    ap.add_argument("--tag", type=str, default="原策略", help="信号文件名里的策略标签")
    ap.add_argument("--exit_mode", type=str, default=cfg.exit_mode, choices=["fixed", "trail"])
    ap.add_argument("--buy_mode", type=str, default=cfg.buy_mode, choices=["dip", "open"])
    ap.add_argument("--no_ice", action="store_true", help="不等冰点")
    ap.add_argument("--hot_rising", action="store_true", help="要求热度在升温")
    ap.add_argument("--no_hot", action="store_true", help="不使用热度过滤")
    ap.add_argument("--hot_strict", action="store_true", help="没有热度数据的日期不开仓")
    ap.add_argument("--keywords", type=str, default="", help="只做名字含这些字的，逗号分隔，如 阳,新华")
    for name in ("start", "end", "data_dir", "out_dir"):
        ap.add_argument(f"--{name}", type=str, default=getattr(cfg, name))
    for name in ("dip", "tp1", "tp2", "stop_loss", "pos_size", "max_pos", "ice_quantile", "ice_premium"):
        ap.add_argument(f"--{name}", type=float, default=getattr(cfg, name))
    ap.add_argument("--leader_mode", type=str, default=cfg.leader_mode, choices=["hot_height", "boards"])
    for name in ("height_min", "min_prev_pct", "pullback_min", "pullback_max", "halt10_cap", "halt30_cap"):
        ap.add_argument(f"--{name}", type=float, default=getattr(cfg, name))
    for name in ("max_hold", "ice_window", "leader_topk", "leader_min_zt", "hot_topn",
                 "height_window", "height_pool", "retreat_days", "trail_max_hold"):
        ap.add_argument(f"--{name}", type=int, default=getattr(cfg, name))
    a = ap.parse_args()
    for k, v in vars(a).items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    if a.keywords:
        cfg.name_keywords = [s.strip() for s in a.keywords.split(",") if s.strip()]

    cfg.use_hot = not a.no_hot
    cfg.use_ice = not a.no_ice
    cfg.hot_rising = a.hot_rising
    if a.update:
        update_data(cfg)
        if not a.signal:
            return
    if a.signal:
        daily_signal(cfg, a.tag)
        return
    if a.selftest:
        import akshare as ak
        print("akshare", ak.__version__)
        for label, fn in [("股票名单", lambda: fetch_universe()),
                          ("日线 600519", lambda: fetch_daily("600519", "20251101", pd.Timestamp.today().strftime("%Y%m%d"))),
                          ("热度 SH600519", lambda: ak.stock_hot_rank_detail_em(symbol="SH600519"))]:
            try:
                df = fn()
                print(f"[OK] {label}: {len(df)} 行")
                print(df.head(3).to_string()); print(df.tail(2).to_string())
            except Exception as e:
                print(f"[失败] {label}: {type(e).__name__}: {e}")
        return
    if a.download:
        download(cfg, a.limit)
        if cfg.use_hot:
            download_hot(cfg)
        print("下载完成。去掉 --download 再运行一次即可回测。")
        return
    panel, names = demo_panel() if a.demo else load_panel(cfg)
    if a.demo:
        print("【演示模式】以下结果来自随机模拟数据，没有任何参考意义，只说明代码能跑通。")
    if a.demo and cfg.use_hot:                                # 模拟热度：近期涨得多的排名靠前 + 噪声
        c = panel["close"]
        raw = (c / c.shift(5) - 1).fillna(0) + np.random.default_rng(1).normal(0, 0.05, c.shape)
        hot = raw.rank(axis=1, ascending=False)
        hot.iloc[:150] = np.nan                               # 模拟“早期没有热度数据”
    else:
        hot = load_hot(cfg, panel["close"])
    sig = build_signals(panel, names, cfg, hot)
    eq, tr = run_backtest(panel, names, sig, cfg)
    report(eq, tr, sig["emotion"], cfg)


if __name__ == "__main__":
    main()
