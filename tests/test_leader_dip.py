import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from low_buy_selector import leader_dip as ld  # noqa: E402
import build_leader_dip  # noqa: E402


def write_demo_dir(target: Path, n_days: int = 320, n_stocks: int = 120) -> None:
    """把模拟行情写成和 AKShare 缓存相同的目录结构。"""
    panel, names = ld.demo_panel(n_days=n_days, n_stocks=n_stocks)
    target.mkdir(parents=True, exist_ok=True)
    (target / "hot").mkdir()
    pd.DataFrame({"code": list(names), "name": list(names.values())}).to_csv(target / "_universe.csv", index=False)
    close = panel["close"]
    for code in close.columns:
        df = pd.DataFrame({
            "date": close.index.strftime("%Y-%m-%d"),
            "open": panel["open"][code].values, "close": close[code].values,
            "high": panel["high"][code].values, "low": panel["low"][code].values,
            "amount": 1e8, "pct": panel["pct"][code].round(2).values,
        })
        df.to_csv(target / f"{code}.csv", index=False)
    raw = (close / close.shift(5) - 1).fillna(0) + np.random.default_rng(1).normal(0, 0.05, close.shape)
    rank = raw.rank(axis=1, ascending=False)
    for code in close.columns:
        pd.DataFrame({"date": close.index.strftime("%Y-%m-%d"), "rank": rank[code].astype(int).values}) \
            .to_csv(target / "hot" / f"{code}.csv", index=False)


class LeaderDipEngineTest(unittest.TestCase):
    def test_signals_do_not_use_same_day_ice(self):
        panel, names = ld.demo_panel(n_days=200, n_stocks=80)
        sig = ld.build_signals(panel, names, ld.Config(), hot=None)
        emo = sig["emotion"]
        # 第 t 天可开仓只取决于 t 之前的冰点
        first_ice = emo.index[emo["冰点"]][0]
        pos = emo.index.get_loc(first_ice)
        self.assertFalse(bool(emo["可开仓"].iloc[: pos + 1].any()))
        self.assertTrue(bool(emo["可开仓"].iloc[pos + 1]))

    def test_hot_height_requires_popularity(self):
        panel, names = ld.demo_panel(n_days=120, n_stocks=50)
        sig = ld.build_signals(panel, names, ld.Config(), hot=None)
        self.assertEqual(int(sig["score"].notna().sum().sum()), 0)

    def test_halt_filter_drops_names_near_threshold(self):
        panel, names = ld.demo_panel(n_days=200, n_stocks=80)
        cfg = ld.Config(start="20240101", leader_mode="boards")
        sig = ld.build_signals(panel, names, cfg, hot=None)
        _, tr_all = ld.run_backtest(panel, names, sig, cfg)
        cfg.halt10_cap, cfg.halt30_cap = 1.0, 1.0   # 极严：几乎全部剔除
        _, tr_strict = ld.run_backtest(panel, names, sig, cfg)
        self.assertLessEqual(len(tr_strict), len(tr_all))


class LeaderDipBuildTest(unittest.TestCase):
    def test_build_writes_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir, out_dir = Path(tmp) / "data", Path(tmp) / "out"
            write_demo_dir(data_dir)
            payload = build_leader_dip.build(data_dir, out_dir, "20240301")
            self.assertEqual(payload["version"], "leader-dip-v2")
            self.assertFalse(payload["coverage"]["sources"]["is_wencai"])
            self.assertEqual(payload["coverage"]["scanned"], 120)
            self.assertEqual(set(payload["strategies"]), {"main"})
            for key in ("main",):
                st = payload["strategies"][key]
                self.assertEqual(set(st["periods"]), {"全区间", "前半段", "后半段"})
                self.assertIn("can_open_next_day", st["signal"])
                self.assertTrue(st["nav"])
            self.assertTrue(payload["variants"][0]["label"].startswith("基准"))
            text = (out_dir / "leader_dip.json").read_text(encoding="utf-8")
            self.assertNotIn("NaN", text)
            json.loads(text)
            self.assertTrue((out_dir / "leader_dip.js").read_text(encoding="utf-8").startswith("window.LEADER_DIP_DATA = "))

    def test_build_refuses_without_popularity(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            write_demo_dir(data_dir, n_days=150, n_stocks=30)
            for f in (data_dir / "hot").iterdir():
                f.unlink()
            (data_dir / "hot").rmdir()
            with self.assertRaises(RuntimeError):
                build_leader_dip.build(data_dir, Path(tmp) / "out", "20240301")


if __name__ == "__main__":
    unittest.main()
