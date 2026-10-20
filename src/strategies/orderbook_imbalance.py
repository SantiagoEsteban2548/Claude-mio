"""Modulo C: scalping intradiario por desbalance del libro (OBI) + VWAP + volatilidad realizada.

Solo largo (sin venta en corto minorista). Objetivo bruto 0.6%-1.2%, stop a la mitad del objetivo.
Las salidas (take-profit / stop / tiempo maximo / cierre forzoso 16:30-16:45) las ejecuta el
orquestador a partir de los parametros que viajan en la senal.

NOTA: ``win_prob`` es una heuristica monotona en la fuerza del desbalance; DEBE calibrarse con
backtest sobre libros reales antes de confiar en el sizing de Kelly.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from src.core.clock import to_art
from src.core.models import Leg, OrderBook, Settlement, Side, Signal
from src.execution.positions import PositionManager
from src.strategies.base import Strategy, rolling_stats
from src.strategies.state import MarketState


def book_imbalance(book: OrderBook, depth: int = 5) -> float:
    """(V_bid - V_ask) / (V_bid + V_ask) ponderado 1/(i+1) por nivel. Rango [-1, 1]."""
    wb = sum(lv.size / (i + 1) for i, lv in enumerate(book.bids[:depth]))
    wa = sum(lv.size / (i + 1) for i, lv in enumerate(book.asks[:depth]))
    tot = wb + wa
    return 0.0 if tot == 0 else (wb - wa) / tot


@dataclass
class _SymbolState:
    mids: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    imbs: deque[float] = field(default_factory=lambda: deque(maxlen=5))
    cum_pv: float = 0.0
    cum_v: float = 0.0
    last_cum_volume: float | None = None
    last_signal: datetime | None = None

    def vwap(self) -> float | None:
        if self.cum_v > 0:
            return self.cum_pv / self.cum_v
        return sum(self.mids) / len(self.mids) if self.mids else None

    def realized_vol(self) -> float | None:
        """Desvio de los retornos logaritmicos entre muestras consecutivas."""
        m = list(self.mids)
        if len(m) < 20:
            return None
        rets = [math.log(m[i] / m[i - 1]) for i in range(1, len(m))]
        return rolling_stats(rets)[1]


class OrderBookImbalance(Strategy):
    name = "C_obi_scalp"

    def __init__(
        self,
        symbols: list[str] | None = None,
        *,
        imbalance_threshold: float = 0.5,
        vwap_tolerance: float = 0.003,
        min_target: float = 0.006,
        max_target: float = 0.012,
        stop_ratio: float = 0.5,
        max_hold_seconds: int = 1200,
        cooldown_seconds: float = 120.0,
        max_age: float = 3.0,
        min_vol: float = 0.0002,
        max_vol: float = 0.006,
    ) -> None:
        self.symbols = symbols or ["GGAL", "AL30"]
        self.imb_thr = imbalance_threshold
        self.vwap_tol = vwap_tolerance
        self.min_target, self.max_target = min_target, max_target
        self.stop_ratio = stop_ratio
        self.max_hold = max_hold_seconds
        self.cooldown = cooldown_seconds
        self.max_age = max_age
        self.min_vol, self.max_vol = min_vol, max_vol
        self._st: dict[str, _SymbolState] = {s: _SymbolState() for s in self.symbols}

    @property
    def subscriptions(self) -> list[tuple[str, Settlement]]:
        return [(s, Settlement.CI) for s in self.symbols]

    def on_book(self, book: OrderBook, state: MarketState, positions: PositionManager) -> list[Signal]:
        if book.symbol not in self._st or book.settlement is not Settlement.CI:
            return []
        if not book.is_two_sided or book.is_crossed:
            return []
        st = self._st[book.symbol]
        assert book.mid and book.best_ask
        st.mids.append(book.mid)
        st.imbs.append(book_imbalance(book))
        if book.last and book.cum_volume is not None:
            if st.last_cum_volume is not None and book.cum_volume > st.last_cum_volume:
                dv = book.cum_volume - st.last_cum_volume
                st.cum_pv += book.last * dv
                st.cum_v += dv
            st.last_cum_volume = book.cum_volume

        pos = positions.get(self.name, book.symbol, Settlement.CI)
        if pos is not None and pos.qty != 0:
            return []
        if st.last_signal and ((to_art(book.ts) - to_art(st.last_signal)).total_seconds() < self.cooldown):
            return []
        if len(st.imbs) < 3 or MarketState.age(book, book.ts) > self.max_age:
            return []

        imb = sum(list(st.imbs)[-3:]) / 3
        vwap, vol = st.vwap(), st.realized_vol()
        if vwap is None or vol is None or imb < self.imb_thr:
            return []
        if not self.min_vol <= vol <= self.max_vol:
            return []
        if book.mid > vwap * (1.0 + self.vwap_tol):
            return []  # no perseguir precio extendido sobre VWAP

        # objetivo escalado por volatilidad (horizonte ~ 30 muestras), acotado a 0.6%-1.2%
        target = min(self.max_target, max(self.min_target, vol * math.sqrt(30) * 2.0))
        stop = target * self.stop_ratio
        score = min(1.0, (imb - self.imb_thr) / (1.0 - self.imb_thr))
        p = 0.45 + 0.30 * score
        ev = p * target - (1.0 - p) * stop
        st.last_signal = book.ts
        return [
            Signal(
                strategy=self.name,
                legs=[Leg(symbol=book.symbol, side=Side.BUY, limit_price=book.best_ask.price)],
                expected_gross_pct=ev,
                win_prob=p,
                take_profit_pct=target,
                stop_loss_pct=stop,
                max_hold_seconds=self.max_hold,
                reason=f"OBI={imb:+.2f} vwap={vwap:.2f} vol={vol:.4%} tp={target:.2%} sl={stop:.2%}",
                ts=book.ts,
            )
        ]
