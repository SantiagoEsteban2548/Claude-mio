"""Sin look-ahead: la señal en t no puede cambiar si se agregan velas posteriores a t."""
import numpy as np
import pandas as pd
import pytest

from tradebot.data import htf_series
from tradebot.strategies import REGISTRY, build_strategy

from .conftest import make_bars


def random_walk(n: int = 3000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 30_000 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    return make_bars(list(closes), spread=20)


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_signals_do_not_depend_on_future_bars(name):
    df = random_walk()
    st = build_strategy(name, allow_short=True, vol_lookback=400)
    full = st.compute(df)
    cut = 2200
    partial = st.compute(df.iloc[:cut])
    pd.testing.assert_frame_equal(full.iloc[:cut], partial, check_freq=False)
    assert full.signal.abs().sum() > 0, "el test necesita al menos una señal para ser útil"


def test_htf_value_is_only_visible_after_htf_bar_closes():
    df = make_bars(list(range(1, 33)), start="2024-01-01 00:00", freq="15min")  # 8 horas
    s = htf_series(df, "1h", lambda h: h.close)
    # La vela 15m de 00:45 cierra a 01:00: recién ahí se conoce la vela 1h [00:00, 01:00), cuyo cierre es 4.
    assert np.isnan(s.loc["2024-01-01 00:30"])
    assert s.loc["2024-01-01 00:45"] == 4
    assert s.loc["2024-01-01 01:00"] == 4
    assert s.loc["2024-01-01 01:45"] == 8
