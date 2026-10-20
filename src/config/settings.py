"""Configuracion central (variables de entorno BOT_* o archivo .env)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.fee_engine.engine import FeeEngine
from src.fee_engine.tiers import get_tier
from src.risk.manager import RiskConfig


class Mode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class LecapSpec(BaseModel):
    """LECAP/BONCAP: pago final por 100 VN al vencimiento (capitalizable)."""

    symbol: str
    maturity: date
    payoff_per_100: float = Field(gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BOT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mode: Mode = Mode.PAPER
    capital_ars: float = 1_000_000.0
    db_path: str = "data/bot.db"

    iol_username: str = ""
    iol_password: SecretStr = SecretStr("")
    iol_base_url: str = "https://api.invertironline.com"
    iol_rate_per_sec: float = 3.0
    iol_burst: int = 5
    iol_poll_interval: float = 1.0

    primary_username: str = ""
    primary_password: SecretStr = SecretStr("")
    primary_account: str = ""
    primary_base_url: str = "https://api.primary.com.ar"
    primary_ws_url: str = "wss://api.primary.com.ar/"
    future_symbol: str = "DLR/DIC26"
    future_expiry: date | None = None

    fee_tier: str = "gold"
    min_net_edge_pct: float = 0.0005

    caucion_colocadora_tna: float = 0.28
    caucion_tomadora_tna: float = 0.34
    lecaps: list[LecapSpec] = Field(default_factory=list)
    holidays: list[date] = Field(default_factory=list)

    # Inventario inicial para PAPER/BACKTEST (permite vender especies que "tenes")
    paper_inventory: dict[str, float] = Field(default_factory=dict)

    telegram_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""

    kill_switch_dd_pct: float = 0.008
    target_daily_net: float = 0.004

    def risk_config(self) -> RiskConfig:
        return RiskConfig(capital_ars=self.capital_ars, kill_switch_dd_pct=self.kill_switch_dd_pct)

    def fee_engine(self) -> FeeEngine:
        return FeeEngine(get_tier(self.fee_tier), min_net_edge_pct=self.min_net_edge_pct)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
