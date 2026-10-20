# Búsqueda de patrones explotables en BTC/USD (Bitstamp, 2023-01 → 2026-10)

Criterio de "explotable": se ve en IS (2023-24), se repite en OOS (2025-26) con p<0.10 tras desagrupar eventos y restar la deriva,
y deja un edge mayor al costo (≈14 bp taker / ≈4 bp maker, ida y vuelta). Scripts: `scan.py`, `validate.py`, `volatility.py`.

## 1. Patrones direccionales: ninguno sobrevive

| Familia | Hipótesis | Pasan FDR en IS | Sobreviven en OOS |
|---|---:|---:|---:|
| Calendario: hora UTC, día de semana, hora×día (1h) | 132 | 10 | **0** |
| Hora-minuto UTC en 15m → próxima hora | 192 | 4 | **0** (por azar se esperaban ~9 con \|t\|≥2) |
| Momentum/reversión (retornos pasados por percentil, 7 horizontes), compresión de volatilidad, picos de volumen, barras extremas, mechas, rachas, z-score | 144 | 62 | 18 en el escáner crudo → **0** tras corregir (ver abajo) |

**Los 18 "sobrevivientes" eran un espejismo estadístico**: los eventos se solapan (24 retornos horarios seguidos dentro de la misma ventana)
y 2023-24 fue un mercado alcista (+465%). Desagrupados (una operación por ventana de 24h), restada la deriva incondicional y con bootstrap por bloques:

| Patrón (largo 24h) | IS exceso / p | OOS exceso / p | OOS neto taker |
|---|---|---|---|
| 7d en el top 5% (continuación) | +92 bp / 0.017 | −17 bp / 0.57 | −31 bp |
| z168 > 2 (continuación) | +60 bp / 0.056 | +20 bp / 0.44 | +6 bp |
| 24h en el bottom 5% (rebote) | +9 bp / 0.74 | +15 bp / 0.64 | +2 bp |
| 72h en el bottom 5% (rebote) | +25 bp / 0.39 | +28 bp / 0.47 | +14 bp |
| 6h en el bottom 5% (rebote) | +7 bp / 0.65 | +7 bp / 0.77 | −7 bp |

Ninguno es significativo en OOS. El único con p<0.05 en IS (continuación tras 7d fuerte) cambia de signo en OOS.

## 2. Patrones estructurales: reales y estables, pero no son alfa direccional

- **Clustering de volatilidad**: autocorrelación de \|ret\| 1h = 0.27 (lag 1) y 0.13–0.17 (lag 24/168), igual en IS y OOS; la volatilidad futura 24h se predice con correlación 0.50–0.56. La dirección no (autocorr de retornos ≈ −0.02…+0.00).
- **Estacionalidad intradía**: perfil horario de volatilidad correlacionado 0.94 entre IS y OOS, y el de volumen 0.97. Más activo 13–17 UTC (1.2–1.6× la media); más tranquilo 04–06 y 10 UTC (~0.75×).
- **Fines de semana**: sábado y domingo tienen 0.57–0.77× la volatilidad de un día hábil, en ambos períodos.

## 3. ¿Se pueden explotar esos patrones estructurales con la estrategia que teníamos?

Momentum 1h + tendencia 4h (la mejor, con edge bruto PF ~1.12 OOS) filtrada por régimen, costos maker/taker, PF OOS:
sin filtro 1.00 · vol alta 0.93 · horas 13–17 UTC 1.06 (stop 3/TP 3) y 0.95 (stop 2/TP 4) · lun–vie 0.98/0.95 · vol alta + lun–vie 0.93/0.90.
**Ningún filtro mejora de forma consistente**. Volatility-targeting sobre BTC largo tampoco ayudó (Sharpe OOS −0.02 vs 0.04 sin escalar).

## Conclusión

Con velas OHLCV de BTC no encontré un patrón direccional explotable: lo que parece edge en IS es deriva alcista + solapamiento de eventos, y desaparece al corregir.
Los únicos patrones estables (volatilidad y su estacionalidad) son útiles para dimensionar riesgo y elegir cuándo ejecutar, pero no generan retorno por sí solos
y no alcanzaron para volver rentable la estrategia existente. Lo que queda por probar necesita datos que acá no hay: funding/basis, libro de órdenes,
liquidaciones, otros activos (cross-sectional) y otros exchanges.
