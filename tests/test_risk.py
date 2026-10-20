from dataclasses import replace

import pandas as pd
import pytest

from tradebot.config import ConservativeConfig, LossStreakConfig, RiskConfig
from tradebot.risk import KELLY_MIN_TRADES, RiskManager

T0 = pd.Timestamp("2024-01-01 00:00", tz="UTC")


def rm(**kw) -> RiskManager:
    base = dict(risk_per_trade=0.01, daily_profit_target=None, conservative=ConservativeConfig(enabled=False),
                loss_streak=LossStreakConfig(after_losses=99, size_multiplier=1.0))
    return RiskManager(RiskConfig(**{**base, **kw}), 10_000)


def test_fixed_fractional_size():
    r = rm()
    qty, risk = r.position_size(10_000, 100, 5, high_vol=False)
    assert risk == pytest.approx(100)
    assert qty == pytest.approx(20)


def test_conservative_mode_halves_size_in_high_vol():
    r = rm(conservative=ConservativeConfig(enabled=True, size_multiplier=0.5))
    assert r.position_size(10_000, 100, 5, high_vol=True)[1] == pytest.approx(50)
    assert r.position_size(10_000, 100, 5, high_vol=False)[1] == pytest.approx(100)


def test_loss_streak_reduces_size_until_a_win():
    r = rm(loss_streak=LossStreakConfig(after_losses=2, size_multiplier=0.5))
    r.record_trade(-1, 1)
    r.record_trade(-1, 1)
    assert r.risk_fraction(False) == pytest.approx(0.005)
    r.record_trade(+1, 1)
    assert r.risk_fraction(False) == pytest.approx(0.01)


def test_daily_breaker_and_reset_next_day():
    r = rm(max_daily_drawdown=0.02)
    r.on_bar(T0, 10_000)
    ev = r.on_bar(T0 + pd.Timedelta("1h"), 9_790)
    assert [e.kind for e in ev] == ["daily_breaker"]
    assert r.must_flatten() and not r.can_open()
    r.on_bar(T0 + pd.Timedelta("1D"), 9_790)
    assert r.can_open()


def test_new_trade_risk_capped_by_remaining_daily_budget():
    r = rm(max_daily_drawdown=0.02)
    r.on_bar(T0, 10_000)
    r.on_bar(T0 + pd.Timedelta("1h"), 9_850)  # -1.5% en el día: queda 0.5%
    assert r.risk_fraction(False) == pytest.approx(0.9 * 0.005 * 10_000 / 9_850, rel=1e-6)


def test_kill_switch_is_permanent():
    r = rm(max_total_drawdown=0.10)
    r.on_bar(T0, 10_000)
    r.on_bar(T0 + pd.Timedelta("1h"), 11_000)
    ev = r.on_bar(T0 + pd.Timedelta("2h"), 9_900)  # -10% desde el pico
    assert "kill_switch" in [e.kind for e in ev]
    r.on_bar(T0 + pd.Timedelta("3D"), 12_000)
    assert r.killed and not r.can_open()


def test_daily_profit_target_stops_new_entries():
    r = rm(daily_profit_target=0.005)
    r.on_bar(T0, 10_000)
    ev = r.on_bar(T0 + pd.Timedelta("1h"), 10_060)
    assert [e.kind for e in ev] == ["daily_target"]
    assert not r.can_open() and not r.must_flatten()


def test_kelly_uses_history_and_is_bounded():
    r = rm(sizing="kelly", kelly_fraction=0.25)
    assert r.risk_fraction(False) == pytest.approx(0.005)  # sin historia: mitad del riesgo base
    for _ in range(KELLY_MIN_TRADES):
        r.record_trade(2, 1)
        r.record_trade(-1, 1)
    # W=0.5, payoff=2 -> f*=0.25 -> 1/4 Kelly = 6.25%, acotado a risk_per_trade
    assert r.risk_fraction(False) == pytest.approx(0.01)
    for _ in range(KELLY_MIN_TRADES * 3):
        r.record_trade(-1, 1)
    assert r.risk_fraction(False) == pytest.approx(0.001)  # edge negativo: tamaño de sondeo


def test_validate_rejects_bad_kelly():
    with pytest.raises(ValueError):
        replace(RiskConfig(), kelly_fraction=0.9).validate()
