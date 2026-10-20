from dataclasses import replace

import pytest

from tradebot.config import ConfigError, RiskConfig, load_settings


def test_default_yaml_loads_and_respects_limits():
    s = load_settings("config/config.yaml")
    assert 0.005 <= s.risk.risk_per_trade <= 0.01
    assert s.risk.max_daily_drawdown <= 0.02
    assert 0.10 <= s.risk.max_total_drawdown <= 0.15
    assert s.risk.max_leverage <= 3.0
    assert s.mode == "paper"


@pytest.mark.parametrize("field,value", [
    ("risk_per_trade", 0.02), ("risk_per_trade", 0.001), ("max_leverage", 3.5),
    ("max_daily_drawdown", 0.03), ("max_total_drawdown", 0.25), ("max_total_drawdown", 0.05),
])
def test_non_negotiable_limits_are_enforced(field, value):
    with pytest.raises(ConfigError):
        replace(RiskConfig(), **{field: value}).validate()


def test_unknown_keys_are_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("risk:\n  risk_per_trad: 0.01\n")
    with pytest.raises(ConfigError, match="desconocidas"):
        load_settings(p)


def test_spot_cannot_use_leverage_or_shorts(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("exchange:\n  market_type: spot\nrisk:\n  max_leverage: 2.0\n")
    with pytest.raises(ConfigError, match="apalancamiento"):
        load_settings(p)
    p.write_text("exchange:\n  market_type: spot\nstrategy:\n  allow_short: true\n")
    with pytest.raises(ConfigError, match="allow_short"):
        load_settings(p)
