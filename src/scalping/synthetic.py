"""Datos SINTETICOS para validar la maquinaria. No representan ningun mercado."""

from __future__ import annotations

import numpy as np
import pandas as pd


def random_walk(
    seed: int = 0,
    start: str = "2021-01-01",
    end: str = "2022-01-01",
    drift: float = 0.0,
    base_vol: float = 0.0015,
    p0: float = 100.0,
) -> pd.DataFrame:
    """OHLCV 5m: retornos t-student con volatilidad agrupada (GARCH-like), sin predictibilidad."""
    idx = pd.date_range(start, end, freq="5min", tz="UTC", inclusive="left")
    n = len(idx)
    rng = np.random.default_rng(seed)
    vol = np.empty(n)
    v = base_vol
    shocks = rng.standard_t(4, n) / np.sqrt(2.0)
    for i in range(n):
        vol[i] = v
        v = 0.95 * v + 0.05 * base_vol * abs(shocks[i]) / 0.8
    ret = drift + vol * shocks
    close = p0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[p0], close[:-1]])
    wick = np.abs(rng.standard_normal((n, 2))) * vol[:, None] * 0.5
    high = np.maximum(open_, close) * (1 + wick[:, 0])
    low = np.minimum(open_, close) * (1 - wick[:, 1])
    volume = rng.lognormal(3, 0.6, n) * (1 + 30 * vol / base_vol * 0.05)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )
