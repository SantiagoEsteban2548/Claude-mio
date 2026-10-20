"""Idea 'caza de mechas' (Gemini): órdenes límite lejanas (stink bids/asks) a k x ATR del precio, salida por reversión a la media o por tiempo.
Se prueba en BTC/USD (Bitstamp) en velas de 1 minuto, 2018-2026, como PISO de la idea: BTC es el mercado más líquido, donde las mechas son más chicas.
No hay datos de altcoins de baja capitalización, de open interest ni de libro de órdenes en este entorno.

Reglas (simulador fastsim, mismas convenciones del resto del repo):
  - en cada vela cerrada se deja una orden límite de COMPRA a close - k*ATR y otra de VENTA a close + k*ATR (se simulan por separado, long y short);
  - se llena si la vela siguiente la toca (a la peor de: el límite o la apertura si gapea); entrada maker;
  - salida: take-profit maker a tp*ATR, stop taker a sl*ATR, o por tiempo a max_bars velas (taker);
  - una posición a la vez por lado. Costos: maker 0.02%, taker 0.05% + slippage 0.02% por lado.
Descubrimiento 2018-2022, holdout 2023-2026.
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import talib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tradebot.fastsim import Costs, simulate, summary  # noqa: E402

SRC = Path("/tmp/claude-0/-home-user-Claude-mio/48e10cf0-e9cd-56ee-ac37-61f29356ace5/scratchpad/src/bs")
COSTS = Costs(taker=0.0005, maker=0.0002, slippage=0.0002)
SPLIT = pd.Timestamp("2023-01-01", tz="UTC")


def load():
    files = [*sorted((SRC / "data/historical").glob("*.csv.gz")), *sorted((SRC / "data/updates").glob("*.csv"))]
    cutoff = pd.Timestamp("2018-01-01", tz="UTC").timestamp()
    parts = [p[p.timestamp >= cutoff] for p in (pd.read_csv(f) for f in files)]
    df = pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp")
    df.index = pd.to_datetime(df.pop("timestamp"), unit="s", utc=True)
    return df[df.volume > 0] if False else df


DF = load()
ATR = talib.ATR(DF.high.values, DF.low.values, DF.close.values, timeperiod=60)


def job(cfg):
    k, tp, sl, mb, side = cfg
    sig = np.full(len(DF), side, dtype=int)
    t = simulate(DF, sig, ATR, sl, tp, mb, COSTS, entry="limit", limit_offset_atr=k)
    out = {"k": k, "tp": tp, "sl": sl, "mb": mb, "side": side}
    for lab, part in (("disc", t[t.time < SPLIT]), ("hold", t[t.time >= SPLIT])):
        days = ((DF.index < SPLIT).sum() if lab == "disc" else (DF.index >= SPLIT).sum()) / 1440
        s = summary(part, days)
        out.update({f"{lab}_n": s["n"], f"{lab}_per_day": s["per_day"], f"{lab}_wr": s["wr"], f"{lab}_pf": s["pf"],
                    f"{lab}_expR": s["exp_r"], f"{lab}_gross_expR": s["gross_exp_r"],
                    f"{lab}_net_bp": float(part.net.mean() * 1e4) if len(part) else 0.0})
    return out


if __name__ == "__main__":
    cfgs = [(k, tp, sl, 30, side) for k in (3.0, 4.0, 6.0) for (tp, sl) in ((k, 3.0), (k / 2, 3.0)) for side in (1, -1)]
    with ProcessPoolExecutor(4) as ex:
        res = pd.DataFrame(list(ex.map(job, cfgs)))
    res.to_csv(Path(__file__).parent / "stink_bids_results.csv", index=False)
    pd.set_option("display.width", 240)
    cols = ["k", "tp", "sl", "side", "disc_n", "disc_per_day", "disc_wr", "disc_pf", "disc_net_bp", "hold_n", "hold_per_day", "hold_wr",
            "hold_pf", "hold_net_bp"]
    print(res[cols].round(3).to_string(index=False))
