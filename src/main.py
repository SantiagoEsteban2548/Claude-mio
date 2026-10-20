"""Punto de entrada: python -m src.main --mode {backtest,paper,live}."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable, Iterator
from datetime import date, timedelta

from rich.console import Console
from rich.live import Live

from src.backtest.runner import run_backtest
from src.backtest.synthetic import generate
from src.config.settings import Mode, Settings, get_settings
from src.connectors.base import MarketConnector
from src.connectors.iol import IOLConnector
from src.connectors.rofex import RofexPrimaryConnector
from src.core import instruments
from src.core.models import OrderBook, Settlement
from src.execution.alerts import Alerts
from src.execution.engine import TradingEngine
from src.execution.live import LiveBroker
from src.execution.paper import Broker, PaperBroker
from src.risk.manager import RiskManager
from src.storage.db import Store
from src.strategies.base import Strategy
from src.strategies.orderbook_imbalance import OrderBookImbalance
from src.strategies.state import LecapQuote, MarketState
from src.strategies.synthetic_rate import SyntheticRate
from src.strategies.term_arbitrage import RatioArbitrage, TermArbitrage
from src.ui.dashboard import render

log = logging.getLogger("bot")
LIVE_CONFIRMATION = "OPERAR EN REAL"


def build_state(s: Settings) -> MarketState:
    for lc in s.lecaps:
        instruments.register(instruments.lecap(lc.symbol))
    return MarketState(
        caucion_colocadora_tna=s.caucion_colocadora_tna,
        caucion_tomadora_tna=s.caucion_tomadora_tna,
        lecaps=[LecapQuote(lc.symbol, lc.maturity, lc.payoff_per_100) for lc in s.lecaps],
        holidays=s.holidays,
        future_symbol=s.future_symbol,
        future_expiry=s.future_expiry,
    )


def build_strategies(s: Settings) -> list[Strategy]:
    strategies: list[Strategy] = [
        TermArbitrage(["AL30", "GD30", *[lc.symbol for lc in s.lecaps]]),
        RatioArbitrage("AL30", "GD30"),
        OrderBookImbalance(["GGAL", "AL30"]),
    ]
    if s.future_expiry is not None:
        strategies.append(SyntheticRate(s.future_symbol))
    return strategies


def build_engine(
    s: Settings, broker: Broker, store: Store | None, notify: Callable[[str], None] | None = None
) -> TradingEngine:
    return TradingEngine(
        build_strategies(s),
        build_state(s),
        broker,
        RiskManager(s.risk_config()),
        s.fee_engine(),
        store,
        notify,
    )


def build_connectors(s: Settings, subs: list[tuple[str, Settlement]]) -> dict[str, MarketConnector]:
    out: dict[str, MarketConnector] = {}
    if any(instruments.get_instrument(sym).market == "bCBA" for sym, _ in subs):
        out["bCBA"] = IOLConnector(
            s.iol_username,
            s.iol_password.get_secret_value(),
            s.iol_base_url,
            s.iol_rate_per_sec,
            s.iol_burst,
            s.iol_poll_interval,
        )
    if any(instruments.get_instrument(sym).market == "ROFX" for sym, _ in subs):
        out["ROFX"] = RofexPrimaryConnector(
            s.primary_username,
            s.primary_password.get_secret_value(),
            s.primary_account,
            s.primary_base_url,
            s.primary_ws_url,
        )
    return out


def _missing_credentials(s: Settings, subs: list[tuple[str, Settlement]]) -> list[str]:
    markets = {instruments.get_instrument(sym).market for sym, _ in subs}
    missing: list[str] = []
    if "bCBA" in markets:
        if not s.iol_username:
            missing.append("BOT_IOL_USERNAME")
        if not s.iol_password.get_secret_value():
            missing.append("BOT_IOL_PASSWORD")
    if "ROFX" in markets:
        if not s.primary_username:
            missing.append("BOT_PRIMARY_USERNAME")
        if not s.primary_password.get_secret_value():
            missing.append("BOT_PRIMARY_PASSWORD")
    return missing


async def _pump(
    conn: MarketConnector, subs: list[tuple[str, Settlement]], q: asyncio.Queue[OrderBook]
) -> None:
    async for book in conn.stream_books(subs):
        await q.put(book)


async def _refresh_rates(conns: dict[str, MarketConnector], engine: TradingEngine) -> None:
    iol = conns.get("bCBA")
    while iol is not None:
        try:
            rates = await iol.get_caucion_rates()
            if rates:
                engine.state.caucion_colocadora_tna, engine.state.caucion_tomadora_tna = rates
        except Exception as e:  # noqa: BLE001 - tasa de referencia es best-effort
            log.warning("no se pudo actualizar caucion: %s", e)
        await asyncio.sleep(60)


async def run_realtime(s: Settings, mode: Mode, use_ui: bool) -> None:
    store = Store(s.db_path)
    alerts = Alerts(s.telegram_token.get_secret_value(), s.telegram_chat_id)
    loop = asyncio.get_running_loop()

    def notify(msg: str) -> None:
        loop.create_task(alerts.send(msg))

    probe = build_engine(s, PaperBroker(s.fee_engine()), None)
    subs = probe.subscriptions
    missing = _missing_credentials(s, subs)
    if missing:
        raise SystemExit(f"Faltan credenciales en .env: {', '.join(missing)} (ver .env.example)")
    conns = build_connectors(s, subs)
    try:
        for c in conns.values():
            await c.connect()
        broker: Broker
        if mode is Mode.LIVE:
            live = LiveBroker(conns, s.fee_engine())
            await live.refresh_holdings()
            broker = live
        else:
            broker = PaperBroker(s.fee_engine(), s.paper_inventory)
        engine = build_engine(s, broker, store, notify)
        q: asyncio.Queue[OrderBook] = asyncio.Queue(maxsize=5000)
        tasks = [
            asyncio.create_task(
                _pump(c, [x for x in subs if instruments.get_instrument(x[0]).market == m], q)
            )
            for m, c in conns.items()
        ]
        tasks.append(asyncio.create_task(_refresh_rates(conns, engine)))
        console = Console()

        async def consume() -> None:
            while True:
                await engine.on_book(await q.get())

        tasks.append(asyncio.create_task(consume()))
        try:
            if use_ui:
                with Live(
                    render(engine, list(conns.values()), mode.value, s.target_daily_net),
                    console=console,
                    refresh_per_second=4,
                    screen=True,
                ) as live_ui:
                    while True:
                        live_ui.update(render(engine, list(conns.values()), mode.value, s.target_daily_net))
                        for t in tasks:
                            if t.done() and not t.cancelled() and (exc := t.exception()):
                                raise exc
                        await asyncio.sleep(0.25)
            else:
                await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if engine.state.books:
                last_ts = max(b.ts for b in engine.state.books.values())
                with contextlib.suppress(Exception):
                    await engine.flatten_all(last_ts, "apagado")
            engine.end_of_data()
    finally:
        for c in conns.values():
            await c.close()
        store.close()


async def run_backtest_mode(s: Settings, db: str | None, synthetic_days: int | None) -> None:
    console = Console()
    broker = PaperBroker(s.fee_engine(), s.paper_inventory or {"AL30": 1e9, "GD30": 1e9, "GGAL": 1e9})
    engine = build_engine(s, broker, None)
    if synthetic_days:
        d = date(2026, 3, 2)
        days: list[date] = []
        while len(days) < synthetic_days:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)

        def feed() -> Iterator[OrderBook]:
            for day in days:
                yield from generate(day)

        console.print(f"[yellow]Datos SINTETICOS ({synthetic_days} dias): solo prueba de humo[/]")
        summary = await run_backtest(engine, feed())
    else:
        store = Store(db or s.db_path)
        if store.count("books") == 0:
            console.print("[red]La base no tiene libros. Grabalos primero con --mode paper.[/]")
            sys.exit(2)
        summary = await run_backtest(engine, store.iter_books())
        store.close()
    for line in summary.lines(s.target_daily_net):
        console.print(line)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ar-quant-bot")
    ap.add_argument("--mode", choices=[m.value for m in Mode], help="backtest | paper | live")
    ap.add_argument("--db", help="SQLite con libros grabados (backtest)")
    ap.add_argument("--synthetic-days", type=int, help="backtest sobre datos sinteticos (humo)")
    ap.add_argument("--no-ui", action="store_true", help="sin TUI (logs a consola)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    s = get_settings()
    mode = Mode(args.mode) if args.mode else s.mode

    if mode is Mode.BACKTEST:
        asyncio.run(run_backtest_mode(s, args.db, args.synthetic_days))
        return
    if mode is Mode.LIVE:
        print("MODO LIVE: se enviaran ordenes REALES con dinero real.")
        if input(f'Escribi "{LIVE_CONFIRMATION}" para continuar: ').strip() != LIVE_CONFIRMATION:
            print("Cancelado.")
            sys.exit(1)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_realtime(s, mode, use_ui=not args.no_ui))


if __name__ == "__main__":
    main()
