"""Patrones sobre 14 años de BTC/USD (Bitstamp). Descubrimiento 2014-2022, holdout virgen 2023-2026. Barras diarias (1 día de horizonte => sin solape)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
ROOT = Path(__file__).resolve().parents[2]
d = pd.read_csv(ROOT/"data/BTCUSD_bitstamp_1d_2012.csv.gz", index_col=0, parse_dates=True)
d = d[d.index >= "2014-01-01"]
c = d.close; r = c.pct_change()
nxt = r.shift(-1)                                    # retorno del día siguiente (la señal se conoce al cierre de hoy)
DISC = (d.index < "2023-01-01"); HOLD = ~DISC
def tt(x):
    x = x.dropna(); return (x.mean()/(x.std(ddof=1)/np.sqrt(len(x))) if len(x)>30 and x.std()>0 else 0.0), x.mean(), len(x)
base = {"disc": nxt[DISC].mean(), "hold": nxt[HOLD].mean()}
print(f"días: descubrimiento {DISC.sum()} | holdout {HOLD.sum()}   deriva diaria: disc {base['disc']*1e4:+.1f}bp  hold {base['hold']*1e4:+.1f}bp")
rows = []
def test(name, mask):
    for lab, sel, b in (("disc", DISC, base["disc"]), ("hold", HOLD, base["hold"])):
        t, m, n = tt((nxt - b)[mask & sel])                     # retorno en exceso de la deriva del período
        rows.append((name, lab, n, m*1e4, t))
# --- calendario
for k in range(7): test(f"día de semana {k} (0=lun)", pd.Series(d.index.dayofweek==k, index=d.index))
for k in range(1,13): test(f"mes {k:02d}", pd.Series(d.index.month==k, index=d.index))
dom = d.index.day; dim = d.index.days_in_month
test("fin de mes (últimos 3 días)", pd.Series(dom > dim-3, index=d.index)); test("inicio de mes (primeros 3)", pd.Series(dom<=3, index=d.index))
# --- momentum / reversión: signo del retorno pasado (serie diaria)
for lb in (1,2,3,5,7,10,14,21,30,60,90,120,180,365):
    past = c/c.shift(lb)-1
    test(f"past{lb}d > 0", past>0); test(f"past{lb}d < 0", past<0)
# --- reversión tras días extremos
sig = r.rolling(60).std()
for k in (1.5,2,3):
    test(f"día > +{k}σ", r > k*sig); test(f"día < -{k}σ", r < -k*sig)
# --- tendencia: precio vs SMA
for n in (20,50,100,200):
    sma = c.rolling(n).mean(); test(f"close > SMA{n}", c>sma); test(f"close < SMA{n}", c<sma)
# --- volatilidad: alta/baja vs mediana móvil
vol = r.rolling(20).std(); vm = vol.rolling(250).median()
test("vol20 > mediana 250d", vol>vm); test("vol20 < mediana 250d", vol<vm)
res = pd.DataFrame(rows, columns=["name","per","n","excess_bp","t"]).pivot(index="name", columns="per", values=["n","excess_bp","t"])
res.columns = [f"{a}_{b}" for a,b in res.columns]
res = res.reset_index()
res["p_disc"] = 2*(1-stats.norm.cdf(res.t_disc.abs()))
p = res.p_disc.values; o = np.argsort(p); rk = p[o]*len(p)/(np.arange(len(p))+1); ok = np.zeros(len(p),bool); kk = np.where(rk<=0.10)[0]
if len(kk): ok[o[:kk.max()+1]] = True
res["fdr"] = ok
res["surv"] = res.fdr & (np.sign(res.excess_bp_disc)==np.sign(res.excess_bp_hold)) & (res.t_hold.abs()>=1.65)
res.to_csv(Path(__file__).parent/"longhist_results.csv", index=False)
print(f"hipótesis: {len(res)} | |t_disc|>=2: {(res.t_disc.abs()>=2).sum()} (azar ~{0.0455*len(res):.0f}) | pasan FDR: {res.fdr.sum()} | sobreviven en holdout: {res.surv.sum()}")
pd.set_option("display.width",200)
x = res.sort_values("t_disc", key=abs, ascending=False).head(14)
print(x[["name","n_disc","excess_bp_disc","t_disc","n_hold","excess_bp_hold","t_hold","fdr","surv"]].round(2).to_string(index=False))
