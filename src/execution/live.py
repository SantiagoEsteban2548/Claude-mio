"""LiveBroker: envia ordenes reales por el conector correspondiente y sigue su estado."""

from __future__ import annotations

import asyncio
import logging

from src.connectors.base import ConnectorError, MarketConnector
from src.core.instruments import get_instrument
from src.core.models import Fill, Order, OrderBook, OrderStatus, Side
from src.fee_engine.engine import FeeEngine

log = logging.getLogger(__name__)


class LiveBroker:
    def __init__(
        self,
        connectors: dict[str, MarketConnector],
        fee_engine: FeeEngine,
        fill_timeout: float = 3.0,
        poll: float = 0.4,
    ) -> None:
        self.connectors = connectors  # mercado ("bCBA", "ROFX") -> conector
        self.fees = fee_engine
        self.fill_timeout = fill_timeout
        self.poll = poll
        self.holdings: dict[str, float] = {}
        self._open: dict[str, tuple[Order, MarketConnector]] = {}

    def _connector(self, symbol: str) -> MarketConnector:
        return self.connectors[get_instrument(symbol).market]

    def available(self, symbol: str) -> float:
        return self.holdings.get(symbol, 0.0)

    def open_orders(self) -> list[Order]:
        return [o for o, _ in self._open.values()]

    def on_book(self, book: OrderBook) -> list[Fill]:
        return []  # los fills se confirman consultando al broker en submit()

    async def refresh_holdings(self) -> None:
        for c in set(self.connectors.values()):
            self.holdings.update((await c.get_account()).holdings)

    async def submit(self, order: Order, book: OrderBook, closing: bool = False) -> tuple[Order, list[Fill]]:
        inst = get_instrument(order.symbol)
        if order.side is Side.SELL and not inst.shortable and order.qty > self.available(order.symbol):
            order.status = OrderStatus.REJECTED
            order.reject_reason = "sin tenencia para vender"
            return order, []
        conn = self._connector(order.symbol)
        try:
            order.broker_id = await conn.place_order(
                order.symbol, order.settlement, order.side, order.qty, order.price
            )
        except ConnectorError as e:
            order.status, order.reject_reason = OrderStatus.REJECTED, str(e)
            return order, []
        self._open[order.id] = (order, conn)

        deadline = asyncio.get_running_loop().time() + self.fill_timeout
        remote = await conn.get_order(order.broker_id)
        while remote.status.is_open and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self.poll)
            remote = await conn.get_order(order.broker_id)
        if remote.status.is_open:  # no se lleno a tiempo: cancelar el remanente
            await conn.cancel_order(order.broker_id)
            remote = await conn.get_order(order.broker_id)

        fills: list[Fill] = []
        if remote.filled_qty > 0:
            fee = float(
                self.fees.leg_cost(
                    inst.asset_class,
                    inst.notional(remote.filled_qty, remote.avg_price),
                    closing_same_day=closing,
                ).fees
            )
            fills.append(
                Fill(
                    order_id=order.id,
                    strategy=order.strategy,
                    symbol=order.symbol,
                    settlement=order.settlement,
                    side=order.side,
                    qty=remote.filled_qty,
                    price=remote.avg_price,
                    fee=fee,
                    ts=order.ts,
                )
            )
            order.filled_qty, order.avg_price, order.fee = remote.filled_qty, remote.avg_price, fee
            self.holdings[order.symbol] = (
                self.holdings.get(order.symbol, 0.0) + remote.filled_qty * order.side.sign
            )
        order.status = remote.status if remote.status is not OrderStatus.NEW else OrderStatus.CANCELLED
        if not order.status.is_open:
            self._open.pop(order.id, None)
        return order, fills

    async def cancel(self, order_id: str) -> None:
        entry = self._open.pop(order_id, None)
        if entry and entry[0].broker_id:
            await entry[1].cancel_order(entry[0].broker_id)

    async def cancel_all(self) -> int:
        n = 0
        for oid, (order, conn) in list(self._open.items()):
            try:
                if order.broker_id:
                    await conn.cancel_order(order.broker_id)
                    n += 1
            except ConnectorError as e:
                log.error("no se pudo cancelar %s: %s", oid, e)
            self._open.pop(oid, None)
        return n
