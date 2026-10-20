"""Ensamble FIJO de tendencia (sin optimizar): 8 reglas diarias -> fracción larga en [0,1]. Largo/flat, 1x, costos reales de turnover.
Comparación contra buy&hold en descubrimiento (2014-22) y holdout virgen (2023-26), con alfa/beta anualizados."""
import numpy as np, pandas as pd
from pathlib import Path
from scipy import stats
ROOT = Path(__file__).resolve().parents[2]
d = pd.read_csv(ROOT/"data/BTCUSD_bitstamp_1d_2012.csv.gz", index_col=0, parse_dates=True); d = d[d.index >= "2014-01-01"]
c = d.close; r = c.pct_change().fillna(0)
rules = [(c > c.rolling(n).mean()) for n in (20,50,100,200)] + [(c/c.shift(n)-1 > 0) for n in (14,30,60,90)]
frac = sum(x.astype(float) for x in rules)/len(rules)
COST = 0.0007 * 2                                          # ~0.14% ida y vuelta por unidad de rotación (taker+slip aprox. por lado 0.07%)
def strat(frac, cost_side=0.0007, lev=1.0, short_when_zero=False):
    w = frac.shift(1).fillna(0)*lev                          # decisión al cierre t-1, retorno de t
    if short_when_zero: w = (2*frac.shift(1).fillna(0)-1)*lev
    return w*r - w.diff().abs().fillna(0)*cost_side, w
def stats_(x, bh, label):
    ann = 365
    eq = (1+x).cumprod(); dd = (eq/eq.cummax()-1).min(); yrs = len(x)/ann
    sh = x.mean()/x.std()*np.sqrt(ann); cagr = eq.iloc[-1]**(1/yrs)-1
    b, a, rv, pv, se = stats.linregress(bh.values, x.values)[:5]
    n = len(x); t_alpha = a/(x.values-(a+b*bh.values)).std(ddof=2)*np.sqrt(n)
    return f"{label:26s} Sharpe={sh:5.2f} CAGR={cagr:+7.1%} maxDD={dd:6.1%} beta={b:4.2f} alfa={a*ann:+6.1%}/año (t={t_alpha:4.1f}) exposición={float((x!=0).mean()):.0%}"
for nm, mask in (("DESCUBRIMIENTO 2014-2022", d.index<"2023-01-01"), ("HOLDOUT VIRGEN 2023-2026-10", d.index>="2023-01-01"), ("  del cual 2025-01 → hoy", d.index>="2025-01-01")):
    bh = r[mask]; s, w = strat(frac); s = s[mask]
    print(f"\n== {nm}  ({mask.sum()} días)")
    print("  "+stats_(bh, bh, "buy & hold BTC"))
    print("  "+stats_(s, bh, "ensamble tendencia largo/flat"))
    s2,_ = strat(frac, short_when_zero=True); print("  "+stats_(s2[mask], bh, "ensamble largo/corto"))
    for lev in (2,3):
        s3,_ = strat(frac, lev=lev); print("  "+stats_(s3[mask], bh, f"largo/flat x{lev}"))
# robustez: sensibilidad al costo y a quitar cada regla
print("\nRobustez (holdout 2023+, largo/flat 1x): Sharpe quitando cada regla / con costos x3")
mask = d.index>="2023-01-01"
for i in range(len(rules)):
    f2 = sum(x.astype(float) for j,x in enumerate(rules) if j!=i)/(len(rules)-1); s,_ = strat(f2); x=s[mask]
    print(f"  sin regla {i}: Sharpe {x.mean()/x.std()*np.sqrt(365):.2f}", end=" |")
s,_ = strat(frac, cost_side=0.0021); x=s[mask]; print(f"\n  costos x3: Sharpe {x.mean()/x.std()*np.sqrt(365):.2f}")
