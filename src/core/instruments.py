"""Catalogo de instrumentos operables. Los LECAPs se agregan por configuracion."""

from __future__ import annotations

from src.core.models import AssetClass, Currency, Instrument


def _bond(symbol: str, ccy: Currency) -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.SOVEREIGN_BOND, currency=ccy, multiplier=0.01)


_CATALOG: dict[str, Instrument] = {
    **{s: _bond(s, Currency.ARS) for s in ("AL30", "GD30", "AL35", "GD35")},
    **{s: _bond(s, Currency.USD_MEP) for s in ("AL30D", "GD30D", "AL35D", "GD35D")},
    **{s: _bond(s, Currency.USD_CCL) for s in ("AL30C", "GD30C", "AL35C", "GD35C")},
    "GGAL": Instrument(symbol="GGAL", asset_class=AssetClass.EQUITY),
    "YPFD": Instrument(symbol="YPFD", asset_class=AssetClass.EQUITY),
    "PAMP": Instrument(symbol="PAMP", asset_class=AssetClass.EQUITY),
    "SPY": Instrument(symbol="SPY", asset_class=AssetClass.CEDEAR),
}


def lecap(symbol: str) -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.LECAP, currency=Currency.ARS, multiplier=0.01)


def future(symbol: str) -> Instrument:
    """Futuro de dolar Rofex: 1 contrato = 1000 USD, precio en ARS por USD."""
    return Instrument(
        symbol=symbol,
        asset_class=AssetClass.FUTURE,
        currency=Currency.ARS,
        multiplier=1000.0,
        market="ROFX",
        shortable=True,
    )


def register(inst: Instrument) -> None:
    _CATALOG[inst.symbol] = inst


def get_instrument(symbol: str) -> Instrument:
    if symbol in _CATALOG:
        return _CATALOG[symbol]
    if symbol.startswith(("DLR/", "DLR ")):
        inst = future(symbol)
        _CATALOG[symbol] = inst
        return inst
    raise KeyError(f"Instrumento desconocido: {symbol}. Registralo con instruments.register().")
