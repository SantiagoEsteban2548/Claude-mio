"""Lead-lag spot -> contrato 'BTC Up/Down 5m' de Polymarket (1 día: 2026-06-15, Marketlens, CC BY 4.0).

En cada snapshot del libro dentro de la ventana de un contrato:
  r      = retorno del spot (Binance) desde la apertura de la ventana hasta el instante del snapshot
  p_fair = Phi(r / (sigma * sqrt(tau)))          sigma = vol por segundo (de TODO el día; leve look-ahead, ver README), tau = segundos restantes
  compra UP   al ask_up        si p_fair - ask_up        > umbral
  compra DOWN a (1 - bid_up)   si (1 - p_fair) - (1 - bid_up) = bid_up - p_fair > umbral
Resultado por acción = 1{gana el token comprado} - precio pagado (sin comisiones de la plataforma; ver README).
Ejecución: 'opt' usa el ask/bid del MISMO snapshot (optimista); 'next' usa el del snapshot SIGUIENTE (conservador, ~20 s de latencia).
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

D = ("/tmp/claude-0/-home-user-Claude-mio/48e10cf0-e9cd-56ee-ac37-61f29356ace5/scratchpad/src/"
     "marketlenstrade_polymarket-historical-data/bitcoin-5m-15m-hourly-2026-06-15/")
m = pd.read_csv(D + "markets.csv", parse_dates=["open_time", "close_time"])
s = pd.read_csv(D + "snapshots.csv")
s["ts"] = pd.to_datetime(s.t_ms, unit="ms", utc=True)
ref = pd.read_parquet(D + "reference-BTC.parquet")
ref["ts"] = pd.to_datetime(ref.timestamp, unit="ms", utc=True)
ref["price"] = ref.price.astype(float)
ref = ref.drop_duplicates("ts").set_index("ts").price.sort_index()
SIG = np.log(ref.resample("1s").last().ffill()).diff().dropna().std()


def px_at(t):
    i = ref.index.searchsorted(t, side="right") - 1
    return ref.iloc[i] if i >= 0 else np.nan


def build(series, window_s):
    rows = []
    for _, mk in m[m.series == series].iterrows():
        x = s[s.market_id == mk.market_id].sort_values("ts").reset_index(drop=True)
        p0 = px_at(mk.open_time)
        win_up = mk.winning_outcome == "Up"
        for i in range(len(x) - 1):
            row, nxt = x.iloc[i], x.iloc[i + 1]
            tau = (mk.close_time - row.ts).total_seconds()
            if not (0 < tau < window_s - 5) or row.ts < mk.open_time:
                continue
            r = px_at(row.ts) / p0 - 1
            p_fair = norm.cdf(r / (SIG * np.sqrt(tau)))
            rows.append(dict(market=mk.market_id, tau=tau, r_bp=r * 1e4, p_fair=p_fair, win_up=win_up,
                             ask=row.best_ask, bid=row.best_bid, ask_n=nxt.best_ask, bid_n=nxt.best_bid,
                             mid=row.midpoint, spread=row.spread, depth_b=row.bid_depth, depth_a=row.ask_depth))
    return pd.DataFrame(rows)


def trades(df, thr, mode):
    ask, bid = ("ask", "bid") if mode == "opt" else ("ask_n", "bid_n")
    up = (df.p_fair - df[ask]) > thr
    dn = (df[bid] - df.p_fair) > thr
    out = []
    for sel, side in ((up, "UP"), (dn, "DOWN")):
        d = df[sel].copy()
        price = d[ask] if side == "UP" else 1 - d[bid]
        won = d.win_up if side == "UP" else ~d.win_up
        d["pnl"] = won.astype(float) - price
        d["price"], d["side"] = price, side
        out.append(d)
    return pd.concat(out)


def cluster_boot(t, n=4000, seed=0):
    """IC 95% de la media de pnl con bootstrap por mercado (los snapshots de un mismo mercado están muy correlacionados)."""
    g = t.groupby("market").pnl.agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n, len(g)))
    means = g["sum"].values[idx].sum(1) / g["count"].values[idx].sum(1)
    return np.percentile(means, [2.5, 97.5])


if __name__ == "__main__":
    for series, w in (("btc-up-or-down-5m", 300), ("btc-up-or-down-15m", 900)):
        df = build(series, w)
        print(f"\n=== {series}: {df.market.nunique()} mercados, {len(df)} snapshots dentro de la ventana, spread medio {df.spread.mean():.3f}")
        print(" umbral | ejec. | trades (mercados) | precio medio | pnl/acción | IC95% (bootstrap por mercado) | hit rate | retorno sobre capital")
        for thr in (0.0, 0.05, 0.10, 0.20):
            for mode in ("opt", "next"):
                t = trades(df, thr, mode)
                if len(t) < 20:
                    continue
                lo, hi = cluster_boot(t)
                print(f" {thr:5.2f}  | {mode:4s}  | {len(t):5d} ({t.market.nunique():3d})    |   {t.price.mean():.3f}     | {t.pnl.mean():+.4f}   | [{lo:+.4f}, {hi:+.4f}]  | "
                      f"{(t.pnl > 0).mean():.0%}    | {t.pnl.sum() / t.price.sum():+.1%}")
