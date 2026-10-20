import numpy as np, pandas as pd
from scipy.stats import norm
D = "/tmp/claude-0/-home-user-Claude-mio/48e10cf0-e9cd-56ee-ac37-61f29356ace5/scratchpad/src/marketlenstrade_polymarket-historical-data/bitcoin-5m-15m-hourly-2026-06-15/"
m = pd.read_csv(D + "markets.csv", parse_dates=["open_time", "close_time"])
s = pd.read_csv(D + "snapshots.csv"); s["ts"] = pd.to_datetime(s.t_ms, unit="ms", utc=True)
ref = pd.read_parquet(D + "reference-BTC.parquet"); ref["ts"] = pd.to_datetime(ref.timestamp, unit="ms", utc=True); ref["price"] = ref.price.astype(float)
ref = ref.drop_duplicates("ts").set_index("ts").price.sort_index()
print("Referencia Binance:", ref.index[0], "→", ref.index[-1], f"| {len(ref):,} ticks | ticks/seg medio {len(ref)/(ref.index[-1]-ref.index[0]).total_seconds():.1f}")
five = m[m.series == "btc-up-or-down-5m"].copy()
print("Mercados 5m:", len(five), "| resolución Up:", (five.winning_outcome == "Up").mean().round(3), "| volumen medio USD:", five.volume_usd.mean().round(1))
# ¿qué token es el de los snapshots? comparar el último midpoint antes del cierre contra el ganador
last = []
for _, r in five.iterrows():
    x = s[(s.market_id == r.market_id) & (s.ts <= r.close_time)]
    if len(x): last.append((r.winning_outcome, x.iloc[-1].midpoint, x.iloc[-1].spread))
l = pd.DataFrame(last, columns=["win", "mid", "spread"])
print("midpoint final antes del cierre | gana Up:", l[l.win == "Up"].mid.mean().round(3), "| gana Down:", l[l.win == "Down"].mid.mean().round(3), "→ los snapshots son del token UP si el primero es mayor")
print("spread medio del libro:", l.spread.mean().round(4), "| snapshots por mercado 5m:", (s.market_id.isin(five.market_id)).sum() / len(five))
# precio de referencia en la apertura y volatilidad
def px_at(t):
    i = ref.index.searchsorted(t, side="right") - 1
    return ref.iloc[i] if i >= 0 else np.nan
five["p0"] = five.open_time.map(px_at); five["p1"] = five.close_time.map(px_at)
five["ret"] = five.p1 / five.p0 - 1
print("¿el ganador coincide con el signo del retorno de Binance en la ventana?", ((five.ret > 0) == (five.winning_outcome == "Up")).mean().round(3))
ret1s = np.log(ref.resample("1s").last().ffill()).diff().dropna()
sig = ret1s.std(); print(f"σ de 1 segundo: {sig*1e4:.3f} bp → σ de 5 min ≈ {sig*np.sqrt(300)*1e4:.1f} bp")
