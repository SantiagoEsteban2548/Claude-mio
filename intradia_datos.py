"""Paso 1: baja velas de 5 min de Binance (data.binance.vision) y las guarda como un parquet/npz por símbolo."""
import io, os, sys, zipfile
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests

OUT = os.environ.get("INTRA_DIR", "intradia")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LTCUSDT"]
MONTHS = pd.period_range("2021-01", "2026-09", freq="M")
URL = "https://data.binance.vision/data/spot/monthly/klines/{s}/5m/{s}-5m-{m}.zip"
COLS = ["t", "open", "high", "low", "close", "volume"]


def get(args):
    s, m = args
    for _ in range(3):
        try:
            r = requests.get(URL.format(s=s, m=m), timeout=60)
            if r.status_code == 404:
                return s, m, None
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=range(6), names=COLS)
            t = df["t"].to_numpy()
            df["t"] = np.where(t > 1e14, t // 1000, t)   # desde 2025 vienen en microsegundos
            return s, m, df
        except Exception as e:
            err = e
    print("fallo", s, m, err, file=sys.stderr)
    return s, m, None


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    jobs = [(s, str(m)) for s in SYMBOLS for m in MONTHS]
    parts = {s: [] for s in SYMBOLS}
    with ThreadPoolExecutor(16) as ex:
        for s, m, df in ex.map(get, jobs):
            if df is not None:
                parts[s].append(df)
    for s in SYMBOLS:
        d = pd.concat(parts[s]).drop_duplicates("t").sort_values("t").reset_index(drop=True)
        d.to_parquet(os.path.join(OUT, f"{s}.parquet")) if False else d.to_pickle(os.path.join(OUT, f"{s}.pkl"))
        gaps = (np.diff(d["t"].to_numpy()) != 300000).sum()
        print(f"{s}: {len(d):>8d} velas  {pd.to_datetime(d['t'].iloc[0], unit='ms')} -> {pd.to_datetime(d['t'].iloc[-1], unit='ms')}  huecos={gaps}")
