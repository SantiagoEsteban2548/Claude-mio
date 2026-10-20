"""Modelos de dominio validados con pydantic v2."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settlement(StrEnum):
    """Plazo de liquidacion. CI = contado inmediato (T+0), H24 = 24hs (T+1)."""

    CI = "CI"
    H24 = "24hs"

    @property
    def days(self) -> int:
        return 0 if self is Settlement.CI else 1

    @property
    def iol_plazo(self) -> str:
        return "t0" if self is Settlement.CI else "t1"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class AssetClass(StrEnum):
    SOVEREIGN_BOND = "bond"
    LECAP = "lecap"
    EQUITY = "equity"
    CEDEAR = "cedear"
    FUTURE = "future"


class Currency(StrEnum):
    ARS = "ARS"
    USD_MEP = "USD_MEP"
    USD_CCL = "USD_CCL"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @property
    def is_open(self) -> bool:
        return self in (OrderStatus.NEW, OrderStatus.PARTIAL)


class Instrument(BaseModel):
    """Especie operable.

    ``multiplier`` convierte ``qty * price`` en monto de la moneda del instrumento:
    bonos/LECAPs cotizan cada 100 VN (0.01), acciones/CEDEARs 1, futuro DLR 1000 USD/contrato.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_class: AssetClass
    currency: Currency = Currency.ARS
    multiplier: float = 1.0
    market: str = "bCBA"  # mercado IOL; "ROFX" para Primary
    shortable: bool = False

    def notional(self, qty: float, price: float) -> float:
        return qty * price * self.multiplier


class BookLevel(BaseModel):
    price: float = Field(gt=0)
    size: float = Field(ge=0)


class OrderBook(BaseModel):
    """Libro de puntas (hasta 5 niveles) para una especie y plazo."""

    symbol: str
    settlement: Settlement = Settlement.CI
    bids: list[BookLevel] = Field(default_factory=list)  # mejor precio primero
    asks: list[BookLevel] = Field(default_factory=list)
    ts: datetime
    last: float | None = None
    cum_volume: float | None = None  # volumen nominal acumulado del dia

    @field_validator("bids")
    @classmethod
    def _sort_bids(cls, v: list[BookLevel]) -> list[BookLevel]:
        return sorted(v, key=lambda lv: -lv.price)

    @field_validator("asks")
    @classmethod
    def _sort_asks(cls, v: list[BookLevel]) -> list[BookLevel]:
        return sorted(v, key=lambda lv: lv.price)

    @property
    def key(self) -> tuple[str, Settlement]:
        return (self.symbol, self.settlement)

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def is_two_sided(self) -> bool:
        return bool(self.bids and self.asks)

    @property
    def is_crossed(self) -> bool:
        return self.is_two_sided and self.bids[0].price >= self.asks[0].price

    @property
    def mid(self) -> float | None:
        if not self.is_two_sided:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2

    @property
    def spread_pct(self) -> float | None:
        m = self.mid
        if m is None:
            return None
        return (self.asks[0].price - self.bids[0].price) / m

    def side_levels(self, side: Side) -> list[BookLevel]:
        """Niveles contra los que se ejecuta una orden de ``side`` (BUY consume asks)."""
        return self.asks if side is Side.BUY else self.bids

    def touch(self, side: Side) -> BookLevel | None:
        lv = self.side_levels(side)
        return lv[0] if lv else None


class Leg(BaseModel):
    symbol: str
    settlement: Settlement = Settlement.CI
    side: Side
    limit_price: float = Field(gt=0)
    qty: float = Field(default=0, ge=0)  # lo completa el sizing


class Signal(BaseModel):
    """Intencion de trading generada por una estrategia."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    strategy: str
    legs: list[Leg]
    expected_gross_pct: float  # retorno bruto esperado sobre el nocional por pata (fraccion)
    reason: str = ""
    is_exit: bool = False
    atomic: bool = False  # ida y vuelta completa en el mismo instante (arbitraje de plazos)
    financing_cost_pct: float = 0.0  # costo de oportunidad/financiamiento ya estimado
    win_prob: float | None = None  # para Kelly fraccional
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    max_hold_seconds: int | None = None
    ts: datetime


class Order(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    strategy: str = ""
    symbol: str
    settlement: Settlement = Settlement.CI
    side: Side
    qty: float = Field(gt=0)
    price: float = Field(gt=0)
    status: OrderStatus = OrderStatus.NEW
    filled_qty: float = 0.0
    avg_price: float = 0.0
    fee: float = 0.0  # en moneda del instrumento
    ts: datetime
    broker_id: str | None = None
    reject_reason: str | None = None


class Fill(BaseModel):
    order_id: str
    strategy: str
    symbol: str
    settlement: Settlement
    side: Side
    qty: float
    price: float
    fee: float  # moneda del instrumento, ya con derechos e IVA
    ts: datetime


class AccountState(BaseModel):
    cash_ars: float = 0.0
    cash_usd: float = 0.0
    holdings: dict[str, float] = Field(default_factory=dict)
