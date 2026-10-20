"""Escáner de patrones en BTC/USD real (Bitstamp). Cada hipótesis = (condición conocida al cierre de t) -> retorno de la(s) barra(s) siguiente(s).
Se mide en IS (2023-24) y OOS (2025-26) por separado; un patrón "sobrevive" si: |t_IS|>=2.5, mismo signo y |t_OOS|>=1.65 en OOS,
FDR(BH,q=.10) sobre TODAS las hipótesis testeadas en IS, y el edge medio supera el costo (ver COST)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tradebot.data import load_csv

ROOT = Path(__file__).resolve().parents[2]
IS_END = pd.Timestamp("2025-01-01", tz="UTC")
COST = {"taker": 0.0014, "maker": 0.0004}   # ida y vuelta (fracción del precio)

def tstat(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    n = len(x)
    if n < 30 or x.std() == 0: return 0.0, 0.0, n
    return x.mean() / (x.std(ddof=1) / np.sqrt(n)), x.mean(), n

def evaluate(name, mask, fwd, side, rows):
    """mask: bool serie (condición al cierre t). fwd: retorno futuro (t -> t+h). side: +1 largo, -1 corto, 0 = ambos por separado."""
    for sd in ((1, -1) if side == 0 else (side,)):
        r = (sd * fwd)[mask].dropna()
        ri, ro = r[r.index < IS_END], r[r.index >= IS_END]
        ti, mi, ni = tstat(ri); to, mo, no = tstat(ro)
        rows.append(dict(name=name, side=sd, n_is=ni, mean_is=mi, t_is=ti, n_oos=no, mean_oos=mo, t_oos=to))

def build():
    h1 = load_csv(ROOT / "data/BTCUSD_bitstamp_1h.csv.gz")
    return h1

def bh_fdr(p, q=0.10):
    p = np.asarray(p); n = len(p); order = np.argsort(p); ranked = p[order] * n / (np.arange(n) + 1)
    ok = np.zeros(n, bool); keep = np.where(ranked <= q)[0]
    if len(keep): ok[order[: keep.max() + 1]] = True
    return ok

if __name__ == "__main__":
    h = build()
    c, o = h.close, h.open
    ret1 = c.pct_change()
    rows = []
    # --- 1. calendario: hora UTC, día de semana, hora×día (retorno de la barra que sigue; la condición es solo el calendario)
    nxt = lambda k: c.shift(-k) / c - 1                      # de cierre t a cierre t+k
    hour = pd.Series(h.index.hour, index=h.index); dow = pd.Series(h.index.dayofweek, index=h.index)
    for hr in range(24):
        evaluate(f"hora {hr:02d}UTC -> barra siguiente", hour == hr, nxt(1), 0, rows)
    for d in range(7):
        evaluate(f"día {d} (0=lun) cierre 00h -> 24h", (dow == d) & (hour == 0), nxt(24), 0, rows)
    for d in range(7):
        for hr in (0, 8, 13, 16, 20):
            evaluate(f"dow{d} hora{hr:02d} -> 4h", (dow == d) & (hour == hr), nxt(4), 0, rows)
    # --- 2. momentum / reversión de retornos pasados (cuantiles terciles/extremos), varios horizontes
    for lb in (1, 3, 6, 12, 24, 72, 168):
        past = c / c.shift(lb) - 1
        q = past.rolling(24 * 90, min_periods=500).rank(pct=True)           # percentil móvil, sin look-ahead
        for h_fwd in (1, 4, 24):
            evaluate(f"past{lb}h top5% -> {h_fwd}h", q >= 0.95, nxt(h_fwd), 0, rows)
            evaluate(f"past{lb}h bottom5% -> {h_fwd}h", q <= 0.05, nxt(h_fwd), 0, rows)
    # --- 3. volatilidad: compresión -> expansión (dirección tras ruptura), vol alta -> reversión
    rng = (h.high - h.low) / c
    comp = rng.rolling(12).mean() / rng.rolling(24 * 30).mean()
    hi24, lo24 = h.high.rolling(24).max().shift(1), h.low.rolling(24).min().shift(1)
    for thr in (0.5, 0.7):
        squeeze = comp < thr
        evaluate(f"squeeze(<{thr}) & ruptura alcista 24h -> 12h", squeeze & (c > hi24), nxt(12), 0, rows)
        evaluate(f"squeeze(<{thr}) & ruptura bajista 24h -> 12h", squeeze & (c < lo24), nxt(12), 0, rows)
    # --- 4. volumen: pico de volumen + dirección de la barra
    vr = h.volume / h.volume.rolling(24 * 14).mean()
    for thr in (3, 5):
        evaluate(f"vol>{thr}x y barra alcista -> 4h", (vr > thr) & (c > o), nxt(4), 0, rows)
        evaluate(f"vol>{thr}x y barra bajista -> 4h", (vr > thr) & (c < o), nxt(4), 0, rows)
    # --- 5. barras extremas: |ret| > k sigma (sigma móvil)
    sig = ret1.rolling(24 * 30).std()
    for k in (2.5, 3.5):
        evaluate(f"barra > +{k}σ -> 1h", ret1 > k * sig, nxt(1), 0, rows)
        evaluate(f"barra < -{k}σ -> 1h", ret1 < -k * sig, nxt(1), 0, rows)
        evaluate(f"barra > +{k}σ -> 6h", ret1 > k * sig, nxt(6), 0, rows)
        evaluate(f"barra < -{k}σ -> 6h", ret1 < -k * sig, nxt(6), 0, rows)
    # --- 6. mechas: cierre cerca del extremo / sombra larga
    body_pos = (c - h.low) / (h.high - h.low).replace(0, np.nan)
    evaluate("cierra en el 10% superior de su rango -> 1h", body_pos > 0.9, nxt(1), 0, rows)
    evaluate("cierra en el 10% inferior de su rango -> 1h", body_pos < 0.1, nxt(1), 0, rows)
    evaluate("cierra en el 10% superior y vol>2x -> 4h", (body_pos > 0.9) & (vr > 2), nxt(4), 0, rows)
    evaluate("cierra en el 10% inferior y vol>2x -> 4h", (body_pos < 0.1) & (vr > 2), nxt(4), 0, rows)
    # --- 7. rachas
    up = (c > o).astype(int); streak = up.groupby((up != up.shift()).cumsum()).cumcount() + 1
    for k in (4, 6, 8):
        evaluate(f"{k}+ velas alcistas seguidas -> 1h", (up == 1) & (streak >= k), nxt(1), 0, rows)
        evaluate(f"{k}+ velas bajistas seguidas -> 1h", (up == 0) & (streak >= k), nxt(1), 0, rows)
    # --- 8. distancia a la media (z-score vs EMA 168h)
    z = (c - c.ewm(span=168).mean()) / c.rolling(168).std()
    for thr in (2, 3):
        evaluate(f"z168 > {thr} -> 24h", z > thr, nxt(24), 0, rows)
        evaluate(f"z168 < -{thr} -> 24h", z < -thr, nxt(24), 0, rows)
    res = pd.DataFrame(rows)
    res["p_is"] = 2 * (1 - stats.norm.cdf(np.abs(res.t_is)))
    res["fdr_ok"] = bh_fdr(res.p_is.values, 0.10)
    res["edge_net_taker"] = res.mean_oos - COST["taker"]
    res["edge_net_maker"] = res.mean_oos - COST["maker"]
    res["survives"] = (res.fdr_ok & (np.sign(res.mean_is) == np.sign(res.mean_oos)) & (res.t_oos.abs() >= 1.65))
    res.to_csv(Path(__file__).parent / "scan_results.csv", index=False)
    print(f"hipótesis (dirección incluida): {len(res)}")
    print(f"|t_IS|>=2: {int((res.t_is.abs()>=2).sum())}  | pasan FDR en IS: {int(res.fdr_ok.sum())}  | sobreviven a OOS (mismo signo, |t|>=1.65): {int(res.survives.sum())}")
    pd.set_option("display.width", 230); pd.set_option("display.max_colwidth", 55)
    show = res[res.fdr_ok | (res.t_is.abs() >= 3)].sort_values("t_is", key=abs, ascending=False)
    show = show.assign(mean_is=(show.mean_is*1e4).round(1), mean_oos=(show.mean_oos*1e4).round(1), t_is=show.t_is.round(2), t_oos=show.t_oos.round(2))
    print("\nTop por |t_IS| (medias en puntos básicos por operación):")
    print(show[["name","side","n_is","mean_is","t_is","n_oos","mean_oos","t_oos","survives"]].head(25).to_string(index=False))
