# Investigación: ¿cómo subir el win rate y el profit factor del scalping?

Datos reales BTC/USD (Bitstamp). Exploración **solo en in-sample (2023–2024)**; un único test **out-of-sample
(2025-01 → 2026-10)** con candidatos fijados antes de mirarlo. Simulador: `tradebot/fastsim.py` (validado contra
el motor backtrader: 3157 vs 3090 trades, PF 0.11 vs 0.09 en la misma config; es levemente optimista).
Laboratorio: `research/scalping/lab.py`.

Costos por lado: **taker** 0.05% + slippage 0.02%; **mixto** = entrada y TP con limit (maker 0.02%), SL taker;
**VIP** = maker 0%, taker 0.04%, slippage 0.01%. R = pérdida al stop incluyendo costos.

## 1. El win rate es casi pura geometría (y no sirve como objetivo)

MR 5m sin filtros, sin costos: sl/tp 1/1 → WR 51%, PF 1.05 · sl/tp 3/1 → WR 74%, PF 0.97 · sl/tp 1/2 → WR 36%, PF 1.12.
Subir el TP relativo al SL baja el WR, y bajarlo lo sube, pero el **PF queda en ~1: las señales crudas no tienen edge**.
Con un WR alto y sin edge, una pérdida se come varias ganancias. Hay que optimizar **PF/expectancy neta**.

## 2. Filtros (MR 5m, sl=tp=1.5 ATR, PF sin costos, IS; entre paréntesis 2023 / 2024)

| filtro | n | PF bruto | estable |
|---|---:|---:|---|
| ninguno | 5558 | 1.04 (1.07 / 1.01) | – |
| **tendencia 1h a favor** | 1830 | **1.14** (1.12 / 1.15) | **sí** |
| tendencia 4h a favor | 2367 | 1.11 (1.09 / 1.13) | sí |
| tendencia en contra | 3775 | 1.00 | – |
| ADX<20 / ADX>30 | 701 / 2862 | 1.06 / 1.02 | no |
| volatilidad alta / baja | 2496 / 3057 | 0.99 / 1.09 | no |
| volumen > 2x, RSI(3) extremo, desvío VWAP | ~4500–5000 | 1.03–1.05 | no |
| vela de confirmación | 5711 | 1.04 (1.00 / 1.08) | no |
| horario EEUU / Asia-Europa | 2100 / 2863 | 0.97 / 1.05 | no |

Solo **operar a favor de la tendencia del timeframe superior** aporta un edge consistente.

## 3. La matemática que manda: costo en R = costo ida y vuelta / distancia del stop

En 5m el stop típico es 0.2–0.4% del precio; un ida y vuelta taker cuesta ~0.14% → **0.35–0.7R por trade**.
Ningún filtro de velas da un edge bruto de ese tamaño (el mejor: +0.06R).

| config (IS) | stop | PF bruto | taker | mixto | VIP |
|---|---:|---:|---:|---:|---:|
| 5m MR+tend sl1.5/tp1.5 | 0.19% | 1.14 | 0.32 | 0.59 | 0.86 |
| 5m MR+tend sl3/tp3 | 0.39% | 1.13 | 0.54 | 0.76 | 0.95 |
| 15m MOM+tend sl3/tp3 | 0.78% | 1.06 | 0.75 | 0.86 | 0.96 |
| 1h MOM+tend sl2/tp4 | 1.15% | 1.18 | 1.01 | 1.07 | 1.13 |
| 1h MOM+tend sl3/tp3 | 1.73% | 1.17 | 0.98 | 1.08 | 1.14 |

Entradas limit más profundas (0.25–1 ATR) no mejoran de forma consistente, por selección adversa. Salir en la media de BB empeora.

## 4. Test out-of-sample (una sola vez)

| candidato | período | n | PF bruto | PF taker | PF mixto | PF VIP | WR mixto |
|---|---|---:|---:|---:|---:|---:|---:|
| C1 scalping 5m MR+tend1h sl3/tp3 | IS | 1275 | 1.13 | 0.54 | 0.76 | 0.95 | 52% |
| | **OOS** | 1166 | **0.96** | 0.43 | 0.60 | 0.75 | 46% |
| C2 1h MOM+tend4h sl2/tp4 | IS | 435 | 1.18 | 1.01 | 1.07 | 1.13 | 39% |
| | **OOS** | 450 | **1.14** | 0.92 | 0.98 | 1.05 | 37% |
| C3 1h MOM+tend4h sl3/tp3 | IS | 465 | 1.17 | 0.98 | 1.08 | 1.14 | 52% |
| | **OOS** | 474 | **1.12** | 0.94 | 1.00 | 1.06 | 51% |

## Conclusiones

1. **El scalping en 5m con velas OHLCV no tiene edge explotable:** el mejor edge bruto encontrado en IS
   desaparece fuera de muestra (PF 1.13 → 0.96), y aun con comisión maker 0% no cubre costos.
   Apalancar no lo arregla: con riesgo fijo por trade, más apalancamiento solo significa más nocional y más
   comisiones.
2. **Para subir el PF importan, en orden:** (a) un edge bruto real (lo único consistente fue operar a favor de la
   tendencia del timeframe superior); (b) stops grandes respecto del costo (timeframes más altos); (c) ejecución maker.
3. **Pista que sobrevive:** momentum + tendencia en 1h conserva el edge bruto fuera de muestra (PF 1.12–1.14), pero
   neto queda ≈ breakeven con costos maker realistas (0.98–1.00) y apenas positivo con fees VIP (1.05).
   No es operable todavía. Falta modelar fills maker reales (probabilidad de llenado) y validarlo con walk-forward.
4. Un scalping viable normalmente necesita datos que acá no hay (libro de órdenes, flujo de órdenes,
   funding/liquidaciones), latencia baja y rebates de maker.
