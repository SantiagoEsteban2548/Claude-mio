"""Generador sintetico de libros para probar el pipeline sin datos grabados.

NO representa el mercado real: sirve para humo/CI. El backtest valido usa libros grabados
con ``--mode paper`` (se persisten en SQLite) para respetar spreads bid-ask reales.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from src.core.clock import ART
from src.core.models import BookLevel, OrderBook, Settlement


def _book(
    sym: str,
    st: Settlement,
    ts: datetime,
    mid: float,
    spread: float,
    size: float,
    skew: float,
    last: float,
    cum_vol: float,
) -> OrderBook:
    half = mid * spread / 2
    bids = [
        BookLevel(price=round(mid - half - i * half, 2), size=size * (1 + skew) / (i + 1)) for i in range(5)
    ]
    asks = [
        BookLevel(price=round(mid + half + i * half, 2), size=size * (1 - skew) / (i + 1)) for i in range(5)
    ]
    return OrderBook(symbol=sym, settlement=st, bids=bids, asks=asks, ts=ts, last=last, cum_volume=cum_vol)


def generate(day: date, seed: int = 7, step_seconds: int = 5) -> Iterator[OrderBook]:
    rng = random.Random(seed + day.toordinal())
    t = datetime.combine(day, time(11, 0), tzinfo=ART)
    end = datetime.combine(day, time(16, 55), tzinfo=ART)
    al30, ratio, ggal, mep = 60_000.0, 1.0, 9_000.0, 1_400.0
    vol_ggal = vol_al = 0.0
    skew_g = 0.0
    while t < end:
        al30 *= math.exp(rng.gauss(0, 0.0004))
        ratio += -0.15 * (ratio - 1.0) + rng.gauss(0, 0.0008)
        gd30 = al30 / ratio
        skew_g = 0.9 * skew_g + rng.gauss(0, 0.2)
        ggal *= math.exp(rng.gauss(0, 0.0006) + 0.0004 * skew_g)
        mep *= math.exp(rng.gauss(0, 0.0001))
        vol_ggal += abs(rng.gauss(500, 200))
        vol_al += abs(rng.gauss(2_000, 800))
        carry = 0.0003 + rng.gauss(0, 0.0002)
        yield _book("AL30", Settlement.CI, t, al30, 0.0010, 50_000, 0.0, al30, vol_al)
        yield _book("AL30", Settlement.H24, t, al30 * (1 + carry), 0.0010, 50_000, 0.0, al30, vol_al)
        yield _book("GD30", Settlement.CI, t, gd30, 0.0010, 50_000, 0.0, gd30, vol_al)
        yield _book("GD30", Settlement.H24, t, gd30 * (1 + carry), 0.0010, 50_000, 0.0, gd30, vol_al)
        yield _book("AL30D", Settlement.CI, t, al30 / mep, 0.0012, 50_000, 0.0, al30 / mep, vol_al)
        yield _book(
            "GGAL", Settlement.CI, t, ggal, 0.0015, 3_000, max(-0.9, min(0.9, skew_g)), ggal, vol_ggal
        )
        t += timedelta(seconds=step_seconds)
