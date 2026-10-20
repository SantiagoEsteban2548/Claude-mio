"""Ingesta de datos: CSV histórico, validación y alineación causal de timeframes."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


def timeframe_to_timedelta(tf: str) -> pd.Timedelta:
    units = {"m": "min", "h": "h", "d": "D", "w": "W"}
    return pd.to_timedelta(int(tf[:-1]), unit=units[tf[-1]])


def load_csv(path: str | Path, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[OHLCV].astype(float).sort_index()
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index < pd.Timestamp(end, tz="UTC")]
    validate_ohlcv(df)
    return df


def validate_ohlcv(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("sin datos")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("índice desordenado o con duplicados")
    if df[OHLCV].isna().any().any():
        raise ValueError("NaN en OHLCV")
    body_hi = df[["open", "close"]].max(axis=1)
    body_lo = df[["open", "close"]].min(axis=1)
    if ((df.high < body_hi) | (df.low > body_lo)).any():
        raise ValueError("velas con high/low inconsistentes")


def bar_step(df: pd.DataFrame) -> pd.Timedelta:
    return pd.Series(df.index).diff().mode().iloc[0]


def htf_series(df: pd.DataFrame, rule: str, fn) -> pd.Series:
    """Calcula `fn(htf_ohlcv) -> Series` en el timeframe superior y la alinea a `df` sin look-ahead.

    Cada vela de `df` (etiquetada por su apertura) recibe el último valor de una vela HTF que ya
    estaba CERRADA cuando cerró esa vela de `df`.
    """
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    htf = df.resample(rule, label="right", closed="left").agg(agg).dropna()  # etiqueta = hora de cierre
    values = fn(htf)
    ltf_close_time = df.index + bar_step(df)
    aligned = values.reindex(values.index.union(ltf_close_time)).ffill().reindex(ltf_close_time)
    aligned.index = df.index
    return aligned
