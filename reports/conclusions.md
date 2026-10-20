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
