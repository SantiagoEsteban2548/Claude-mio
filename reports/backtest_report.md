# Informe de backtesting

> Generado por `python scripts/run_matrix.py` con datos REALES de BTC/USD (Bitstamp, velas de 1 minuto
> resampleadas). Nada de este informe está estimado a mano. Riesgo de pérdida total: ver README.

## Configuración

- Datos: `data/BTCUSD_bitstamp_{5m,15m}.csv.gz`, 2023-01-01 → 2026-10-20.
- **In-sample (IS)**: 2023-01-01 → 2024-12-31. **Out-of-sample (OOS)**: 2025-01-01 → fin de datos.
  Los parámetros son los defaults de `config/config.yaml`, fijados ANTES de mirar resultados (no optimizados).
- Costos: comisión 0.10% + slippage 0.05% **por lado** (0.30% ida y vuelta).
- Riesgo (producción): 0.75% por trade, circuit breaker diario 2%, kill switch 12%, 1x, objetivo diario 0.5%.
- Variantes de diagnóstico (NO operables): `sin_cortes` quita breaker y kill switch; `sin_costos` además
  pone comisión y slippage en cero. Sirven para separar el edge de la estrategia del efecto de los costos.

## Variante: produccion

| estrategia | tf | período | retorno | prom. diario | max DD | Sharpe | Sortino | trades | win rate | PF | expectancy (R) | comisiones | slippage | buy&hold | kill switch |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| mean_reversion | 5m | IS | -11.91% | -0.017% | -11.91% | -2.51 | -0.66 | 88 | 27.3% | 0.10 | -0.37 | $1,140 | $570 | 464.9% | sí |
| mean_reversion | 5m | OOS | -11.91% | -0.019% | -11.91% | -2.28 | -0.58 | 84 | 28.6% | 0.16 | -0.40 | $1,129 | $564 | -12.7% | sí |
| mean_reversion | 15m | IS | -11.42% | -0.017% | -11.87% | -1.98 | -0.60 | 78 | 44.9% | 0.35 | -0.30 | $917 | $458 | 464.9% | sí |
| mean_reversion | 15m | OOS | -11.83% | -0.019% | -11.87% | -2.23 | -0.63 | 59 | 37.3% | 0.21 | -0.41 | $786 | $393 | -12.7% | sí |
| momentum_trend | 5m | IS | -11.96% | -0.017% | -11.96% | -2.05 | -0.62 | 87 | 35.6% | 0.39 | -0.33 | $1,084 | $542 | 464.9% | sí |
| momentum_trend | 5m | OOS | -11.79% | -0.019% | -11.85% | -1.86 | -0.80 | 54 | 31.5% | 0.25 | -0.44 | $785 | $392 | -12.7% | sí |
| momentum_trend | 15m | IS | -10.80% | -0.016% | -11.88% | -1.39 | -0.98 | 94 | 41.5% | 0.65 | -0.14 | $1,161 | $580 | 464.9% | sí |
| momentum_trend | 15m | OOS | -10.50% | -0.017% | -11.89% | -1.98 | -0.66 | 44 | 27.3% | 0.33 | -0.47 | $537 | $269 | -12.7% | sí |

## Variante: sin_cortes

| estrategia | tf | período | retorno | prom. diario | max DD | Sharpe | Sortino | trades | win rate | PF | expectancy (R) | comisiones | slippage | buy&hold | kill switch |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| mean_reversion | 5m | IS | -90.39% | -0.320% | -90.40% | -11.66 | -10.94 | 1332 | 24.0% | 0.10 | -0.44 | $7,499 | $3,748 | 464.9% | no |
| mean_reversion | 5m | OOS | -89.31% | -0.339% | -89.31% | -11.89 | -11.12 | 1140 | 17.5% | 0.06 | -0.50 | $7,069 | $3,533 | -12.7% | no |
| mean_reversion | 15m | IS | -50.76% | -0.097% | -51.01% | -5.11 | -3.33 | 374 | 43.3% | 0.27 | -0.35 | $3,746 | $1,872 | 464.9% | no |
| mean_reversion | 15m | OOS | -53.77% | -0.117% | -54.01% | -6.30 | -4.41 | 312 | 34.9% | 0.15 | -0.45 | $3,347 | $1,673 | -12.7% | no |
| momentum_trend | 5m | IS | -97.57% | -0.507% | -97.57% | -13.68 | -17.75 | 1978 | 33.5% | 0.33 | -0.39 | $8,039 | $4,017 | 464.9% | no |
| momentum_trend | 5m | OOS | -96.59% | -0.512% | -96.59% | -14.11 | -16.69 | 1542 | 27.9% | 0.20 | -0.49 | $6,746 | $3,371 | -12.7% | no |
| momentum_trend | 15m | IS | -57.90% | -0.118% | -59.19% | -4.29 | -6.49 | 700 | 39.1% | 0.64 | -0.20 | $6,356 | $3,176 | 464.9% | no |
| momentum_trend | 15m | OOS | -65.80% | -0.163% | -66.33% | -6.80 | -8.93 | 542 | 31.9% | 0.43 | -0.38 | $4,665 | $2,332 | -12.7% | no |

## Variante: sin_costos

| estrategia | tf | período | retorno | prom. diario | max DD | Sharpe | Sortino | trades | win rate | PF | expectancy (R) | comisiones | slippage | buy&hold | kill switch |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| mean_reversion | 5m | IS | 20.30% | 0.025% | -8.07% | 1.39 | 1.21 | 1332 | 53.9% | 1.13 | 0.07 | $0 | $0 | 464.9% | no |
| mean_reversion | 5m | OOS | 2.31% | 0.003% | -7.09% | 0.24 | 0.22 | 1140 | 52.0% | 1.02 | 0.03 | $0 | $0 | -12.7% | no |
| mean_reversion | 15m | IS | -2.03% | -0.003% | -12.32% | -0.16 | -0.11 | 374 | 48.7% | 0.97 | -0.02 | $0 | $0 | 464.9% | no |
| mean_reversion | 15m | OOS | -13.30% | -0.022% | -17.73% | -1.61 | -1.16 | 312 | 45.2% | 0.77 | -0.11 | $0 | $0 | -12.7% | no |
| momentum_trend | 5m | IS | 55.45% | 0.060% | -8.48% | 1.67 | 4.29 | 1978 | 35.8% | 1.13 | 0.08 | $0 | $0 | 464.9% | no |
| momentum_trend | 5m | OOS | -12.79% | -0.021% | -25.06% | -0.63 | -1.17 | 1542 | 33.1% | 0.94 | -0.02 | $0 | $0 | -12.7% | no |
| momentum_trend | 15m | IS | 55.98% | 0.061% | -6.21% | 1.78 | 4.00 | 700 | 39.4% | 1.22 | 0.16 | $0 | $0 | 464.9% | no |
| momentum_trend | 15m | OOS | -8.25% | -0.013% | -14.45% | -0.41 | -0.79 | 542 | 32.7% | 0.94 | -0.02 | $0 | $0 | -12.7% | no |

## Conclusiones (honestas)

1. **Ninguna de las 8 configuraciones de producción es rentable.** Todas pierden entre −10.5% y −12% y
   terminan detenidas por el kill switch, tanto en IS como en OOS. No hay que operarlas con dinero real.
2. **La gestión de riesgo funcionó como se diseñó.** Las mismas estrategias sin cortes pierden entre −50% y
   −97%. Con el overlay, la pérdida quedó acotada al ~12%, ningún día superó el límite de 2%, y la pérdida
   por operación quedó en ≈ −1R salvo gaps.
3. **El problema principal son los costos.** Sin comisiones ni slippage, momentum muestra un edge chico en
   IS (profit factor 1.13–1.22) y mean reversion 5m apenas 1.13. Fuera de muestra ese edge desaparece
   (PF 0.77–1.02). Con 0.30% de costo de ida y vuelta, y movimientos objetivo de 1–2 ATR de 5m/15m
   (~0.3–0.6% del precio), los costos se comen la mayor parte de cada operación.
4. **El objetivo de 0.5% diario no está al alcance de estas estrategias.** El mejor caso (momentum 15m,
   IS, sin costos) promedia 0.06% diario. 0.5% diario sostenido es ≈ 517% anual compuesto: si un backtest
   lo mostrara, lo más probable sería un error u overfitting, no un edge.
5. **Qué tendría que cambiar para que valga la pena seguir** (próximos pasos):
   - Bajar costos: órdenes limit/maker (comisión 0–0.02%), exchange con fees bajos, o timeframes más altos
     (1h–4h), donde los costos pesan mucho menos frente al movimiento.
   - Walk-forward optimization con embargo: cualquier mejora tiene que aparecer en OOS, no solo en IS.
   - Datos de ETH/USDT y de más exchanges cuando la red del entorno lo permita (hoy solo hay BTC/USD de Bitstamp).
