"""Métricas de performance. Sharpe/Sortino anualizados sobre retornos DIARIOS (crypto: 365 días)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

DAILY_TARGET = 0.005


def compute(equity: pd.Series, trades: pd.DataFrame, initial: float, exposure: float,
            fees: float, slippage: float) -> dict[str, Any]:
    eq = equity.dropna()
    daily = eq.resample("1D").last().dropna()
    daily_ret = pd.concat([pd.Series([initial]), daily.reset_index(drop=True)]).pct_change().dropna()
    sd, dsd = daily_ret.std(), daily_ret[daily_ret < 0].std()
    years = max((eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400), 1e-9)
    final = float(eq.iloc[-1])
    n = len(trades)
    pnl = trades["pnl"] if n else pd.Series(dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    dd = eq / eq.cummax() - 1
    max_dd = float(dd.min())
    cagr = (final / initial) ** (1 / years) - 1 if final > 0 else -1.0
    geo_daily = (final / initial) ** (1 / max(len(daily_ret), 1)) - 1 if final > 0 else -1.0
    return {
        "start": str(eq.index[0]), "end": str(eq.index[-1]), "days": int(len(daily_ret)),
        "initial_equity": initial, "final_equity": final,
        "total_return": final / initial - 1,
        "cagr": cagr,
        "avg_daily_return": geo_daily,
        "daily_target": DAILY_TARGET,
        "pct_days_target_hit": float((daily_ret >= DAILY_TARGET - 1e-12).mean()) if len(daily_ret) else 0.0,
        "pct_days_positive": float((daily_ret > 0).mean()) if len(daily_ret) else 0.0,
        "worst_day": float(daily_ret.min()) if len(daily_ret) else 0.0,
        "sharpe": float(daily_ret.mean() / sd * math.sqrt(365)) if sd > 0 else 0.0,
        "sortino": float(daily_ret.mean() / dsd * math.sqrt(365)) if dsd > 0 else 0.0,
        "max_drawdown": max_dd,
        "calmar": float(cagr / -max_dd) if max_dd < 0 else 0.0,
        "n_trades": n,
        "win_rate": float(len(wins) / n) if n else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if n and losses.sum() < 0 else (math.inf if n else 0.0),
        "expectancy": float(pnl.mean()) if n else 0.0,
        "expectancy_r": float(trades["r"].mean()) if n else 0.0,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "fees_paid": fees,
        "slippage_cost": slippage,
        "exposure": exposure,
    }


PCT = {"total_return", "cagr", "avg_daily_return", "daily_target", "pct_days_target_hit", "pct_days_positive",
       "worst_day", "max_drawdown", "win_rate", "exposure", "buy_hold_return"}


def fmt(m: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in m.items():
        if k in PCT and isinstance(v, (int, float)):
            out[k] = f"{v:.3%}" if k in {"avg_daily_return", "daily_target", "worst_day"} else f"{v:.2%}"
        elif isinstance(v, float):
            out[k] = "inf" if v == math.inf else f"{v:,.2f}"
        else:
            out[k] = str(v)
    return out


__all__ = ["compute", "fmt", "np", "DAILY_TARGET"]
