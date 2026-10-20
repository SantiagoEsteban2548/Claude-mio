"""Genera velas OHLCV 5m/15m/1h REALES de BTC/USD (Bitstamp) desde el dataset público de 1 minuto
https://github.com/ff137/bitstamp-btcusd-minute-data (CC BY-SA 4.0).

Uso:
  git clone --depth 1 https://github.com/ff137/bitstamp-btcusd-minute-data /tmp/bs
  python scripts/prepare_data.py /tmp/bs --since 2023-01-01
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def load_minutes(src: Path, since: str) -> pd.DataFrame:
    files = [*sorted((src / "data/historical").glob("*.csv.gz")), *sorted((src / "data/updates").glob("*.csv"))]
    cutoff = pd.Timestamp(since, tz="UTC").timestamp()
    parts = [p[p.timestamp >= cutoff] for p in (pd.read_csv(f) for f in files)]
    df = pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp")
    df.index = pd.to_datetime(df.pop("timestamp"), unit="s", utc=True)
    return df


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(rule, label="left", closed="left").agg(agg).dropna()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--since", default="2023-01-01")
    a = ap.parse_args()
    minutes = load_minutes(a.src, a.since)
    dest = Path(__file__).resolve().parent.parent / "data"
    for rule in ("5min", "15min", "1h"):
        bars = resample(minutes, rule)
        bars.index.name = "time"
        name = f"BTCUSD_bitstamp_{rule.replace('min', 'm')}.csv.gz"
        bars.to_csv(dest / name, float_format="%.8g")
        print(name, bars.index[0], bars.index[-1], len(bars))


if __name__ == "__main__":
    main()
