"""Importador de CSV exportados a mano desde TradingView + control de calidad de datos.

TradingView no ofrece API publica de historicos; este modulo solo lee archivos que EXPORTA la persona
usuaria (Export chart data). Los formatos varian: `time` puede ser ISO con offset, texto sin zona
(zona del grafico -> `tz`) o UNIX en segundos/milisegundos; las columnas pueden venir en distinto caso
y con indicadores extra, que se ignoran.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


def parse_tradingview_csv(path: str | Path, tz: str = "UTC") -> pd.DataFrame:
    raw = pd.read_csv(path)
    raw.columns = [str(c).strip().lower() for c in raw.columns]
    if "time" not in raw.columns:
        raise ValueError("El CSV no tiene columna 'time' (¿es un export de TradingView?)")
    for c in ("open", "high", "low", "close"):
        if c not in raw.columns:
            raise ValueError(f"Falta la columna '{c}'")
    vol_col = next((c for c in raw.columns if c == "volume"), None)
    t = raw["time"]
    if pd.api.types.is_numeric_dtype(t):
        unit = "ms" if float(t.iloc[0]) > 1e11 else "s"
        idx = pd.to_datetime(t, unit=unit, utc=True)
    else:
        idx = pd.to_datetime(t, utc=False)
        idx = idx.dt.tz_localize(tz) if idx.dt.tz is None else idx
        idx = idx.dt.tz_convert("UTC")
    df = pd.DataFrame(
        {
            "open": raw["open"].astype(float),
            "high": raw["high"].astype(float),
            "low": raw["low"].astype(float),
            "close": raw["close"].astype(float),
            "volume": raw[vol_col].astype(float) if vol_col else 0.0,
        }
    )
    df.index = pd.DatetimeIndex(idx, name="ts")
    return df.sort_index()


def infer_step(df: pd.DataFrame) -> pd.Timedelta:
    return pd.Timedelta(df.index.to_series().diff().dropna().median())


def to_5m(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza a barras de 5m. Acepta 1m/3m/5m; mas grueso no se puede reconstruir."""
    step = infer_step(df)
    if step > pd.Timedelta(minutes=5):
        raise ValueError(f"Timeframe {step} > 5m: no se puede derivar 5m. Exporta 5m o menos.")
    if step == pd.Timedelta(minutes=5):
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample("5min", label="left", closed="left").agg(agg).dropna()


@dataclass
class Quality:
    bars: int
    start: str
    end: str
    duplicates: int
    bad_ohlc: int
    gaps: int
    largest_gap_minutes: float
    zero_volume_pct: float
    coverage_pct: float  # barras presentes / barras esperadas de 5m entre inicio y fin

    @property
    def ok(self) -> bool:
        return self.bad_ohlc == 0 and self.duplicates == 0 and self.coverage_pct >= 98.0

    def as_dict(self) -> dict:
        return asdict(self)


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Elimina duplicados y barras con OHLC invalido. Devuelve (df, duplicados, invalidas)."""
    dups = int(df.index.duplicated().sum())
    df = df[~df.index.duplicated(keep="last")].sort_index()
    ok = (
        (df[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (df["high"] >= df[["open", "close"]].max(axis=1))
        & (df["low"] <= df[["open", "close"]].min(axis=1))
        & np.isfinite(df[OHLCV]).all(axis=1)
    )
    return df[ok], dups, int((~ok).sum())


def quality(df: pd.DataFrame, dups: int = 0, bad: int = 0) -> Quality:
    step = pd.Timedelta(minutes=5)
    delta = df.index.to_series().diff().dropna()
    gaps = delta[delta > step]
    expected = int((df.index[-1] - df.index[0]) / step) + 1
    return Quality(
        bars=len(df),
        start=str(df.index[0]),
        end=str(df.index[-1]),
        duplicates=dups,
        bad_ohlc=bad,
        gaps=len(gaps),
        largest_gap_minutes=float(gaps.max().total_seconds() / 60) if len(gaps) else 0.0,
        zero_volume_pct=float((df["volume"] == 0).mean() * 100),
        coverage_pct=len(df) / expected * 100,
    )


def import_file(path: str | Path, symbol: str, out_dir: str | Path, tz: str = "UTC") -> Quality:
    df = to_5m(parse_tradingview_csv(path, tz))
    df, dups, bad = clean(df)
    q = quality(df, dups, bad)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_pickle(out / f"{symbol}_5m.pkl.gz")
    return q
