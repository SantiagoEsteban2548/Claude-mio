"""Investigacion sin contaminar el out-of-sample.

Fases:
1. ``research``: SOLO datos < oos_start. Grid de familias x ejecucion, walk-forward expansivo
   (seleccion con el pasado, test en los 6 meses siguientes) y congelado de la mejor config.
2. ``oos``: una unica corrida con la config congelada sobre [oos_start, fin]. Deja un lock.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.scalping.data import resample
from src.scalping.engine import EngineCfg, simulate
from src.scalping.metrics import Metrics, compute
from src.scalping.signals import EXEC_GRID, GRIDS, atr, make_signal

OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
WARMUP_BARS = 600
MIN_TRADES_SELECT = 100
WF_STARTS = [pd.Timestamp(x, tz="UTC") for x in ("2023-01-01", "2023-07-01", "2024-01-01", "2024-07-01")]
WF_LEN = pd.DateOffset(months=6)


@dataclass(frozen=True)
class Config:
    family: str
    params: tuple[tuple[str, float], ...]
    tf: str
    stop_atr: float
    max_hold: int

    @property
    def key(self) -> str:
        return f"{self.family}|{dict(self.params)}|{self.tf}|sl{self.stop_atr}|h{self.max_hold}"

    def engine(self, base: EngineCfg) -> EngineCfg:
        return EngineCfg(**{**base.__dict__, "stop_atr": self.stop_atr, "max_hold": self.max_hold})

    def to_json(self) -> dict:
        return {
            "family": self.family,
            "params": dict(self.params),
            "tf": self.tf,
            "stop_atr": self.stop_atr,
            "max_hold": self.max_hold,
        }

    @staticmethod
    def from_json(d: dict) -> Config:
        return Config(d["family"], tuple(sorted(d["params"].items())), d["tf"], d["stop_atr"], d["max_hold"])


def all_configs() -> list[Config]:
    out = []
    for fam, grid in GRIDS.items():
        for p, e in itertools.product(grid, EXEC_GRID):
            out.append(Config(fam, tuple(sorted(p.items())), e["tf"], e["stop_atr"], e["max_hold"]))
    return out


@dataclass
class Run:
    ts: pd.DatetimeIndex
    r: np.ndarray
    outcome: np.ndarray

    def window(self, start: pd.Timestamp | None, end: pd.Timestamp | None) -> Run:
        m = np.ones(len(self.r), dtype=bool)
        if start is not None:
            m &= self.ts >= start
        if end is not None:
            m &= self.ts < end
        return Run(self.ts[m], self.r[m], self.outcome[m])

    def metrics(self, rr: float) -> Metrics:
        return compute(self.r, self.outcome, self.ts, rr)


def clip(
    data: dict[str, pd.DataFrame], start: pd.Timestamp | None, end: pd.Timestamp | None
) -> dict[str, pd.DataFrame]:
    out = {}
    for s, df in data.items():
        d = df
        if end is not None:
            d = d[d.index < end]
        if start is not None:
            d = d[d.index >= start]
        out[s] = d
    return out


def run_config(
    frames: dict[str, dict[str, pd.DataFrame]],
    cfg: Config,
    base: EngineCfg,
    count_from: pd.Timestamp | None = None,
) -> Run:
    """Corre una config sobre todos los simbolos. ``frames[tf][symbol]`` ya remuestreado."""
    ts_all, r_all, o_all = [], [], []
    ecfg = cfg.engine(base)
    for df in frames[cfg.tf].values():
        if len(df) < WARMUP_BARS:
            continue
        sig = make_signal(df, cfg.family, dict(cfg.params))
        t = simulate(
            df["open"].to_numpy(),
            df["high"].to_numpy(),
            df["low"].to_numpy(),
            df["close"].to_numpy(),
            atr(df),
            sig,
            ecfg,
        )
        if len(t):
            ts_all.append(df.index[t.entry_idx])
            r_all.append(t.r_net)
            o_all.append(t.outcome)
    if not r_all:
        return Run(pd.DatetimeIndex([], tz="UTC"), np.array([]), np.array([], dtype=np.int8))
    ts = ts_all[0].append(ts_all[1:]) if len(ts_all) > 1 else ts_all[0]
    order = np.argsort(ts.to_numpy())
    run = Run(ts[order], np.concatenate(r_all)[order], np.concatenate(o_all)[order])
    return run.window(count_from, None) if count_from is not None else run


def prepare_frames(data: dict[str, pd.DataFrame]) -> dict[str, dict[str, pd.DataFrame]]:
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for tf in {e["tf"] for e in EXEC_GRID}:
        out[tf] = {s: (df if tf == "5min" else resample(df, tf)) for s, df in data.items()}
    return out


def score(run: Run) -> float:
    if len(run.r) < MIN_TRADES_SELECT:
        return -np.inf
    sd = run.r.std(ddof=1)
    return float(run.r.mean() / sd * np.sqrt(len(run.r))) if sd > 0 else -np.inf


def research(data: dict[str, pd.DataFrame], base: EngineCfg, oos_start: pd.Timestamp = OOS_START) -> dict:
    data = clip(data, None, oos_start)  # garantia dura: el OOS no entra
    frames = prepare_frames(data)
    configs = all_configs()
    runs = {c.key: run_config(frames, c, base) for c in configs}
    cfgs = {c.key: c for c in configs}

    folds, pooled = [], []
    for start in WF_STARTS:
        end = start + WF_LEN
        if end > oos_start:
            continue
        best = max(runs, key=lambda k: score(runs[k].window(None, start)))
        train = runs[best].window(None, start)
        test = runs[best].window(start, end)
        pooled.append(test)
        folds.append(
            {
                "test_start": str(start.date()),
                "test_end": str(end.date()),
                "config": best,
                "train": train.metrics(base.rr).as_dict(),
                "test": test.metrics(base.rr).as_dict(),
            }
        )
    wf = (
        Run(
            pooled[0].ts.append([p.ts for p in pooled[1:]]),
            np.concatenate([p.r for p in pooled]),
            np.concatenate([p.outcome for p in pooled]),
        )
        if pooled
        else None
    )

    best_key = max(runs, key=lambda k: score(runs[k]))
    full = runs[best_key]
    top = sorted(runs, key=lambda k: score(runs[k]), reverse=True)[:10]
    return {
        "oos_start": str(oos_start.date()),
        "configs_tested": len(configs),
        "symbols": sorted(data),
        "walk_forward": folds,
        "walk_forward_pooled": wf.metrics(base.rr).as_dict() if wf is not None else None,
        "frozen": cfgs[best_key].to_json(),
        "frozen_in_sample": full.metrics(base.rr).as_dict(),
        "top10_in_sample": [{"config": k, **runs[k].metrics(base.rr).as_dict()} for k in top],
        "engine": base.__dict__,
    }


def verdict(m: Metrics, min_trades: int = 200) -> dict:
    checks = {
        "win_rate_gt_35pct": m.win_rate > 0.35,
        "wr_ci_low_gt_breakeven": m.wr_ci_low > m.breakeven_wr,
        "expectancy_positive": m.expectancy_r > 0,
        f"trades_ge_{min_trades}": m.trades >= min_trades,
    }
    return {"checks": checks, "pass": all(checks.values())}


def oos(
    data: dict[str, pd.DataFrame], frozen: dict, base: EngineCfg, oos_start: pd.Timestamp = OOS_START
) -> dict:
    cfg = Config.from_json(frozen)
    warm = {s: df[df.index < oos_start].tail(WARMUP_BARS * 3) for s, df in data.items()}
    tail = {s: df[df.index >= oos_start] for s, df in data.items()}
    merged = {s: pd.concat([warm[s], tail[s]]) for s in data}
    run = run_config(prepare_frames(merged), cfg, base, count_from=oos_start)
    m = run.metrics(base.rr)
    quarters = {}
    for q, idx in pd.Series(np.arange(len(run.r)), index=run.ts).groupby(
        run.ts.tz_localize(None).to_period("Q")
    ):
        sub = Run(run.ts[idx.to_numpy()], run.r[idx.to_numpy()], run.outcome[idx.to_numpy()])
        quarters[str(q)] = sub.metrics(base.rr).as_dict()
    return {
        "config": cfg.key,
        "oos_start": str(oos_start.date()),
        "metrics": m.as_dict(),
        "by_quarter": quarters,
        "verdict": verdict(m),
    }


def data_fingerprint(data: dict[str, pd.DataFrame]) -> str:
    h = hashlib.sha256()
    for s in sorted(data):
        h.update(s.encode())
        h.update(str(len(data[s])).encode())
        h.update(str(data[s].index[-1]).encode())
    return h.hexdigest()[:16]


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
