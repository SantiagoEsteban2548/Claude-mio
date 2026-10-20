import numpy as np
import pandas as pd
import pytest

from tradebot import trend_ensemble as te


def series(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D", tz="UTC"), dtype=float)


def test_target_exposure_is_causal():
    rng = np.random.default_rng(3)
    close = series(100 * np.exp(np.cumsum(rng.normal(0, 0.03, 600))))
    full = te.target_exposure(close)
    pd.testing.assert_series_equal(full.iloc[:400], te.target_exposure(close.iloc[:400]), check_freq=False)


def test_uptrend_is_fully_long_downtrend_flat():
    up, down = series(np.linspace(100, 400, 400)), series(np.linspace(400, 100, 400))
    assert te.target_exposure(up).iloc[-1] == 1.0
    assert te.target_exposure(down).iloc[-1] == 0.0


def test_position_uses_previous_close_and_costs_apply_on_changes_only():
    close = series(np.linspace(100, 400, 400))
    out = te.backtest(close, cost_per_side=0.001)
    assert out.exposure.iloc[0] == 0.0  # sin información previa no hay posición
    # exposición constante en 1.0 al final: sin rotación -> retorno neto == retorno del activo
    assert out.ret.iloc[-1] == pytest.approx(out.bh.iloc[-1])
    first_full = out.exposure[out.exposure > 0].index[0]
    step = out.exposure.diff().abs().loc[first_full]
    assert out.ret.loc[first_full] == pytest.approx(out.exposure.loc[first_full] * out.bh.loc[first_full] - step * 0.001)


def test_flat_in_downtrend_avoids_the_loss():
    close = series(np.r_[np.linspace(100, 300, 250), np.linspace(300, 60, 250)])
    out = te.backtest(close)
    assert te.summarize(out.ret)["max_drawdown"] > te.summarize(out.bh)["max_drawdown"] + 0.2
