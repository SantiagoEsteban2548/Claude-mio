"""Patrones intradía con historia larga. Retorno de UNA barra (sin solape) en exceso de la deriva del período.
Descubrimiento 2014-2022, holdout virgen 2023-2026. FDR (BH q=0.10) sobre todas las hipótesis."""
import numpy as np, pandas as pd
from pathlib import Path
from scipy import stats
LONG = Path("/tmp/claude-0/-home-user-Claude-mio/48e10cf0-e9cd-56ee-ac37-61f29356ace5/scratchpad/long")
rows = []
def tt(x):
    x = x.dropna(); return (x.mean()/(x.std(ddof=1)/np.sqrt(len(x))) if len(x) > 30 and x.std() > 0 else 0.0), x.mean(), len(x)
for tf in ("h1", "h4"):
    d = pd.read_csv(LONG/f"btc_{tf}.csv.gz", index_col=0, parse_dates=True)
    d = d[(d.index >= "2014-01-01") & (d.volume > 0)]
    r = d.close.pct_change()                              # retorno de la barra (apertura aprox. = cierre previo)
    disc = d.index < "2023-01-01"
    base = {"disc": r[disc].mean(), "hold": r[~disc].mean()}
    hour, dow = pd.Series(d.index.hour, index=d.index), pd.Series(d.index.dayofweek, index=d.index)
    def test(name, mask):
        for per, sel in (("disc", disc), ("hold", ~disc)):
            t, m, n = tt((r - base[per])[mask & sel]); rows.append((tf, name, per, n, m*1e4, t))
    for h in sorted(hour.unique()): test(f"hora {h:02d}", hour == h)
    for dd in range(7):
        for h in sorted(hour.unique()): test(f"dow{dd} hora{h:02d}", (dow == dd) & (hour == h))
    # barra siguiente condicionada a la barra previa (reversión/continuación intradía)
    prev = r.shift(1); sg = r.rolling(24*30 if tf == "h1" else 6*30).std().shift(1)
    for k in (1, 2, 3):
        test(f"tras barra > +{k}σ", prev > k*sg); test(f"tras barra < -{k}σ", prev < -k*sg)
    up_streak = (r > 0).astype(int); st = up_streak.groupby((up_streak != up_streak.shift()).cumsum()).cumcount() + 1
    for k in (3, 4, 5, 6):
        test(f"tras {k}+ barras alcistas seguidas", (r.shift(1) > 0) & (st.shift(1) >= k))
        test(f"tras {k}+ barras bajistas seguidas", (r.shift(1) <= 0) & (st.shift(1) >= k))
res = pd.DataFrame(rows, columns=["tf", "name", "per", "n", "excess_bp", "t"]).pivot_table(index=["tf", "name"], columns="per", values=["n", "excess_bp", "t"])
res.columns = [f"{a}_{b}" for a, b in res.columns]; res = res.reset_index().dropna()
res["p_disc"] = 2*(1-stats.norm.cdf(res.t_disc.abs()))
p = res.p_disc.values; o = np.argsort(p); rk = p[o]*len(p)/(np.arange(len(p))+1); ok = np.zeros(len(p), bool); kk = np.where(rk <= 0.10)[0]
if len(kk): ok[o[:kk.max()+1]] = True
res["fdr"] = ok
res["surv"] = res.fdr & (np.sign(res.excess_bp_disc) == np.sign(res.excess_bp_hold)) & (res.t_hold.abs() >= 1.96)
res.to_csv(Path(__file__).parent/"intraday_long_results.csv", index=False)
print(f"hipótesis: {len(res)} | |t_disc|>=2: {(res.t_disc.abs()>=2).sum()} (azar ~{0.0455*len(res):.0f}) | pasan FDR: {res.fdr.sum()} | sobreviven en holdout (|t|>=1.96): {res.surv.sum()}")
pd.set_option("display.width", 200)
x = res[res.fdr].sort_values("t_disc", key=abs, ascending=False).head(15)
print(x[["tf", "name", "n_disc", "excess_bp_disc", "t_disc", "n_hold", "excess_bp_hold", "t_hold", "surv"]].round(2).to_string(index=False))
