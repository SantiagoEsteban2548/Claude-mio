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

---

## 4. Segunda ronda: 14 años de historia (2014–2026) y un patrón que sí resiste

Las secciones anteriores usaban solo 2023–2026. El dataset de Bitstamp llega hasta 2012, así que se repitió la búsqueda con
**descubrimiento 2014–2022** (mercados alcistas, bajistas y laterales) y **holdout virgen 2023–2026-10** (`longhist.py`, `trend_ensemble.py`).

**Escáner diario** (65 hipótesis: día de semana, mes, fin/inicio de mes, retorno pasado a 14 horizontes, SMA, días extremos, régimen de volatilidad;
exceso sobre la deriva del período): 3 con |t|≥2 (el azar da ~3), **0 pasan FDR**. Pero todas las reglas de *tendencia* (precio sobre SMA20/50/100,
retorno pasado a 10–60 días > 0) tienen el mismo signo positivo en ambos períodos (+15 a +20 bp/día en exceso en descubrimiento, +3 a +9 en holdout).

**Estrategia derivada (reglas fijas, sin optimizar, `tradebot/trend_ensemble.py`)**: 8 votos de tendencia (SMA 20/50/100/200 y momentum 14/30/60/90 días),
exposición = votos/8, largo/flat, spot, 1x, costo 0.07% por lado sobre la rotación.

| Período | Estrategia | Sharpe | CAGR | Max DD | Beta | Alfa anual (t) |
|---|---|---:|---:|---:|---:|---:|
| Descubrimiento 2014–2022 | buy & hold | 0.84 | +40.9% | −83.4% | 1.00 | – |
| | **ensamble** | **1.34** | +68.3% | **−60.9%** | 0.49 | +32.6% (3.3) |
| Holdout 2023–2026-10 | buy & hold | 1.13 | +52.1% | −53.1% | 1.00 | – |
| | **ensamble** | **1.26** | +42.2% | **−28.7%** | 0.57 | +10.5% (1.1) |
| 2025-01 → 2026-10 | buy & hold | 0.04 | −7.3% | −53.1% | 1.00 | – |
| | **ensamble** | **0.38** | +6.1% | **−23.0%** | 0.36 | +7.8% (0.7) |

Robustez: menor drawdown que buy & hold en **12 de 13 años**; mayor Sharpe en 9 de 13; en ventanas móviles de 12 meses pierde dinero el 25% de las veces
(buy & hold 33%); quitar cualquier regla deja el Sharpe del holdout en 1.22–1.28; con costos ×3 queda en 1.16.

### Lectura honesta
- **Qué es**: persistencia de tendencia a horizonte diario en BTC. Reduce el drawdown a casi la mitad con Sharpe igual o mayor. Es un patrón de *gestión de riesgo*.
- **Qué no es**: no es una fuente de retorno alto. En el holdout rinde menos que comprar y mantener (+42% vs +52% anual) y equivale a ~0.10% diario, no 0.7%.
  El alfa del holdout (+10.5%/año) tiene el signo correcto pero **no es estadísticamente significativo** (t=1.1); el de descubrimiento sí (t=3.3).
- **Apalancarlo no ayuda a los límites de riesgo**: ×2 da +83% anual en el holdout pero con −52% de drawdown; ×3, −70%.
- Riesgos: rachas laterales con cruces falsos (2018, 2022 y 2024 tuvieron Sharpe peor que buy & hold en parte del año); el patrón depende de que BTC siga teniendo
  tendencias largas, algo que puede cambiar; datos de un solo exchange (Bitstamp).
