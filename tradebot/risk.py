"""Gestión de riesgo compartida por backtest, paper y live.

- Tamaño: fixed fractional o Kelly fraccional (acotado por risk_per_trade), con nocional <= equity * max_leverage.
- Presupuesto: el riesgo de una operación nueva nunca excede lo que queda del límite diario ni del total,
  así un stop-out no puede, por sí solo, perforar el circuit breaker.
- Circuit breaker diario (UTC): pérdida >= max_daily_drawdown -> cerrar todo y no operar hasta el día siguiente.
- Kill switch: drawdown desde el pico >= max_total_drawdown -> cerrar todo y no operar más (reinicio manual).
- Objetivo diario: al llegar a daily_profit_target no se abren posiciones nuevas ese día.
- Degradación: modo conservador en alta volatilidad y reducción tras rachas de pérdidas.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime

from .config import RiskConfig

KELLY_MIN_TRADES = 20
SAFETY_BUFFER = 0.9
GAP_BUFFER = 0.01     # la entrada se llena en la apertura siguiente: margen por si abre más arriba
MIN_REMAINING_BUDGET = 0.25  # kill switch si queda menos de 1/4 de risk_per_trade de margen de drawdown  # usa como máximo el 90% del presupuesto restante, por gaps y slippage en el stop


@dataclass(frozen=True)
class RiskEvent:
    ts: datetime
    kind: str  # daily_breaker | kill_switch | daily_target
    message: str


class RiskManager:
    def __init__(self, cfg: RiskConfig, initial_equity: float):
        self.cfg = cfg
        self.peak = initial_equity
        self.day: date | None = None
        self.day_start = initial_equity
        self.last_equity = initial_equity
        self.breaker_day: date | None = None
        self.target_day: date | None = None
        self.killed = False
        self.kill_reason = ""
        self.loss_streak = 0
        self.r_multiples: deque[float] = deque(maxlen=cfg.kelly_lookback_trades)

    # ---------------------------------------------------------------- estado por vela
    def on_bar(self, ts: datetime, equity: float) -> list[RiskEvent]:
        events: list[RiskEvent] = []
        today = ts.date()
        if today != self.day:
            self.day, self.day_start = today, self.last_equity
        self.last_equity = equity
        self.peak = max(self.peak, equity)

        remaining = self.cfg.max_total_drawdown - self.total_drawdown()
        if not self.killed and remaining < MIN_REMAINING_BUDGET * self.cfg.risk_per_trade:
            # Con el presupuesto de drawdown agotado ya no se puede abrir nada útil: se detiene del todo.
            self.killed = True
            self.kill_reason = f"drawdown total {self.total_drawdown():.2%} (límite {self.cfg.max_total_drawdown:.0%})"
            events.append(RiskEvent(ts, "kill_switch", self.kill_reason))
        if self.breaker_day != today and self.daily_loss() >= self.cfg.max_daily_drawdown:
            self.breaker_day = today
            events.append(RiskEvent(ts, "daily_breaker",
                                    f"pérdida diaria {self.daily_loss():.2%} >= {self.cfg.max_daily_drawdown:.0%}"))
        target = self.cfg.daily_profit_target
        if target is not None and self.target_day != today and self.daily_return() >= target:
            self.target_day = today
            events.append(RiskEvent(ts, "daily_target", f"objetivo diario alcanzado ({self.daily_return():.2%})"))
        return events

    def daily_return(self) -> float:
        return self.last_equity / self.day_start - 1

    def daily_loss(self) -> float:
        return max(0.0, -self.daily_return())

    def total_drawdown(self) -> float:
        return 1 - self.last_equity / self.peak

    def must_flatten(self) -> bool:
        return self.killed or (self.breaker_day is not None and self.breaker_day == self.day)

    def can_open(self) -> bool:
        return not self.must_flatten() and (self.target_day is None or self.target_day != self.day)

    def kill(self, reason: str) -> None:
        self.killed, self.kill_reason = True, reason

    # ---------------------------------------------------------------- tamaño
    def record_trade(self, pnl: float, risk_amount: float) -> None:
        if risk_amount > 0:
            self.r_multiples.append(pnl / risk_amount)
        self.loss_streak = self.loss_streak + 1 if pnl <= 0 else 0

    def kelly_risk(self) -> float:
        rs = list(self.r_multiples)
        if len(rs) < KELLY_MIN_TRADES:
            return self.cfg.risk_per_trade * 0.5
        wins = [r for r in rs if r > 0]
        losses = [-r for r in rs if r <= 0]
        if not wins or not losses:
            return self.cfg.risk_per_trade * (1.0 if wins else 0.1)
        w = len(wins) / len(rs)
        payoff = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
        f = w - (1 - w) / payoff
        # Edge negativo: no se apaga del todo (sin trades no hay datos para detectar que mejoró),
        # pero queda en un tamaño mínimo de sondeo.
        return min(max(self.cfg.kelly_fraction * f, self.cfg.risk_per_trade * 0.1), self.cfg.risk_per_trade)

    def risk_fraction(self, high_vol: bool) -> float:
        base = self.kelly_risk() if self.cfg.sizing == "kelly" else self.cfg.risk_per_trade
        if high_vol and self.cfg.conservative.enabled:
            base *= self.cfg.conservative.size_multiplier
        if self.loss_streak >= self.cfg.loss_streak.after_losses:
            base *= self.cfg.loss_streak.size_multiplier
        daily_budget = (self.cfg.max_daily_drawdown - self.daily_loss()) * self.day_start / self.last_equity
        total_budget = self.cfg.max_total_drawdown - self.total_drawdown()
        return max(0.0, min(base, SAFETY_BUFFER * daily_budget, SAFETY_BUFFER * total_budget))

    def position_size(self, equity: float, price: float, stop_dist: float, high_vol: bool,
                      cost_rate: float = 0.0) -> tuple[float, float]:
        """Devuelve (cantidad, riesgo en moneda). 0 si no corresponde operar."""
        if not self.can_open() or price <= 0 or not math.isfinite(stop_dist) or stop_dist <= 0:
            return 0.0, 0.0
        risk_amount = equity * self.risk_fraction(high_vol)
        qty = risk_amount / (stop_dist + price * 2 * cost_rate)  # el stop-out también paga costos de ida y vuelta
        cap = equity * self.cfg.max_leverage / (price * (1 + cost_rate) * (1 + GAP_BUFFER))
        qty = min(qty, cap)
        return qty, qty * (stop_dist + price * 2 * cost_rate)
