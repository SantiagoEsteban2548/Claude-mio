import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.scalping import research as R
from src.scalping.data import parse_klines_csv, parse_zip
from src.scalping.engine import LOSS, TIME, WIN, EngineCfg, simulate
from src.scalping.signals import GRIDS, atr, make_signal
from src.scalping.synthetic import random_walk

NO_COST = EngineCfg(fee_bps=0, slip_bps=0, min_stop_pct=0, max_cost_r=99, rr=3.0, max_hold=300)


def flat(n: int, px: float = 100.0):
    a = np.full(n, px)
    return a.copy(), a.copy(), a.copy(), a.copy(), np.full(n, 1.0)  # o,h,low,c,atr


def test_entry_at_next_open_and_target_hit() -> None:
    o, h, lo, c, a = flat(10)
    o[3] = 100.0
    h[4] = 103.5  # objetivo = 100 + 3*1.0
    sig = np.zeros(10, dtype=np.int8)
    sig[2] = 1
    t = simulate(o, h, lo, c, a, sig, EngineCfg(**{**NO_COST.__dict__, "stop_atr": 1.0}))
    assert t.entry_idx[0] == 3 and t.outcome[0] == WIN and t.r_net[0] == pytest.approx(3.0)


def test_same_bar_stop_and_target_counts_as_loss() -> None:
    o, h, lo, c, a = flat(10)
    h[4], lo[4] = 104.0, 98.0  # la barra cubre stop y objetivo
    sig = np.zeros(10, dtype=np.int8)
    sig[2] = 1
    t = simulate(o, h, lo, c, a, sig, EngineCfg(**{**NO_COST.__dict__, "stop_atr": 1.0}))
    assert t.outcome[0] == LOSS and t.r_net[0] == pytest.approx(-1.0)


def test_short_and_time_exit() -> None:
    o, h, lo, c, a = flat(60)
    c[-1] = 99.5
    sig = np.zeros(60, dtype=np.int8)
    sig[2] = -1
    t = simulate(o, h, lo, c, a, sig, EngineCfg(**{**NO_COST.__dict__, "stop_atr": 1.0, "max_hold": 20}))
    assert t.outcome[0] == TIME and t.exit_idx[0] == 22
    assert t.r_net[0] == pytest.approx(0.0)  # c[22] == entry


def test_costs_are_charged_in_r_and_expensive_trades_skipped() -> None:
    o, h, lo, c, a = flat(10)
    h[4] = 110.0
    sig = np.zeros(10, dtype=np.int8)
    sig[2] = 1
    cfg = EngineCfg(fee_bps=5, slip_bps=0, min_stop_pct=0, max_cost_r=99, stop_atr=1.0)
    t = simulate(o, h, lo, c, a, sig, cfg)
    assert t.r_net[0] == pytest.approx(3.0 - 100 * 2 * 5e-4 / 1.0)  # 0.1 / 1.0 = 0.1R
    strict = EngineCfg(**{**cfg.__dict__, "max_cost_r": 0.05})
    assert len(simulate(o, h, lo, c, a, sig, strict)) == 0


def test_null_hypothesis_random_signals_give_25pct_wr_and_zero_expectancy() -> None:
    """Control negativo: sin edge y sin costos, R:R 1:3 debe dar WR ~25% y E[R] ~ 0."""
    df = random_walk(seed=3, start="2021-01-01", end="2022-07-01")
    rng = np.random.default_rng(1)
    sig = (rng.random(len(df)) < 0.01).astype(np.int8) * rng.choice([-1, 1], len(df)).astype(np.int8)
    t = simulate(
        df["open"].to_numpy(),
        df["high"].to_numpy(),
        df["low"].to_numpy(),
        df["close"].to_numpy(),
        atr(df),
        sig,
        EngineCfg(**{**NO_COST.__dict__, "stop_atr": 1.5, "max_hold": 500}),
    )
    wr = (t.outcome == WIN).mean()
    assert len(t) > 500
    assert 0.20 < wr < 0.30
    assert abs(t.r_net.mean()) < 0.2


@pytest.mark.parametrize("family", list(GRIDS))
def test_signals_are_causal(family: str) -> None:
    """La senal en i no puede cambiar si se recorta el futuro (sin lookahead)."""
    df = random_walk(seed=5, start="2021-01-01", end="2021-03-01")
    p = GRIDS[family][0]
    full = make_signal(df, family, p)
    cut = 6000
    part = make_signal(df.iloc[:cut], family, p)
    assert np.array_equal(full[:cut], part)
    assert full.any()


def test_clip_hides_oos() -> None:
    df = random_walk(seed=0, start="2024-12-01", end="2025-02-01")
    out = R.clip({"X": df}, None, R.OOS_START)["X"]
    assert out.index.max() < R.OOS_START and len(out) < len(df)


def test_all_configs_count_and_roundtrip() -> None:
    cfgs = R.all_configs()
    assert len(cfgs) == (6 + 8 + 6) * 8
    assert R.Config.from_json(cfgs[5].to_json()) == cfgs[5]


def _csv(ts: int, header: bool) -> bytes:
    head = "open_time,open,high,low,close,volume,close_time\n" if header else ""
    return (head + f"{ts},1,2,0.5,1.5,10,{ts + 299999}\n").encode()


@pytest.mark.parametrize(("ts", "header"), [(1_700_000_000_000, False), (1_700_000_000_000_000, True)])
def test_parse_ms_and_us_timestamps(ts: int, header: bool) -> None:
    df = parse_klines_csv(_csv(ts, header))
    assert df.index[0] == pd.Timestamp("2023-11-14 22:13:20", tz="UTC")
    assert df["close"].iloc[0] == 1.5


def test_parse_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", _csv(1_700_000_000_000, False))
    assert len(parse_zip(buf.getvalue())) == 1


def test_positive_control_detects_a_planted_edge() -> None:
    """Con autocorrelacion AR(1) real, la senal 'sigue la barra previa' debe superar el 25% de WR."""
    rng = np.random.default_rng(7)
    n = 120_000
    shock = rng.standard_normal(n) * 0.002
    ret = np.zeros(n)
    for i in range(1, n):
        ret[i] = 0.35 * ret[i - 1] + shock[i]
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * 1.0004
    low = np.minimum(open_, close) * 0.9996
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1.0})
    sig = np.sign(ret).astype(np.int8)
    t = simulate(
        open_,
        high,
        low,
        close,
        atr(df),
        sig,
        EngineCfg(**{**NO_COST.__dict__, "stop_atr": 1.0, "max_hold": 20}),
    )
    wr = (t.outcome == WIN).mean()
    assert wr > 0.27 and t.r_net.mean() > 0.1
