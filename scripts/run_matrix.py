"""Corre la matriz de backtests reales y escribe reports/backtest_report.md.

Variantes:
  produccion   config tal cual (riesgo y costos reales)
  sin_cortes   DIAGNÓSTICO: sin circuit breaker ni kill switch (mide el edge crudo de la estrategia)
  sin_costos   DIAGNÓSTICO: sin cortes y sin comisiones/slippage (¿hay edge antes de costos?)
Las variantes de diagnóstico NO son configuraciones operables: violan los límites de riesgo a propósito.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tradebot.backtest import run_backtest  # noqa: E402
from tradebot.config import CostConfig, load_settings  # noqa: E402
from tradebot.data import load_csv  # noqa: E402
from tradebot.strategies import strategy_from_settings  # noqa: E402

STRATEGIES = ["mean_reversion", "momentum_trend"]
TIMEFRAMES = ["5m", "15m"]
PERIODS = ["is", "oos"]
VARIANTS = ["produccion", "sin_cortes", "sin_costos"]


def variant_settings(s, variant):
    if variant == "produccion":
        return s
    risk = replace(s.risk, max_daily_drawdown=1.0, max_total_drawdown=1.0, daily_profit_target=None)
    s = replace(s, risk=risk)
    if variant == "sin_costos":
        s = replace(s, costs=CostConfig(fee_rate=0.0, slippage_rate=0.0))
    return s


def job(args):
    name, tf, period, variant = args
    base = load_settings(ROOT / "config/config.yaml")
    s = variant_settings(base, variant)
    df = load_csv(ROOT / s.backtest.data_file.format(timeframe=tf))
    st = strategy_from_settings(s, name, timeframe=tf)
    start, end = (s.backtest.in_sample if period == "is" else s.backtest.out_of_sample)
    r = run_backtest(df, s, st, start=start, end=end)
    return {"strategy": name, "timeframe": tf, "period": period, "variant": variant, **r.metrics}


def main():
    jobs = [(n, tf, p, v) for n in STRATEGIES for tf in TIMEFRAMES for p in PERIODS for v in VARIANTS]
    with ProcessPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(job, jobs))
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "matrix.json").write_text(json.dumps(rows, indent=2, default=str))
    write_report(rows)
    print(f"{len(rows)} corridas -> reports/matrix.json, reports/backtest_report.md")


def pct(v, d=2):
    return f"{v * 100:.{d}f}%"


def write_report(rows):
    lines = [
        "# Informe de backtesting",
        "",
        "> Generado por `python scripts/run_matrix.py` con datos REALES de BTC/USD (Bitstamp, velas de 1 minuto",
        "> resampleadas). Nada de este informe está estimado a mano. Riesgo de pérdida total: ver README.",
        "",
        "## Configuración",
        "",
        "- Datos: `data/BTCUSD_bitstamp_{5m,15m}.csv.gz`, 2023-01-01 → 2026-10-20.",
        "- **In-sample (IS)**: 2023-01-01 → 2024-12-31. **Out-of-sample (OOS)**: 2025-01-01 → fin de datos.",
        "  Los parámetros son los defaults de `config/config.yaml`, fijados ANTES de mirar resultados (no optimizados).",
        "- Costos: comisión 0.10% + slippage 0.05% **por lado** (0.30% ida y vuelta).",
        "- Riesgo (producción): 0.75% por trade, circuit breaker diario 2%, kill switch 12%, 1x, objetivo diario 0.5%.",
        "- Variantes de diagnóstico (NO operables): `sin_cortes` quita breaker y kill switch; `sin_costos` además",
        "  pone comisión y slippage en cero. Sirven para separar el edge de la estrategia del efecto de los costos.",
        "",
    ]
    for variant in VARIANTS:
        lines += [f"## Variante: {variant}", "",
                  "| estrategia | tf | período | retorno | prom. diario | max DD | Sharpe | Sortino | trades | win rate"
                  " | PF | expectancy (R) | comisiones | slippage | buy&hold | kill switch |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for r in rows:
            if r["variant"] != variant:
                continue
            ks = "sí" if r["kill_switch"] != "no" else "no"
            lines.append(
                f"| {r['strategy']} | {r['timeframe']} | {r['period'].upper()} | {pct(r['total_return'])} | "
                f"{pct(r['avg_daily_return'], 3)} | {pct(r['max_drawdown'])} | {r['sharpe']:.2f} | {r['sortino']:.2f} | "
                f"{r['n_trades']} | {pct(r['win_rate'], 1)} | {r['profit_factor']:.2f} | {r['expectancy_r']:.2f} | "
                f"${r['fees_paid']:,.0f} | ${r['slippage_cost']:,.0f} | {pct(r['buy_hold_return'], 1)} | {ks} |")
        lines.append("")
    conclusions = ROOT / "reports/conclusions.md"
    if conclusions.exists():
        lines += [conclusions.read_text()]
    (ROOT / "reports/backtest_report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    if "--report-only" in sys.argv:
        write_report(json.loads((ROOT / "reports/matrix.json").read_text()))
    else:
        main()
