"""Simulador de PaperTrading: matchea contra las puntas reales y descuenta comisiones exactas."""

from __future__ import annotations

from typing import Protocol

from src.core.instruments import get_instrument
from src.core.models import Fill, Order, OrderBook, OrderStatus, Side
from src.fee_engine.engine import FeeEngine


class Broker(Protocol):
    """Contrato que usa el orquestador (PaperBroker en paper/backtest, LiveBroker en live)."""

    async def submit(
        self, order: Order, book: OrderBook, closing: bool = False
    ) -> tuple[Order, list[Fill]]: ...
    async def cancel_all(self) -> int: ...
    async def cancel(self, order_id: str) -> None: ...
    def open_orders(self) -> list[Order]: ...
    def available(self, symbol: str) -> float: ...
    def on_book(self, book: OrderBook) -> list[Fill]: ...


class PaperBroker:
    """Reglas de matching:
    - Una orden limite ejecutable consume niveles del libro opuesto hasta su precio limite.
    - Si el libro no alcanza, el remanente queda en reposo y solo se llena cuando una punta
      posterior cruza el limite (sin prioridad de cola: supuesto conservador).
    - No hay ventas en descubierto salvo futuros: se rechaza vender mas que el inventario.
    """

    def __init__(self, fee_engine: FeeEngine, inventory: dict[str, float] | None = None) -> None:
        self.fees = fee_engine
        self.inventory: dict[str, float] = dict(inventory or {})
        self._resting: dict[str, tuple[Order, bool]] = {}

    # ---- helpers ----
    def available(self, symbol: str) -> float:
        return self.inventory.get(symbol, 0.0)

    def open_orders(self) -> list[Order]:
        return [o for o, _ in self._resting.values()]

    async def cancel(self, order_id: str) -> None:
        entry = self._resting.pop(order_id, None)
        if entry is not None:
            entry[0].status = OrderStatus.CANCELLED

    async def cancel_all(self) -> int:
        n = len(self._resting)
        for o, _ in self._resting.values():
            o.status = OrderStatus.CANCELLED
        self._resting.clear()
        return n

    def _match(self, order: Order, book: OrderBook, closing: bool) -> list[Fill]:
        inst = get_instrument(order.symbol)
        remaining = order.qty - order.filled_qty
        fills: list[Fill] = []
        for lv in book.side_levels(order.side):
            if remaining <= 0:
                break
            ok_price = lv.price <= order.price if order.side is Side.BUY else lv.price >= order.price
            if not ok_price:
                break
            take = min(remaining, lv.size)
            if take <= 0:
                continue
            fee = float(
                self.fees.leg_cost(
                    inst.asset_class, inst.notional(take, lv.price), closing_same_day=closing
                ).fees
            )
            fills.append(
                Fill(
                    order_id=order.id,
                    strategy=order.strategy,
                    symbol=order.symbol,
                    settlement=order.settlement,
                    side=order.side,
                    qty=take,
                    price=lv.price,
                    fee=fee,
                    ts=book.ts,
                )
            )
            remaining -= take
        self._apply(order, fills)
        return fills

    def _apply(self, order: Order, fills: list[Fill]) -> None:
        for f in fills:
            prev = order.filled_qty * order.avg_price
            order.filled_qty += f.qty
            order.avg_price = (prev + f.qty * f.price) / order.filled_qty
            order.fee += f.fee
            self.inventory[f.symbol] = self.inventory.get(f.symbol, 0.0) + f.qty * f.side.sign
        if order.filled_qty >= order.qty - 1e-12:
            order.status = OrderStatus.FILLED
        elif order.filled_qty > 0:
            order.status = OrderStatus.PARTIAL

    # ---- API ----
    async def submit(self, order: Order, book: OrderBook, closing: bool = False) -> tuple[Order, list[Fill]]:
        inst = get_instrument(order.symbol)
        if order.side is Side.SELL and not inst.shortable and order.qty > self.available(order.symbol) + 1e-9:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "sin inventario para vender (no se permite venta en corto)"
            return order, []
        fills = self._match(order, book, closing)
        if order.status.is_open:
            self._resting[order.id] = (order, closing)
        return order, fills

    def on_book(self, book: OrderBook) -> list[Fill]:
        fills: list[Fill] = []
        for oid, (order, closing) in list(self._resting.items()):
            if order.symbol != book.symbol or order.settlement != book.settlement:
                continue
            fills += self._match(order, book, closing)
            if not order.status.is_open:
                del self._resting[oid]
        return fills
