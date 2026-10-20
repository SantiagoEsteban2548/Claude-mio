"""Backtest con respuestas conocidas: se verifican precios de llenado, costos y PnL exactos."""
from dataclasses import replace

import pytest

from tradebot.backtest import run_backtest
from tradebot.strategies import build_strategy

from .conftest import make_bars, make_signals

FEE, SLIP = 0.001, 0.0005


def strat(sl=1.0, tp=2.0, max_bars=1000):
    return build_strategy("mean_reversion", {"sl_atr": sl, "tp_atr": tp, "max_bars": max_bars})


def test_entry_next_open_and_take_profit_exact_pnl(settings):
    # vela 0: señal al cierre (100). vela 1 abre 100 -> entrada. TP = 100 + 2*10 = 120 (precio de referencia: cierre señal)
    ohlc = [(100, 100.5, 99.5, 100), (100, 105, 99, 104), (104, 125, 103, 124), (124, 125, 123, 124)]
    df = make_bars([], ohlc=ohlc)
    r = run_backtest(df, settings, strat(), signals=make_signals(df, {0: 1}))
    t = r.trades.iloc[0]
    entry = 100 * (1 + SLIP)
    assert t.entry_price == pytest.approx(entry)
    assert t.reason == "take_profit"
    qty = r.trades.iloc[0].risk / (10 + 100 * 2 * (FEE + SLIP))
    exit_px = 120  # límite: el slippage no lo empeora (slip_limit)
    expected = qty * (exit_px - entry) - FEE * qty * (entry + exit_px)
    assert t.pnl == pytest.approx(expected, rel=1e-6)


def test_stop_triggers_on_the_entry_bar(settings):
    # La vela de entrada perfora el stop (90). Debe salir en ESA vela a 90, no en la siguiente apertura (70).
    ohlc = [(100, 100.5, 99.5, 100), (100, 100.5, 85, 86), (70, 71, 69, 70), (70, 71, 69, 70)]
    df = make_bars([], ohlc=ohlc)
    r = run_backtest(df, settings, strat(), signals=make_signals(df, {0: 1}))
    t = r.trades.iloc[0]
    assert t.reason == "stop_loss"
    assert t.bars == 0
    assert t.r == pytest.approx(-1.0, abs=0.06)
    assert len(r.trades) == 1 and r.trades.side.eq("long").all()


def test_stop_wins_when_stop_and_tp_share_a_bar(settings):
    ohlc = [(100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100), (100, 130, 80, 100), (100, 101, 99, 100)]
    df = make_bars([], ohlc=ohlc)
    r = run_backtest(df, settings, strat(), signals=make_signals(df, {0: 1}))
    assert r.trades.iloc[0].reason == "stop_loss"


def test_gap_through_stop_fills_at_open(settings):
    ohlc = [(100, 100.5, 99.5, 100), (100, 101, 99, 100), (80, 81, 79, 80), (80, 81, 79, 80)]
    df = make_bars([], ohlc=ohlc)
    r = run_backtest(df, settings, strat(), signals=make_signals(df, {0: 1}))
    t = r.trades.iloc[0]
    assert t.reason == "stop_loss"
    assert t.r < -1.5  # el gap cuesta más que 1R: el test documenta que el stop no es una garantía


def test_time_exit(settings):
    df = make_bars([100] * 12)
    r = run_backtest(df, settings, strat(sl=5, tp=5, max_bars=3), signals=make_signals(df, {0: 1}))
    assert r.trades.iloc[0].reason == "time_exit"


def test_risk_per_trade_respected_and_costs_reported(settings):
    df = make_bars([100] * 3 + [80] * 5)
    r = run_backtest(df, settings, strat(sl=1.0), signals=make_signals(df, {2: 1}))
    t = r.trades.iloc[0]
    assert t.risk == pytest.approx(settings.backtest.initial_cash * settings.risk.risk_per_trade, rel=1e-6)
    assert r.metrics["fees_paid"] > 0 and r.metrics["slippage_cost"] > 0


def test_leverage_cap_limits_notional(settings):
    # ATR diminuto => tamaño por riesgo enorme; el tope 1x lo limita al equity.
    df = make_bars([100] * 6)
    r = run_backtest(df, settings, strat(sl=0.001, tp=1000, max_bars=2), signals=make_signals(df, {0: 1}, atr=0.01))
    t = r.trades.iloc[0]
    notional = t.risk / (0.00001 + 100 * 2 * (FEE + SLIP)) * t.entry_price
    assert 0.95 * settings.backtest.initial_cash < notional <= settings.backtest.initial_cash


def test_daily_budget_shrinks_later_trades(settings):
    risk = replace(settings.risk, risk_per_trade=0.01, max_daily_drawdown=0.015)
    s = replace(settings, risk=risk)
    # tres pérdidas seguidas el mismo día: cada nueva operación arriesga como máximo lo que queda del límite
    closes = [100, 100, 80, 80, 80, 80, 60, 60, 60, 60, 40, 40, 40]
    df = make_bars(closes, spread=0.1)
    sig = make_signals(df, {1: 1, 5: 1, 9: 1}, atr=5.0)
    r = run_backtest(df, s, strat(sl=1.0, tp=10), signals=sig)
    day_pnl = r.equity.iloc[-1] / s.backtest.initial_cash - 1
    assert day_pnl > -0.015
    risks = list(r.trades.risk)
    assert risks[0] == pytest.approx(100, rel=1e-6)
    assert risks[1] < 0.5 * risks[0] and risks[2] < 0.1 * risks[0]


def test_short_mirror(settings):
    ohlc = [(100, 100.5, 99.5, 100), (100, 101, 95, 96), (96, 97, 75, 76), (76, 77, 75, 76)]
    df = make_bars([], ohlc=ohlc)
    st = build_strategy("mean_reversion", {"sl_atr": 1.0, "tp_atr": 2.0}, allow_short=True)
    r = run_backtest(df, settings, st, signals=make_signals(df, {0: -1}))
    t = r.trades.iloc[0]
    assert t.side == "short" and t.reason == "take_profit" and t.pnl > 0


def test_daily_breaker_after_gap_blocks_rest_of_day(settings):
    # Un gap atraviesa el stop y la pérdida del día supera 2%: se dispara el breaker y las señales
    # siguientes de ese día se ignoran; al día siguiente se vuelve a operar.
    ohlc = [(100, 100.5, 99.5, 100)] * 3 + [(70, 70.5, 69.5, 70)] * 4
    df = make_bars([], ohlc=ohlc, freq="6h")  # 7 velas de 6h: días 1 y 2
    sig = make_signals(df, {1: 1, 4: 1, 5: 1}, atr=2.0)
    r = run_backtest(df, settings, strat(sl=1.0, tp=10), signals=sig)
    assert r.metrics["daily_breakers"] == 1
    assert r.trades.iloc[0].reason == "stop_loss"
    assert len(r.trades) == 2  # la señal de la vela 4 (día 2) sí se opera
    assert r.trades.iloc[1].entry_time.date() > r.trades.iloc[0].exit_time.date()


def test_leverage_2x_allows_twice_the_notional(settings):
    from dataclasses import replace as rep
    s = rep(settings, risk=rep(settings.risk, max_leverage=2.0))
    df = make_bars([100] * 6)
    r = run_backtest(df, s, strat(sl=0.001, tp=1000, max_bars=2), signals=make_signals(df, {0: 1}, atr=0.01))
    t = r.trades.iloc[0]
    notional = t.risk / (0.00001 + 100 * 2 * (FEE + SLIP)) * t.entry_price
    assert 1.9 * s.backtest.initial_cash < notional <= 2 * s.backtest.initial_cash
