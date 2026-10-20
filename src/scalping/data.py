"""Datos historicos de futuros perpetuos (Binance Vision) y carga a DataFrame OHLCV UTC.

Descarga mensual 2021 -> hoy; el mes en curso (sin archivo mensual) se completa con archivos diarios.
Binance paso los timestamps de microsegundos en spot desde 2025: se detecta la unidad por magnitud.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

import aiohttp
import pandas as pd

BASE = "https://data.binance.vision/data/futures/um"
OHLCV = ["open", "high", "low", "close", "volume"]


def months(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_klines_csv(raw: bytes) -> pd.DataFrame:
    """CSV de klines (con o sin encabezado) -> DataFrame indexado por apertura UTC."""
    df = pd.read_csv(io.BytesIO(raw), header=None, usecols=range(6))
    if not str(df.iloc[0, 0]).lstrip("-").isdigit():  # fila de encabezado
        df = df.iloc[1:]
    df.columns = ["ts", *OHLCV]
    df = df.astype({"ts": "int64", **{c: "float64" for c in OHLCV}})
    unit = "us" if df["ts"].iloc[0] > 10**14 else "ms"
    df.index = pd.to_datetime(df.pop("ts"), unit=unit, utc=True)
    df.index.name = "ts"
    return df


def parse_zip(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return parse_klines_csv(z.read(z.namelist()[0]))


async def _get(session: aiohttp.ClientSession, url: str) -> bytes | None:
    async with session.get(url) as r:
        if r.status == 404:
            return None
        r.raise_for_status()
        return await r.read()


async def download_symbol(
    session: aiohttp.ClientSession, symbol: str, interval: str, start: date, end: date, out: Path
) -> pd.DataFrame:
    sem = asyncio.Semaphore(6)

    async def month(y: int, m: int) -> list[pd.DataFrame]:
        async with sem:
            url = f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{y}-{m:02d}.zip"
            blob = await _get(session, url)
            if blob is not None:
                return [parse_zip(blob)]
            frames = []  # mes incompleto: dias sueltos
            d = date(y, m, 1)
            while d.month == m and d <= end:
                u = f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d.isoformat()}.zip"
                b = await _get(session, u)
                if b is not None:
                    frames.append(parse_zip(b))
                d += timedelta(days=1)
            return frames

    parts = await asyncio.gather(*(month(y, m) for y, m in months(start, end)))
    frames = [f for p in parts for f in p]
    if not frames:
        raise RuntimeError(f"Sin datos para {symbol} {interval}")
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated()]
    out.mkdir(parents=True, exist_ok=True)
    df.to_pickle(out / f"{symbol}_{interval}.pkl.gz")
    return df


def load_cached(symbol: str, interval: str, folder: Path) -> pd.DataFrame:
    return pd.read_pickle(folder / f"{symbol}_{interval}.pkl.gz")


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """5m -> 15m etc. Las barras quedan etiquetadas por su apertura (sin mirar el futuro)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(rule, label="left", closed="left").agg(agg).dropna()
