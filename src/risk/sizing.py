"""Position sizing: Kelly fraccional + tope por liquidez en la punta contraria."""

from __future__ import annotations

import math

from src.core.models import OrderBook, Side
from src.risk.manager import RiskConfig


def kelly_fraction(win_prob: float, win_loss_ratio: float) -> float:
    """Kelly completo f* = (p*b - q) / b, truncado a [0, 1]."""
    if win_loss_ratio <= 0 or not 0.0 < win_prob < 1.0:
        return 0.0
    q = 1.0 - win_prob
    return max(0.0, min(1.0, (win_prob * win_loss_ratio - q) / win_loss_ratio))


def liquidity_cap_qty(book: OrderBook, side: Side, cap_pct: float) -> float:
    """Max cantidad = cap_pct del volumen en la mejor punta contraria (BUY -> ask, SELL -> bid)."""
    lv = book.touch(side)
    return 0.0 if lv is None else math.floor(lv.size * cap_pct)


def max_notional_ars(
    cfg: RiskConfig,
    *,
    win_prob: float | None,
    take_profit_pct: float | None,
    stop_loss_pct: float | None,
) -> float:
    """Nocional maximo por pata en ARS: Kelly fraccional acotado por ``max_position_pct``."""
    cap = cfg.capital_ars * cfg.max_position_pct
    if win_prob is None or not take_profit_pct or not stop_loss_pct:
        return cap  # sin estimacion estadistica: tope fijo
    f = kelly_fraction(win_prob, take_profit_pct / stop_loss_pct) * cfg.kelly_fraction
    return min(cap, cfg.capital_ars * f)


def qty_for_notional(notional_ars: float, price: float, multiplier: float, fx: float) -> float:
    """Cantidad entera de unidades que entra en ``notional_ars`` (fx = ARS por unidad de moneda)."""
    unit = price * multiplier * fx
    return 0.0 if unit <= 0 else float(math.floor(notional_ars / unit))
