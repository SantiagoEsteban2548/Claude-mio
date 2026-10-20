"""Barrido de estrategias de tendencia apalancadas sobre BTC real. Objetivo: ¿alguna logra >=0.7% diario OOS?
Selección de parámetros SOLO en IS (2023-2024); se reporta OOS (2025-01 -> fin). Costos: taker 0.05% + slip 0.02% por
lado sobre el cambio de posición; funding 0.01% cada 8h sobre el nocional largo (los cortos lo cobran);
liquidación si el movimiento adverso intrabarra * L >= 90%."""
import sys, itertools, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tradebot.data import load_csv
from tradebot import indicators as ind

ROOT = Path(__file__).resolve().parents[2]
FEE, SLIP, FUND8H = 0.0005, 0.0002, 0.0001
IS = ("2023-01-01", "2025-01-01"); OOS = ("2025-01-01", None)

def bars(tf):
    if tf == "4h":
        d = load_csv(ROOT/"data/BTCUSD_bitstamp_1h.csv.gz")
        return d.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    if tf == "1d":
        d = load_csv(ROOT/"data/BTCUSD_bitstamp_1h.csv.gz")
        return d.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    return load_csv(ROOT/f"data/BTCUSD_bitstamp_{tf}.csv.gz")

def signal(df, kind, a, b, shorts):
    c = df.close
    if kind == "ema":
        s = np.sign(ind.ema(c, a) - ind.ema(c, b))
    elif kind == "donch":
        hi = df.high.shift(1).rolling(a).max(); lo = df.low.shift(1).rolling(a).min()
        s = pd.Series(np.nan, index=df.index); s[c > hi] = 1; s[c < lo] = -1; s = s.ffill().fillna(0)
    else:  # tsmom
        s = np.sign(c / c.shift(a) - 1)
    s = s.fillna(0)
    return s if shorts else s.clip(lower=0)

def backtest(df, pos, lev, bar_hours, period):
    c, h, l = df.close.values, df.high.values, df.low.values
    ret = np.r_[0, c[1:]/c[:-1]-1]
    p = pos.shift(1).fillna(0).values               # señal al cierre t-1 -> posición durante la barra t
    prev = np.r_[0, p[:-1]]
    turnover = np.abs(p - prev) * lev
    cost = turnover * (FEE + SLIP)
    funding = np.where(p > 0, 1, np.where(p < 0, -1, 0)) * lev * FUND8H * (bar_hours/8)
    adverse = np.where(p > 0, l/np.r_[c[0], c[:-1]]-1, np.where(p < 0, -(h/np.r_[c[0], c[:-1]]-1), 0.0))
    gross = lev * p * ret - cost - np.abs(funding)*0 - funding
    gross = np.where(lev*adverse <= -0.9, -1.0, gross)   # liquidación
    r = pd.Series(gross, index=df.index)
    a, b = period
    r = r[(r.index >= pd.Timestamp(a, tz="UTC")) & ((r.index < pd.Timestamp(b, tz="UTC")) if b else True)]
    eq = (1 + r).cumprod()
    days = max((r.index[-1]-r.index[0]).days, 1)
    final = float(eq.iloc[-1]); dd = float((eq/eq.cummax()-1).min())
    daily = final ** (1/days) - 1 if final > 0 else -1.0
    return dict(final=final, daily=daily, dd=dd, days=days, trades=int((turnover[r.index.get_indexer(r.index)] > 0).sum()) if False else int((np.abs(np.diff(p)) > 0).sum()))

if __name__ == "__main__":
    rows = []
    grid = []
    for tf, bh in (("1h",1), ("4h",4), ("1d",24)):
        mult = {"1h":1, "4h":1, "1d":1}[tf]
        for kind, params in (("ema", [(5,20),(10,30),(12,26),(20,50),(20,100),(50,200)]),
                             ("donch", [(10,0),(20,0),(40,0),(55,0),(100,0)]),
                             ("tsmom", [(5,0),(10,0),(20,0),(40,0),(90,0)])):
            for (a,b) in params:
                for shorts in (False, True):
                    grid.append((tf,bh,kind,a,b,shorts))
    cache = {}
    for tf,bh,kind,a,b,shorts in grid:
        df = cache.setdefault(tf, bars(tf))
        pos = signal(df, kind, a, b, shorts)
        for lev in (1,2,3,5,10):
            i = backtest(df, pos, lev, bh, IS); o = backtest(df, pos, lev, bh, OOS)
            rows.append(dict(tf=tf, kind=kind, a=a, b=b, shorts=shorts, lev=lev,
                             is_daily=i["daily"], is_dd=i["dd"], oos_daily=o["daily"], oos_dd=o["dd"], oos_final=o["final"], oos_trades=o["trades"]))
    out = pd.DataFrame(rows)
    out.to_csv(Path(__file__).parent/"sweep_results.csv", index=False)
    print(len(out), "combinaciones")
