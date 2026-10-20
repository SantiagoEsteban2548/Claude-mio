import pandas as pd
import pytest

from tradebot import metrics


def test_known_equity_curve():
    idx = pd.date_range("2024-01-01", periods=11, freq="1D", tz="UTC")
    eq = pd.Series([10_000 * 1.005 ** i for i in range(11)], index=idx)
    trades = pd.DataFrame({"pnl": [100.0, -50.0, 30.0], "r": [1.0, -0.5, 0.3]})
    m = metrics.compute(eq, trades, 10_000 / 1.005, exposure=0.5, fees=1.0, slippage=0.5)
    assert m["avg_daily_return"] == pytest.approx(0.005)
    assert m["pct_days_target_hit"] == pytest.approx(1.0)
    assert m["max_drawdown"] == 0
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert m["profit_factor"] == pytest.approx(130 / 50)
    assert m["expectancy"] == pytest.approx(80 / 3)
