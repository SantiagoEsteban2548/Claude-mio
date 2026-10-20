"""Alertas por consola y Telegram (opcional)."""

from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("alerts")


class Alerts:
    def __init__(self, telegram_token: str = "", telegram_chat_id: str = "") -> None:
        self._token = telegram_token
        self._chat = telegram_chat_id

    @property
    def telegram_enabled(self) -> bool:
        return bool(self._token and self._chat)

    async def send(self, text: str) -> None:
        log.warning("ALERTA: %s", text)
        if not self.telegram_enabled:
            return
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s,
                s.post(url, json={"chat_id": self._chat, "text": text}) as r,
            ):
                if r.status != 200:
                    log.error("Telegram HTTP %s", r.status)
        except (aiohttp.ClientError, TimeoutError) as e:
            log.error("Telegram fallo: %s", e)
