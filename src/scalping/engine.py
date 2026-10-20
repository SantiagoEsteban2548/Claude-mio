"""Simulador de scalping con R:R fijo (default 1:3), sin lookahead y con costos reales.

Reglas (todas conservadoras):
- Senal en el cierre de la barra i -> entrada al OPEN de i+1 (+ slippage adverso).
- Stop = stop_atr * ATR (piso: min_stop_pct del precio); objetivo = rr * stop.
- Si stop y objetivo caen en la misma barra, se asume que pego el STOP.
- Una sola posicion a la vez por simbolo; salida por tiempo al cierre tras max_hold barras.
- Se omiten trades cuyo costo supera max_cost_r (el costo se come el edge: mismo criterio del FeeEngine).
- Costos en R: (2*fee + 2*slippage) * precio / distancia_stop, restados al resultado bruto.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WIN, LOSS, TIME = 1, 0, 2


@dataclass(frozen=True)
class EngineCfg:
    rr: float = 3.0
    stop_atr: float = 1.5
    max_hold: int = 48
    fee_bps: float = 4.5  # taker futuros por lado (aprox. nivel base con BNB; verificar)
    slip_bps: float = 2.0  # por lado
    min_stop_pct: float = 0.004
    max_cost_r: float = 0.35


@dataclass
class Trades:
    entry_idx: np.ndarray
    exit_idx: np.ndarray
    side: np.ndarray
    outcome: np.ndarray
    r_net: np.ndarray

    def __len__(self) -> int:
        return len(self.r_net)


def simulate(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
    signal: np.ndarray,
    cfg: EngineCfg,
) -> Trades:
    n = len(close)
    slip = cfg.slip_bps / 1e4
    e_i: list[int] = []
    x_i: list[int] = []
    sides: list[int] = []
    outs: list[int] = []
    rs: list[float] = []
    free_at = 0
    for i_raw in np.flatnonzero(signal):
        i = int(i_raw)
        if i < free_at or i + 1 >= n:
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        side = int(signal[i])
        entry = open_[i + 1] * (1 + side * slip)
        d = max(cfg.stop_atr * a, cfg.min_stop_pct * entry)
        cost_r = entry * (2 * cfg.fee_bps / 1e4 + 2 * slip) / d
        if cost_r > cfg.max_cost_r:
            continue
        end = min(n, i + 1 + cfg.max_hold)
        lo, hi = low[i + 1 : end], high[i + 1 : end]
        if side == 1:
            stop_hit, tgt_hit = lo <= entry - d, hi >= entry + cfg.rr * d
        else:
            stop_hit, tgt_hit = hi >= entry + d, lo <= entry - cfg.rr * d
        fs = int(stop_hit.argmax()) if stop_hit.any() else n
        ft = int(tgt_hit.argmax()) if tgt_hit.any() else n
        j: int
        gross: float
        out: int
        if fs == n and ft == n:
            j = end - 1
            gross, out = side * (close[j] - entry) / d, TIME
        elif fs <= ft:  # empate en la misma barra -> stop
            j, gross, out = i + 1 + fs, -1.0, LOSS
        else:
            j, gross, out = i + 1 + ft, cfg.rr, WIN
        e_i.append(i + 1)
        x_i.append(j)
        sides.append(side)
        outs.append(out)
        rs.append(gross - cost_r)
        free_at = j + 1
    return Trades(
        np.array(e_i, dtype=np.int64),
        np.array(x_i, dtype=np.int64),
        np.array(sides, dtype=np.int8),
        np.array(outs, dtype=np.int8),
        np.array(rs, dtype=np.float64),
    )
