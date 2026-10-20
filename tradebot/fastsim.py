"""Simulador rápido de operaciones para INVESTIGACIÓN (explorar cientos de variantes).

No reemplaza al motor (backtest/engine.py): no aplica breaker, kill switch ni compounding. Mide la
distribución de resultados por operación en R (R = pérdida si salta el stop, incluyendo costos), que es
lo que determinan win rate, profit factor y expectancy cuando el riesgo por trade es fijo.

Reglas de ejecución (mismas convenciones que el motor):
  - señal al cierre de la vela i; entrada en la vela i+1:
      market: a la apertura (+ slippage)
      limit:  a `close_i -/+ offset*ATR`, solo si la vela i+1 la toca (si no, la orden se cancela);
  - SL/TP fijados desde el precio de entrada; se chequean desde la misma vela de entrada;
    si ambos caen en una vela, se asume el stop (peor caso); los gaps se llenan a la apertura;
  - salida por tiempo a la apertura después de `max_bars`, y salida por regla (`exit_mask`) a la apertura
    siguiente;
  - no hay operaciones superpuestas.
Costos por lado: entrada market = taker+slip, entrada limit = maker; TP = maker (limit); SL y salidas por
tiempo/regla = taker+slip.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Costs:
    taker: float = 0.0005
    maker: float = 0.0002
    slippage: float = 0.0002


def simulate(df: pd.DataFrame, signal: np.ndarray, atr: np.ndarray, sl_atr: float, tp_atr: float, max_bars: int,
             costs: Costs = Costs(), entry: str = "market", limit_offset_atr: float = 0.0,
             exit_long: np.ndarray | None = None, exit_short: np.ndarray | None = None) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(df)
    sig = np.asarray(signal)
    exl = np.zeros(n, bool) if exit_long is None else np.asarray(exit_long, bool)
    exs = np.zeros(n, bool) if exit_short is None else np.asarray(exit_short, bool)
    rows = []
    i = 0
    idx = np.flatnonzero(sig != 0)
    k = 0
    while k < len(idx):
        i = idx[k]
        if i + 1 >= n or not np.isfinite(atr[i]) or atr[i] <= 0:
            k += 1
            continue
        d = int(sig[i])
        j = i + 1
        if entry == "market":
            px = o[j] * (1 + d * costs.slippage)
            fee_in = costs.taker
        else:
            lim = c[i] - d * limit_offset_atr * atr[i]
            touched = l[j] <= lim if d > 0 else h[j] >= lim
            if not touched:
                k += 1
                continue
            px = min(o[j], lim) if d > 0 else max(o[j], lim)
            fee_in = costs.maker
        sl, tp = sl_atr * atr[i], tp_atr * atr[i]
        stop, take = px - d * sl, px + d * tp
        exit_px, fee_out, reason, jj = np.nan, costs.taker, "", j
        for jj in range(j, min(j + max_bars, n)):
            if jj > j:  # gaps: la apertura ya está más allá del nivel
                if (d > 0 and o[jj] <= stop) or (d < 0 and o[jj] >= stop):
                    exit_px, reason = o[jj] * (1 - d * costs.slippage), "stop"
                    break
                if (d > 0 and o[jj] >= take) or (d < 0 and o[jj] <= take):
                    exit_px, reason, fee_out = o[jj], "tp", costs.maker
                    break
            if (d > 0 and l[jj] <= stop) or (d < 0 and h[jj] >= stop):
                exit_px, reason = stop * (1 - d * costs.slippage), "stop"
                break
            if (d > 0 and h[jj] >= take) or (d < 0 and l[jj] <= take):
                exit_px, reason, fee_out = take, "tp", costs.maker
                break
            if ((d > 0 and exl[jj]) or (d < 0 and exs[jj])) and jj + 1 < n:
                jj += 1
                exit_px, reason = o[jj] * (1 - d * costs.slippage), "rule"
                break
        else:
            jj = min(j + max_bars, n - 1)
            exit_px, reason = o[jj] * (1 - d * costs.slippage), "time"
        gross = d * (exit_px - px) / px
        net = gross - fee_in - fee_out * exit_px / px
        risk = sl / px + fee_in + costs.taker + costs.slippage  # pérdida al stop, en fracción del nocional
        rows.append((df.index[i], d, px, exit_px, reason, jj - j, gross, net, net / risk, risk))
        k = int(np.searchsorted(idx, max(jj, i + 1), side="left"))  # sin superposición: la próxima señal puede ser la del cierre de la vela de salida
    return pd.DataFrame(rows, columns=["time", "side", "entry", "exit", "reason", "bars", "gross", "net", "r", "risk"])


def summary(t: pd.DataFrame, days: float | None = None) -> dict:
    if t.empty:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "exp_r": 0.0, "gross_exp_r": 0.0, "per_day": 0.0}
    r = t.r
    wins, losses = r[r > 0].sum(), -r[r <= 0].sum()
    return {"n": int(len(t)), "wr": float((r > 0).mean()), "pf": float(wins / losses) if losses > 0 else np.inf,
            "exp_r": float(r.mean()), "gross_exp_r": float((t.gross / t.risk).mean()),
            "per_day": float(len(t) / days) if days else np.nan}
