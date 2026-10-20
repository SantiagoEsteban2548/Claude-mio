from __future__ import annotations

from typing import Any

from .base import SIGNAL_COLUMNS, Strategy
from .mean_reversion import MeanReversion
from .momentum_trend import MomentumTrend

REGISTRY: dict[str, type[Strategy]] = {c.name: c for c in (MeanReversion, MomentumTrend)}


def strategy_from_settings(settings: Any, name: str | None = None, params: dict[str, Any] | None = None,
                           timeframe: str | None = None) -> Strategy:
    """Construye la estrategia con los parámetros de la config (o `params`) y el filtro HTF/vol configurado."""
    from ..data import timeframe_to_timedelta

    name = name or settings.strategy.name
    tf = timeframe or settings.exchange.timeframe
    base = dict(settings.strategy.params.get(name, {}))
    bars_per_day = int(round(86400 / timeframe_to_timedelta(tf).total_seconds()))
    c = settings.risk.conservative
    return build_strategy(name, {**base, **(params or {})}, allow_short=settings.strategy.allow_short,
                          htf_rule=settings.exchange.htf_timeframe,
                          vol_lookback=c.vol_lookback_days * bars_per_day, vol_quantile=c.vol_quantile)


def build_strategy(name: str, params: dict[str, Any] | None = None, **kw: Any) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"estrategia desconocida: {name}. Opciones: {sorted(REGISTRY)}")
    return REGISTRY[name](params, **kw)


__all__ = ["REGISTRY", "SIGNAL_COLUMNS", "Strategy", "build_strategy", "strategy_from_settings"]
