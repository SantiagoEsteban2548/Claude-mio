"""Mercados argentinos con los datos públicos alcanzables desde GitHub.

A) Merval 1992-2016 (isantolin/Historic_Merval_Scrap, Stooq): ensamble de tendencia (tradebot.trend_ensemble) y escáner de patrones.
   Descubrimiento 1992-2008, holdout 2009-2016. Retornos nominales en pesos (hay inflación alta: el buy&hold nominal está inflado).
B) Brechas cambiarias 2018-2026 (jonathancalb/dolar-argentina-historico, CC BY 4.0): estadísticos y reversión a la media de CCL/MEP y cripto/MEP.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tradebot import trend_ensemble as te  # noqa: E402

AR = Path("/tmp/claude-0/-home-user-Claude-mio/48e10cf0-e9cd-56ee-ac37-61f29356ace5/scratchpad/src/ar")
HOLD = pd.Timestamp("2009-01-01")

# ---------------------------------------------------------------- A) Merval
mv = pd.read_csv(AR / "Historic_Merval_Scrap/Stooq_Merv_Scrap.csv", parse_dates=["Date"]).set_index("Date").sort_index()
mv = mv[~mv.index.duplicated()]
c = mv.Close[mv.index >= "1992-01-01"]
print(f"A) Merval: {len(c)} días, {c.index[0].date()} → {c.index[-1].date()}")
gaps = c.index.to_series().diff().dt.days
print(f"   huecos > 7 días: {(gaps > 7).sum()} (máximo {int(gaps.max())} días)")
ret = c.pct_change().fillna(0)


def metrics(x, ppy=252):
    eq = (1 + x).cumprod()
    yrs = len(x) / ppy
    return dict(sharpe=x.mean() / x.std() * np.sqrt(ppy) if x.std() > 0 else 0, cagr=eq.iloc[-1] ** (1 / yrs) - 1,
                dd=(eq / eq.cummax() - 1).min())


out = te.backtest(c, cost_per_side=0.003)
for lab, sel in (("descubrimiento 1992-2008", c.index < HOLD), ("holdout 2009-2016", c.index >= HOLD)):
    b, e = metrics(out.bh[sel]), metrics(out.ret[sel])
    print(f"   {lab}: buy&hold Sharpe {b['sharpe']:.2f} CAGR {b['cagr']:+.1%} maxDD {b['dd']:.0%} | "
          f"ensamble Sharpe {e['sharpe']:.2f} CAGR {e['cagr']:+.1%} maxDD {e['dd']:.0%} | exposición media {out.exposure[sel].mean():.0%}")

# escáner de patrones (retorno del día siguiente en exceso de la deriva del período)
nxt = ret.shift(-1)
disc = c.index < HOLD
base = {"d": nxt[disc].mean(), "h": nxt[~disc].mean()}
rows = []


def test(name, mask):
    for lab, sel in (("d", disc), ("h", ~disc)):
        x = (nxt - base[lab])[mask & sel].dropna()
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 30 and x.std() > 0 else 0
        rows.append((name, lab, len(x), x.mean() * 1e4, t))


idx = c.index
for k in range(5):
    test(f"dow {k}", pd.Series(idx.dayofweek == k, index=idx))
for k in range(1, 13):
    test(f"mes {k:02d}", pd.Series(idx.month == k, index=idx))
for lb in (1, 2, 3, 5, 10, 20, 60, 120, 250):
    past = c / c.shift(lb) - 1
    test(f"past{lb}d>0", past > 0)
    test(f"past{lb}d<0", past < 0)
sg = ret.rolling(60).std()
for k in (1.5, 2, 3):
    test(f"día>+{k}σ", ret > k * sg)
    test(f"día<-{k}σ", ret < -k * sg)
for n in (20, 50, 100, 200):
    sma = c.rolling(n).mean()
    test(f"close>SMA{n}", c > sma)
    test(f"close<SMA{n}", c < sma)
res = pd.DataFrame(rows, columns=["name", "per", "n", "bp", "t"]).pivot(index="name", columns="per", values=["bp", "t"])
res.columns = [f"{a}_{b}" for a, b in res.columns]
res["p_d"] = 2 * (1 - stats.norm.cdf(res.t_d.abs()))
p = res.p_d.values
o = np.argsort(p)
rk = p[o] * len(p) / (np.arange(len(p)) + 1)
ok = np.zeros(len(p), bool)
kk = np.where(rk <= 0.10)[0]
if len(kk):
    ok[o[:kk.max() + 1]] = True
res["fdr"] = ok
res["surv"] = res.fdr & (np.sign(res.bp_d) == np.sign(res.bp_h)) & (res.t_h.abs() >= 1.65)
print(f"   escáner: {len(res)} hipótesis | |t_desc|>=2: {(res.t_d.abs() >= 2).sum()} (azar ~{0.0455 * len(res):.0f}) | pasan FDR: {res.fdr.sum()} | sobreviven al holdout: {res.surv.sum()}")
print(res.reindex(res.t_d.abs().sort_values(ascending=False).index).head(8).round(2).to_string())

# ---------------------------------------------------------------- B) FX
fx = pd.read_csv(AR / "dolar-argentina-historico/historico.csv", parse_dates=["fecha"]).set_index("fecha")
print("\nB) Brechas cambiarias")
for name, ser, start in (("CCL/MEP − 1", fx.ccl / fx.mep - 1, "2019-01-01"), ("cripto/MEP − 1", fx.cripto / fx.mep - 1, "2023-06-01")):
    s = ser[start:].dropna()
    x, y = s.shift(1).dropna(), s.iloc[1:]
    ar1 = np.polyfit(x.values[:len(y)], y.values[:len(x)], 1)[0]
    hl = np.log(0.5) / np.log(ar1) if 0 < ar1 < 1 else float("nan")
    print(f"   {name}: n={len(s)} media {s.mean():+.2%} mediana {s.median():+.2%} p10/p90 {s.quantile(.1):+.2%}/{s.quantile(.9):+.2%} | AR(1) diario {ar1:.3f} → vida media ≈ {hl:.0f} días")
    fwd = s.shift(-10) - s
    z = (s - s.rolling(60).mean()) / s.rolling(60).std()
    for thr in (1, 2):
        sel = z > thr
        print(f"     tras z60>+{thr}: cambio medio de la brecha a 10 días {fwd[sel].mean() * 100:+.2f} pp (n={int(sel.sum())}) vs incondicional {fwd.mean() * 100:+.2f} pp")
y2 = fx["2024":]
print(f"   Desde 2024: cripto/MEP>3% en {((y2.cripto / y2.mep - 1) > 0.03).mean():.0%} de los días; CCL/MEP>3% en {((y2.ccl / y2.mep - 1) > 0.03).mean():.0%}")
