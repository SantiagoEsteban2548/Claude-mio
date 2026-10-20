from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from ..data import htf_series
from .base import Strategy


class MeanReversion(Strategy):
    """Reversión a la media en 5m-15m con filtro de tendencia del timeframe superior.

    Long : cierre < banda inferior de Bollinger  y  RSI < rsi_entry        y  HTF alcista (cierre HTF > EMA HTF)
    Short: cierre > banda superior               y  RSI > 100 - rsi_entry  y  HTF bajista
    Salida de estrategia: el cierre vuelve a la media de Bollinger. Además SL/TP en ATR y salida por tiempo.
    """
    name = "mean_reversion"
    defaults = {"bb_period": 20, "bb_std": 2.0, "rsi_period": 14, "rsi_entry": 30, "trend_ema": 50,
                "atr_period": 14, "sl_atr": 1.5, "tp_atr": 1.5, "max_bars": 32}
    grid = {"bb_std": [2.0, 2.5], "rsi_entry": [25, 30], "sl_atr": [1.0, 1.5, 2.0], "tp_atr": [1.0, 1.5, 2.5]}

    def _signals(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        up, mid, lo = ind.bbands(df.close, int(p["bb_period"]), float(p["bb_std"]))
        r = ind.rsi(df.close, int(p["rsi_period"]))
        n = int(p["trend_ema"])
        trend = htf_series(df, self.htf_rule, lambda h: np.sign(h.close - ind.ema(h.close, n)))
        long_ = (df.close < lo) & (r < p["rsi_entry"]) & (trend > 0)
        short = (df.close > up) & (r > 100 - p["rsi_entry"]) & (trend < 0)
        return pd.DataFrame({"signal": long_.astype(int) - short.astype(int),
                             "exit_long": df.close >= mid, "exit_short": df.close <= mid}, index=df.index)
