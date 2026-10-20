"""¿Es operable el momentum diario del Merval? Señal = signo del retorno de ayer. Tres formas de ejecutar el día siguiente:
  A) close→close (optimista: asume operar al cierre de hoy cuando ya se conoce la señal; en la práctica el cierre se conoce al final)
  B) open→close del día siguiente (operable: se decide con el cierre de hoy y se entra a la apertura de mañana)
  C) open→open (operable, retorno completo de las 24 h)
Costo por lado: 5, 15 y 30 bp. Descubrimiento 1996-2008 (open real disponible desde 1996), holdout 2009-2016."""
import numpy as np, pandas as pd
from pathlib import Path
AR = Path("/tmp/claude-0/-home-user-Claude-mio/48e10cf0-e9cd-56ee-ac37-61f29356ace5/scratchpad/src/ar")
d = pd.read_csv(AR / "Historic_Merval_Scrap/Stooq_Merv_Scrap.csv", parse_dates=["Date"]).set_index("Date").sort_index()
d = d[~d.index.duplicated()]; d = d[d.index >= "1996-01-01"]
print("filas con open==close:", f"{(d.Open == d.Close).mean():.1%}")
ret = d.Close.pct_change()
sig = np.sign(ret).shift(0)                      # señal conocida al cierre de t
r_cc = d.Close.shift(-1) / d.Close - 1           # cierre t -> cierre t+1
r_oc = d.Close.shift(-1) / d.Open.shift(-1) - 1  # apertura t+1 -> cierre t+1
r_oo = d.Open.shift(-2) / d.Open.shift(-1) - 1   # apertura t+1 -> apertura t+2
def run(label, r, side_filter, cost):
    pos = sig.where(sig.isin([1, -1]), 0)
    if side_filter == "long": pos = pos.clip(lower=0)
    pnl = pos * r - pos.diff().abs().fillna(0) * cost  # un solo ajuste de posición por día
    return pnl
HOLD = pd.Timestamp("2009-01-01")
for mode, r in (("A close→close (optimista)", r_cc), ("B open→close (operable)", r_oc), ("C open→open (operable)", r_oo)):
    print(f"\n{mode}")
    for side in ("long/short", "long/flat"):
        for cost in (0.0005, 0.0015, 0.003):
            p = run(mode, r, "long" if side == "long/flat" else "ls", cost).dropna()
            cells = []
            for lab, sel in (("desc", p.index < HOLD), ("hold", p.index >= HOLD)):
                x = p[sel]; eq = (1 + x).cumprod()
                cells.append(f"{lab}: Sharpe {x.mean()/x.std()*np.sqrt(252):5.2f} CAGR {eq.iloc[-1]**(252/len(x))-1:+6.1%} DD {(eq/eq.cummax()-1).min():5.0%}")
            print(f"  {side:10s} costo {cost*1e4:4.0f}bp/lado | " + " | ".join(cells))
