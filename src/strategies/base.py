"""Interfaz base de las estrategias."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.models import OrderBook, Settlement, Signal
from src.execution.positions import PositionManager
from src.strategies.state import MarketState


class Strategy(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def subscriptions(self) -> list[tuple[str, Settlement]]:
        """(especie, plazo) cuyos libros necesita la estrategia."""

    @abstractmethod
    def on_book(self, book: OrderBook, state: MarketState, positions: PositionManager) -> list[Signal]:
        """Evalua un libro nuevo (ya incorporado a ``state``) y devuelve senales."""

    def on_result(self, signal: Signal, executed: bool) -> None:  # noqa: B027
        """Notificacion de si la senal se ejecuto (para actualizar el estado interno)."""


def rolling_stats(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / max(n - 1, 1)
    return mean, var**0.5
