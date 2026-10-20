"""Laboratorio de scalping (investigación). Señales parametrizables + helpers. Solo se usa in-sample salvo
que se llame explícitamente con el período OOS."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tradebot import indicators as ind  # noqa: E402
from tradebot.data import htf_series, load_csv  # noqa: E402
from tradebot.fastsim import Costs, simulate, summary  # noqa: E402

IS = ("2023-01-01", "2025-01-01")
OOS = ("2025-01-01", None)
TAKER = Costs(taker=0.0005, maker=0.0005, slippage=0.0002)   # todo taker (market + stop market + TP market)
MIXED = Costs(taker=0.0005, maker=0.0002, slippage=0.0002)   # entrada/TP limit maker, SL taker
VIP = Costs(taker=0.0004, maker=0.0000, slippage=0.0001)     # maker 0% (nivel VIP / rebates), BTC muy líquido
ZERO = Costs(0, 0, 0)


def load(tf: str = "5m") -> pd.DataFrame:
    return load_csv(Path(__file__).resolve().parents[2] / f"data/BTCUSD_bitstamp_{tf}.csv.gz")


def features(df: pd.DataFrame, htf: str = "1h") -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["atr"] = ind.atr(df, 14)
    f["atr_pct"] = f.atr / df.close
    up, mid, lo = ind.bbands(df.close, 20, 2.0)
    f["bb_up"], f["bb_mid"], f["bb_lo"] = up, mid, lo
    f["rsi"] = ind.rsi(df.close, 14)
    f["rsi3"] = ind.rsi(df.close, 3)
    f["adx"] = pd.Series(talib.ADX(df.high.values, df.low.values, df.close.values, 14), index=df.index)
    f["vol_ratio"] = df.volume / df.volume.rolling(50).mean()
    f["hour"] = df.index.hour
    f["htf_trend"] = htf_series(df, htf, lambda h: np.sign(h.close - ind.ema(h.close, 50)))
    f["ema200"] = ind.ema(df.close, 200)
    f["hh24"], f["ll24"] = ind.prior_high(df.high, 24), ind.prior_low(df.low, 24)
    f["vwap_dev"] = (df.close - (df.close * df.volume).rolling(96).sum() / df.volume.rolling(96).sum()) / f.atr
    return f


def run(df, f, signal, sl, tp, mb, costs, entry="market", off=0.0, period=IS, exit_long=None, exit_short=None):
    a, b = period
    m = (df.index >= pd.Timestamp(a, tz="UTC")) & ((df.index < pd.Timestamp(b, tz="UTC")) if b else True)
    sub = df[m]
    sig = np.where(m, signal, 0)[m]
    t = simulate(sub, sig, f.atr.values[m], sl, tp, mb, costs, entry, off,
                 None if exit_long is None else np.asarray(exit_long)[m],
                 None if exit_short is None else np.asarray(exit_short)[m])
    days = (sub.index[-1] - sub.index[0]).days
    return t, summary(t, days)


def fmt(s: dict) -> str:
    return (f"n={s['n']:5d} ({s['per_day']:.1f}/día)  WR={s['wr']:.1%}  PF={s['pf']:.2f}  "
            f"expR={s['exp_r']:+.3f}  brutoR={s['gross_exp_r']:+.3f}")
