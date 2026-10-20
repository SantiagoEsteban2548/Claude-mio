"""Conector Primary / Matba Rofex (API Matriz): Market Data L2 por WebSocket + ordenes REST.

Es el mismo protocolo que usa ``pyRofex`` por debajo; se implementa directo sobre aiohttp para
mantener todo en un unico event loop asincrono (pyRofex usa threads y callbacks sincronicos).
El ruteo FIX nativo requiere credenciales y un engine FIX dedicado: queda fuera de este conector
(las ordenes viajan por REST autenticado, el camino soportado sin acuerdo FIX).
Verifica los payloads contra https://apihub.primary.com.ar antes de operar en live.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from src.connectors.base import ConnectorError, MarketConnector
from src.core.clock import now_art
from src.core.models import (
    AccountState,
    BookLevel,
    Order,
    OrderBook,
    OrderStatus,
    Settlement,
    Side,
)

log = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 20 * 3600.0  # el token de Primary dura ~24h; renovamos antes
_STATUS = {
    "NEW": OrderStatus.NEW,
    "PENDING_NEW": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIAL,
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
}


class RofexPrimaryConnector(MarketConnector):
    name = "rofex"

    def __init__(
        self,
        username: str,
        password: str,
        account: str,
        base_url: str = "https://api.primary.com.ar",
        ws_url: str = "wss://api.primary.com.ar/",
        market_id: str = "ROFX",
        depth: int = 5,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__()
        self._user, self._pass, self._account = username, password, account
        self._base = base_url.rstrip("/")
        self._ws_url = ws_url
        self._market = market_id
        self._depth = depth
        self._session = session
        self._owns_session = session is None
        self._token: str | None = None
        self._token_at = 0.0
        self._books: dict[str, OrderBook] = {}

    async def connect(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        await self._login()

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
        self._session = None

    async def _login(self) -> None:
        assert self._session is not None
        t0 = time.perf_counter()
        async with self._session.post(
            f"{self._base}/auth/getToken",
            headers={"X-Username": self._user, "X-Password": self._pass},
        ) as r:
            self.latency.record(time.perf_counter() - t0)
            token = r.headers.get("X-Auth-Token")
            if r.status != 200 or not token:
                raise ConnectorError(f"Primary auth HTTP {r.status}")
        self._token, self._token_at = token, time.monotonic()

    async def _headers(self) -> dict[str, str]:
        if self._token is None or time.monotonic() - self._token_at > TOKEN_TTL_SECONDS:
            await self._login()
        assert self._token is not None
        return {"X-Auth-Token": self._token}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self._session is not None
        t0 = time.perf_counter()
        async with self._session.get(
            f"{self._base}{path}", headers=await self._headers(), params=params
        ) as r:
            self.latency.record(time.perf_counter() - t0)
            if r.status >= 400:
                raise ConnectorError(f"Primary GET {path} HTTP {r.status}")
            data: dict[str, Any] = await r.json()
        if data.get("status") not in (None, "OK"):
            raise ConnectorError(f"Primary GET {path}: {data}")
        return data

    # ---------- market data ----------
    async def get_order_book(self, symbol: str, settlement: Settlement) -> OrderBook:
        data = await self._get(
            "/rest/marketdata/get",
            {
                "marketId": self._market,
                "symbol": symbol,
                "entries": "BI,OF,LA,TV",
                "depth": self._depth,
            },
        )
        return parse_md(
            {"instrumentId": {"symbol": symbol}, "marketData": data.get("marketData", {})},
            settlement,
        )

    async def stream_books(self, subscriptions: list[tuple[str, Settlement]]) -> AsyncIterator[OrderBook]:
        symbols = sorted({s for s, _ in subscriptions})
        backoff = 1.0
        while True:
            try:
                async for book in self._ws_session(symbols):
                    backoff = 1.0
                    yield book
            except (aiohttp.ClientError, ConnectorError, TimeoutError) as e:
                log.warning("WS Primary caido (%s); reconectando en %.0fs", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _ws_session(self, symbols: list[str]) -> AsyncIterator[OrderBook]:
        assert self._session is not None
        async with self._session.ws_connect(
            self._ws_url, headers=await self._headers(), heartbeat=20.0
        ) as ws:
            await ws.send_str(json.dumps(subscribe_message(symbols, self._market, self._depth)))
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    if payload.get("type") == "Md":
                        book = parse_md(payload, Settlement.CI)
                        self._books[book.symbol] = book
                        yield book
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise ConnectorError("WebSocket cerrado")

    # ---------- cuenta y ordenes ----------
    async def get_account(self) -> AccountState:
        d = await self._get(f"/rest/risk/accountReport/{self._account}")
        cash = float(d.get("accountData", {}).get("availableToCollateral", 0.0))
        return AccountState(cash_ars=cash)

    async def place_order(
        self, symbol: str, settlement: Settlement, side: Side, qty: float, price: float
    ) -> str:
        d = await self._get(
            "/rest/order/newSingleOrder",
            {
                "marketId": self._market,
                "symbol": symbol,
                "orderQty": int(qty),
                "price": price,
                "ordType": "Limit",
                "side": "Buy" if side is Side.BUY else "Sell",
                "timeInForce": "Day",
                "account": self._account,
                "cancelPrevious": "false",
            },
        )
        o = d.get("order") or {}
        if "clientId" not in o:
            raise ConnectorError(f"Primary rechazo la orden: {d}")
        return f"{o['clientId']}|{o.get('proprietary', 'api')}"

    async def cancel_order(self, broker_id: str) -> None:
        cl, prop = broker_id.split("|")
        await self._get("/rest/order/cancelById", {"clOrdId": cl, "proprietary": prop})

    async def get_order(self, broker_id: str) -> Order:
        cl, prop = broker_id.split("|")
        d = (await self._get("/rest/order/id", {"clOrdId": cl, "proprietary": prop}))["order"]
        return Order(
            symbol=d["instrumentId"]["symbol"],
            settlement=Settlement.CI,
            side=Side.BUY if str(d.get("side", "")).upper() == "BUY" else Side.SELL,
            qty=float(d.get("orderQty", 1)) or 1.0,
            price=float(d.get("price", 1)) or 1.0,
            status=_STATUS.get(str(d.get("status", "")).upper(), OrderStatus.NEW),
            filled_qty=float(d.get("cumQty", 0)),
            avg_price=float(d.get("avgPx", 0)),
            ts=now_art(),
            broker_id=broker_id,
        )


def subscribe_message(symbols: list[str], market_id: str, depth: int) -> dict[str, Any]:
    return {
        "type": "smd",
        "level": 1,
        "entries": ["BI", "OF", "LA", "TV"],
        "products": [{"symbol": s, "marketId": market_id} for s in symbols],
        "depth": depth,
    }


def parse_md(msg: dict[str, Any], settlement: Settlement) -> OrderBook:
    """Convierte un mensaje 'Md' de Primary en OrderBook (hasta 5 niveles por lado)."""
    md = msg.get("marketData", {})
    bids = [BookLevel(price=x["price"], size=x["size"]) for x in md.get("BI") or [] if x.get("price")]
    asks = [BookLevel(price=x["price"], size=x["size"]) for x in md.get("OF") or [] if x.get("price")]
    la = md.get("LA") or {}
    tv = md.get("TV")
    ts_ms = msg.get("timestamp")
    ts = now_art()
    if ts_ms:
        with contextlib.suppress(ValueError, OSError, OverflowError):
            ts = ts.fromtimestamp(float(ts_ms) / 1000.0, tz=ts.tzinfo)
    cum = tv.get("size") if isinstance(tv, dict) else tv
    return OrderBook(
        symbol=msg["instrumentId"]["symbol"],
        settlement=settlement,
        bids=bids,
        asks=asks,
        ts=ts,
        last=float(la["price"]) if la.get("price") else None,
        cum_volume=float(cum) if cum is not None else None,
    )
