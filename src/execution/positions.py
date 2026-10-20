"""Posiciones abiertas por (estrategia, especie, plazo) con P&L en moneda del instrumento."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.core.instruments import get_instrument
from src.core.models import Fill, OrderBook, Settlement, Side

Key = tuple[str, str, Settlement]


@dataclass
class Position:
    strategy: str
    symbol: str
    settlement: Settlement
    qty: float = 0.0  # con signo: >0 largo, <0 corto
    avg_price: float = 0.0
    opened_ts: datetime | None = None
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    max_hold_seconds: int | None = None
    entry_fees: float = 0.0

    @property
    def key(self) -> Key:
        return (self.strategy, self.symbol, self.settlement)

    @property
    def side(self) -> Side:
        return Side.BUY if self.qty > 0 else Side.SELL


class PositionManager:
    def __init__(self) -> None:
        self.positions: dict[Key, Position] = {}

    def get(self, strategy: str, symbol: str, settlement: Settlement) -> Position | None:
        return self.positions.get((strategy, symbol, settlement))

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if abs(p.qty) > 1e-12]

    def apply_fill(
        self,
        fill: Fill,
        *,
        take_profit_pct: float | None = None,
        stop_loss_pct: float | None = None,
        max_hold_seconds: int | None = None,
    ) -> float:
        """Aplica un fill y devuelve el P&L bruto realizado (moneda del instrumento)."""
        inst = get_instrument(fill.symbol)
        key: Key = (fill.strategy, fill.symbol, fill.settlement)
        pos = self.positions.get(key)
        if pos is None:
            pos = self.positions[key] = Position(fill.strategy, fill.symbol, fill.settlement)
        signed = fill.qty * fill.side.sign
        realized = 0.0
        if pos.qty == 0 or (pos.qty > 0) == (signed > 0):
            total = abs(pos.qty) + fill.qty
            pos.avg_price = (abs(pos.qty) * pos.avg_price + fill.qty * fill.price) / total
            if pos.qty == 0:
                pos.opened_ts = fill.ts
                pos.take_profit_pct = take_profit_pct
                pos.stop_loss_pct = stop_loss_pct
                pos.max_hold_seconds = max_hold_seconds
            pos.qty += signed
            pos.entry_fees += fill.fee
        else:
            closing = min(abs(pos.qty), fill.qty)
            direction = 1.0 if pos.qty > 0 else -1.0
            realized = direction * closing * (fill.price - pos.avg_price) * inst.multiplier
            pos.qty += signed
            if abs(pos.qty) < 1e-12:
                pos.qty = 0.0
                pos.entry_fees = 0.0
            elif (pos.qty > 0) == (signed > 0):  # dio vuelta la posicion
                pos.avg_price = fill.price
                pos.opened_ts = fill.ts
        return realized

    def unrealized(self, books: dict[tuple[str, Settlement], OrderBook]) -> dict[Key, float]:
        """P&L no realizado a valor de liquidacion (largo -> bid, corto -> ask), moneda instr."""
        out: dict[Key, float] = {}
        for p in self.open_positions():
            b = books.get((p.symbol, p.settlement))
            if b is None:
                continue
            lv = b.touch(Side.SELL if p.qty > 0 else Side.BUY)
            if lv is None:
                continue
            inst = get_instrument(p.symbol)
            out[p.key] = p.qty * (lv.price - p.avg_price) * inst.multiplier
        return out

    def gross_exposure(self, prices: dict[tuple[str, Settlement], float]) -> float:
        """Suma de |qty| * precio * multiplicador en moneda del instrumento (sin FX)."""
        total = 0.0
        for p in self.open_positions():
            px = prices.get((p.symbol, p.settlement), p.avg_price)
            total += abs(p.qty) * px * get_instrument(p.symbol).multiplier
        return total
