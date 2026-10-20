# Búsqueda de ≥0.7% diario (≈12.6x/año compuesto) en BTC real

Datos: BTC/USD Bitstamp 2023-01 → 2026-10. Parámetros elegidos **solo con IS (2023-24)**; se reporta OOS (2025-01 → fin).
Costos: taker 0.05% + slippage 0.02% por lado sobre el cambio de posición, funding 0.01%/8h (largos pagan, cortos cobran),
liquidación si el movimiento adverso intrabarra × apalancamiento ≥ 90%.
Scripts: `sweep.py` (480 combinaciones) y `ensemble.py` (32 ensambles). Resultados crudos en los `.csv`.

## Resultados

| Familia | Combinaciones | ≥0.7%/día IS | ≥0.7%/día OOS | Mejor IS (diario / DD) | Su resultado OOS | Techo OOS (con hindsight) |
|---|---:|---:|---:|---|---|---|
| Tendencia apalancada (EMA, Donchian, TSMOM; 1h/4h/1d; largo o largo-corto; 1x–10x) | 480 | 0 | 0 | 0.57% / −81% (4h Donchian20, 5x) | −0.52% / −99% | 0.05% (4h Donchian40 L/S, 1–2x) |
| Ensamble de 12 señales + volatility targeting (4h/1d; tope 1x–10x) | 32 | 0 | 0 | 0.08% / −42% | −0.00% / −48% | 0.02% |

- La mediana OOS por apalancamiento empeora al subir: 1x −0.06%, 3x −0.28%, 5x −0.62%, 10x −3.6% diario.
- Lo más cerca que se estuvo de 0.7% fue **in-sample con 5x y drawdown de −81% a −90%**, y se desploma OOS (−99%): es overfitting + apalancamiento.
- Incluso eligiendo la mejor configuración *mirando* el OOS (hindsight), el máximo es **0.05% diario**, 14 veces por debajo de la meta.

## Cota teórica: el Sharpe que haría falta

| Vol. anual de la cuenta | Sharpe necesario para 0.7%/día |
|---:|---:|
| 10% (DD ~12%) | 25.5 |
| 20% | 12.8 |
| 40% | 6.6 |
| 80% | 3.6 |
| 150% | 2.4 |

Con un drawdown tolerable de 10–15% (vol ~10%) se necesita un Sharpe ~25. Lo mejor documentado en las fuentes verificadas
(AdaptiveTrend, preprint) es Sharpe 2.4 con ~40% anual (≈0.09%/día). Para llegar a 0.7%/día con Sharpe 2.4 habría que
aceptar vol ~150% anual, es decir, drawdowns de 70–90% y probabilidad alta de ruina.

## Conclusión

Con velas OHLCV de BTC no existe, en lo que se pudo medir, una forma de alcanzar 0.7% diario respetando 10–15% de drawdown.
El apalancamiento no crea ventaja: multiplica pérdidas y comisiones. Lo realista con lo que hay es del orden de
0.03–0.09%/día con drawdowns de 12–25%, y eso todavía no está demostrado fuera de muestra con costos.
Quedan sin probar (por falta de datos/acceso de red en este entorno) arbitraje de funding/basis, cartera multi-par y
estrategias con libro de órdenes; ninguna tiene evidencia verificada de rendir 0.7%/día sostenido.
