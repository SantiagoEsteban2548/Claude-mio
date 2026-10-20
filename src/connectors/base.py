"""Interfaz comun de conectores de mercado y utilidades de latencia."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator

from src.core.models import AccountState, Order, OrderBook, Settlement, Side


class LatencyTracker:
    """Media movil de latencias de la API en milisegundos."""

    def __init__(self, maxlen: int = 50) -> None:
        self._samples: deque[float] = deque(maxlen=maxlen)

    def record(self, seconds: float) -> None:
        self._samples.append(seconds * 1000.0)

    @property
    def last_ms(self) -> float | None:
        return self._samples[-1] if self._samples else None

    @property
    def avg_ms(self) -> float | None:
        return sum(self._samples) / len(self._samples) if self._samples else None

    def timer(self) -> float:
        return time.perf_counter()


class ConnectorError(RuntimeError):
    pass


class MarketConnector(ABC):
    """Abstraccion de un broker/mercado: datos, cuenta y ordenes."""

    name: str = "base"

    def __init__(self) -> None:
        self.latency = LatencyTracker()

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def get_order_book(self, symbol: str, settlement: Settlement) -> OrderBook: ...

    @abstractmethod
    def stream_books(self, subscriptions: list[tuple[str, Settlement]]) -> AsyncIterator[OrderBook]:
        """Flujo continuo de libros (polling en IOL, WebSocket en Primary)."""

    @abstractmethod
    async def get_account(self) -> AccountState: ...

    @abstractmethod
    async def place_order(
        self, symbol: str, settlement: Settlement, side: Side, qty: float, price: float
    ) -> str:
        """Envia una orden limite DAY y devuelve el id del broker."""

    @abstractmethod
    async def cancel_order(self, broker_id: str) -> None: ...

    @abstractmethod
    async def get_order(self, broker_id: str) -> Order: ...

    async def get_caucion_rates(self) -> tuple[float, float] | None:
        """(colocadora_tna, tomadora_tna) como fracciones, o None si el conector no las provee."""
        return None
