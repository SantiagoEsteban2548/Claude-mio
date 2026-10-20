"""Validación dura de los sobrevivientes del escáner: eventos sin solape, exceso sobre la deriva incondicional,
bootstrap por bloques y operaciones con costos. 24h de tenencia."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tradebot.data import load_csv
ROOT = Path(__file__).resolve().parents[2]
IS_END = pd.Timestamp("2025-01-01", tz="UTC")
TAKER, MAKER = 0.0014, 0.0004
rng = np.random.default_rng(0)

h = load_csv(ROOT / "data/BTCUSD_bitstamp_1h.csv.gz")
c = h.close
fwd24 = c.shift(-24) / c - 1

def declustered(mask, hold):
    """primer evento y luego saltar `hold` barras (sin solape)."""
    idx = np.flatnonzero(mask.fillna(False).values)
    keep, last = [], -10**9
    for i in idx:
        if i - last >= hold: keep.append(i); last = i
    return h.index[keep]

def block_boot_p(x, base, block=5, n=4000):
    """p-value (dos colas) de que media(x) - base == 0, bootstrap por bloques sobre la secuencia de eventos."""
    x = np.asarray(x) - base; m = len(x)
    if m < 15: return np.nan
    obs = x.mean(); xc = x - obs
    nb = int(np.ceil(m / block)); stat = np.empty(n)
    for k in range(n):
        s = rng.integers(0, m - block + 1, nb); stat[k] = np.concatenate([xc[i:i+block] for i in s])[:m].mean()
    return float((np.abs(stat) >= abs(obs)).mean())

past = lambda lb: c / c.shift(lb) - 1
pct = lambda s: s.rolling(24 * 90, min_periods=500).rank(pct=True)
z168 = (c - c.ewm(span=168).mean()) / c.rolling(168).std()
patterns = {
    "A  7d top5% -> LARGO 24h (continuación)":      pct(past(168)) >= 0.95,
    "B  z168>2 -> LARGO 24h (continuación)":        z168 > 2,
    "C  24h bottom5% -> LARGO 24h (rebote)":        pct(past(24)) <= 0.05,
    "D  72h bottom5% -> LARGO 24h (rebote)":        pct(past(72)) <= 0.05,
    "E  6h bottom5% -> LARGO 24h (rebote)":         pct(past(6)) <= 0.05,
}
base_is = fwd24[fwd24.index < IS_END].mean(); base_oos = fwd24[fwd24.index >= IS_END].mean()
print(f"deriva incondicional 24h: IS {base_is*1e4:+.1f}bp  OOS {base_oos*1e4:+.1f}bp  (BTC buy&hold OOS fue negativo)\n")
for name, m in patterns.items():
    ev = declustered(m, 24)
    r = fwd24.loc[ev].dropna()
    ri, ro = r[r.index < IS_END], r[r.index >= IS_END]
    out = []
    for lab, x, base in (("IS", ri, base_is), ("OOS", ro, base_oos)):
        exc = x.mean() - base
        p = block_boot_p(x.values, base)
        net_t = x.mean() - TAKER; net_m = x.mean() - MAKER
        wr = (x - TAKER > 0).mean()
        out.append(f"{lab}: n={len(x):3d} medio={x.mean()*1e4:+6.1f}bp exceso={exc*1e4:+6.1f}bp p={p:.3f} neto(taker)={net_t*1e4:+6.1f}bp WR={wr:.0%}")
    print(name); print("   " + "\n   ".join(out))
