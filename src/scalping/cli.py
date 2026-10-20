"""CLI del motor de scalping: download | research | oos | demo-synthetic."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import aiohttp
import numpy as np
import pandas as pd

from src.scalping import research as R
from src.scalping.data import download_symbol, load_cached
from src.scalping.engine import EngineCfg

DEFAULT_SYMBOLS = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT"


def _load(symbols: list[str], folder: Path) -> dict[str, pd.DataFrame]:
    return {s: load_cached(s, "5m", folder) for s in symbols}


async def _download(symbols: list[str], start: date, end: date, folder: Path) -> None:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as sess:
        for s in symbols:
            df = await download_symbol(sess, s, "5m", start, end, folder)
            print(f"{s}: {len(df):,} barras {df.index[0]} -> {df.index[-1]}")


def _print_metrics(title: str, m: dict) -> None:
    print(f"\n== {title}")
    print(
        f"trades={m['trades']}  WR(3R)={m['win_rate']:.1%} [IC95 {m['wr_ci_low']:.1%}-{m['wr_ci_high']:.1%}]"
        f"  WR_breakeven={m['breakeven_wr']:.1%}"
    )
    print(
        f"expectativa={m['expectancy_r']:+.3f}R  t={m['t_stat']:.2f}  PF={m['profit_factor']:.2f}"
        f"  maxDD={m['max_dd_r']:.1f}R  trades/dia={m['trades_per_day']:.2f}"
        f"  ret/dia est.={m['est_daily_return']:.3%} (riesgo 0.5%/trade)"
    )


def cmd_research(a: argparse.Namespace) -> None:
    data = _load(a.symbols.split(","), Path(a.data_dir))
    out = R.research(data, EngineCfg())
    out["data_fingerprint"] = R.data_fingerprint(R.clip(data, None, R.OOS_START))
    out["created"] = R.stamp()
    rep = Path(a.reports_dir)
    R.write_json(rep / "research.json", out)
    R.write_json(
        rep / "frozen.json",
        {
            "config": out["frozen"],
            "engine": out["engine"],
            "configs_tested": out["configs_tested"],
            "created": out["created"],
        },
    )
    for f in out["walk_forward"]:
        _print_metrics(f"WF test {f['test_start']}..{f['test_end']}  cfg={f['config']}", f["test"])
    if out["walk_forward_pooled"]:
        _print_metrics(
            "WALK-FORWARD agregado (estimacion honesta dentro de 2021-2024)", out["walk_forward_pooled"]
        )
    _print_metrics(
        f"IN-SAMPLE de la config congelada ({out['configs_tested']} configs probadas: optimista)",
        out["frozen_in_sample"],
    )
    print(f"\nConfig congelada -> {rep / 'frozen.json'}  (el OOS NO fue tocado)")


def cmd_oos(a: argparse.Namespace) -> None:
    rep = Path(a.reports_dir)
    lock = rep / "oos_result.json"
    if lock.exists() and not a.force:
        sys.exit(f"OOS ya consumido ({lock}). Re-correrlo invalida la validacion; --force solo reproduce.")
    frozen = json.loads((rep / "frozen.json").read_text())
    data = _load(a.symbols.split(","), Path(a.data_dir))
    out = R.oos(data, frozen["config"], EngineCfg(**frozen["engine"]))
    out["created"] = R.stamp()
    if not lock.exists():
        R.write_json(lock, out)
    _print_metrics(f"OUT-OF-SAMPLE {out['oos_start']} -> fin  cfg={out['config']}", out["metrics"])
    for q, m in out["by_quarter"].items():
        print(f"  {q}: n={m['trades']:4d} WR={m['win_rate']:.1%} E={m['expectancy_r']:+.3f}R")
    print("\nVEREDICTO:", "CUMPLE" if out["verdict"]["pass"] else "NO CUMPLE", out["verdict"]["checks"])


def cmd_import_tv(a: argparse.Namespace) -> None:
    from src.scalping.tv import import_file

    q = import_file(a.file, a.symbol, a.data_dir, a.tz)
    print(f"{a.symbol}: {q.bars:,} barras 5m {q.start} -> {q.end}")
    print(
        f"  duplicadas={q.duplicates} OHLC invalidas={q.bad_ohlc} huecos={q.gaps} "
        f"(max {q.largest_gap_minutes:.0f} min) cobertura={q.coverage_pct:.1f}% vol0={q.zero_volume_pct:.1f}%"
    )
    print("  CALIDAD:", "OK" if q.ok else "REVISAR (cobertura < 98% o datos invalidos)")


def cmd_quality(a: argparse.Namespace) -> None:
    from src.scalping.tv import clean, quality

    for s in a.symbols.split(","):
        df, dups, bad = clean(load_cached(s, "5m", Path(a.data_dir)))
        q = quality(df, dups, bad)
        print(
            f"{s}: {q.bars:,} barras {q.start[:10]} -> {q.end[:10]}  huecos={q.gaps} "
            f"cobertura={q.coverage_pct:.1f}%  {'OK' if q.ok else 'REVISAR'}"
        )


def cmd_demo(a: argparse.Namespace) -> None:
    """Pipeline completo sobre caminata aleatoria SIN edge: debe dar NO CUMPLE (control negativo)."""
    from src.scalping.synthetic import random_walk

    folder, rep = Path(a.data_dir), Path(a.reports_dir)
    (rep / "oos_result.json").unlink(missing_ok=True)  # el demo siempre parte limpio
    print("*** DATOS SINTETICOS (random walk sin edge): valida la maquinaria, NO es evidencia de mercado ***")
    folder.mkdir(parents=True, exist_ok=True)
    syms = a.symbols.split(",")
    for i, s in enumerate(syms):
        random_walk(seed=i, start="2021-01-01", end="2026-06-30").to_pickle(folder / f"{s}_5m.pkl.gz")
    ns = argparse.Namespace(symbols=a.symbols, data_dir=a.data_dir, reports_dir=a.reports_dir, force=True)
    cmd_research(ns)
    cmd_oos(ns)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="scalping")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("download", "research", "oos", "demo", "import-tv", "quality"):
        p = sub.add_parser(name)
        p.add_argument("--symbols", default=DEFAULT_SYMBOLS)
        # el demo usa carpetas propias para no pisar datos ni reportes reales
        p.add_argument("--data-dir", default="data/synthetic" if name == "demo" else "data/crypto")
        p.add_argument("--reports-dir", default="reports/synthetic" if name == "demo" else "reports")
        if name == "download":
            p.add_argument("--start", default="2021-01-01")
            p.add_argument("--end", default=str(date.today()))
        if name == "import-tv":
            p.add_argument("--file", required=True)
            p.add_argument("--symbol", required=True)
            p.add_argument("--tz", default="UTC", help="zona del grafico si el CSV trae hora sin offset")
        if name == "oos":
            p.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "download":
        asyncio.run(
            _download(
                a.symbols.split(","), date.fromisoformat(a.start), date.fromisoformat(a.end), Path(a.data_dir)
            )
        )
    elif a.cmd == "research":
        cmd_research(a)
    elif a.cmd == "oos":
        cmd_oos(a)
    elif a.cmd == "import-tv":
        cmd_import_tv(a)
    elif a.cmd == "quality":
        cmd_quality(a)
    else:
        cmd_demo(a)


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
