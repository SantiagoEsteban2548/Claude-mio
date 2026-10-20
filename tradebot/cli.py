"""CLI: python -m tradebot <comando>

  backtest   --strategy NAME --timeframe 15m --period is|oos|all [--params JSON] [--save]
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from . import metrics
from .backtest import run_backtest
from .config import Settings, load_settings
from .data import load_csv
from .logging_setup import setup_logging
from .strategies import strategy_from_settings

log = logging.getLogger("tradebot")


def period_bounds(settings: Settings, period: str) -> tuple[str | None, str | None]:
    b = settings.backtest
    return {"is": tuple(b.in_sample), "oos": tuple(b.out_of_sample),
            "all": (b.in_sample[0], b.out_of_sample[1])}[period]


def cmd_backtest(settings: Settings, a: argparse.Namespace) -> dict:
    tf = a.timeframe or settings.exchange.timeframe
    df = load_csv(settings.backtest.data_file.format(timeframe=tf))
    strat = strategy_from_settings(settings, a.strategy, json.loads(a.params) if a.params else None, tf)
    start, end = period_bounds(settings, a.period)
    log.info("backtest %s %s %s [%s, %s) params=%s", strat.name, tf, a.period, start, end, strat.params)
    r = run_backtest(df, settings, strat, start=start, end=end)
    out = {"strategy": strat.name, "timeframe": tf, "period": a.period, "params": strat.params,
           "metrics": r.metrics}
    if a.save:
        Path("reports/runs").mkdir(parents=True, exist_ok=True)
        stem = f"reports/runs/{strat.name}_{tf}_{a.period}"
        Path(f"{stem}.json").write_text(json.dumps(out, indent=2, default=str))
        r.trades.to_csv(f"{stem}_trades.csv", index=False)
        r.equity.to_csv(f"{stem}_equity.csv", header=["equity"])
    print(json.dumps({**out, "metrics": metrics.fmt(r.metrics)}, indent=2, ensure_ascii=False, default=str))
    return out


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="tradebot")
    ap.add_argument("--config", default="config/config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="backtest sobre datos históricos")
    b.add_argument("--strategy")
    b.add_argument("--timeframe")
    b.add_argument("--period", choices=["is", "oos", "all"], default="is")
    b.add_argument("--params", help="JSON que pisa los parámetros de la config")
    b.add_argument("--save", action="store_true", help="guarda métricas, trades y equity en reports/runs/")
    a = ap.parse_args(argv)
    settings = load_settings(a.config)
    setup_logging(settings.logging.level, settings.logging.file)
    if a.cmd == "backtest":
        cmd_backtest(settings, a)


if __name__ == "__main__":
    main()
