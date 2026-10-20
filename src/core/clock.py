"""Horario de mercado argentino (UTC-3 fijo, Argentina no tiene DST) y calendario habil."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone

ART = timezone(timedelta(hours=-3), name="ART")


def now_art() -> datetime:
    return datetime.now(ART)


def to_art(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=ART)
    return ts.astimezone(ART)


def is_business_day(d: date, holidays: Iterable[date] = ()) -> bool:
    return d.weekday() < 5 and d not in set(holidays)


def next_business_day(d: date, holidays: Iterable[date] = ()) -> date:
    hs = set(holidays)
    nxt = d + timedelta(days=1)
    while not is_business_day(nxt, hs):
        nxt += timedelta(days=1)
    return nxt


def settlement_calendar_days(d: date, holidays: Iterable[date] = ()) -> int:
    """Dias corridos entre liquidar CI (hoy) y 24hs (proximo habil). Viernes -> 3."""
    return (next_business_day(d, holidays) - d).days
