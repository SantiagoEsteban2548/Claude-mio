"""Modulo B: tasa implicita Dolar MEP spot vs Futuro Rofex vs LECAP/caucion.

Tasa implicita ejecutable (vendiendo el futuro y comprando dolar MEP sintetico):
    mep_compra  = ask(AL30) / bid(AL30D)          # comprar AL30 en pesos, vender AL30D en USD
    tna_impl    = (bid(futuro) / mep_compra - 1) * 365 / dias_al_vencimiento
Se opera la reversion de picos intradiarios: se abre cuando la tasa implicita supera su media
movil en ``entry_z`` desvios Y excede la tasa libre de riesgo (LECAP/caucion) + ``min_spread_tna``.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

from src.core.clock import to_art
from src.core.models import Leg, OrderBook, Settlement, Side, Signal
from src.execution.positions import PositionManager
from src.strategies.base import Strategy, rolling_stats
from src.strategies.state import MarketState


class SyntheticRate(Strategy):
    name = "B_synth_rate"

    def __init__(
        self,
        future_symbol: str,
        *,
        window: int = 300,
        min_samples: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        min_spread_tna: float = 0.03,
        max_age: float = 3.0,
        sample_every: float = 1.0,
    ) -> None:
        self.fut = future_symbol
        self.window, self.min_samples = window, min_samples
        self.entry_z, self.exit_z = entry_z, exit_z
        self.min_spread_tna = min_spread_tna
        self.max_age = max_age
        self.sample_every = sample_every
        self.rates: deque[float] = deque(maxlen=window)
        self._last_sample: datetime | None = None
        self.open = False
        self.last_z: float | None = None
        self.last_tna: float | None = None

    @property
    def subscriptions(self) -> list[tuple[str, Settlement]]:
        return [(self.fut, Settlement.CI), ("AL30", Settlement.CI), ("AL30D", Settlement.CI)]

    def on_book(self, book: OrderBook, state: MarketState, positions: PositionManager) -> list[Signal]:
        if book.symbol not in (self.fut, "AL30", "AL30D") or state.future_expiry is None:
            return []
        now = book.ts
        today = to_art(now).date()
        days = (state.future_expiry - today).days
        if days <= 0:
            return []
        f = state.book(self.fut, Settlement.CI, now=now, max_age=self.max_age)
        a = state.book("AL30", Settlement.CI, now=now, max_age=self.max_age)
        d = state.book("AL30D", Settlement.CI, now=now, max_age=self.max_age)
        if f is None or a is None or d is None:
            return []
        assert f.mid and a.mid and d.mid
        assert f.best_bid and f.best_ask and a.best_bid and a.best_ask and d.best_bid and d.best_ask

        if self.open and not any(p.strategy == self.name for p in positions.open_positions()):
            self.open = False

        mid_tna = (f.mid / (a.mid / d.mid) - 1.0) * 365.0 / days
        self.last_tna = mid_tna
        if (
            self._last_sample is None
            or (to_art(now) - to_art(self._last_sample)).total_seconds() >= self.sample_every
        ):
            self.rates.append(mid_tna)
            self._last_sample = now
        if len(self.rates) < self.min_samples:
            return []
        mean, std = rolling_stats(list(self.rates))
        if std <= 0:
            return []
        z = (mid_tna - mean) / std
        self.last_z = z

        if self.open:
            if z <= self.exit_z:
                return [self._exit(f, a, d, now, z)]
            return []

        mep_buy = a.best_ask.price / d.best_bid.price
        exec_tna = (f.best_bid.price / mep_buy - 1.0) * 365.0 / days
        hurdle = state.hurdle_tna(today)
        if z < self.entry_z or exec_tna < hurdle + self.min_spread_tna:
            return []
        edge = (exec_tna - mean) * days / 365.0  # convergencia a la tasa media
        if edge <= 0:
            return []
        return [
            Signal(
                strategy=self.name,
                legs=[
                    Leg(symbol=self.fut, side=Side.SELL, limit_price=f.best_bid.price),
                    Leg(symbol="AL30", side=Side.BUY, limit_price=a.best_ask.price),
                    Leg(symbol="AL30D", side=Side.SELL, limit_price=d.best_bid.price),
                ],
                expected_gross_pct=edge,
                reason=f"tna_impl={exec_tna:.2%} z={z:+.2f} libre_riesgo={hurdle:.2%}",
                ts=now,
            )
        ]

    def on_result(self, signal: Signal, executed: bool) -> None:
        if executed:
            self.open = not signal.is_exit

    def _exit(self, f: OrderBook, a: OrderBook, d: OrderBook, now: datetime, z: float) -> Signal:
        assert f.best_ask and a.best_bid and d.best_ask
        return Signal(
            strategy=self.name,
            legs=[
                Leg(symbol=self.fut, side=Side.BUY, limit_price=f.best_ask.price),
                Leg(symbol="AL30", side=Side.SELL, limit_price=a.best_bid.price),
                Leg(symbol="AL30D", side=Side.BUY, limit_price=d.best_ask.price),
            ],
            expected_gross_pct=0.0,
            is_exit=True,
            reason=f"salida z={z:+.2f}",
            ts=now,
        )
