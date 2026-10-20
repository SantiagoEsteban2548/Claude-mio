from datetime import datetime

from src.core.clock import ART
from src.core.models import BookLevel, OrderBook, Settlement


def t(h: int, m: int, s: int = 0, day: int = 20) -> datetime:  # 2026-10-20 = martes
    return datetime(2026, 10, day, h, m, s, tzinfo=ART)


def mk_book(
    sym: str,
    bid: float,
    ask: float,
    ts: datetime,
    st: Settlement = Settlement.CI,
    bsize: float = 10_000,
    asize: float = 10_000,
    last: float | None = None,
    vol: float | None = None,
) -> OrderBook:
    return OrderBook(
        symbol=sym,
        settlement=st,
        bids=[BookLevel(price=bid, size=bsize), BookLevel(price=bid * 0.999, size=bsize)],
        asks=[BookLevel(price=ask, size=asize), BookLevel(price=ask * 1.001, size=asize)],
        ts=ts,
        last=last,
        cum_volume=vol,
    )
