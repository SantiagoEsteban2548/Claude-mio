"""Persistencia local en SQLite (modo WAL): libros/ticks, ordenes, fills, P&L y auditoria."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.models import BookLevel, Fill, Order, OrderBook, Settlement

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
    ts TEXT NOT NULL, symbol TEXT NOT NULL, settlement TEXT NOT NULL,
    bids TEXT NOT NULL, asks TEXT NOT NULL, last REAL, cum_volume REAL);
CREATE INDEX IF NOT EXISTS ix_books_ts ON books(ts);
CREATE TABLE IF NOT EXISTS orders(
    id TEXT PRIMARY KEY, ts TEXT, strategy TEXT, symbol TEXT, settlement TEXT, side TEXT,
    qty REAL, price REAL, status TEXT, filled_qty REAL, avg_price REAL, fee REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS fills(
    ts TEXT, order_id TEXT, strategy TEXT, symbol TEXT, settlement TEXT, side TEXT,
    qty REAL, price REAL, fee REAL);
CREATE TABLE IF NOT EXISTS pnl(
    ts TEXT, realized_net_ars REAL, unrealized_net_ars REAL, pct REAL);
CREATE TABLE IF NOT EXISTS audit(ts TEXT, kind TEXT, payload TEXT);
"""


class Store:
    def __init__(self, path: str = "data/bot.db", flush_every: int = 200) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._pending = 0
        self._flush_every = flush_every

    def _tick(self) -> None:
        self._pending += 1
        if self._pending >= self._flush_every:
            self.flush()

    def flush(self) -> None:
        self.conn.commit()
        self._pending = 0

    def close(self) -> None:
        self.flush()
        self.conn.close()

    def save_book(self, b: OrderBook) -> None:
        self.conn.execute(
            "INSERT INTO books VALUES (?,?,?,?,?,?,?)",
            (
                b.ts.isoformat(),
                b.symbol,
                b.settlement.value,
                json.dumps([[lv.price, lv.size] for lv in b.bids]),
                json.dumps([[lv.price, lv.size] for lv in b.asks]),
                b.last,
                b.cum_volume,
            ),
        )
        self._tick()

    def save_order(self, o: Order) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                o.id,
                o.ts.isoformat(),
                o.strategy,
                o.symbol,
                o.settlement.value,
                o.side.value,
                o.qty,
                o.price,
                o.status.value,
                o.filled_qty,
                o.avg_price,
                o.fee,
                o.reject_reason,
            ),
        )
        self._tick()

    def save_fill(self, f: Fill) -> None:
        self.conn.execute(
            "INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?)",
            (
                f.ts.isoformat(),
                f.order_id,
                f.strategy,
                f.symbol,
                f.settlement.value,
                f.side.value,
                f.qty,
                f.price,
                f.fee,
            ),
        )
        self._tick()

    def save_pnl(self, ts: datetime, realized: float, unrealized: float, pct: float) -> None:
        self.conn.execute("INSERT INTO pnl VALUES (?,?,?,?)", (ts.isoformat(), realized, unrealized, pct))
        self._tick()

    def audit(self, ts: datetime, kind: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO audit VALUES (?,?,?)", (ts.isoformat(), kind, json.dumps(payload, default=str))
        )
        self._tick()

    def iter_books(self) -> Iterator[OrderBook]:
        cur = self.conn.execute(
            "SELECT ts,symbol,settlement,bids,asks,last,cum_volume FROM books ORDER BY ts, rowid"
        )
        for ts, sym, st, bids, asks, last, vol in cur:
            yield OrderBook(
                symbol=sym,
                settlement=Settlement(st),
                bids=[BookLevel(price=p, size=s) for p, s in json.loads(bids)],
                asks=[BookLevel(price=p, size=s) for p, s in json.loads(asks)],
                ts=datetime.fromisoformat(ts),
                last=last,
                cum_volume=vol,
            )

    def count(self, table: str) -> int:
        if table not in {"books", "orders", "fills", "pnl", "audit"}:
            raise ValueError(table)
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
