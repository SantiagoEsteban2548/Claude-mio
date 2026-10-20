"""Motor de backtesting sobre backtrader.

Ejecución:
  - Las señales se calculan al cierre de la vela t (columnas precalculadas, causales) y la orden de
    mercado se llena en la APERTURA de t+1 (comportamiento por defecto de backtrader).
  - Cada entrada es una orden bracket: stop-loss y take-profit en múltiplos de ATR (OCO), chequeados
    intrabar contra high/low; si la vela abre más allá del stop, se llena a la apertura (gap).
  - Comisión `fee_rate` por lado sobre el nocional y slippage `slippage_rate` por lado en contra.
  - El RiskManager decide tamaño, circuit breaker diario, kill switch y objetivo diario.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import backtrader as bt
import pandas as pd

from .. import metrics
from ..config import Settings
from ..risk import RiskEvent, RiskManager
from ..strategies import SIGNAL_COLUMNS, Strategy

MIN_NOTIONAL = 10.0


class SameBarBracketBroker(bt.brokers.BackBroker):
    """backtrader activa el stop/TP de un bracket recién en la vela SIGUIENTE a la entrada, así que una
    vela que atraviesa el stop justo después de entrar no lo dispara y la salida se llena (mucho) peor.
    Este broker evalúa los hijos recién activados contra la misma vela de entrada. El stop se evalúa
    antes que el take-profit: si ambos caen dentro de la vela, se asume el peor caso."""

    def next(self) -> None:
        super().next()
        fresh = []
        while self._toactivate:
            o = self._toactivate.popleft()
            o.activate()
            fresh.append(o)
        for o in fresh:
            if not (o.alive() and o in self.pending):
                continue
            pref = getattr(o.parent, "ref", o.ref)
            siblings = [x for x in self._pchildren.get(pref, []) if x is not o]
            # Fuera de `pending` mientras se ejecuta: el chequeo OCO interno de backtrader, si la
            # encuentra ahí, la marca como cancelada aunque se haya llenado y deja vivo al hermano.
            self.pending.remove(o)
            self._try_exec(o)
            if o.alive():
                self.pending.append(o)
            elif o.status == bt.Order.Completed:
                for sib in siblings:
                    if sib.alive():
                        self.cancel(sib, bracket=True)
                self._pchildren.pop(pref, None)
        if fresh:
            self._get_value()


class SignalFeed(bt.feeds.PandasData):
    lines = tuple(SIGNAL_COLUMNS)
    params = tuple((c, -1) for c in SIGNAL_COLUMNS) + (("openinterest", None),)


class _BTStrategy(bt.Strategy):
    params = (("settings", None), ("signal_strategy", None))

    def __init__(self) -> None:
        s: Settings = self.p.settings
        self.s = s
        self.strat: Strategy = self.p.signal_strategy
        self.cost_rate = s.costs.fee_rate + s.costs.slippage_rate
        self.rm = RiskManager(s.risk, self.broker.getvalue())
        self.events: list[RiskEvent] = []
        self.equity: list[tuple[pd.Timestamp, float]] = []
        self.trades: list[dict[str, Any]] = []
        self.in_pos_bars = 0
        self.fees = 0.0
        self.slippage = 0.0
        self.pending: list[bt.Order] = []
        self.entry_bar = 0
        self.entry_risk = 0.0
        self.entry_side = ""
        self.exit_reason = ""

    # -------------------------------------------------------------- órdenes
    def notify_order(self, order: bt.Order) -> None:
        if order.status == order.Completed:
            ex = order.executed
            self.fees += ex.comm
            slip = self.s.costs.slippage_rate
            self.slippage += abs(ex.size) * ex.price * slip / (1 + slip)
            if order.exectype == bt.Order.Stop:
                self.exit_reason = self.exit_reason or "stop_loss"
            elif order.exectype == bt.Order.Limit:
                self.exit_reason = self.exit_reason or "take_profit"
        if not order.alive() and order in self.pending:
            self.pending.remove(order)

    def notify_trade(self, trade: bt.Trade) -> None:
        if not trade.isclosed:
            return
        self.rm.record_trade(trade.pnlcomm, self.entry_risk)
        self.trades.append({
            "entry_time": bt.num2date(trade.dtopen), "exit_time": bt.num2date(trade.dtclose),
            "side": self.entry_side,
            "entry_price": trade.price, "pnl": trade.pnlcomm, "gross_pnl": trade.pnl, "commission": trade.commission,
            "risk": self.entry_risk, "r": trade.pnlcomm / self.entry_risk if self.entry_risk else 0.0,
            "bars": trade.barlen, "reason": self.exit_reason or "signal",
        })
        self.exit_reason = ""

    def _flatten(self, reason: str) -> None:
        for o in list(self.pending):
            self.cancel(o)
        self.exit_reason = reason
        self.close()

    # -------------------------------------------------------------- por vela
    def next(self) -> None:
        d = self.data
        ts = pd.Timestamp(d.datetime.datetime(0), tz="UTC")
        equity = self.broker.getvalue()
        self.equity.append((ts, equity))
        self.events += self.rm.on_bar(ts, equity)
        pos = self.position.size
        if pos:
            self.in_pos_bars += 1

        if len(self) >= self.data.buflen() - 1:  # cerrar en la penúltima vela: se llena en la apertura de la última
            if pos and not any(o.alive() and o.exectype == bt.Order.Market for o in self.pending):
                self._flatten("end_of_data")
            return
        if pos and self.rm.must_flatten():
            self._flatten("kill_switch" if self.rm.killed else "daily_breaker")
            return
        if pos:
            held = len(self) - self.entry_bar
            if (pos > 0 and d.exit_long[0]) or (pos < 0 and d.exit_short[0]):
                self._flatten("signal_exit")
            elif held >= self.strat.max_bars:
                self._flatten("time_exit")
            return
        if any(o.alive() for o in self.pending):
            return

        sig = int(d.signal[0])
        atr = float(d.atr[0])
        if sig == 0 or not math.isfinite(atr) or atr <= 0:
            return
        price = float(d.close[0])
        stop_dist, tp_dist = self.strat.sl_atr * atr, self.strat.tp_atr * atr
        qty, risk_amount = self.rm.position_size(equity, price, stop_dist, bool(d.high_vol[0]), self.cost_rate)
        if qty * price < MIN_NOTIONAL:
            return
        self.entry_bar, self.entry_risk = len(self), risk_amount
        self.entry_side = "long" if sig > 0 else "short"
        if sig > 0:
            orders = self.buy_bracket(size=qty, exectype=bt.Order.Market,
                                      stopprice=price - stop_dist, limitprice=price + tp_dist)
        else:
            orders = self.sell_bracket(size=qty, exectype=bt.Order.Market,
                                       stopprice=price + stop_dist, limitprice=price - tp_dist)
        self.pending = [o for o in orders if o is not None]


@dataclass
class BacktestResult:
    metrics: dict[str, Any]
    equity: pd.Series
    trades: pd.DataFrame
    events: list[RiskEvent] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def run_backtest(df: pd.DataFrame, settings: Settings, strategy: Strategy, start: str | None = None,
                 end: str | None = None, initial_cash: float | None = None,
                 signals: pd.DataFrame | None = None) -> BacktestResult:
    """`df` debe incluir historia previa a `start`: las señales se calculan sobre todo `df` (causales)
    y solo se opera dentro de [start, end)."""
    sig = signals if signals is not None else strategy.compute(df)
    full = df.join(sig)
    if start:
        full = full[full.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        full = full[full.index < pd.Timestamp(end, tz="UTC")]
    if len(full) < 2:
        raise ValueError("rango de backtest vacío")
    cash = float(initial_cash if initial_cash is not None else settings.backtest.initial_cash)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker = SameBarBracketBroker()
    feed_df = full.copy()
    feed_df.index = feed_df.index.tz_convert(None)
    cerebro.adddata(SignalFeed(dataname=feed_df))
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=settings.costs.fee_rate, leverage=settings.risk.max_leverage)
    cerebro.broker.set_slippage_perc(settings.costs.slippage_rate, slip_open=True, slip_limit=True,
                                     slip_match=True, slip_out=False)
    # El tope de nocional lo impone el RiskManager (max_leverage); así backtrader no rechaza por margen.
    cerebro.broker.set_checksubmit(False)
    cerebro.addstrategy(_BTStrategy, settings=settings, signal_strategy=strategy)
    strat: _BTStrategy = cerebro.run()[0]

    equity = pd.Series(dict(strat.equity)).astype(float)
    equity.index = pd.DatetimeIndex(equity.index)
    trades = pd.DataFrame(strat.trades)
    m = metrics.compute(equity, trades, cash, strat.in_pos_bars / max(len(equity), 1), strat.fees, strat.slippage)
    m["buy_hold_return"] = float(full.close.iloc[-1] / full.open.iloc[0] - 1)
    m["kill_switch"] = strat.rm.kill_reason or "no"
    m["daily_breakers"] = sum(e.kind == "daily_breaker" for e in strat.events)
    m["daily_targets_hit_stop"] = sum(e.kind == "daily_target" for e in strat.events)
    return BacktestResult(m, equity, trades, strat.events, dict(strategy.params))
