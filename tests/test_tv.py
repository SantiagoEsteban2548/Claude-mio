import numpy as np
import pandas as pd
import pytest

from src.scalping.tv import clean, import_file, parse_tradingview_csv, quality, to_5m


def write(tmp_path, text: str):
    p = tmp_path / "x.csv"
    p.write_text(text)
    return p


def test_iso_with_offset_converted_to_utc(tmp_path) -> None:
    p = write(tmp_path, "time,open,high,low,close,Volume\n2024-01-01T00:00:00-03:00,1,2,0.5,1.5,10\n")
    df = parse_tradingview_csv(p)
    assert df.index[0] == pd.Timestamp("2024-01-01 03:00", tz="UTC")
    assert df["volume"].iloc[0] == 10


def test_naive_time_uses_chart_timezone(tmp_path) -> None:
    p = write(tmp_path, "time,open,high,low,close\n2024-01-01 00:00:00,1,2,0.5,1.5\n")
    df = parse_tradingview_csv(p, tz="America/Argentina/Buenos_Aires")
    assert df.index[0] == pd.Timestamp("2024-01-01 03:00", tz="UTC")
    assert df["volume"].iloc[0] == 0


@pytest.mark.parametrize("ts", [1_700_000_000, 1_700_000_000_000])
def test_unix_seconds_and_millis(tmp_path, ts: int) -> None:
    p = write(tmp_path, f"time,open,high,low,close,volume,MA\n{ts},1,2,0.5,1.5,3,9\n")
    assert parse_tradingview_csv(p).index[0] == pd.Timestamp("2023-11-14 22:13:20", tz="UTC")


def test_missing_columns_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        parse_tradingview_csv(write(tmp_path, "foo,bar\n1,2\n"))


def _minute_csv(tmp_path, n: int = 50) -> str:
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    px = 100 + np.arange(n) * 0.01
    df = pd.DataFrame(
        {
            "time": idx.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": px,
            "high": px + 0.1,
            "low": px - 0.1,
            "close": px,
            "Volume": 1.0,
        }
    )
    p = tmp_path / "m.csv"
    df.to_csv(p, index=False)
    return str(p)


def test_one_minute_resampled_to_5m_without_lookahead(tmp_path) -> None:
    df = to_5m(parse_tradingview_csv(_minute_csv(tmp_path)))
    assert len(df) == 10 and (df["volume"] == 5).all()
    first = parse_tradingview_csv(_minute_csv(tmp_path)).iloc[:5]
    assert df["open"].iloc[0] == first["open"].iloc[0] and df["close"].iloc[0] == first["close"].iloc[4]


def test_coarser_than_5m_rejected(tmp_path) -> None:
    idx = pd.date_range("2024-01-01", periods=5, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx)
    with pytest.raises(ValueError):
        to_5m(df)


def test_clean_and_quality_detect_problems() -> None:
    idx = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC").delete(range(40, 60))
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx)
    df.iloc[5, df.columns.get_loc("high")] = 99.5  # high < close: invalida
    dup = pd.concat([df, df.iloc[[0]]])
    cleaned, dups, bad = clean(dup)
    q = quality(cleaned, dups, bad)
    assert dups == 1 and bad == 1 and q.gaps == 1 and q.largest_gap_minutes == 105
    assert not q.ok and q.coverage_pct < 90


def test_import_file_writes_loadable_pickle(tmp_path) -> None:
    q = import_file(_minute_csv(tmp_path), "TESTUSDT", tmp_path / "out")
    assert q.ok and q.bars == 10
    assert len(pd.read_pickle(tmp_path / "out" / "TESTUSDT_5m.pkl.gz")) == 10
