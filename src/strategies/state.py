"""Estado de mercado compartido: ultimos libros, tasas de referencia y conversiones FX."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from src.core.clock import to_art
from src.core.models import Currency, OrderBook, Settlement


class LecapQuote:
    """LECAP/BONCAP: TNA implicita desde precio por 100 VN y pago final."""

    def __init__(self, symbol: str, maturity: date, payoff_per_100: float) -> None:
        self.symbol = symbol
        self.maturity = maturity
        self.payoff = payoff_per_100

    def tna(self, price_per_100: float, today: date, settle_days: int = 0) -> float | None:
        days = (self.maturity - today).days - settle_days
        if days <= 0 or price_per_100 <= 0:
            return None
        return (self.payoff / price_per_100 - 1.0) * 365.0 / days


class MarketState:
    def __init__(
        self,
        *,
        caucion_colocadora_tna: float,
        caucion_tomadora_tna: float,
        lecaps: Sequence[LecapQuote] = (),
        holidays: Sequence[date] = (),
        future_symbol: str | None = None,
        future_expiry: date | None = None,
    ) -> None:
        self.books: dict[tuple[str, Settlement], OrderBook] = {}
        self.caucion_colocadora_tna = caucion_colocadora_tna
        self.caucion_tomadora_tna = caucion_tomadora_tna
        self.lecaps = list(lecaps)
        self.holidays = list(holidays)
        self.future_symbol = future_symbol
        self.future_expiry = future_expiry
        self._last_mep: float | None = None

    def update(self, book: OrderBook) -> None:
        self.books[book.key] = book

    def book(
        self,
        symbol: str,
        settlement: Settlement,
        *,
        now: datetime | None = None,
        max_age: float | None = None,
    ) -> OrderBook | None:
        b = self.books.get((symbol, settlement))
        if b is None or not b.is_two_sided or b.is_crossed:
            return None
        if now is not None and max_age is not None and self.age(b, now) > max_age:
            return None
        return b

    @staticmethod
    def age(book: OrderBook, now: datetime) -> float:
        return abs((to_art(now) - to_art(book.ts)).total_seconds())

    def mep(self) -> float | None:
        """Dolar MEP implicito = AL30 (ARS) / AL30D (USD), contado inmediato."""
        a, d = self.books.get(("AL30", Settlement.CI)), self.books.get(("AL30D", Settlement.CI))
        if a and d and a.mid and d.mid:
            self._last_mep = a.mid / d.mid
        return self._last_mep

    def ccl(self) -> float | None:
        a, c = self.books.get(("AL30", Settlement.CI)), self.books.get(("AL30C", Settlement.CI))
        return a.mid / c.mid if a and c and a.mid and c.mid else None

    def fx(self, currency: Currency) -> float | None:
        """ARS por unidad de la moneda del instrumento."""
        if currency is Currency.ARS:
            return 1.0
        return self.mep() if currency is Currency.USD_MEP else self.ccl()

    def lecap_tna(self, today: date) -> float | None:
        rates = []
        for lc in self.lecaps:
            b = self.books.get((lc.symbol, Settlement.CI))
            if b and b.mid:
                r = lc.tna(b.mid, today)
                if r is not None:
                    rates.append(r)
        return sum(rates) / len(rates) if rates else None

    def hurdle_tna(self, today: date) -> float:
        """Tasa libre de riesgo de referencia: LECAP si hay datos, si no caucion colocadora."""
        return self.lecap_tna(today) or self.caucion_colocadora_tna
