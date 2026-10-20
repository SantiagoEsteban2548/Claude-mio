"""Indicadores vía TA-Lib (todos causales: el valor en t usa datos hasta t)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib


def _s(values: np.ndarray, index: pd.Index) -> pd.Series:
    return pd.Series(values, index=index)


def ema(close: pd.Series, n: int) -> pd.Series:
    return _s(talib.EMA(close.to_numpy(float), timeperiod=n), close.index)


def rsi(close: pd.Series, n: int) -> pd.Series:
    return _s(talib.RSI(close.to_numpy(float), timeperiod=n), close.index)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    return _s(talib.ATR(df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float), timeperiod=n),
              df.index)


def bbands(close: pd.Series, n: int, k: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    up, mid, lo = talib.BBANDS(close.to_numpy(float), timeperiod=n, nbdevup=k, nbdevdn=k, matype=0)
    return _s(up, close.index), _s(mid, close.index), _s(lo, close.index)


def prior_high(high: pd.Series, n: int) -> pd.Series:
    """Máximo de las n velas anteriores (excluye la actual)."""
    return high.shift(1).rolling(n, min_periods=n).max()


def prior_low(low: pd.Series, n: int) -> pd.Series:
    return low.shift(1).rolling(n, min_periods=n).min()
