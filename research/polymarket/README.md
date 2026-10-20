# Mercados de predicción como "mercado poco competitivo": lead-lag spot → contratos BTC Up/Down de Polymarket

Datos: [marketlenstrade/polymarket-historical-data](https://github.com/marketlenstrade/polymarket-historical-data) (CC BY 4.0, atribución a Marketlens), carpeta `bitcoin-5m-15m-hourly-2026-06-15`:
408 contratos de un solo día (288 de 5 min, 96 de 15 min, 24 de 1 h) con snapshots del libro (bid/ask, ~13 por contrato de 5 min) y la cinta de trades de Binance como precio spot de referencia.
Scripts: `explore.py`, `leadlag.py` (los datos no se copian al repo; ver la ruta en los scripts).

Hipótesis (de la conversación de Gemini, "los mercados de predicción tardan segundos en reflejar el dato primario"): con el spot ya movido, el libro de un contrato Up/Down cotiza por debajo de su probabilidad justa
p = Φ(r / (σ·√τ)), con r = retorno del spot desde la apertura de la ventana y τ = segundos restantes.

## Hallazgos de estructura
- La cinta de Binance coincide con el ganador del contrato en el **97,6%** de las ventanas: sirve como proxy del precio de resolución.
- **Capacidad muy baja**: el volumen medio por contrato de 5 min es **$94** (ver tabla de volumen por serie en la salida de `explore.py`). Este es el sentido de "poco competitivo": hay poca competencia porque casi no hay dinero.
- Spread medio del libro: 3,1¢ en 5 min y 2,0¢ en 15 min.

## Resultado del lead-lag (resultado real de cada contrato; sin comisiones de la plataforma)

| Serie | Ejecución | Umbral | Trades (mercados) | P&L por acción | IC 95% (bootstrap por mercado) |
|---|---|---:|---:|---:|---|
| 5 min | mismo snapshot (optimista) | 0,00 | 1.672 (288) | −0,0044 | [−0,035; +0,027] |
| 5 min | snapshot siguiente (~20 s) | 0,00 | 1.647 (288) | −0,0213 | [−0,046; +0,002] |
| 5 min | siguiente | 0,10 | 650 (252) | −0,0234 | [−0,051; +0,004] |
| 15 min | mismo snapshot | 0,00 | 1.750 (96) | +0,0543 | [+0,008; +0,103] |
| 15 min | siguiente | 0,00 | 1.791 (96) | +0,0222 | [−0,009; +0,055] |
| 15 min | siguiente | 0,10 | 456 (88) | +0,0302 | [−0,016; +0,079] |

- **5 min: sin edge.** El libro ya refleja el movimiento del spot al ritmo de nuestros snapshots.
- **15 min: señal positiva pero débil**, significativa solo con ejecución optimista (sin latencia). Con ~20 s de retardo el intervalo incluye el cero.

## Límites de esta prueba (por qué NO es una conclusión)
- **Un solo día** y un solo régimen; los 96 contratos de 15 min comparten la misma jornada y sus resultados están correlacionados.
- Snapshots dispersos (~13 por contrato de 5 min): no se puede medir el rezago a escala de segundos; para eso hay que usar los `history-*-compact.parquet` (trades y deltas del libro).
- σ se estimó con todo el día (leve look-ahead); las comisiones de la plataforma y el costo del capital inmovilizado no están incluidos; se probaron 2 series × 8 configuraciones sin corrección por pruebas múltiples.
- Los archivos completos (otros días y series) requieren una clave de la API de Marketlens y acceso de red que este entorno no tiene.
