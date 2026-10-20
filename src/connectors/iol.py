"""Conector InvertirOnline REST API v2 (OAuth2 + token bucket).

Los nombres de campos siguen la documentacion publica de IOL (https://api.invertironline.com).
Verificalos contra tu cuenta antes de operar en live: IOL puede cambiar el payload.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import aiohttp

from src.connectors.base import ConnectorError, MarketConnector
from src.connectors.ratelimit import TokenBucket
from src.core.clock import now_art
from src.core.instruments import get_instrument
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

# El access_token de IOL dura ~15-20 min: se renueva con margen antes de vencer.
REFRESH_MARGIN_SECONDS = 120.0
MAX_TOKEN_AGE_SECONDS = 12 * 60.0

_IOL_STATUS = {
    "iniciada": OrderStatus.NEW,
    "en_curso": OrderStatus.PARTIAL,
    "parcialmente_terminada": OrderStatus.PARTIAL,
    "terminada": OrderStatus.FILLED,
    "cancelada": OrderStatus.CANCELLED,
    "rechazada": OrderStatus.REJECTED,
    "vencida": OrderStatus.CANCELLED,
}


class IOLConnector(MarketConnector):
    name = "iol"

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str = "https://api.invertironline.com",
        rate_per_sec: float = 3.0,
        burst: int = 5,
        poll_interval: float = 1.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__()
        self._username = username
        self._password = password
        self._base = base_url.rstrip("/")
        self._bucket = TokenBucket(rate_per_sec, burst)
        self._poll_interval = poll_interval
        self._session = session
        self._owns_session = session is None
        self._access: str | None = None
        self._refresh: str | None = None
        self._expires_at = 0.0
        self._issued_at = 0.0
        self._auth_lock = asyncio.Lock()

    # ---------- ciclo de vida ----------
    async def connect(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        await self._login()

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
        self._session = None

    # ---------- OAuth2 ----------
    async def _token_request(self, data: dict[str, str]) -> None:
        assert self._session is not None
        t0 = time.perf_counter()
        async with self._session.post(f"{self._base}/token", data=data) as r:
            self.latency.record(time.perf_counter() - t0)
            if r.status != 200:
                raise ConnectorError(f"IOL auth HTTP {r.status}: {(await r.text())[:200]}")
            body = await r.json()
        now = time.monotonic()
        self._access = body["access_token"]
        self._refresh = body.get("refresh_token", self._refresh)
        self._issued_at = now
        self._expires_at = now + float(body.get("expires_in", 900))

    async def _login(self) -> None:
        await self._token_request(
            {"username": self._username, "password": self._password, "grant_type": "password"}
        )

    async def _refresh_token(self) -> None:
        if not self._refresh:
            return await self._login()
        try:
            await self._token_request({"refresh_token": self._refresh, "grant_type": "refresh_token"})
        except ConnectorError:
            log.warning("refresh_token rechazado; re-login con credenciales")
            await self._login()

    def _needs_refresh(self) -> bool:
        now = time.monotonic()
        return (
            self._access is None
            or now >= self._expires_at - REFRESH_MARGIN_SECONDS
            or now - self._issued_at >= MAX_TOKEN_AGE_SECONDS
        )

    async def _ensure_token(self) -> str:
        if self._needs_refresh():
            async with self._auth_lock:
                if self._needs_refresh():  # otro task pudo haberlo renovado
                    await self._refresh_token()
        assert self._access is not None
        return self._access

    # ---------- HTTP con rate limit, 401 y 429 ----------
    async def _request(self, method: str, path: str, *, retries: int = 3, **kwargs: Any) -> Any:
        assert self._session is not None, "connect() no fue llamado"
        for attempt in range(retries + 1):
            await self._bucket.acquire()
            token = await self._ensure_token()
            headers = {"Authorization": f"Bearer {token}"}
            t0 = time.perf_counter()
            async with self._session.request(method, f"{self._base}{path}", headers=headers, **kwargs) as r:
                self.latency.record(time.perf_counter() - t0)
                if r.status == 401 and attempt < retries:
                    async with self._auth_lock:
                        await self._refresh_token()
                    continue
                if r.status == 429 and attempt < retries:
                    wait = float(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                    self._bucket.penalize(wait)
                    continue
                if r.status >= 400:
                    raise ConnectorError(f"IOL {method} {path} HTTP {r.status}: {(await r.text())[:200]}")
                if r.content_type == "application/json":
                    return await r.json()
                return await r.text()
        raise ConnectorError(f"IOL {method} {path}: reintentos agotados")

    # ---------- datos de mercado ----------
    async def get_order_book(self, symbol: str, settlement: Settlement) -> OrderBook:
        inst = get_instrument(symbol)
        data = await self._request(
            "GET",
            f"/api/v2/{inst.market}/Titulos/{symbol}/Cotizacion",
            params={
                "model.simbolo": symbol,
                "model.mercado": inst.market,
                "model.plazo": settlement.iol_plazo,
            },
        )
        return parse_iol_book(symbol, settlement, data)

    async def stream_books(self, subscriptions: list[tuple[str, Settlement]]) -> AsyncIterator[OrderBook]:
        while True:
            started = time.monotonic()
            results = await asyncio.gather(
                *(self.get_order_book(s, p) for s, p in subscriptions), return_exceptions=True
            )
            for res in results:
                if isinstance(res, OrderBook):
                    yield res
                else:
                    log.warning("error de cotizacion IOL: %s", res)
            await asyncio.sleep(max(0.0, self._poll_interval - (time.monotonic() - started)))

    async def get_caucion_rates(self) -> tuple[float, float] | None:
        data = await self._request("GET", "/api/v2/Cotizaciones/cauciones/argentina/Todas")
        return parse_iol_caucion(data)

    # ---------- cuenta ----------
    async def get_account(self) -> AccountState:
        est = await self._request("GET", "/api/v2/estadocuenta")
        port = await self._request("GET", "/api/v2/portafolio/argentina")
        cash_ars = cash_usd = 0.0
        for c in est.get("cuentas", []):
            amount = float(c.get("disponible", 0.0))
            moneda = str(c.get("moneda", "")).lower()
            if "peso" in moneda:
                cash_ars += amount
            elif "dolar" in moneda:
                cash_usd += amount
        holdings = {a["titulo"]["simbolo"]: float(a.get("cantidad", 0.0)) for a in port.get("activos", [])}
        return AccountState(cash_ars=cash_ars, cash_usd=cash_usd, holdings=holdings)

    # ---------- ordenes ----------
    async def place_order(
        self, symbol: str, settlement: Settlement, side: Side, qty: float, price: float
    ) -> str:
        inst = get_instrument(symbol)
        validez = (now_art() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = {
            "mercado": inst.market,
            "simbolo": symbol,
            "cantidad": qty,
            "precio": price,
            "plazo": settlement.iol_plazo,
            "validez": validez,
            "tipoOrden": "precioLimite",
        }
        action = "Comprar" if side is Side.BUY else "Vender"
        resp = await self._request("POST", f"/api/v2/operar/{action}", json=body)
        if not resp.get("ok", False):
            raise ConnectorError(f"IOL rechazo la orden: {resp.get('messages')}")
        num = resp.get("numeroOperacion")
        if num is None:  # IOL informa el numero dentro de messages[].description
            m = re.search(r"\d{4,}", " ".join(str(x) for x in resp.get("messages", [])))
            num = m.group(0) if m else None
        if num is None:
            raise ConnectorError(f"No se pudo obtener numero de operacion: {resp}")
        return str(num)

    async def cancel_order(self, broker_id: str) -> None:
        await self._request("DELETE", f"/api/v2/operaciones/{broker_id}")

    async def get_order(self, broker_id: str) -> Order:
        d = await self._request("GET", f"/api/v2/operaciones/{broker_id}")
        fills = d.get("operaciones", []) or []
        filled = sum(float(f.get("cantidad", 0)) for f in fills)
        avg = (
            sum(float(f.get("cantidad", 0)) * float(f.get("precio", 0)) for f in fills) / filled
            if filled
            else 0.0
        )
        status = _IOL_STATUS.get(str(d.get("estadoActual", "")).lower(), OrderStatus.NEW)
        return Order(
            symbol=d.get("simbolo", ""),
            settlement=Settlement.CI if str(d.get("plazo", "t0")).lower() == "t0" else Settlement.H24,
            side=Side.BUY if str(d.get("tipo", "")).lower().startswith("compra") else Side.SELL,
            qty=float(d.get("cantidad", 0)) or 1.0,
            price=float(d.get("precio", 0)) or 1.0,
            status=status,
            filled_qty=filled,
            avg_price=avg,
            ts=now_art(),
            broker_id=broker_id,
        )


def parse_iol_book(symbol: str, settlement: Settlement, data: dict[str, Any]) -> OrderBook:
    bids: list[BookLevel] = []
    asks: list[BookLevel] = []
    for p in data.get("puntas") or []:
        pb, qb = float(p.get("precioCompra") or 0), float(p.get("cantidadCompra") or 0)
        pv, qv = float(p.get("precioVenta") or 0), float(p.get("cantidadVenta") or 0)
        if pb > 0:
            bids.append(BookLevel(price=pb, size=qb))
        if pv > 0:
            asks.append(BookLevel(price=pv, size=qv))
    last = data.get("ultimoPrecio")
    vol = data.get("volumenNominal")
    return OrderBook(
        symbol=symbol,
        settlement=settlement,
        bids=bids,
        asks=asks,
        ts=now_art(),
        last=float(last) if last else None,
        cum_volume=float(vol) if vol is not None else None,
    )


def parse_iol_caucion(data: dict[str, Any]) -> tuple[float, float] | None:
    """Toma la caucion a 1 dia: colocadora = tasa menor, tomadora = tasa mayor (TNA)."""
    for t in data.get("titulos", []):
        if str(t.get("plazo", "")).strip() in ("1", "1 dia", "1 día"):
            rates = [float(t[k]) for k in ("ultimoPrecio",) if t.get(k)]
            for p in t.get("puntas") or []:
                rates += [float(p[k]) for k in ("precioCompra", "precioVenta") if p.get(k)]
            if rates:
                return min(rates) / 100.0, max(rates) / 100.0
    return None
