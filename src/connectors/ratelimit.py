"""Token bucket asincrono para respetar los limites de la API y evitar HTTP 429."""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: int) -> None:
        if rate_per_sec <= 0 or capacity < 1:
            raise ValueError("rate_per_sec > 0 y capacity >= 1")
        self.rate = rate_per_sec
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                await asyncio.sleep((tokens - self._tokens) / self.rate)

    def penalize(self, seconds: float) -> None:
        """Tras un 429: vacia el bucket y retrasa el proximo token ``seconds``."""
        self._tokens = -seconds * self.rate
        self._updated = time.monotonic()
