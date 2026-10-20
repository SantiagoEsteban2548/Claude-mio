"""Backtest: repite libros grabados (o sinteticos) por el mismo motor que paper/live."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.core.models import OrderBook
from src.execution.engine import DayResult, TradingEngine
from src.fee_engine.benchmark import TARGET_DAILY_NET, compound


@dataclass
class BacktestSummary:
    days: list[DayResult]
    compounded: float
    hit_rate: float  # % de dias con retorno neto >= meta
    worst_day: float
    beat_hurdle_rate: float

    def lines(self, target: float = TARGET_DAILY_NET) -> list[str]:
        out = [
            f"Dias simulados            : {len(self.days)}",
            f"Retorno compuesto neto    : {self.compounded:+.3%}",
            f"Dias que superan {target:.2%}   : {self.hit_rate:.0%}",
            f"Dias que superan caucion  : {self.beat_hurdle_rate:.0%}",
            f"Peor dia                  : {self.worst_day:+.3%}",
            "",
            "Dia          Neto %    USD MEP %   Fills   Neto ARS",
        ]
        for d in self.days:
            usd = "   n/d  " if d.usd_mep_pct is None else f"{d.usd_mep_pct:+8.3%}"
            out.append(f"{d.day}  {d.net_pct:+8.3%}  {usd}  {d.trades:5d}  {d.net_pnl_ars:+12,.0f}")
        return out


def summarize(days: list[DayResult], target: float = TARGET_DAILY_NET) -> BacktestSummary:
    rets = [d.net_pct for d in days]
    n = len(days) or 1
    return BacktestSummary(
        days=days,
        compounded=compound(rets),
        hit_rate=sum(r >= target for r in rets) / n,
        worst_day=min(rets) if rets else 0.0,
        beat_hurdle_rate=sum(d.net_pct > d.hurdle_pct for d in days) / n,
    )


async def run_backtest(engine: TradingEngine, books: Iterable[OrderBook]) -> BacktestSummary:
    for b in books:
        await engine.on_book(b)
    engine.end_of_data()
    return summarize(engine.day_results)
