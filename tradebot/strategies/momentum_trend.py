from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from ..data import htf_series
from .base import Strategy


class MomentumTrend(Strategy):
    """Breakout de momentum con filtro de tendencia del timeframe superior.

    Long : cierre > máximo de las `breakout_period` velas previas  y  HTF alcista
    Short: cierre < mínimo de las `breakout_period` velas previas  y  HTF bajista
    Salida de estrategia: la tendencia HTF se da vuelta. Además SL/TP en ATR y salida por tiempo.
    """
    name = "momentum_trend"
    defaults = {"breakout_period": 48, "trend_ema": 50, "atr_period": 14, "sl_atr": 2.0, "tp_atr": 4.0,
                "max_bars": 96}
    grid = {"breakout_period": [24, 48, 96], "sl_atr": [1.5, 2.0, 3.0], "tp_atr": [3.0, 4.0, 6.0]}

    def _signals(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        n = int(p["trend_ema"])
        trend = htf_series(df, self.htf_rule, lambda h: np.sign(h.close - ind.ema(h.close, n)))
        k = int(p["breakout_period"])
        long_ = (df.close > ind.prior_high(df.high, k)) & (trend > 0)
        short = (df.close < ind.prior_low(df.low, k)) & (trend < 0)
        return pd.DataFrame({"signal": long_.astype(int) - short.astype(int),
                             "exit_long": trend < 0, "exit_short": trend > 0}, index=df.index)
