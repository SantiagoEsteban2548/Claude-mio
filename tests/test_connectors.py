import asyncio
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.connectors.iol import (
    REFRESH_MARGIN_SECONDS,
    IOLConnector,
    parse_iol_book,
    parse_iol_caucion,
)
from src.connectors.ratelimit import TokenBucket
from src.connectors.rofex import parse_md, subscribe_message
from src.core.models import Settlement, Side


class FakeIOL:
    def __init__(self) -> None:
        self.logins = self.refreshes = self.quotes = 0
        self.fail_429_once = True
        self.expires_in = 1199
        self.orders: list[dict] = []

    async def token(self, req: web.Request) -> web.Response:
        form = await req.post()
        if form["grant_type"] == "password":
            self.logins += 1
        else:
            self.refreshes += 1
            assert form["refresh_token"] == "R"
        return web.json_response(
            {
                "access_token": f"A{self.logins}.{self.refreshes}",
                "refresh_token": "R",
                "expires_in": self.expires_in,
            }
        )

    async def quote(self, req: web.Request) -> web.Response:
        assert req.headers["Authorization"].startswith("Bearer A")
        if self.fail_429_once:
            self.fail_429_once = False
            return web.Response(status=429, headers={"Retry-After": "0"})
        self.quotes += 1
        return web.json_response(
            {
                "ultimoPrecio": 60010,
                "volumenNominal": 1234,
                "puntas": [
                    {"precioCompra": 60000, "cantidadCompra": 500, "precioVenta": 60020, "cantidadVenta": 300}
                ],
            }
        )

    async def buy(self, req: web.Request) -> web.Response:
        self.orders.append(await req.json())
        return web.json_response({"ok": True, "messages": [{"description": "Operacion 123456"}]})


@pytest.fixture
async def iol():
    fake = FakeIOL()
    app = web.Application()
    app.router.add_post("/token", fake.token)
    app.router.add_get("/api/v2/bCBA/Titulos/AL30/Cotizacion", fake.quote)
    app.router.add_post("/api/v2/operar/Comprar", fake.buy)
    server = TestServer(app)
    await server.start_server()
    conn = IOLConnector("u", "p", str(server.make_url("")), rate_per_sec=1000, burst=100)
    await conn.connect()
    yield conn, fake
    await conn.close()
    await server.close()


async def test_login_quote_and_429_retry(iol) -> None:
    conn, fake = iol
    book = await conn.get_order_book("AL30", Settlement.CI)
    assert fake.logins == 1 and fake.quotes == 1  # el 429 se reintento
    assert book.best_bid.price == 60000 and book.best_ask.size == 300
    assert conn.latency.last_ms is not None


async def test_token_is_refreshed_preventively_before_expiry(iol) -> None:
    conn, fake = iol
    await conn.get_order_book("AL30", Settlement.CI)
    conn._expires_at = time.monotonic() + REFRESH_MARGIN_SECONDS - 1  # a punto de vencer
    await conn.get_order_book("AL30", Settlement.CI)
    assert fake.refreshes == 1 and fake.logins == 1


async def test_place_order_returns_operation_number(iol) -> None:
    conn, fake = iol
    oid = await conn.place_order("AL30", Settlement.H24, Side.BUY, 100, 60000)
    assert oid == "123456"
    assert fake.orders[0]["plazo"] == "t1" and fake.orders[0]["tipoOrden"] == "precioLimite"


def test_parse_helpers() -> None:
    b = parse_iol_book(
        "GGAL",
        Settlement.CI,
        {"puntas": [{"precioCompra": 1, "cantidadCompra": 2, "precioVenta": 3, "cantidadVenta": 4}]},
    )
    assert b.mid == 2
    assert parse_iol_caucion(
        {"titulos": [{"plazo": "1", "ultimoPrecio": 30, "puntas": [{"precioCompra": 28, "precioVenta": 33}]}]}
    ) == (0.28, 0.33)
    assert parse_iol_caucion({"titulos": []}) is None


def test_rofex_market_data_parsing() -> None:
    msg = {
        "timestamp": 1760000000000,
        "instrumentId": {"symbol": "DLR/DIC26", "marketId": "ROFX"},
        "marketData": {
            "BI": [{"price": 1500, "size": 10}, {"price": 1499, "size": 5}],
            "OF": [{"price": 1502, "size": 7}],
            "LA": {"price": 1501, "size": 1},
        },
    }
    b = parse_md(msg, Settlement.CI)
    assert b.symbol == "DLR/DIC26" and len(b.bids) == 2 and b.best_ask.price == 1502
    sub = subscribe_message(["DLR/DIC26"], "ROFX", 5)
    assert sub["depth"] == 5 and sub["products"][0]["marketId"] == "ROFX"


async def test_token_bucket_throttles() -> None:
    tb = TokenBucket(rate_per_sec=50, capacity=2)
    t0 = time.perf_counter()
    for _ in range(7):
        await tb.acquire()
    assert time.perf_counter() - t0 >= 0.08  # 5 tokens extra a 50/s ~ 0.1s


async def test_token_bucket_penalty_delays_next_request() -> None:
    tb = TokenBucket(rate_per_sec=100, capacity=5)
    tb.penalize(0.05)
    t0 = time.perf_counter()
    await tb.acquire()
    assert time.perf_counter() - t0 >= 0.04
    await asyncio.sleep(0)
