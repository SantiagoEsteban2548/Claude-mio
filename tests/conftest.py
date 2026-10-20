from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from tradebot.config import ConservativeConfig, CostConfig, LossStreakConfig, RiskConfig, Settings


@pytest.fixture
def settings() -> Settings:
    risk = RiskConfig(risk_per_trade=0.01, max_leverage=1.0, max_daily_drawdown=0.02, max_total_drawdown=0.15,
                      daily_profit_target=None, conservative=ConservativeConfig(enabled=False),
                      loss_streak=LossStreakConfig(after_losses=99, size_multiplier=1.0))
    return replace(Settings(), risk=risk, costs=CostConfig(fee_rate=0.001, slippage_rate=0.0005))


def make_bars(closes: list[float], start: str = "2024-01-01", freq: str = "15min", spread: float = 0.5,
              ohlc: list[tuple[float, float, float, float]] | None = None) -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(ohlc or closes), freq=freq, tz="UTC")
    if ohlc is None:
        c = np.asarray(closes, float)
        o = np.r_[c[0], c[:-1]]
        ohlc = [(oo, max(oo, cc) + spread, min(oo, cc) - spread, cc) for oo, cc in zip(o, c)]
    df = pd.DataFrame(ohlc, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1.0
    return df


def make_signals(df: pd.DataFrame, entries: dict[int, int], atr: float = 10.0) -> pd.DataFrame:
    sig = pd.DataFrame({"signal": 0, "exit_long": False, "exit_short": False, "atr": atr, "high_vol": False},
                       index=df.index)
    for i, v in entries.items():
        sig.iloc[i, 0] = v
    return sig
