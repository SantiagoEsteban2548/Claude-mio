"""Metricas en multiplos de R, intervalos de confianza y equity con riesgo fijo por trade."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.scalping.engine import LOSS, WIN


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


@dataclass
class Metrics:
    trades: int
    win_rate: float  # % de trades que llegan al objetivo (3R)
    wr_ci_low: float
    wr_ci_high: float
    expectancy_r: float  # R neto medio por trade (incluye costos)
    t_stat: float
    profit_factor: float
    max_dd_r: float
    breakeven_wr: float  # WR necesario para rr dado, con el costo medio observado
    trades_per_day: float
    est_daily_return: float  # con riesgo fijo por trade, sin compounding

    def as_dict(self) -> dict:
        return asdict(self)


def compute(
    r: np.ndarray, outcome: np.ndarray, ts: pd.DatetimeIndex, rr: float = 3.0, risk_pct: float = 0.005
) -> Metrics:
    n = len(r)
    if n == 0:
        return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    wins = int((outcome == WIN).sum())
    lo, hi = wilson(wins, n)
    mean, sd = float(r.mean()), float(r.std(ddof=1)) if n > 1 else 0.0
    gp, gl = float(r[r > 0].sum()), float(-r[r < 0].sum())
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    days = max((ts.max() - ts.min()).days, 1) if len(ts) else 1
    losses = r[outcome == LOSS]
    avg_cost_r = float(np.mean(-1.0 - losses)) if len(losses) else 0.0  # en un stop: r = -1 - costo
    return Metrics(
        trades=n,
        win_rate=wins / n,
        wr_ci_low=lo,
        wr_ci_high=hi,
        expectancy_r=mean,
        t_stat=mean / sd * math.sqrt(n) if sd > 0 else 0.0,
        profit_factor=gp / gl if gl > 0 else float("inf"),
        max_dd_r=dd,
        breakeven_wr=(1 + avg_cost_r) / (rr + 1),
        trades_per_day=n / days,
        est_daily_return=mean * risk_pct * n / days,
    )
