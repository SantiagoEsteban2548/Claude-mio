"""Motor de costos exactos (Decimal).

Formulas (por pata, sobre el nocional N):
    comision      = N * commission_pct * (1 - descuento)      descuento solo en pata de cierre intradiaria
    derechos      = N * market_rights_pct
    iva           = (comision + derechos) * iva_pct
    slippage      = N * slippage_bps / 10_000
    costo_pata    = comision + derechos + iva + slippage

Ida y vuelta intradiaria (mismo dia y plazo): pata de entrada sin descuento + pata de cierre con descuento.
Una senal es valida si:  retorno_bruto - costo_total/N_base - financiamiento >= min_net_edge_pct
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from src.core.models import AssetClass
from src.fee_engine.tiers import BrokerTier

D = Decimal
ZERO = D("0")
DEFAULT_MIN_NET_EDGE = D("0.0005")  # 5 bps de margen neto minimo


def to_dec(x: float | int | str | Decimal) -> Decimal:
    return x if isinstance(x, Decimal) else D(str(x))


class CostBreakdown(BaseModel):
    notional: Decimal
    commission: Decimal = ZERO
    market_rights: Decimal = ZERO
    iva: Decimal = ZERO
    slippage: Decimal = ZERO

    @property
    def fees(self) -> Decimal:
        """Costo cobrado efectivamente por broker/mercado (sin slippage)."""
        return self.commission + self.market_rights + self.iva

    @property
    def total(self) -> Decimal:
        return self.fees + self.slippage

    @property
    def total_pct(self) -> Decimal:
        return self.total / self.notional if self.notional else ZERO

    def __add__(self, other: CostBreakdown) -> CostBreakdown:
        return CostBreakdown(
            notional=self.notional + other.notional,
            commission=self.commission + other.commission,
            market_rights=self.market_rights + other.market_rights,
            iva=self.iva + other.iva,
            slippage=self.slippage + other.slippage,
        )


@dataclass(frozen=True)
class LegNotional:
    asset_class: AssetClass
    notional: Decimal


@dataclass(frozen=True)
class EdgeResult:
    valid: bool
    gross_pct: Decimal
    cost_pct: Decimal
    financing_pct: Decimal
    net_pct: Decimal
    reason: str


class FeeEngine:
    def __init__(self, tier: BrokerTier, min_net_edge_pct: float | Decimal = DEFAULT_MIN_NET_EDGE) -> None:
        self.tier = tier
        self.min_net_edge_pct = to_dec(min_net_edge_pct)

    def leg_cost(
        self,
        asset_class: AssetClass,
        notional: float | Decimal,
        *,
        closing_same_day: bool = False,
    ) -> CostBreakdown:
        n = to_dec(notional)
        f = self.tier.fees[asset_class]
        discount = self.tier.intraday_exit_discount if closing_same_day else ZERO
        commission = n * f.commission_pct * (D(1) - discount)
        rights = n * f.market_rights_pct
        iva = (commission + rights) * self.tier.iva_pct
        slippage = n * f.slippage_bps / D(10_000)
        return CostBreakdown(
            notional=n, commission=commission, market_rights=rights, iva=iva, slippage=slippage
        )

    def round_trip(
        self, asset_class: AssetClass, notional: float | Decimal, *, same_day: bool = True
    ) -> CostBreakdown:
        entry = self.leg_cost(asset_class, notional)
        exit_ = self.leg_cost(asset_class, notional, closing_same_day=same_day)
        return entry + exit_

    def breakeven_move_pct(self, asset_class: AssetClass, *, same_day: bool = True) -> Decimal:
        """Movimiento bruto minimo (fraccion) para empatar una operacion de ida y vuelta."""
        return self.round_trip(asset_class, D(1), same_day=same_day).total_pct

    def signal_cost(self, legs: Sequence[LegNotional], *, atomic: bool) -> CostBreakdown:
        """Costo total de una senal.

        atomic=True : cada pata se ejecuta una sola vez (arbitraje de plazos), sin bonificacion
                      porque las patas son de plazos/especies distintos.
        atomic=False: cada pata se abre y luego se cierra el mismo dia (ida y vuelta).
        """
        total: CostBreakdown | None = None
        for lg in legs:
            c = (
                self.leg_cost(lg.asset_class, lg.notional)
                if atomic
                else self.round_trip(lg.asset_class, lg.notional, same_day=True)
            )
            total = c if total is None else total + c
        if total is None:
            raise ValueError("La senal no tiene patas")
        return total

    def evaluate(
        self,
        expected_gross_pct: float | Decimal,
        legs: Sequence[LegNotional],
        *,
        atomic: bool,
        financing_pct: float | Decimal = ZERO,
    ) -> EdgeResult:
        """Valida el edge neto. ``expected_gross_pct`` es relativo al nocional de la primera pata."""
        base = legs[0].notional
        if base <= 0:
            raise ValueError("Nocional base debe ser positivo")
        gross = to_dec(expected_gross_pct)
        fin = to_dec(financing_pct)
        cost = self.signal_cost(legs, atomic=atomic)
        cost_pct = cost.total / base
        net = gross - cost_pct - fin
        valid = net >= self.min_net_edge_pct
        reason = (
            "ok"
            if valid
            else f"edge neto {net:.5f} < minimo {self.min_net_edge_pct:.5f} "
            f"(bruto {gross:.5f}, costos {cost_pct:.5f}, financ. {fin:.5f})"
        )
        return EdgeResult(valid, gross, cost_pct, fin, net, reason)
