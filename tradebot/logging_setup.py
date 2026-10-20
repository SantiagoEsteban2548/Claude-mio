from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level: str = "INFO", file: str | None = None) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    if file:
        Path(file).parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(file, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
