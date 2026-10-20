"""Tiers de comisiones del broker. Todos los porcentajes son fracciones (0.0015 = 0.15%).

IMPORTANTE: los valores por defecto son SUPUESTOS conservadores razonables; hay que reemplazarlos
por el cuadro tarifario real de tu cuenta (IOL / Primary) antes de operar en live.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from src.core.models import AssetClass

D = Decimal


class ClassFees(BaseModel):
    commission_pct: Decimal  # comision del broker por pata
    market_rights_pct: Decimal  # derechos de mercado BYMA / Rofex por pata
    slippage_bps: Decimal  # reserva de slippage por pata (adverso, ademas del spread cruzado)


class BrokerTier(BaseModel):
    name: str
    iva_pct: Decimal = D("0.21")  # IVA sobre comision + derechos
    # Bonificacion de comision en la pata de cierre si se compra/vende el mismo dia y plazo
    intraday_exit_discount: Decimal = Field(default=D("0"), ge=0, le=1)
    fees: dict[AssetClass, ClassFees]


def _fees(comm: str, rights: str, slip_bps: str) -> ClassFees:
    return ClassFees(commission_pct=D(comm), market_rights_pct=D(rights), slippage_bps=D(slip_bps))


def _tier(name: str, comm: str, discount: str, fut_comm: str) -> BrokerTier:
    return BrokerTier(
        name=name,
        intraday_exit_discount=D(discount),
        fees={
            AssetClass.SOVEREIGN_BOND: _fees(comm, "0.0001", "2"),
            AssetClass.LECAP: _fees(comm, "0.0001", "1"),
            AssetClass.EQUITY: _fees(comm, "0.0008", "5"),
            AssetClass.CEDEAR: _fees(comm, "0.0008", "5"),
            AssetClass.FUTURE: _fees(fut_comm, "0.0001", "3"),
        },
    )


TIERS: dict[str, BrokerTier] = {
    # minorista: 0.25% por pata, sin bonificacion
    "standard": _tier("standard", "0.0025", "0", "0.0010"),
    # frecuente/Gold: 0.15% por pata, la pata de cierre intradiaria paga 1/3 menos (~0.10%)
    "gold": _tier("gold", "0.0015", "0.3333", "0.0006"),
    # alto volumen: 0.10% por pata, cierre intradiario con 50% de bonificacion
    "vip": _tier("vip", "0.0010", "0.5", "0.0004"),
}


def get_tier(name: str) -> BrokerTier:
    try:
        return TIERS[name.lower()]
    except KeyError as e:
        raise ValueError(f"Tier desconocido '{name}'. Opciones: {sorted(TIERS)}") from e
