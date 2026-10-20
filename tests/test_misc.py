from datetime import date

from rich.console import Console

from src.backtest.runner import run_backtest
from src.backtest.synthetic import generate
from src.config.settings import Settings
from src.core.clock import settlement_calendar_days
from src.execution.paper import PaperBroker
from src.main import build_engine
from src.storage.db import Store
from src.ui.dashboard import render
from tests.helpers import mk_book, t


def test_settlement_days_over_weekend_and_holiday() -> None:
    assert settlement_calendar_days(date(2026, 10, 20)) == 1  # martes
    assert settlement_calendar_days(date(2026, 10, 23)) == 3  # viernes -> lunes
    assert settlement_calendar_days(date(2026, 10, 23), [date(2026, 10, 26)]) == 4


def test_store_roundtrip_wal(tmp_path) -> None:
    s = Store(str(tmp_path / "x.db"))
    assert s.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    s.save_book(mk_book("AL30", 100, 101, t(12, 0), last=100.5, vol=10))
    s.flush()
    (b,) = list(s.iter_books())
    assert b.symbol == "AL30" and b.best_ask.price == 101 and b.cum_volume == 10
    s.close()


async def test_synthetic_backtest_smoke_and_ui_render() -> None:
    s = Settings(_env_file=None)
    engine = build_engine(s, PaperBroker(s.fee_engine(), {"AL30": 1e9, "GD30": 1e9}), None)
    summary = await run_backtest(engine, generate(date(2026, 3, 2)))
    assert len(summary.days) == 1
    assert engine.risk.daily_pnl_pct > -s.kill_switch_dd_pct  # el kill-switch nunca debe saltarse
    console = Console(record=True, width=140, height=45)
    console.print(render(engine, [], "paper", s.target_daily_net))
    out = console.export_text()
    assert "P&L" in out and "Spreads" in out and "AL30" in out
