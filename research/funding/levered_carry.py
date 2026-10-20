"""Funding carry APALANCADO (nocional = K x capital) con funding real de Binance 2020-2023.

Modelo (deliberadamente simple, optimista en lo que NO modela):
  retorno diario sobre capital = K * funding_dia - (K-1) * costo_financiamiento_dia - costo_entrada/salida amortizado
Se asume colateral cruzado spot+perp (como en margen de cartera): la suba del precio gana en spot lo que pierde el perp corto.
NO modelado (y es donde ocurren las ruinas): riesgo de base spot/perp, liquidacion por cuenta, ADL, contraparte del exchange,
recortes (haircuts) del colateral y cambios de regla de funding.
"""
import numpy as np
import pandas as pd
from pathlib import Path

RAW = Path(__file__).parent / "raw"
ENTRY_EXIT = 0.0034          # ciclo completo de ida y vuelta (spot + perp), como en carry.py
rows = []


def funding(sym):
    f = next((RAW / f"{sym}-USDT").glob(f"{sym}-USDT_binance_*.csv"))
    s = pd.read_csv(f, parse_dates=["Date"]).set_index("Date")["Funding Rate"]
    return s.resample("1D").sum()


btc, eth = funding("BTC"), funding("ETH")
mix = (btc + eth) / 2
print("Retorno diario NETO sobre el capital, carry apalancado. Colateral cruzado; financiamiento sobre (K-1)·capital.")
print("(un solo ciclo de entrada/salida por período; no se modelan base, liquidación, ADL ni contraparte)\n")
for name, ser in (("BTC", btc), ("ETH", eth), ("50/50 BTC+ETH", mix)):
    print(f"== {name}")
    print("año  |  funding medio/día (1x) | " + " | ".join(f"K={k:>2d} (5%/11% fin.)" for k in (3, 5, 8, 10)))
    for y in (2020, 2021, 2022, 2023):
        x = ser[str(y)]
        cells = []
        for k in (3, 5, 8, 10):
            out = []
            for borrow_year in (0.05, 0.11):
                net = k * x - (k - 1) * borrow_year / 365 - ENTRY_EXIT / len(x)
                out.append(net.mean())
            cells.append(f"{out[0]:+.3%}/{out[1]:+.3%}")
        print(f"{y} |        {x.mean():.4%}          | " + " | ".join(f"{c:>17s}" for c in cells))
    # detalle K=8 y K=10 con financiamiento 5%: dias >= 0.7%, peor mes, caida maxima
    for k in (8, 10):
        net = k * ser - (k - 1) * 0.05 / 365
        eq = (1 + net).cumprod()
        worst_30 = net.rolling(30).sum().min()
        print(f"   K={k} (fin. 5%): días ≥0,7% = {(net >= 0.007).mean():.0%} | peor ventana de 30 días {worst_30:+.1%} | "
              f"caída máxima del P&L {(eq / eq.cummax() - 1).min():.1%} | retorno medio diario {net.mean():+.3%} "
              f"(2020-23), mediana final {eq.iloc[-1]:.1f}x")
    print()
