"""RiskManager: kill-switch diario, filtros horarios y limites de exposicion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field

from src.core.clock import to_art


class MarketPhase(StrEnum):
    CLOSED = "CLOSED"
    OPENING_BLOCK = "OPENING_BLOCK"  # 11:00-11:05, sin operar
    TRADING = "TRADING"
    NO_NEW_ENTRIES = "NO_NEW_ENTRIES"  # cerca del cierre: solo salidas
    FLATTEN = "FLATTEN"  # cierre forzoso de posiciones intradiarias


class RiskConfig(BaseModel):
    capital_ars: float = Field(gt=0)
    kill_switch_dd_pct: float = 0.008  # -0.8% del capital
    open_time: time = time(11, 0)
    opening_block_minutes: int = 5
    no_new_entries_time: time = time(16, 10)
    flatten_time: time = time(16, 30)  # corte de CI
    hard_close_time: time = time(16, 45)  # nada abierto despues (Modulo C)
    market_close_time: time = time(16, 55)
    liquidity_cap_pct: float = 0.25  # max % del volumen en la punta contraria
    max_position_pct: float = 0.20  # max % del capital por operacion (nocional por pata)
    max_gross_exposure_pct: float = 0.60  # max exposicion bruta total sobre capital
    kelly_fraction: float = 0.25
    max_spread_pct: float = 0.01  # no operar libros con spread > 1%
    max_book_age_seconds: float = 5.0


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = "ok"


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.cfg = config
        self.day: date | None = None
        self.realized_net_ars = 0.0
        self.unrealized_net_ars = 0.0
        self.peak_pnl_ars = 0.0
        self.kill_switch = False
        self.kill_reason = ""

    # ---- fases horarias ----
    def phase(self, ts: datetime) -> MarketPhase:
        t = to_art(ts)
        if t.weekday() >= 5:
            return MarketPhase.CLOSED
        tt = t.time()
        c = self.cfg
        block_end = (
            datetime.combine(t.date(), c.open_time).replace(tzinfo=t.tzinfo)
            + timedelta(minutes=c.opening_block_minutes)
        ).time()
        if tt < c.open_time or tt >= c.market_close_time:
            return MarketPhase.CLOSED
        if tt < block_end:
            return MarketPhase.OPENING_BLOCK
        if tt >= c.flatten_time:
            return MarketPhase.FLATTEN
        if tt >= c.no_new_entries_time:
            return MarketPhase.NO_NEW_ENTRIES
        return MarketPhase.TRADING

    def must_flatten(self, ts: datetime) -> bool:
        return self.kill_switch or self.phase(ts) is MarketPhase.FLATTEN

    # ---- P&L y kill switch ----
    def roll_day(self, ts: datetime) -> bool:
        """Reinicia contadores en un nuevo dia. Devuelve True si hubo cambio de dia."""
        d = to_art(ts).date()
        if self.day == d:
            return False
        self.day = d
        self.realized_net_ars = 0.0
        self.unrealized_net_ars = 0.0
        self.peak_pnl_ars = 0.0
        self.kill_switch = False
        self.kill_reason = ""
        return True

    @property
    def daily_pnl_ars(self) -> float:
        return self.realized_net_ars + self.unrealized_net_ars

    @property
    def daily_pnl_pct(self) -> float:
        return self.daily_pnl_ars / self.cfg.capital_ars

    def update_pnl(self, realized_net_ars: float, unrealized_net_ars: float) -> bool:
        """Actualiza P&L neto del dia. Devuelve True si en esta llamada se activo el kill-switch."""
        self.realized_net_ars = realized_net_ars
        self.unrealized_net_ars = unrealized_net_ars
        self.peak_pnl_ars = max(self.peak_pnl_ars, self.daily_pnl_ars)
        if not self.kill_switch and self.daily_pnl_pct <= -self.cfg.kill_switch_dd_pct:
            self.kill_switch = True
            self.kill_reason = (
                f"drawdown diario {self.daily_pnl_pct:.4%} <= -{self.cfg.kill_switch_dd_pct:.2%}"
            )
            return True
        return False

    # ---- validaciones pre-trade ----
    def check_entry(self, ts: datetime, *, gross_exposure_ars: float, new_notional_ars: float) -> Decision:
        if self.kill_switch:
            return Decision(False, f"kill-switch activo ({self.kill_reason})")
        ph = self.phase(ts)
        if ph is not MarketPhase.TRADING:
            return Decision(False, f"fase {ph.value}: sin nuevas entradas")
        limit = self.cfg.max_gross_exposure_pct * self.cfg.capital_ars
        if gross_exposure_ars + new_notional_ars > limit:
            return Decision(False, "excede exposicion bruta maxima")
        return Decision(True)

    def check_book(self, spread_pct: float | None, age_seconds: float) -> Decision:
        if spread_pct is None:
            return Decision(False, "libro sin dos puntas")
        if spread_pct > self.cfg.max_spread_pct:
            return Decision(False, f"spread {spread_pct:.4%} > maximo")
        if age_seconds > self.cfg.max_book_age_seconds:
            return Decision(False, f"libro desactualizado ({age_seconds:.1f}s)")
        return Decision(True)
