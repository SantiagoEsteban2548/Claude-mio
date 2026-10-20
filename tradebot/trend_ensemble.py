"""Ensamble de tendencia diario, largo/flat, spot, sin apalancamiento.

Patrón (research/patterns/README.md): en BTC, a horizonte diario, "estar largo cuando el precio está en tendencia alcista
y salir a efectivo si no" reduce el drawdown a la mitad con un Sharpe igual o mayor que comprar y mantener. Es persistencia
de tendencia, no una fuente de retorno alto.

Reglas FIJAS (no optimizadas): 8 votos, cada uno 1 si
  close > SMA(n) para n en 20, 50, 100, 200      y      close/close[-n] - 1 > 0 para n en 14, 30, 60, 90.
Exposición objetivo = votos / 8, en [0, 1]. La decisión al cierre de t-1 se ejecuta para la barra t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SMA_WINDOWS = (20, 50, 100, 200)
MOMENTUM_WINDOWS = (14, 30, 60, 90)
COST_PER_SIDE = 0.0007  # comisión + slippage por lado, sobre el cambio de exposición


def target_exposure(close: pd.Series) -> pd.Series:
    """Fracción del capital a mantener en BTC al cierre de cada barra (causal: usa solo datos hasta esa barra)."""
    votes = [(close > close.rolling(n).mean()) for n in SMA_WINDOWS]
    votes += [(close / close.shift(n) - 1 > 0) for n in MOMENTUM_WINDOWS]
    return sum(v.astype(float) for v in votes) / len(votes)


def backtest(close: pd.Series, cost_per_side: float = COST_PER_SIDE, leverage: float = 1.0) -> pd.DataFrame:
    """Retornos diarios del ensamble. Devuelve columnas: exposure, ret (neto de costos), bh (buy & hold)."""
    ret = close.pct_change().fillna(0.0)
    w = target_exposure(close).shift(1).fillna(0.0) * leverage
    net = w * ret - w.diff().abs().fillna(0.0) * cost_per_side
    return pd.DataFrame({"exposure": w, "ret": net, "bh": ret})


def summarize(x: pd.Series, periods_per_year: int = 365) -> dict[str, float]:
    eq = (1 + x).cumprod()
    years = len(x) / periods_per_year
    return {
        "total_return": float(eq.iloc[-1] - 1),
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1) if eq.iloc[-1] > 0 else -1.0,
        "sharpe": float(x.mean() / x.std() * np.sqrt(periods_per_year)) if x.std() > 0 else 0.0,
        "max_drawdown": float((eq / eq.cummax() - 1).min()),
        "avg_daily": float(eq.iloc[-1] ** (1 / len(x)) - 1) if eq.iloc[-1] > 0 else -1.0,
    }
