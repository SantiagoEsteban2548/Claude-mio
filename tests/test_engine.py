from datetime import timedelta

import pytest

from src.core.models import Settlement
from src.execution.engine import TradingEngine
from src.execution.paper import PaperBroker
from src.fee_engine.engine import FeeEngine
from src.fee_engine.tiers import get_tier
from src.risk.manager import RiskConfig, RiskManager
from src.strategies.orderbook_imbalance import OrderBookImbalance, book_imbalance
from src.strategies.state import MarketState
from src.strategies.term_arbitrage import RatioArbitrage, TermArbitrage
from tests.helpers import mk_book, t


def make_engine(strategies, capital: float = 1_000_000, inventory=None) -> TradingEngine:
    fees = FeeEngine(get_tier("gold"))
    state = MarketState(caucion_colocadora_tna=0.28, caucion_tomadora_tna=0.34)
    return TradingEngine(
        strategies,
        state,
        PaperBroker(fees, inventory or {}),
        RiskManager(RiskConfig(capital_ars=capital)),
        fees,
    )


async def feed_term(engine: TradingEngine, ts, ci_ask: float, h24_bid: float) -> None:
    await engine.on_book(mk_book("AL30", ci_ask - 5, ci_ask, ts, Settlement.CI))
    await engine.on_book(mk_book("AL30", h24_bid, h24_bid + 5, ts, Settlement.H24))


async def test_term_arb_rejected_when_carry_below_costs() -> None:
    e = make_engine([TermArbitrage(["AL30"])])
    await feed_term(e, t(12, 0), 60_000, 60_060)  # +0.10%: no cubre 2 patas de costos
    assert e.trades == 0 and e.rejections.get("edge insuficiente", 0) >= 1


async def test_term_arb_executes_and_pnl_is_net_of_fees() -> None:
    e = make_engine([TermArbitrage(["AL30"])])
    await feed_term(e, t(12, 0), 60_000, 61_500)  # +2.5%
    assert e.trades == 2
    assert e.realized_gross_ars > 0 and e.fees_ars > 0
    assert e.realized_net_ars == pytest.approx(e.realized_gross_ars - e.fees_ars)
    assert e.risk.daily_pnl_ars == pytest.approx(e.realized_net_ars)


async def test_order_size_never_exceeds_25pct_of_touch() -> None:
    e = make_engine([TermArbitrage(["AL30"])], capital=10**10)
    sent: list[float] = []
    real_submit = e.broker.submit

    async def spy(order, book, closing=False):  # type: ignore[no-untyped-def]
        sent.append(order.qty)
        return await real_submit(order, book, closing)

    e.broker.submit = spy  # type: ignore[method-assign]
    await e.on_book(mk_book("AL30", 59_995, 60_000, t(12, 0), Settlement.CI, asize=400))
    await e.on_book(mk_book("AL30", 61_500, 61_505, t(12, 0), Settlement.H24, bsize=10_000))
    assert sent == [100, 100]  # 25% de 400 en la punta vendedora de CI


async def test_no_entries_during_opening_block() -> None:
    e = make_engine([TermArbitrage(["AL30"])])
    await feed_term(e, t(11, 2), 60_000, 61_500)
    assert e.trades == 0


async def test_kill_switch_flattens_and_blocks_new_trades() -> None:
    obi = OrderBookImbalance(["AL30"], cooldown_seconds=0)
    e = make_engine([obi], inventory={})
    start = t(11, 10)
    # historia con volatilidad realista y desbalance comprador sostenido
    px = 60_000.0
    for i in range(30):
        px *= 1.0 + (0.002 if i % 2 else -0.002)
        await e.on_book(
            mk_book(
                "AL30",
                px - 15,
                px + 15,
                start + timedelta(seconds=5 * i),
                bsize=9000,
                asize=500,
                last=px,
                vol=1000 * (i + 1),
            )
        )
    assert e.positions.open_positions(), e.rejections
    pos = e.positions.open_positions()[0]
    # el precio se desploma: P&L no realizado cruza -0.8% del capital
    crash = pos.avg_price * 0.80
    await e.on_book(
        mk_book(
            "AL30",
            crash,
            crash + 30,
            start + timedelta(minutes=5),
            bsize=9000,
            asize=500,
            last=crash,
            vol=40_000,
        )
    )
    assert e.risk.kill_switch
    assert not e.positions.open_positions()  # cerrado por flatten
    n = e.trades
    await e.on_book(mk_book("AL30", 60_000, 60_030, start + timedelta(minutes=9), bsize=9000, asize=500))
    assert e.trades == n  # sin nuevas operaciones tras el kill-switch


async def test_forced_flatten_at_1630() -> None:
    obi = OrderBookImbalance(["AL30"], cooldown_seconds=0)
    e = make_engine([obi])
    px = 60_000.0
    for i in range(30):
        px *= 1.0 + (0.002 if i % 2 else -0.002)
        await e.on_book(
            mk_book(
                "AL30",
                px - 15,
                px + 15,
                t(16, 5, 0) + timedelta(seconds=i),
                bsize=9000,
                asize=500,
                last=px,
                vol=1000 * (i + 1),
            )
        )
    assert e.positions.open_positions()
    await e.on_book(mk_book("AL30", px - 15, px + 15, t(16, 30, 1), bsize=9000, asize=500))
    assert not e.positions.open_positions()


def test_book_imbalance_bounds() -> None:
    b = mk_book("GGAL", 100, 101, t(12, 0), bsize=900, asize=100)
    assert book_imbalance(b) > 0.7
    assert book_imbalance(mk_book("GGAL", 100, 101, t(12, 0), bsize=100, asize=900)) < -0.7


async def test_ratio_arb_enters_on_zscore_and_exits_on_reversion() -> None:
    strat = RatioArbitrage(window=200, min_samples=60, entry_z=2.0, exit_z=0.5, sample_every=1.0)
    e = make_engine([strat], inventory={"AL30": 1e6, "GD30": 1e6}, capital=10**9)
    base = t(11, 30)
    # el ratio oscila alrededor de 1.0 con ruido amplio (std ~ 1.5%) y luego se dispara
    for i in range(80):
        r = 1.0 + (0.015 if i % 2 else -0.015)
        await e.on_book(mk_book("GD30", 60_000 - 3, 60_000 + 3, base + timedelta(seconds=2 * i)))
        await e.on_book(mk_book("AL30", 60_000 * r - 3, 60_000 * r + 3, base + timedelta(seconds=2 * i)))
    spike = base + timedelta(seconds=200)
    await e.on_book(mk_book("GD30", 59_997, 60_003, spike))
    await e.on_book(mk_book("AL30", 60_000 * 1.06 - 3, 60_000 * 1.06 + 3, spike))
    assert strat.open_side == "short_ratio", (strat.last_z, e.rejections)
    # el ratio revierte a la media
    back = spike + timedelta(seconds=30)
    await e.on_book(mk_book("GD30", 59_997, 60_003, back))
    await e.on_book(mk_book("AL30", 59_997, 60_003, back))
    assert strat.open_side is None and not e.positions.open_positions()
    assert e.realized_net_ars > 0
