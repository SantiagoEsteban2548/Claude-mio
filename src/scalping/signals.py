"""Generadores de senales causales: la senal en la barra i usa solo datos <= i (entrada en i+1)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(
        axis=1
    )
    return tr.ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def breakout_volume(df: pd.DataFrame, n: int, vol_mult: float, trend: int = 200) -> np.ndarray:
    """Ruptura del rango de n barras previas con volumen anomalo a favor de la tendencia."""
    hh = df["high"].rolling(n).max().shift(1)
    ll = df["low"].rolling(n).min().shift(1)
    vol_ok = df["volume"] > vol_mult * df["volume"].rolling(n).mean().shift(1)
    tr = ema(df["close"], trend)
    long = (df["close"] > hh) & vol_ok & (df["close"] > tr)
    short = (df["close"] < ll) & vol_ok & (df["close"] < tr)
    return (long.astype(np.int8) - short.astype(np.int8)).to_numpy()


def pullback_trend(df: pd.DataFrame, fast: int, slow: int, level: float) -> np.ndarray:
    """Tendencia (EMA rapida vs lenta) + RSI que recupera `level` tras un retroceso."""
    c = df["close"]
    r = rsi(c)
    up = ema(c, fast) > ema(c, slow)
    dn = ~up
    long = up & (r.shift(1) < level) & (r >= level)
    short = dn & (r.shift(1) > 100 - level) & (r <= 100 - level)
    return (long.astype(np.int8) - short.astype(np.int8)).to_numpy()


def zscore_reversion(df: pd.DataFrame, n: int, z: float) -> np.ndarray:
    """Cierre en extremo estadistico (z-score) y la barra siguiente-confirmacion: vela de rebote."""
    c = df["close"]
    zs = (c - c.rolling(n).mean()) / c.rolling(n).std()
    bounce_up = c > df["open"]
    bounce_dn = c < df["open"]
    long = (zs.shift(1) < -z) & bounce_up
    short = (zs.shift(1) > z) & bounce_dn
    return (long.astype(np.int8) - short.astype(np.int8)).to_numpy()


def make_signal(df: pd.DataFrame, family: str, p: dict) -> np.ndarray:
    if family == "breakout":
        return breakout_volume(df, p["n"], p["vol_mult"])
    if family == "pullback":
        return pullback_trend(df, p["fast"], p["slow"], p["level"])
    if family == "reversion":
        return zscore_reversion(df, p["n"], p["z"])
    raise ValueError(family)


GRIDS: dict[str, list[dict[str, Any]]] = {
    "breakout": [{"n": n, "vol_mult": v} for n in (20, 40, 80) for v in (1.5, 2.5)],
    "pullback": [
        {"fast": f, "slow": s, "level": lv} for f in (20, 50) for s in (100, 200) for lv in (35, 45)
    ],
    "reversion": [{"n": n, "z": z} for n in (20, 50) for z in (2.0, 2.5, 3.0)],
}
EXEC_GRID: list[dict[str, Any]] = [
    {"tf": tf, "stop_atr": sa, "max_hold": mh}
    for tf in ("5min", "15min")
    for sa in (1.0, 2.0)
    for mh in (24, 48)
]
