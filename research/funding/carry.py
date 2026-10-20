"""Cash-and-carry (largo spot + corto perpetuo, delta-neutral) con funding REAL (Binance, 2020-2023; datos de
github.com/supervik/historical-funding-rates-fetcher). Se ignora el riesgo de base spot/perp (se estima aparte) y se modelan costos,
capital inmovilizado y riesgo de liquidación del perpetuo con los máximos horarios de Bitstamp."""
import numpy as np, pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; RAW = Path(__file__).parent/"raw"
SPOT_FEE, PERP_FEE, SLIP = 0.0010, 0.0005, 0.0002          # taker por lado; spot 0.10%, perp 0.05%, slippage 0.02%
ROUND_TRIP = 2*(SPOT_FEE + PERP_FEE + 2*SLIP)                # abrir + cerrar ambas patas
def load(sym):
    f = next((RAW/f"{sym}-USDT").glob(f"{sym}-USDT_binance_*.csv"))
    d = pd.read_csv(f, parse_dates=["Date"]); d["Date"] = d.Date.dt.tz_localize("UTC")
    return d.set_index("Date")["Funding Rate"].sort_index()
def stats(fr, name):
    print(f"\n=== {name}: funding Binance perpetuo, {len(fr)} liquidaciones de 8h, {fr.index[0].date()} → {fr.index[-1].date()}")
    print("año  | media 8h | anualizado | % positivas | peor mes | mejor día (3 liq.)")
    for y, g in fr.groupby(fr.index.year):
        daily = g.resample("1D").sum(); m = g.resample("30D").sum()
        print(f"{y} | {g.mean()*1e4:6.2f}bp | {g.mean()*3*365:9.1%} | {(g>0).mean():10.0%} | {m.min():+8.2%} | {daily.max():+7.3%}")
for sym in ("BTC", "ETH"):
    fr = load(sym); stats(fr, sym)
    daily = fr.resample("1D").sum()
    print(f"  mejor día histórico {daily.max():+.3%} | mejor ventana de 30 días {fr.resample('30D').sum().max():+.1%} | días con ≥0.7%: {(daily>=0.007).sum()} de {len(daily)}")
    # Estrategia 1: carry permanente. Capital = nocional spot + margen del perp (nocional/L)
    for L in (1, 2, 3):
        cap = 1 + 1/L
        for lab, per in (("2020-21", fr[:"2021-12-31"]), ("2022-23", fr["2022-01-01":])):
            yrs = (per.index[-1]-per.index[0]).days/365
            gross = per.sum(); net = gross - ROUND_TRIP
            eq = (per.cumsum() - np.r_[ROUND_TRIP, np.zeros(len(per)-1)].cumsum())/cap
            print(f"  carry permanente, margen perp x{L} ({lab}): neto {net/cap/yrs:+6.1%}/año sobre el capital → {(net/cap/yrs)/365*100:+.3f}%/día | peor caída del P&L {((per.cumsum()+1).div((per.cumsum()+1).cummax())-1).min():.1%}")
    # Estrategia 2: carry condicional — solo si el funding medio de los últimos 3 días (9 liq.) > umbral; cuesta ROUND_TRIP en cada cambio
    for thr in (0.0, 0.0001, 0.0002):
        sig = (fr.rolling(9).mean().shift(1) > thr)
        ret = fr*sig; flips = sig.astype(int).diff().abs().fillna(0).sum()/2
        for lab, a, b in (("2020-21", None, "2021-12-31"), ("2022-23", "2022-01-01", None)):
            r = ret.loc[a:b]; f = flips if False else sig.loc[a:b].astype(int).diff().abs().fillna(0).sum()/2
            yrs = (r.index[-1]-r.index[0]).days/365; net = r.sum() - f*ROUND_TRIP
            print(f"  carry condicional (3d>{thr*1e4:.0f}bp), x2 ({lab}): neto {net/1.5/yrs:+6.1%}/año → {net/1.5/yrs/365*100:+.3f}%/día | cambios {f:.0f}, tiempo en posición {sig.loc[a:b].mean():.0%}")
# riesgo de liquidación del perp corto: máximo avance del precio contra el corto en 1,3,7 días (spot Bitstamp 1h)
h = pd.read_csv(ROOT/"data/BTCUSD_bitstamp_1h.csv.gz", index_col=0, parse_dates=True)
h = h[(h.index >= "2020-01-01") & (h.index < "2024-01-01")]
print("\nRiesgo del perp corto (sube el precio contra el corto): peor avance máximo intra-ventana, BTC 2020-2023")
for days in (1, 3, 7):
    w = days*24; up = (h.high.rolling(w).max().shift(-w+1)/h.close - 1).max(); print(f"  {days:2d} días: +{up:.0%}  → liquidación con margen x{1/up:.1f} si no se repone margen")
