import numpy as np
import pytest

from tradebot.fastsim import Costs, simulate

from .conftest import make_bars

ZERO = Costs(0, 0, 0)


def run(ohlc, sig, **kw):
    df = make_bars([], ohlc=ohlc)
    s = np.zeros(len(df), int)
    for i, v in sig.items():
        s[i] = v
    return simulate(df, s, np.full(len(df), 10.0), kw.pop("sl", 1.0), kw.pop("tp", 2.0), kw.pop("mb", 100),
                    kw.pop("costs", ZERO), **kw)


def test_take_profit_is_plus_two_r_without_costs():
    t = run([(100, 100.5, 99.5, 100), (100, 105, 99, 104), (104, 125, 103, 124), (124, 125, 123, 124)], {0: 1})
    assert t.iloc[0].reason == "tp" and t.iloc[0].r == pytest.approx(2.0)


def test_stop_on_entry_bar_and_tie_goes_to_stop():
    t = run([(100, 100.5, 99.5, 100), (100, 130, 80, 100), (100, 101, 99, 100)], {0: 1})
    assert t.iloc[0].reason == "stop" and t.iloc[0].r == pytest.approx(-1.0)


def test_gap_through_stop_costs_more_than_one_r():
    t = run([(100, 100.5, 99.5, 100), (100, 101, 99, 100), (80, 81, 79, 80)], {0: 1})
    assert t.iloc[0].r == pytest.approx(-2.0)


def test_costs_make_a_stopout_exactly_minus_one_r():
    c = Costs(taker=0.0005, maker=0.0002, slippage=0.0002)
    t = run([(100, 100.5, 99.5, 100), (100, 100.5, 85, 86), (86, 87, 85, 86)], {0: 1}, costs=c)
    assert t.iloc[0].r == pytest.approx(-1.0, abs=0.02)


def test_limit_entry_only_fills_when_touched():
    ohlc = [(100, 100.5, 99.5, 100), (100, 101, 99, 100), (100, 101, 94, 95), (95, 120, 94, 119)]
    t = run(ohlc, {0: 1, 1: 1}, entry="limit", limit_offset_atr=0.5)  # límite a 95
    assert len(t) == 1 and t.iloc[0].entry == 95  # la señal 0 no se llena (low 99), la 1 sí


def test_no_overlap_and_short_mirror():
    ohlc = [(100, 100.5, 99.5, 100), (100, 101, 95, 96), (96, 97, 75, 76), (76, 77, 75, 76)]
    t = run(ohlc, {0: -1, 1: -1})
    assert len(t) == 1 and t.iloc[0].side == -1 and t.iloc[0].r == pytest.approx(2.0)
