"""Contrato de estrategia.

`compute(df)` devuelve, por vela y con datos hasta su CIERRE:
  signal      +1 abrir long, -1 abrir short, 0 nada (se ejecuta en la apertura de la vela siguiente)
  exit_long   cerrar long por regla de la estrategia
  exit_short  cerrar short por regla de la estrategia
  atr         ATR para stops/take-profit
  high_vol    True si la volatilidad está en régimen alto (lo usa el modo conservador)
Los stops/TP en múltiplos de ATR y la salida por tiempo los aplica el motor con `sl_atr`, `tp_atr`, `max_bars`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import pandas as pd

from .. import indicators as ind

SIGNAL_COLUMNS = ["signal", "exit_long", "exit_short", "atr", "high_vol"]


class Strategy(ABC):
    name: ClassVar[str]
    defaults: ClassVar[dict[str, Any]]
    grid: ClassVar[dict[str, list[Any]]]

    def __init__(self, params: dict[str, Any] | None = None, allow_short: bool = False,
                 htf_rule: str = "4h", vol_lookback: int = 2880, vol_quantile: float = 0.8):
        self.params = {**self.defaults, **(params or {})}
        unknown = set(self.params) - set(self.defaults)
        if unknown:
            raise ValueError(f"{self.name}: parámetros desconocidos {sorted(unknown)}")
        self.allow_short = allow_short
        self.htf_rule = htf_rule
        self.vol_lookback = vol_lookback
        self.vol_quantile = vol_quantile

    @property
    def sl_atr(self) -> float:
        return float(self.params["sl_atr"])

    @property
    def tp_atr(self) -> float:
        return float(self.params["tp_atr"])

    @property
    def max_bars(self) -> int:
        return int(self.params["max_bars"])

    @abstractmethod
    def _signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Debe devolver columnas signal, exit_long, exit_short."""

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self._signals(df)
        if not self.allow_short:
            out["signal"] = out["signal"].clip(lower=0)
        a = ind.atr(df, int(self.params["atr_period"]))
        atr_pct = a / df.close
        threshold = atr_pct.rolling(self.vol_lookback, min_periods=self.vol_lookback // 4).quantile(self.vol_quantile)
        out["atr"] = a
        out["high_vol"] = (atr_pct > threshold).fillna(False)
        out.loc[a.isna(), "signal"] = 0
        out["signal"] = out["signal"].fillna(0).astype(int)
        out[["exit_long", "exit_short"]] = out[["exit_long", "exit_short"]].fillna(False).astype(bool)
        return out[SIGNAL_COLUMNS]
