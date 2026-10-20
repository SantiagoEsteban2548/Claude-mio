"""TUI en vivo con rich: P&L neto, progreso a la meta, spreads, ordenes/posiciones y latencia."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.connectors.base import MarketConnector
from src.core.clock import now_art, to_art
from src.core.models import Side
from src.execution.engine import TradingEngine
from src.fee_engine.benchmark import daily_prorated, target_progress


def _pct(x: float | None, digits: int = 3) -> str:
    return "n/d" if x is None else f"{x * 100:+.{digits}f}%"


def _bar(progress: float, width: int = 30) -> Text:
    clamped = max(0.0, min(1.0, progress))
    filled = int(clamped * width)
    color = "green" if progress >= 1 else "yellow" if progress > 0 else "red"
    t = Text("█" * filled, style=color)
    t.append("░" * (width - filled), style="dim")
    t.append(f" {progress * 100:5.0f}%")
    return t


def header(engine: TradingEngine, mode: str) -> Panel:
    ph = engine.risk.phase(now_art())
    kill = engine.risk.kill_switch
    txt = Text()
    txt.append(f" MODO {mode.upper()} ", style="bold white on blue")
    txt.append(f"  {to_art(now_art()):%Y-%m-%d %H:%M:%S} ART  fase: {ph.value}  ")
    if kill:
        txt.append(f" KILL-SWITCH: {engine.risk.kill_reason} ", style="bold white on red")
    return Panel(txt, style="red" if kill else "blue")


def pnl_panel(engine: TradingEngine, target: float) -> Panel:
    r = engine.risk
    pct = r.daily_pnl_pct
    days = 1
    hurdle = daily_prorated(engine.state.caucion_colocadora_tna, days)
    t = Table.grid(padding=(0, 2))
    style = "green" if pct >= 0 else "red"
    t.add_row("P&L neto dia", Text(f"{pct * 100:+.3f}%  (ARS {r.daily_pnl_ars:+,.0f})", style=style))
    t.add_row("Meta diaria", f"{target * 100:.2f}%")
    t.add_row("Progreso", _bar(target_progress(pct, target)))
    t.add_row("Caucion 1d (hurdle)", _pct(hurdle))
    t.add_row("Exceso vs caucion", _pct(pct - hurdle))
    usd = None
    if engine.mep_open and engine.mep_last:
        usd = (1 + pct) / (engine.mep_last / engine.mep_open) - 1
    t.add_row("Retorno USD MEP", _pct(usd))
    t.add_row("Realizado / No realiz.", f"{engine.realized_net_ars:+,.0f} / {r.unrealized_net_ars:+,.0f}")
    t.add_row("Operaciones (fills)", str(engine.trades))
    t.add_row("Drawdown limite", f"-{r.cfg.kill_switch_dd_pct * 100:.2f}%")
    return Panel(t, title="P&L", border_style=style)


def spreads_panel(engine: TradingEngine, limit: int = 14) -> Panel:
    t = Table(expand=True, show_edge=False)
    for c in ("Especie", "Plazo", "Bid", "Ask", "Spread", "Edad"):
        t.add_column(c, justify="right" if c != "Especie" else "left")
    now = now_art()
    for (sym, st), b in sorted(engine.state.books.items(), key=lambda kv: (kv[0][0], kv[0][1].value))[:limit]:
        bb, ba = b.best_bid, b.best_ask
        t.add_row(
            sym,
            st.value,
            f"{bb.price:,.2f}" if bb else "-",
            f"{ba.price:,.2f}" if ba else "-",
            _pct(b.spread_pct, 2),
            f"{engine.state.age(b, now):.0f}s",
        )
    return Panel(t, title="Spreads", border_style="cyan")


def orders_panel(engine: TradingEngine) -> Panel:
    t = Table(expand=True, show_edge=False)
    for c in ("Estrategia", "Especie", "Qty", "PPC", "P&L"):
        t.add_column(c)
    unreal = engine.positions.unrealized(engine.state.books)
    for p in engine.positions.open_positions():
        t.add_row(
            p.strategy,
            f"{p.symbol} {p.settlement.value}",
            f"{p.qty:+,.0f}",
            f"{p.avg_price:,.2f}",
            f"{unreal.get(p.key, 0.0):+,.0f}",
        )
    for o in engine.broker.open_orders():
        t.add_row(
            o.strategy,
            f"{o.symbol} {o.settlement.value}",
            f"{'+' if o.side is Side.BUY else '-'}{o.qty:,.0f}",
            f"{o.price:,.2f}",
            "orden abierta",
        )
    return Panel(t, title="Posiciones y ordenes activas", border_style="magenta")


def latency_panel(connectors: Sequence[MarketConnector]) -> Panel:
    t = Table.grid(padding=(0, 2))
    if not connectors:
        t.add_row("sin conectores", "")
    for c in connectors:
        last, avg = c.latency.last_ms, c.latency.avg_ms
        t.add_row(c.name, "n/d" if last is None or avg is None else f"{last:.0f} ms (prom {avg:.0f})")
    return Panel(t, title="Latencia API", border_style="yellow")


def events_panel(engine: TradingEngine) -> Panel:
    rej = ", ".join(f"{k}: {v}" for k, v in sorted(engine.rejections.items(), key=lambda kv: -kv[1])[:4])
    lines = [Text(e) for e in list(engine.events)[-9:]] + [Text(f"Rechazos: {rej or '-'}", style="dim")]
    return Panel(Group(*lines), title="Eventos", border_style="white")


def render(
    engine: TradingEngine, connectors: Sequence[MarketConnector], mode: str, target: float
) -> RenderableType:
    layout = Layout()
    layout.split_column(Layout(header(engine, mode), size=3), Layout(name="body"))
    layout["body"].split_row(Layout(name="left"), Layout(name="right"))
    layout["left"].split_column(
        Layout(pnl_panel(engine, target), size=13),
        Layout(latency_panel(connectors), size=5),
        Layout(events_panel(engine)),
    )
    layout["right"].split_column(Layout(spreads_panel(engine)), Layout(orders_panel(engine), size=10))
    return layout
