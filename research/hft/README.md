# ¿Existe una vía hacia ≥0,7% diario con procesos repetitivos (HFT / scalping / intradía)?

> Nota de método: el workflow `deep-research` (verificación 3-0 por afirmación) no pudo ejecutarse porque el clasificador del servidor falló
> repetidamente. Esta investigación se hizo con búsquedas directas; cada fuente se etiqueta por calidad. Lo que no se pudo verificar está marcado.
> Pendiente: ejecutar `feasibility.py` (sección 4, Monte Carlo) y calcular el Sharpe real del funding carry; Bash no estuvo disponible en este tramo.

## 1. La matemática: de dónde podría salir 0,7% diario

0,7% diario = 365·ln(1,007) = **2,55 de crecimiento logarítmico anual** (≈12,6x/año).

**Kelly.** Con retornos de Sharpe anual S y apalancamiento L, el crecimiento esperado es g(L) = L·μ − L²·σ²/2, máximo en L* = μ/σ², donde g* = S²/2 por año.
Solo existen tres formas de llegar a 2,55:

| Apalancamiento | Sharpe anual necesario | Qué implica |
|---|---:|---|
| Kelly completo (L = L*) | **2,26** | caídas típicas > 50%; cualquier error de estimación del edge lleva a crecimiento negativo |
| Medio Kelly (L = L*/2, 75% del crecimiento óptimo) | 2,61 | caídas típicas ~35–40% |
| Cuarto Kelly (44% del óptimo) | 3,41 | caídas ~20–25% |
| Sin apalancar (L = 1, vol anual 150%) | 2,4 | solo con activos muy volátiles y sobreexpuestos |

Pasarse de 2·L* da crecimiento **negativo** aunque el edge sea real: "apalancar sin límite" no es una opción matemática.
Por eso la pregunta útil no es el apalancamiento sino **¿hay algún proceso con Sharpe real ≥ 2,3 que admita apalancamiento ≈ Kelly?**

En lo que medimos nosotros: estrategias direccionales en velas de BTC → Sharpe real ≈ 0 a 1,3 (holdout), **sin** edge por encima de ~1,3. Funding carry → la serie es muy estable (caída máxima −0,3% a −1,8%) pero **no admite** el apalancamiento que Kelly pediría (sección 4).

## 2. Escala necesaria para un proceso de alta frecuencia

Si cada fill opera nocional = apalancamiento × capital, el edge **neto** por fill necesario para 0,7%/día es 70/(L·fills) bp:

| apalancamiento ↓ / fills por día → | 20 | 100 | 500 | 2.000 |
|---|---:|---:|---:|---:|
| x1 | 3,50 bp | 0,70 | 0,14 | 0,035 |
| x3 | 1,17 | 0,23 | 0,047 | 0,012 |
| x5 | 0,70 | 0,14 | 0,028 | 0,007 |
| x10 | 0,35 | 0,07 | 0,014 | 0,0035 |

Parece poco, pero el edge **bruto** debe cubrir la comisión de cada fill y el volumen que se genera es enorme (capital $10.000):

| Caso | Volumen por día | Comisión maker 2 bp | Comisión taker 5 bp |
|---|---:|---:|---:|
| x5, 100 fills | $5 M | $1.000 (10% del capital por día) | $2.500 (25%) |
| x5, 500 fills | $25 M | $5.000 (50%) | $12.500 (125%) |
| x10, 500 fills | $50 M | $10.000 (100%) | $25.000 (250%) |

Esto es lo que hacen las firmas de HFT: edge bruto minúsculo × rotación gigantesca, con **comisión cercana a cero o negativa (rebates)**. Con 2 bp de comisión maker estándar, hace falta un edge bruto
> 2 bp por fill, estable, en todo el volumen. Nuestros mejores edges medidos: reversión de 1h ≈ 3,9 bp **por operación completa** (~2 bp por fill) en 2023–24, decayendo a ≈0 en 2025–26.

## 3. Evidencia encontrada (calidad de cada fuente)

| Línea | Hallazgo | Calidad |
|---|---|---|
| **Market making** (Hummingbot) | No hay retornos diarios auditados. Una reseña cita una prueba de 7 días con $200 en Binance Spot: +$5,58 neto (~0,4%/día) y desbalance de inventario en un pico de volatilidad. Un paper de simulación ([arXiv 2204.13265](https://arxiv.org/pdf/2204.13265)) de 3 meses de BTC/USDT muestra grandes oscilaciones entre períodos. Sentimiento de usuarios: rentabilidad mixta, tras una curva de aprendizaje dura. | anécdota / simulación; [reseña](https://www.gncrypto.news/trading-bots/hummingbot-review/) |
| **Alfa de microestructura** | El desbalance del libro (OFI) predice el movimiento de muy corto plazo, y más desde que Binance cobra comisión (R² de 5% a 21,5%, [Springer](https://link.springer.com/chapter/10.1007/978-3-032-18109-1_13)), pero el movimiento predicho en 10 s suele ser < 10 bp con comisión de ~10 bp por lado ([análisis](https://towardsdatascience.com/price-impact-of-order-book-imbalance-in-cryptocurrency-markets-bf39695246f6/)), y un paper clásico encuentra que el valor esperado de la predicción [no supera spread + comisiones](https://arxiv.org/pdf/1610.00261). Un preprint 2026 ([arXiv 2602.00776](https://arxiv.org/pdf/2602.00776)) da OFI entre los mejores predictores, advirtiendo que latencia y posición en la cola son difíciles de simular. | papers (parcial); sin evidencia neta de fees |
| **Arbitraje** | Sobre cadena (DEX), [Bitquery](https://bitquery.io/investigations/crypto-arbitrage-69-cents) mide 139 M de operaciones y $95,8 M de ganancia: **69 centavos por operación**; en Ethereum el beneficio medio bajó de ~$320 (2021) a < $8 (2026); totales ≈ $180 M en 2024 y ≈ $159 M en 2025, concentrados en pocos días. Para CEX, las cifras "0,1–0,3% diario para retail" no tienen fuente primaria. | on-chain sólido (DEX); CEX = marketing sin fuente |
| **Vaults on-chain** | El vault de market making de Hyperliquid (HLP) tuvo ~3,7% anualizado en un registro de septiembre de 2026 y entre 10–35% anual en otras fuentes (inconsistentes); gana en mercados violentos comprando liquidaciones con descuento ([resumen](https://www.vaasblock.com/news/hyperliquid-hlp-vault-economics-perp-dex-2026/)). Los "leader vaults de 50–300%+" no tienen respaldo. | secundarias, inconsistentes |
| **Apalancamiento** | A 10x el colchón hasta la liquidación es ~9,5%; a 20x, ~4,5% ([Bybit](https://www.bybit.com/en/wiki/article/crypto-liquidation-explained-complete-trading-guide/)). La literatura formal sobre supervivencia de traders apalancados es escasa ([arXiv 2512.01112](https://arxiv.org/pdf/2512.01112)). | documentación del exchange |
| **Day trading retail** | [Chague, De-Losso y Giovannetti](https://www.financemagnates.com/forex/analysis/new-study-shows-just-how-unprofitable-day-trading-is/) (Brasil, ~20.000 day traders, 2013–2015): entre quienes siguieron más de 300 días, **97% perdió**; solo 0,5% ganó más que un sueldo inicial de cajero (US$ 54/día). Sin evidencia de aprendizaje. | estudio regulatorio (fuente secundaria) |

**No se encontró** ningún registro verificado (fondo, vault o trader) que sostenga ≥ 0,5–1% diario durante meses o años. Lo más alto con respaldo razonable es ~40% anual en backtest (AdaptiveTrend) y 10–35% anual en HLP.

## 4. Lo que medimos nosotros contra la frontera de Kelly

| Fuente de retorno | Sharpe real medido | ¿Admite apalancamiento ≈ Kelly? |
|---|---|---|
| Velas OHLCV de BTC: scalping 5m–1h | ≈ 0 neto | no hay edge que apalancar |
| Ensamble de tendencia diario | 1,26 (holdout) | no llega al Sharpe 2,26 necesario |
| Funding carry | pendiente de calcular sobre los datos (la serie es muy estable) | **no**: el perpetuo corto se liquida con subas de 19% en un día; el carry es delta-neutral pero exige margen y reposición, y tiene riesgo de base y de contraparte |

## 5. Qué cambiaría el panorama (y qué no)

1. **Datos L2/L3 + latencia baja + posición en la cola**: es donde está el alfa de microestructura. Requiere feeds de libro completo, colocation o VPS cercano al matching engine, y simuladores de cola. Costo y complejidad muy superiores a un bot retail.
2. **Comisión maker ≈ 0 o negativa**: sin eso, la sección 2 muestra que las comisiones consumen 10–250% del capital diario al volumen necesario. Los programas de market maker de los exchanges existen, pero **no pude verificar** las tablas de rebates vigentes; hay que consultarlas en cada exchange.
3. **Otros mercados/activos**: más pares reducen la correlación y suben el Sharpe agregado (con Sharpe individual bajo, diversificar entre N activos independientes lo multiplica por ~√N).
4. **Lo que no ayuda**: más apalancamiento sobre un edge inexistente (g(L) < 0 pasado 2·L*), martingalas/grid (el "winrate alto" es un perfil de ruina diferida) y señales de velas de 5m.

## Conclusión

No existe, en las fuentes revisadas ni en nuestras mediciones, un proceso repetitivo retail que sostenga ≥ 0,7% diario. La única ruta matemática es **Sharpe real ≥ ~2,3 más apalancamiento cercano a Kelly completo** (con caídas > 50%), o un **edge de microestructura minúsculo con comisión ≈ 0 y rotación enorme**. Ambas requieren infraestructura y datos que no tenemos, y ninguna tiene evidencia pública de sostenerse en retail.
