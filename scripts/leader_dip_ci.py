"""GitHub Actions 用：龙头低吸每日数据更新。

流程：
  1. 有缓存（data/leader_dip/_universe.csv）就增量更新日线和人气榜；没有就从头下载（首次约需 30~60 分钟）。
  2. 生成看板数据到临时目录。
  3. 当天有收盘价的股票占有效历史股票的比例低于 --min-coverage（默认 95%）时，
     认为数据源还没更新完，不覆盖 outputs/，留给下一次定时任务重试。
  4. 覆盖率达标才把 leader_dip.json / .js / _trades.csv 写进 outputs/。

结果写到 $GITHUB_OUTPUT：status=ok|incomplete，data_as_of，coverage。
仅供研究复盘，不构成投资建议。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_leader_dip as bld  # noqa: E402
from low_buy_selector import leader_dip as ld  # noqa: E402

FILES = ("leader_dip.json", "leader_dip.js", "leader_dip_trades.csv")


def set_output(**kv: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="龙头低吸每日数据更新（GitHub Actions）")
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "leader_dip"))
    ap.add_argument("--out-dir", default=str(ROOT / "outputs"))
    ap.add_argument("--start", default="20251201")
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    data_dir = Path(a.data_dir)
    cfg = ld.Config()
    cfg.data_dir = str(data_dir)
    cfg.start = a.start

    if not (data_dir / "_universe.csv").exists():
        print("没有行情缓存，开始首次全量下载（日线 + 人气榜）", flush=True)
        ld.download(cfg, workers=a.workers)
        ld.download_hot(cfg, workers=a.workers)
    else:
        print("使用缓存，增量更新日线和人气榜", flush=True)
        ld.update_data(cfg, workers=a.workers)
    ld.download(cfg, workers=a.workers)  # 只会补下之前失败、还没有文件的股票

    tmp = ROOT / "_leader_dip_build"
    shutil.rmtree(tmp, ignore_errors=True)
    payload = bld.build(data_dir, tmp, a.start)
    cov = payload["coverage"]
    ratio = cov["updated_today"] / max(cov["valid_history"], 1)
    msg = (f"数据日期 {payload['data_as_of']}；当天有行情 {cov['updated_today']}/{cov['valid_history']}"
           f"（{ratio:.1%}）；当日人气榜覆盖 {cov['hot_ranked_on_last_day']} 只")
    print(msg, flush=True)
    set_output(data_as_of=payload["data_as_of"], coverage=f"{ratio:.3f}")

    if ratio < a.min_coverage:
        print(f"::warning::当天行情覆盖不足 {a.min_coverage:.0%}，数据源可能还没更新完，本次不发布。{msg}")
        set_output(status="incomplete")
        shutil.rmtree(tmp, ignore_errors=True)
        return 0

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if (tmp / name).exists():
            shutil.copyfile(tmp / name, out / name)
    shutil.rmtree(tmp, ignore_errors=True)
    for key, st in payload["strategies"].items():
        p = st["periods"]["全区间"]
        print(f"{st['label']}：全区间 {p['total_return_pct']:+.2f}%，回撤 {p['max_drawdown_pct']:.2f}%，"
              f"{p['trades']} 笔；下一交易日{'可开仓' if st['signal']['can_open_next_day'] else '不开仓'}")
    set_output(status="ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
