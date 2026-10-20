"""Modulo A: arbitraje de plazos (T+0 vs T+1) y de ratio AL30/GD30 por reversion a la media."""

from __future__ import annotations

from collections import deque
from datetime import datetime

from src.core.clock import settlement_calendar_days, to_art
from src.core.models import Leg, OrderBook, Settlement, Side, Signal
from src.execution.positions import PositionManager
from src.strategies.base import Strategy, rolling_stats
from src.strategies.state import MarketState


class TermArbitrage(Strategy):
    """Compra CI / vende 24hs: el spread de plazos es un prestamo implicito.

    Rinde si  bid24/ask_CI - 1  supera la tasa de colocacion (caucion colocadora) prorrateada
    por los dias corridos hasta T+1 (viernes -> 3 dias) mas todos los costos. El caso inverso
    (vender CI / comprar 24hs) solo se habilita con inventario propio (allow_sell_inventory).
    """

    name = "A1_term_arb"

    def __init__(
        self,
        symbols: list[str],
        *,
        max_age: float = 3.0,
        cooldown_seconds: float = 20.0,
        allow_sell_inventory: bool = False,
    ) -> None:
        self.symbols = symbols
        self.max_age = max_age
        self.cooldown = cooldown_seconds
        self.allow_sell_inventory = allow_sell_inventory
        self._last: dict[str, datetime] = {}

    @property
    def subscriptions(self) -> list[tuple[str, Settlement]]:
        return [(s, p) for s in self.symbols for p in (Settlement.CI, Settlement.H24)]

    def on_book(self, book: OrderBook, state: MarketState, positions: PositionManager) -> list[Signal]:
        sym = book.symbol
        if sym not in self.symbols:
            return []
        now = book.ts
        last = self._last.get(sym)
        if last and (to_art(now) - to_art(last)).total_seconds() < self.cooldown:
            return []
        ci = state.book(sym, Settlement.CI, now=now, max_age=self.max_age)
        h24 = state.book(sym, Settlement.H24, now=now, max_age=self.max_age)
        if ci is None or h24 is None:
            return []
        days = settlement_calendar_days(to_art(now).date(), state.holidays)
        rate_col = state.caucion_colocadora_tna * days / 365.0
        assert ci.best_ask and ci.best_bid and h24.best_ask and h24.best_bid
        signals: list[Signal] = []

        gross = h24.best_bid.price / ci.best_ask.price - 1.0
        if gross > rate_col:
            signals.append(
                Signal(
                    strategy=self.name,
                    legs=[
                        Leg(
                            symbol=sym, settlement=Settlement.CI, side=Side.BUY, limit_price=ci.best_ask.price
                        ),
                        Leg(
                            symbol=sym,
                            settlement=Settlement.H24,
                            side=Side.SELL,
                            limit_price=h24.best_bid.price,
                        ),
                    ],
                    expected_gross_pct=gross,
                    financing_cost_pct=rate_col,
                    atomic=True,
                    reason=f"carry CI->24hs {gross:.4%} vs caucion {rate_col:.4%} ({days}d)",
                    ts=now,
                )
            )
        if self.allow_sell_inventory:
            gross_inv = (ci.best_bid.price - h24.best_ask.price) / ci.best_bid.price
            if gross_inv + rate_col > 0 and positions is not None:
                signals.append(
                    Signal(
                        strategy=self.name,
                        legs=[
                            Leg(
                                symbol=sym,
                                settlement=Settlement.CI,
                                side=Side.SELL,
                                limit_price=ci.best_bid.price,
                            ),
                            Leg(
                                symbol=sym,
                                settlement=Settlement.H24,
                                side=Side.BUY,
                                limit_price=h24.best_ask.price,
                            ),
                        ],
                        expected_gross_pct=gross_inv,
                        financing_cost_pct=-rate_col,  # colocamos el efectivo en caucion
                        atomic=True,
                        reason=f"venta CI/recompra 24hs {gross_inv:.4%} + caucion {rate_col:.4%}",
                        ts=now,
                    )
                )
        if signals:
            self._last[sym] = now
        return signals


class RatioArbitrage(Strategy):
    """Arbitraje estadistico del ratio AL30/GD30 (CI) con Z-score en ventana movil."""

    name = "A2_ratio_zscore"

    def __init__(
        self,
        leg_a: str = "AL30",
        leg_b: str = "GD30",
        *,
        window: int = 300,
        min_samples: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        stop_z: float = 4.0,
        max_age: float = 3.0,
        sample_every: float = 1.0,
    ) -> None:
        self.a, self.b = leg_a, leg_b
        self.window, self.min_samples = window, min_samples
        self.entry_z, self.exit_z, self.stop_z = entry_z, exit_z, stop_z
        self.max_age = max_age
        self.sample_every = sample_every
        self.ratios: deque[float] = deque(maxlen=window)
        self._last_sample: datetime | None = None
        self.open_side: str | None = None  # "short_ratio" (vende A, compra B) | "long_ratio"
        self.last_z: float | None = None
        self._pending_side: str | None = None

    @property
    def subscriptions(self) -> list[tuple[str, Settlement]]:
        return [(self.a, Settlement.CI), (self.b, Settlement.CI)]

    def on_book(self, book: OrderBook, state: MarketState, positions: PositionManager) -> list[Signal]:
        if book.symbol not in (self.a, self.b):
            return []
        now = book.ts
        ba = state.book(self.a, Settlement.CI, now=now, max_age=self.max_age)
        bb = state.book(self.b, Settlement.CI, now=now, max_age=self.max_age)
        if ba is None or bb is None:
            return []
        assert ba.mid and bb.mid and ba.best_bid and ba.best_ask and bb.best_bid and bb.best_ask

        pos_a = positions.get(self.name, self.a, Settlement.CI)
        if self.open_side and (pos_a is None or pos_a.qty == 0):
            self.open_side = None  # cierre forzoso externo

        if (
            self._last_sample is None
            or (to_art(now) - to_art(self._last_sample)).total_seconds() >= self.sample_every
        ):
            self.ratios.append(ba.mid / bb.mid)
            self._last_sample = now
        if len(self.ratios) < self.min_samples:
            return []
        mean, std = rolling_stats(list(self.ratios))
        if std <= 0:
            return []
        z = (ba.mid / bb.mid - mean) / std
        self.last_z = z

        if self.open_side:
            if abs(z) <= self.exit_z or abs(z) >= self.stop_z:
                return [self._exit_signal(ba, bb, now, positions, z)]
            return []
        if abs(z) < self.entry_z:
            return []
        if z > 0:  # A cara vs B: vender A, comprar B
            r_exec = ba.best_bid.price / bb.best_ask.price
            legs = [
                Leg(symbol=self.a, side=Side.SELL, limit_price=ba.best_bid.price),
                Leg(symbol=self.b, side=Side.BUY, limit_price=bb.best_ask.price),
            ]
            side = "short_ratio"
            edge = r_exec / mean - 1.0
        else:
            r_exec = ba.best_ask.price / bb.best_bid.price
            legs = [
                Leg(symbol=self.a, side=Side.BUY, limit_price=ba.best_ask.price),
                Leg(symbol=self.b, side=Side.SELL, limit_price=bb.best_bid.price),
            ]
            side = "long_ratio"
            edge = 1.0 - r_exec / mean
        if edge <= 0:
            return []
        sig = Signal(
            strategy=self.name,
            legs=legs,
            expected_gross_pct=edge,
            reason=f"z={z:+.2f} ratio={ba.mid / bb.mid:.5f} media={mean:.5f}",
            ts=now,
        )
        self._pending_side = side
        return [sig]

    def on_result(self, signal: Signal, executed: bool) -> None:
        if signal.is_exit:
            if executed:
                self.open_side = None
        elif executed:
            self.open_side = self._pending_side

    def _exit_signal(
        self, ba: OrderBook, bb: OrderBook, now: datetime, positions: PositionManager, z: float
    ) -> Signal:
        assert ba.best_bid and ba.best_ask and bb.best_bid and bb.best_ask
        if self.open_side == "short_ratio":  # estabamos cortos A, largos B
            legs = [
                Leg(symbol=self.a, side=Side.BUY, limit_price=ba.best_ask.price),
                Leg(symbol=self.b, side=Side.SELL, limit_price=bb.best_bid.price),
            ]
        else:
            legs = [
                Leg(symbol=self.a, side=Side.SELL, limit_price=ba.best_bid.price),
                Leg(symbol=self.b, side=Side.BUY, limit_price=bb.best_ask.price),
            ]
        return Signal(
            strategy=self.name,
            legs=legs,
            expected_gross_pct=0.0,
            is_exit=True,
            reason=f"salida z={z:+.2f}",
            ts=now,
        )
