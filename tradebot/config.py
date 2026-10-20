"""Carga y validación de config/config.yaml. Los límites de riesgo no negociables se validan acá."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

MAX_LEVERAGE_HARD_CAP = 3.0


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ConservativeConfig:
    enabled: bool = True
    vol_lookback_days: int = 30
    vol_quantile: float = 0.80
    size_multiplier: float = 0.5


@dataclass(frozen=True)
class LossStreakConfig:
    after_losses: int = 3
    size_multiplier: float = 0.5


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade: float = 0.0075
    sizing: Literal["fixed_fractional", "kelly"] = "fixed_fractional"
    kelly_fraction: float = 0.25
    kelly_lookback_trades: int = 50
    max_leverage: float = 1.0
    max_daily_drawdown: float = 0.02
    max_total_drawdown: float = 0.12
    daily_profit_target: float | None = 0.005
    conservative: ConservativeConfig = field(default_factory=ConservativeConfig)
    loss_streak: LossStreakConfig = field(default_factory=LossStreakConfig)

    def validate(self) -> None:
        checks = [
            (0.005 <= self.risk_per_trade <= 0.01, "risk_per_trade debe estar entre 0.5% y 1%"),
            (self.sizing in ("fixed_fractional", "kelly"), "sizing debe ser fixed_fractional o kelly"),
            (0 < self.kelly_fraction <= 0.5, "kelly_fraction debe estar en (0, 0.5]"),
            (0 < self.max_leverage <= MAX_LEVERAGE_HARD_CAP, f"max_leverage debe ser <= {MAX_LEVERAGE_HARD_CAP}x"),
            (0 < self.max_daily_drawdown <= 0.02, "max_daily_drawdown debe ser <= 2%"),
            (0.10 <= self.max_total_drawdown <= 0.15, "max_total_drawdown debe estar entre 10% y 15%"),
            (0 < self.conservative.size_multiplier <= 1, "conservative.size_multiplier debe estar en (0, 1]"),
            (0 < self.conservative.vol_quantile < 1, "conservative.vol_quantile debe estar en (0, 1)"),
            (0 < self.loss_streak.size_multiplier <= 1, "loss_streak.size_multiplier debe estar en (0, 1]"),
        ]
        errors = [msg for ok, msg in checks if not ok]
        if errors:
            raise ConfigError("; ".join(errors))


@dataclass(frozen=True)
class CostConfig:
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005


@dataclass(frozen=True)
class ExchangeConfig:
    id: str = "binance"
    market_type: Literal["spot", "future"] = "spot"
    sandbox: bool = True
    symbols: tuple[str, ...] = ("BTC/USDT",)
    timeframe: str = "15m"
    htf_timeframe: str = "4h"
    history_bars: int = 1500


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "mean_reversion"
    allow_short: bool = False
    params: dict[str, dict[str, Any]] = field(default_factory=dict)

    def active_params(self) -> dict[str, Any]:
        return dict(self.params.get(self.name, {}))


@dataclass(frozen=True)
class BacktestConfig:
    data_file: str = "data/BTCUSD_bitstamp_{timeframe}.csv.gz"
    initial_cash: float = 10_000.0
    in_sample: tuple[str, str | None] = ("2023-01-01", "2025-01-01")
    out_of_sample: tuple[str, str | None] = ("2025-01-01", None)


@dataclass(frozen=True)
class WalkForwardConfig:
    train_days: int = 90
    test_days: int = 30
    embargo_days: int = 1
    min_trades: int = 20
    objective: str = "sharpe"


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/tradebot.log"
    db: str = "tradebot.sqlite"


@dataclass(frozen=True)
class Settings:
    mode: Literal["paper", "live"] = "paper"
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    walk_forward: WalkForwardConfig = field(default_factory=WalkForwardConfig)
    telegram_enabled: bool = True
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _make(cls: type, data: dict[str, Any] | None, section: str) -> Any:
    data = dict(data or {})
    known = set(cls.__dataclass_fields__)
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"[{section}] claves desconocidas: {sorted(unknown)}")
    for k, v in data.items():
        if isinstance(v, list):
            data[k] = tuple(v)
    return cls(**data)


def load_settings(path: str | Path = "config/config.yaml") -> Settings:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text()) or {}
    risk_raw = dict(raw.get("risk") or {})
    risk = _make(RiskConfig, {
        **risk_raw,
        "conservative": _make(ConservativeConfig, risk_raw.get("conservative"), "risk.conservative"),
        "loss_streak": _make(LossStreakConfig, risk_raw.get("loss_streak"), "risk.loss_streak"),
    }, "risk")
    risk.validate()
    strategy_raw = dict(raw.get("strategy") or {})
    settings = Settings(
        mode=raw.get("mode", "paper"),
        exchange=_make(ExchangeConfig, raw.get("exchange"), "exchange"),
        strategy=StrategyConfig(name=strategy_raw.get("name", "mean_reversion"),
                                allow_short=bool(strategy_raw.get("allow_short", False)),
                                params=strategy_raw.get("params") or {}),
        risk=risk,
        costs=_make(CostConfig, raw.get("costs"), "costs"),
        backtest=_make(BacktestConfig, raw.get("backtest"), "backtest"),
        walk_forward=_make(WalkForwardConfig, raw.get("walk_forward"), "walk_forward"),
        telegram_enabled=bool((raw.get("telegram") or {}).get("enabled", True)),
        logging=_make(LoggingConfig, raw.get("logging"), "logging"),
    )
    if settings.mode not in ("paper", "live"):
        raise ConfigError("mode debe ser paper o live")
    if settings.risk.max_leverage > 1.0 and settings.exchange.market_type == "spot":
        raise ConfigError("spot no admite apalancamiento: usar max_leverage: 1.0 o market_type: future")
    if settings.strategy.allow_short and settings.exchange.market_type == "spot":
        raise ConfigError("allow_short requiere market_type: future")
    return settings
