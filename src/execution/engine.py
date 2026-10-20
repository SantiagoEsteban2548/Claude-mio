"""Motor de trading: une estrategias, fee engine, riesgo y broker (paper o live)."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.core.clock import to_art
from src.core.instruments import get_instrument
from src.core.models import Fill, Leg, Order, OrderBook, OrderStatus, Settlement, Side, Signal
from src.execution.paper import Broker
from src.execution.positions import Position, PositionManager
from src.fee_engine.benchmark import usd_mep_return
from src.fee_engine.engine import FeeEngine, LegNotional
from src.risk.manager import RiskManager
from src.risk.sizing import liquidity_cap_qty, max_notional_ars, qty_for_notional
from src.storage.db import Store
from src.strategies.base import Strategy
from src.strategies.state import MarketState

log = logging.getLogger(__name__)

UNWIND_SLIPPAGE = 0.01  # tolerancia de precio al deshacer patas / cerrar forzosamente


@dataclass
class DayResult:
    day: date
    net_pnl_ars: float
    net_pct: float
    usd_mep_pct: float | None
    hurdle_pct: float
    trades: int


class TradingEngine:
    def __init__(
        self,
        strategies: Sequence[Strategy],
        state: MarketState,
        broker: Broker,
        risk: RiskManager,
        fees: FeeEngine,
        store: Store | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self.strategies = list(strategies)
        self.state = state
        self.broker = broker
        self.risk = risk
        self.fees = fees
        self.store = store
        self.notify = notify
        self.positions = PositionManager()
        self.events: deque[str] = deque(maxlen=40)
        self.day_results: list[DayResult] = []
        self.rejections: dict[str, int] = {}
        self._reset_day_counters()
        self._by_key: dict[tuple[str, Settlement], list[Strategy]] = {}
        for s in self.strategies:
            for key in s.subscriptions:
                self._by_key.setdefault(key, []).append(s)
        self._last_pnl_save: datetime | None = None
        self._flatten_lock = asyncio.Lock()

    # ------------------------------------------------------------------ estado diario
    def _reset_day_counters(self) -> None:
        self.realized_gross_ars = 0.0
        self.fees_ars = 0.0
        self.trades = 0
        self.mep_open: float | None = None
        self.mep_last: float | None = None

    @property
    def subscriptions(self) -> list[tuple[str, Settlement]]:
        return sorted(self._by_key, key=lambda k: (k[0], k[1].value))

    def _event(self, msg: str) -> None:
        self.events.append(msg)
        log.info(msg)

    def _alert(self, msg: str) -> None:
        self._event(msg)
        if self.notify:
            self.notify(msg)

    def _reject(self, sig: Signal, why: str) -> None:
        key = why.split("(")[0].strip()[:40]
        self.rejections[key] = self.rejections.get(key, 0) + 1
        if self.store:
            self.store.audit(sig.ts, "signal_rejected", {"strategy": sig.strategy, "why": why})

    def _fx(self, symbol: str) -> float | None:
        return self.state.fx(get_instrument(symbol).currency)

    # ------------------------------------------------------------------ P&L
    def _unrealized_net_ars(self) -> float:
        total = 0.0
        for key, u in self.positions.unrealized(self.state.books).items():
            inst = get_instrument(key[1])
            fx = self.state.fx(inst.currency) or 1.0
            pos = self.positions.positions[key]
            px = self.state.books[(pos.symbol, pos.settlement)].touch(Side.SELL if pos.qty > 0 else Side.BUY)
            exit_fee = 0.0
            if px:
                exit_fee = float(
                    self.fees.leg_cost(
                        inst.asset_class, inst.notional(abs(pos.qty), px.price), closing_same_day=True
                    ).fees
                )
            total += (u - exit_fee) * fx
        return total

    @property
    def realized_net_ars(self) -> float:
        return self.realized_gross_ars - self.fees_ars

    def gross_exposure_ars(self) -> float:
        total = 0.0
        for p in self.positions.open_positions():
            b = self.state.books.get((p.symbol, p.settlement))
            px = b.mid if b and b.mid else p.avg_price
            inst = get_instrument(p.symbol)
            total += abs(p.qty) * px * inst.multiplier * (self.state.fx(inst.currency) or 1.0)
        return total

    def _refresh_pnl(self, ts: datetime) -> None:
        newly = self.risk.update_pnl(self.realized_net_ars, self._unrealized_net_ars())
        mep = self.state.mep()
        if mep:
            self.mep_open = self.mep_open or mep
            self.mep_last = mep
        if newly:
            self._alert(f"KILL-SWITCH: {self.risk.kill_reason}")
            if self.store:
                self.store.audit(ts, "kill_switch", {"reason": self.risk.kill_reason})
        if self.store and (self._last_pnl_save is None or (ts - self._last_pnl_save).total_seconds() >= 30):
            self.store.save_pnl(
                ts, self.risk.realized_net_ars, self.risk.unrealized_net_ars, self.risk.daily_pnl_pct
            )
            self._last_pnl_save = ts

    def _finalize_day(self) -> None:
        if self.risk.day is None:
            return
        pct = self.risk.daily_pnl_pct
        usd = None
        if self.mep_open and self.mep_last:
            usd = usd_mep_return(pct, self.mep_open, self.mep_last)
        hurdle = self.state.caucion_colocadora_tna / 365.0
        self.day_results.append(
            DayResult(self.risk.day, self.risk.daily_pnl_ars, pct, usd, hurdle, self.trades)
        )

    # ------------------------------------------------------------------ flujo principal
    async def on_book(self, book: OrderBook) -> None:
        self.state.update(book)
        if self.store:
            self.store.save_book(book)
        had_day = self.risk.day is not None
        if self.risk.day is None or to_art(book.ts).date() != self.risk.day:
            if had_day:
                self._finalize_day()
            self.risk.roll_day(book.ts)
            self._reset_day_counters()

        for f in self.broker.on_book(book):
            self._book_fill(f, None, atomic=False)

        self._refresh_pnl(book.ts)

        if self.risk.must_flatten(book.ts):
            if self.positions.open_positions() or self.broker.open_orders():
                await self.flatten_all(book.ts, "kill-switch" if self.risk.kill_switch else "cierre")
            return

        await self._check_exits(book)
        for strat in self._by_key.get((book.symbol, book.settlement), []):
            for sig in strat.on_book(book, self.state, self.positions):
                await self._handle_signal(strat, sig)
        self._refresh_pnl(book.ts)

    def end_of_data(self) -> None:
        """Cierra el ultimo dia (backtest / fin de sesion)."""
        self._finalize_day()

    # ------------------------------------------------------------------ contabilidad de fills
    def _book_fill(self, fill: Fill, sig: Signal | None, *, atomic: bool) -> None:
        inst = get_instrument(fill.symbol)
        fx = self.state.fx(inst.currency) or 1.0
        self.fees_ars += fill.fee * fx
        self.trades += 1
        if self.store:
            self.store.save_fill(fill)
        if atomic:
            # ida y vuelta completa: el flujo de fondos neto de las patas es el resultado bruto
            self.realized_gross_ars += -fill.side.sign * inst.notional(fill.qty, fill.price) * fx
            return
        realized = self.positions.apply_fill(
            fill,
            take_profit_pct=sig.take_profit_pct if sig else None,
            stop_loss_pct=sig.stop_loss_pct if sig else None,
            max_hold_seconds=sig.max_hold_seconds if sig else None,
        )
        self.realized_gross_ars += realized * fx

    async def _send(
        self, strategy: str, leg: Leg, qty: float, book: OrderBook, closing: bool
    ) -> tuple[Order, list[Fill]]:
        order = Order(
            strategy=strategy,
            symbol=leg.symbol,
            settlement=leg.settlement,
            side=leg.side,
            qty=qty,
            price=leg.limit_price,
            ts=book.ts,
        )
        order, fills = await self.broker.submit(order, book, closing)
        if order.status.is_open:  # semantica IOC para entradas: no dejar remanentes dando vueltas
            await self.broker.cancel(order.id)
            order.status = OrderStatus.CANCELLED if not fills else OrderStatus.PARTIAL
        if self.store:
            self.store.save_order(order)
        return order, fills

    # ------------------------------------------------------------------ senales
    async def _handle_signal(self, strat: Strategy, sig: Signal) -> None:
        if sig.is_exit:
            ok = await self._execute_exit(sig)
            strat.on_result(sig, ok)
            return
        plan = self._plan(sig)
        if isinstance(plan, str):
            self._reject(sig, plan)
            strat.on_result(sig, False)
            return
        ok = await self._execute_entry(sig, plan)
        strat.on_result(sig, ok)

    def _plan(self, sig: Signal) -> list[float] | str:
        """Valida (libro, edge neto, riesgo) y dimensiona. Devuelve cantidades por pata o un motivo."""
        cfg = self.risk.cfg
        caps: list[float] = []  # topes de nocional (ARS)
        unit_caps: list[float] = []  # topes en unidades (para patas del mismo papel)
        units: list[float] = []
        has_buy = {lg.symbol for lg in sig.legs if lg.side is Side.BUY}
        for lg in sig.legs:
            book = self.state.books.get((lg.symbol, lg.settlement))
            if book is None:
                return f"sin libro {lg.symbol}"
            d = self.risk.check_book(book.spread_pct, self.state.age(book, sig.ts))
            if not d.allowed:
                return f"{lg.symbol}: {d.reason}"
            inst = get_instrument(lg.symbol)
            fx = self.state.fx(inst.currency)
            if fx is None:
                return f"sin FX para {inst.currency}"
            unit = lg.limit_price * inst.multiplier * fx
            q_liq = liquidity_cap_qty(book, lg.side, cfg.liquidity_cap_pct)
            units.append(unit)
            caps.append(q_liq * unit)
            unit_caps.append(q_liq)
            if lg.side is Side.SELL and not inst.shortable and lg.symbol not in has_buy:
                caps.append(self.broker.available(lg.symbol) * unit)
                unit_caps.append(self.broker.available(lg.symbol))
        cap = max_notional_ars(
            cfg,
            win_prob=sig.win_prob,
            take_profit_pct=sig.take_profit_pct,
            stop_loss_pct=sig.stop_loss_pct,
        )
        base = min([cap, *caps])
        if base <= 0:
            return "tamano 0 (liquidez, inventario o Kelly)"

        if len({lg.symbol for lg in sig.legs}) == 1:
            # patas del mismo papel (arbitraje de plazos): igual cantidad en unidades
            units_max = min([cap / max(units), *unit_caps])
            qtys = [float(int(units_max))] * len(sig.legs)
        else:
            qtys = []
            for lg in sig.legs:
                inst = get_instrument(lg.symbol)
                fx = self.state.fx(inst.currency) or 1.0
                qtys.append(qty_for_notional(base, lg.limit_price, inst.multiplier, fx))
        if any(q < 1 for q in qtys):
            return "cantidad < 1 (capital insuficiente para el lote minimo)"

        leg_notionals = []
        for lg, q in zip(sig.legs, qtys, strict=True):
            inst = get_instrument(lg.symbol)
            fx = self.state.fx(inst.currency) or 1.0
            leg_notionals.append(inst.notional(q, lg.limit_price) * fx)
        edge = self.fees.evaluate(
            sig.expected_gross_pct,
            [
                LegNotional(get_instrument(lg.symbol).asset_class, Decimal(str(n)))
                for lg, n in zip(sig.legs, leg_notionals, strict=True)
            ],
            atomic=sig.atomic,
            financing_pct=sig.financing_cost_pct,
        )
        if not edge.valid:
            return f"edge insuficiente ({edge.reason})"
        d = self.risk.check_entry(
            sig.ts,
            gross_exposure_ars=self.gross_exposure_ars(),
            new_notional_ars=sum(leg_notionals),
        )
        if not d.allowed:
            return f"riesgo ({d.reason})"
        return qtys

    async def _execute_entry(self, sig: Signal, qtys: list[float]) -> bool:
        done: list[tuple[Leg, list[Fill]]] = []
        self._event(f"SENAL {sig.strategy}: {sig.reason}")
        for lg, qty in zip(sig.legs, qtys, strict=True):
            book = self.state.books[(lg.symbol, lg.settlement)]
            order, fills = await self._send(sig.strategy, lg, qty, book, closing=False)
            got = sum(f.qty for f in fills)
            if order.status is OrderStatus.REJECTED or got < qty * 0.999:
                if len(sig.legs) > 1:
                    # una pata fallo: deshacer lo ya ejecutado para no quedar con riesgo direccional
                    for f in fills:  # el parcial de esta pata
                        self._book_fill(f, sig, atomic=sig.atomic)
                        done.append((lg, [f]))
                    await self._unwind(sig, done)
                    self._event(f"ENTRADA ABORTADA {lg.symbol}: {order.reject_reason or 'sin liquidez'}")
                    return False
                for f in fills:
                    self._book_fill(f, sig, atomic=sig.atomic)
                return got > 0
            for f in fills:
                self._book_fill(f, sig, atomic=sig.atomic)
            done.append((lg, fills))
        return True

    async def _unwind(self, sig: Signal, done: list[tuple[Leg, list[Fill]]]) -> None:
        for lg, fills in done:
            qty = sum(f.qty for f in fills)
            if qty <= 0:
                continue
            book = self.state.books.get((lg.symbol, lg.settlement))
            if book is None:
                continue
            rev = self._aggressive_leg(lg.symbol, lg.settlement, lg.side.opposite, book)
            if rev is None:
                self._alert(f"NO SE PUDO DESHACER {lg.symbol} (libro vacio): revisar manualmente")
                continue
            _, ufills = await self._send(sig.strategy, rev, qty, book, closing=True)
            for f in ufills:
                self._book_fill(f, sig, atomic=sig.atomic)

    @staticmethod
    def _aggressive_leg(symbol: str, st: Settlement, side: Side, book: OrderBook) -> Leg | None:
        lv = book.touch(side)
        if lv is None:
            return None
        px = lv.price * (1 + UNWIND_SLIPPAGE if side is Side.BUY else 1 - UNWIND_SLIPPAGE)
        return Leg(symbol=symbol, settlement=st, side=side, limit_price=px)

    async def _execute_exit(self, sig: Signal) -> bool:
        ok = True
        for lg in sig.legs:
            pos = self.positions.get(sig.strategy, lg.symbol, lg.settlement)
            if pos is None or pos.qty == 0:
                continue
            ok &= await self._close_position(pos, sig.ts, reason=sig.reason)
        return ok

    async def _close_position(self, pos: Position, ts: datetime, reason: str) -> bool:
        book = self.state.books.get((pos.symbol, pos.settlement))
        if book is None:
            return False
        leg = self._aggressive_leg(pos.symbol, pos.settlement, pos.side.opposite, book)
        if leg is None:
            return False
        order, fills = await self._send(pos.strategy, leg, abs(pos.qty), book, closing=True)
        for f in fills:
            self._book_fill(f, None, atomic=False)
        self._event(f"CIERRE {pos.symbol} {pos.strategy}: {reason}")
        return order.status is OrderStatus.FILLED

    async def _check_exits(self, book: OrderBook) -> None:
        for pos in list(self.positions.open_positions()):
            if pos.symbol != book.symbol or pos.settlement != book.settlement:
                continue
            lv = book.touch(pos.side.opposite)
            if lv is None or pos.opened_ts is None:
                continue
            ret = pos.side.sign * (lv.price / pos.avg_price - 1.0)
            held = (to_art(book.ts) - to_art(pos.opened_ts)).total_seconds()
            reason = None
            if pos.take_profit_pct is not None and ret >= pos.take_profit_pct:
                reason = f"take-profit {ret:.2%}"
            elif pos.stop_loss_pct is not None and ret <= -pos.stop_loss_pct:
                reason = f"stop-loss {ret:.2%}"
            elif pos.max_hold_seconds is not None and held >= pos.max_hold_seconds:
                reason = f"tiempo maximo {held:.0f}s ({ret:.2%})"
            if reason:
                await self._close_position(pos, book.ts, reason)

    async def flatten_all(self, ts: datetime, reason: str) -> None:
        """Cancela ordenes abiertas y cierra todas las posiciones intradiarias."""
        async with self._flatten_lock:
            n = await self.broker.cancel_all()
            for pos in list(self.positions.open_positions()):
                await self._close_position(pos, ts, f"flatten ({reason})")
            left = self.positions.open_positions()
            msg = f"FLATTEN ({reason}): {n} ordenes canceladas, {len(left)} posiciones sin cerrar"
            (self._alert if left or "kill" in reason else self._event)(msg)
            if self.store:
                self.store.audit(ts, "flatten", {"reason": reason, "left": len(left)})
            self._refresh_pnl(ts)
