from decimal import Decimal as D

import pytest

from src.core.models import AssetClass
from src.fee_engine.benchmark import compound, usd_mep_return
from src.fee_engine.engine import FeeEngine, LegNotional
from src.fee_engine.tiers import get_tier


@pytest.fixture
def gold() -> FeeEngine:
    return FeeEngine(get_tier("gold"))


def test_leg_cost_exact_components(gold: FeeEngine) -> None:
    c = gold.leg_cost(AssetClass.SOVEREIGN_BOND, D("1000000"))
    assert c.commission == D("1500")  # 0.15%
    assert c.market_rights == D("100")  # 0.01%
    assert c.iva == D("336")  # 21% de (1500 + 100)
    assert c.slippage == D("200")  # 2 bps
    assert c.fees == D("1936")
    assert c.total == D("2136")


def test_intraday_discount_only_on_closing_leg(gold: FeeEngine) -> None:
    entry = gold.leg_cost(AssetClass.EQUITY, D("100000"))
    exit_ = gold.leg_cost(AssetClass.EQUITY, D("100000"), closing_same_day=True)
    assert exit_.commission < entry.commission
    assert exit_.commission == D("100000") * D("0.0015") * (D(1) - D("0.3333"))
    assert exit_.market_rights == entry.market_rights  # derechos de mercado no se bonifican


def test_round_trip_equals_entry_plus_exit(gold: FeeEngine) -> None:
    rt = gold.round_trip(AssetClass.EQUITY, D("50000"))
    e = gold.leg_cost(AssetClass.EQUITY, D("50000"))
    x = gold.leg_cost(AssetClass.EQUITY, D("50000"), closing_same_day=True)
    assert rt.total == e.total + x.total
    assert rt.notional == D("100000")  # suma de nocionales de ambas patas


def test_breakeven_includes_rights_iva_and_slippage(gold: FeeEngine) -> None:
    be = gold.breakeven_move_pct(AssetClass.EQUITY)
    commissions_only = D("0.0015") + D("0.0015") * (D(1) - D("0.3333"))
    assert be > commissions_only * 2 / 2  # estrictamente mayor que solo comisiones
    # Ida y vuelta de acciones en Gold ronda 0.4%-0.5% del nocional de una pata
    assert D("0.003") < be * 2 < D("0.006")


def test_standard_tier_costs_more_than_gold() -> None:
    std = FeeEngine(get_tier("standard")).breakeven_move_pct(AssetClass.EQUITY)
    gld = FeeEngine(get_tier("gold")).breakeven_move_pct(AssetClass.EQUITY)
    assert std > gld


def test_signal_rejected_when_edge_below_costs(gold: FeeEngine) -> None:
    legs = [LegNotional(AssetClass.EQUITY, D("100000"))]
    res = gold.evaluate(D("0.002"), legs, atomic=False)  # 0.2% bruto < costos de ida y vuelta
    assert not res.valid
    assert res.net_pct < 0


def test_signal_accepted_when_edge_covers_everything(gold: FeeEngine) -> None:
    legs = [LegNotional(AssetClass.EQUITY, D("100000"))]
    res = gold.evaluate(D("0.010"), legs, atomic=False)
    assert res.valid
    assert res.net_pct == res.gross_pct - res.cost_pct


def test_financing_cost_is_deducted(gold: FeeEngine) -> None:
    legs = [LegNotional(AssetClass.SOVEREIGN_BOND, D("100000"))]
    no_fin = gold.evaluate(D("0.0060"), legs, atomic=True)
    with_fin = gold.evaluate(D("0.0060"), legs, atomic=True, financing_pct=D("0.0010"))
    assert with_fin.net_pct == no_fin.net_pct - D("0.0010")


def test_atomic_has_no_intraday_discount_but_two_legs_cost_double(gold: FeeEngine) -> None:
    legs = [
        LegNotional(AssetClass.SOVEREIGN_BOND, D("100000")),
        LegNotional(AssetClass.SOVEREIGN_BOND, D("100000")),
    ]
    cost = gold.signal_cost(legs, atomic=True)
    one = gold.leg_cost(AssetClass.SOVEREIGN_BOND, D("100000"))
    assert cost.total == one.total * 2


def test_min_net_edge_threshold_boundary() -> None:
    eng = FeeEngine(get_tier("gold"), min_net_edge_pct=D("0.001"))
    legs = [LegNotional(AssetClass.SOVEREIGN_BOND, D("100000"))]
    cost_pct = eng.signal_cost(legs, atomic=True).total_pct
    assert eng.evaluate(cost_pct + D("0.001"), legs, atomic=True).valid
    assert not eng.evaluate(cost_pct + D("0.0009"), legs, atomic=True).valid


def test_empty_legs_raise(gold: FeeEngine) -> None:
    with pytest.raises(ValueError):
        gold.signal_cost([], atomic=True)


def test_unknown_tier() -> None:
    with pytest.raises(ValueError):
        get_tier("platinum")


def test_benchmarks() -> None:
    assert compound([0.004, 0.004]) == pytest.approx(1.004**2 - 1)
    # 0.4% en ARS con MEP +0.4% => 0% en USD
    assert usd_mep_return(0.004, 1000, 1004) == pytest.approx(0.0, abs=1e-12)
