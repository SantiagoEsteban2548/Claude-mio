"""Benchmarks de la meta diaria: ARS (vs caucion/LECAP prorrateada) y USD MEP implicito."""

from __future__ import annotations

TARGET_DAILY_NET = 0.004  # 0.4%


def daily_prorated(tna: float, calendar_days: int = 1) -> float:
    """TNA (fraccion, base 365) prorrateada a ``calendar_days`` dias corridos."""
    return tna * calendar_days / 365.0


def excess_over_hurdle(net_return_ars: float, tna_hurdle: float, calendar_days: int = 1) -> float:
    """Retorno neto en ARS menos lo que rendiria la caucion/LECAP en el mismo periodo."""
    return net_return_ars - daily_prorated(tna_hurdle, calendar_days)


def usd_mep_return(net_return_ars: float, mep_open: float, mep_close: float) -> float:
    """Retorno en USD MEP implicito: (1+r_ars) / (1+var_mep) - 1."""
    if mep_open <= 0 or mep_close <= 0:
        raise ValueError("Cotizaciones MEP deben ser positivas")
    return (1.0 + net_return_ars) / (mep_close / mep_open) - 1.0


def target_progress(net_return: float, target: float = TARGET_DAILY_NET) -> float:
    return net_return / target if target else 0.0


def compound(daily_returns: list[float]) -> float:
    total = 1.0
    for r in daily_returns:
        total *= 1.0 + r
    return total - 1.0
