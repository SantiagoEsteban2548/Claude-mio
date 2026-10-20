from datetime import datetime

import pytest

from src.core.clock import ART
from src.core.models import BookLevel, OrderBook, Settlement, Side
from src.risk.manager import MarketPhase, RiskConfig, RiskManager
from src.risk.sizing import kelly_fraction, liquidity_cap_qty, max_notional_ars, qty_for_notional


def ts(h: int, m: int, day: int = 20) -> datetime:  # 2026-10-20 es martes
    return datetime(2026, 10, day, h, m, tzinfo=ART)


@pytest.fixture
def rm() -> RiskManager:
    r = RiskManager(RiskConfig(capital_ars=1_000_000))
    r.roll_day(ts(11, 0))
    return r


def test_phases(rm: RiskManager) -> None:
    assert rm.phase(ts(10, 59)) is MarketPhase.CLOSED
    assert rm.phase(ts(11, 0)) is MarketPhase.OPENING_BLOCK
    assert rm.phase(ts(11, 4)) is MarketPhase.OPENING_BLOCK
    assert rm.phase(ts(11, 5)) is MarketPhase.TRADING
    assert rm.phase(ts(16, 9)) is MarketPhase.TRADING
    assert rm.phase(ts(16, 10)) is MarketPhase.NO_NEW_ENTRIES
    assert rm.phase(ts(16, 30)) is MarketPhase.FLATTEN
    assert rm.phase(ts(16, 55)) is MarketPhase.CLOSED
    assert rm.phase(ts(12, 0, day=24)) is MarketPhase.CLOSED  # sabado


def test_flatten_window(rm: RiskManager) -> None:
    assert not rm.must_flatten(ts(15, 0))
    assert rm.must_flatten(ts(16, 30))


def test_no_entries_in_opening_block(rm: RiskManager) -> None:
    d = rm.check_entry(ts(11, 3), gross_exposure_ars=0, new_notional_ars=1000)
    assert not d.allowed


def test_kill_switch_triggers_at_minus_point_eight_percent(rm: RiskManager) -> None:
    assert not rm.update_pnl(-7_000, 0)  # -0.7%
    assert not rm.kill_switch
    assert rm.update_pnl(-4_000, -4_000)  # -0.8%
    assert rm.kill_switch
    assert rm.must_flatten(ts(12, 0))
    d = rm.check_entry(ts(12, 0), gross_exposure_ars=0, new_notional_ars=1000)
    assert not d.allowed and "kill-switch" in d.reason


def test_kill_switch_counts_unrealized_losses(rm: RiskManager) -> None:
    assert rm.update_pnl(0, -8_000)
    assert rm.kill_switch


def test_kill_switch_resets_next_day(rm: RiskManager) -> None:
    rm.update_pnl(-9_000, 0)
    assert rm.kill_switch
    assert rm.roll_day(ts(11, 10, day=21))
    assert not rm.kill_switch and rm.daily_pnl_ars == 0


def test_gross_exposure_limit(rm: RiskManager) -> None:
    d = rm.check_entry(ts(12, 0), gross_exposure_ars=500_000, new_notional_ars=150_000)
    assert not d.allowed
    assert rm.check_entry(ts(12, 0), gross_exposure_ars=100_000, new_notional_ars=150_000).allowed


def test_book_checks(rm: RiskManager) -> None:
    assert not rm.check_book(None, 0).allowed
    assert not rm.check_book(0.05, 0).allowed
    assert not rm.check_book(0.001, 30).allowed
    assert rm.check_book(0.001, 1).allowed


def _book() -> OrderBook:
    return OrderBook(
        symbol="GGAL",
        settlement=Settlement.CI,
        bids=[BookLevel(price=100, size=1000)],
        asks=[BookLevel(price=101, size=400), BookLevel(price=102, size=5000)],
        ts=ts(12, 0),
    )


def test_liquidity_cap_is_25_percent_of_opposite_touch() -> None:
    b = _book()
    assert liquidity_cap_qty(b, Side.BUY, 0.25) == 100  # 25% de 400 (ask)
    assert liquidity_cap_qty(b, Side.SELL, 0.25) == 250  # 25% de 1000 (bid)


def test_kelly() -> None:
    assert kelly_fraction(0.5, 1.0) == 0.0
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.4)
    assert kelly_fraction(0.3, 1.0) == 0.0  # edge negativo => no apostar


def test_sizing_caps(rm: RiskManager) -> None:
    cfg = rm.cfg
    assert max_notional_ars(cfg, win_prob=None, take_profit_pct=None, stop_loss_pct=None) == (
        cfg.capital_ars * cfg.max_position_pct
    )
    n = max_notional_ars(cfg, win_prob=0.6, take_profit_pct=0.008, stop_loss_pct=0.004)
    assert n == pytest.approx(cfg.capital_ars * 0.4 * 0.25)  # Kelly 0.4 * fraccion 0.25 = 10%
    assert max_notional_ars(cfg, win_prob=0.3, take_profit_pct=0.008, stop_loss_pct=0.004) == 0


def test_qty_for_notional_bond_multiplier() -> None:
    # AL30 a 60000 ARS cada 100 VN => 600 ARS por nominal
    assert qty_for_notional(100_000, 60_000, 0.01, 1.0) == 166
