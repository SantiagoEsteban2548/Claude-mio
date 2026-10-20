# Ideas de "mercados poco competitivos" (conversación de Gemini) — qué se puede verificar y qué no

| Idea | ¿Verificable con los datos que tenemos? | Estado |
|---|---|---|
| Caza de mechas con stink bids (órdenes límite lejanas) | **Parcial**: solo BTC (1 min, 2018–2026); sin altcoins, OI ni funding por par | **probada**, ver abajo |
| Market making Avellaneda-Stoikov en libros delgados | No: requiere libro de órdenes (L2) y trades de un par ilíquido | pendiente de datos |
| Arbitraje de funding en pares secundarios / DEX | No: solo tenemos funding de BTC y ETH (2020–2023) | pendiente de datos |
| Pairs trading con filtro de Kalman en nichos | No: no hay series de pares de segundo orden | pendiente de datos |
| Lead-lag en activos dual-listed (CEDEARs/ADRs) | No: requiere feed del mercado local y del subyacente | pendiente de datos |
| Sniping en mercados no financieros (TCG, skins, predicción) | No: son mercados distintos, con APIs propias | fuera de alcance de los datos |

Las cifras de la conversación (spreads de 0,8–3%, mechas de 5–15%, anomalías de funding de 24–72 h) **no tienen fuente citada** y no se pudieron verificar.

## Prueba: stink bids en BTC (`stink_bids.py`)

Órdenes límite de compra a `close − k·ATR(60)` y de venta a `close + k·ATR` en velas de 1 minuto, salida por take-profit maker (reversión), stop de 3 ATR o 30 minutos. Costos maker 0,02% / taker 0,05% + 0,02% de slippage.
Descubrimiento 2018–2022, holdout 2023–2026-10; 12 configuraciones (k = 3, 4, 6; dos relaciones TP; largo y corto).

| | Descubrimiento 2018–22 | Holdout 2023–26 |
|---|---|---|
| Operaciones por día | 1,3 a 12,5 | 2,2 a 19,5 |
| Win rate | 47% a 76% | 39% a 54% |
| Profit factor | 0,96 a 1,15 | **0,33 a 0,57** |
| Resultado neto por operación | +3,4 a +7,8 bp (en las 12) | **−1,2 a −3,2 bp (en las 12)** |

- En 2018–22 había un edge pequeño (~+4 bp por operación, ≈ 0,04% diario a 1x). En 2023–26 desaparece y las 12 configuraciones pierden.
- Coherente con el resto de la investigación: los patrones de microestructura en BTC se agotan a medida que el mercado madura. Esto **no descarta** la idea en altcoins ilíquidas, donde las mechas son mucho mayores, pero ahí no hay datos para medirlo y el riesgo de hack/delisting es real.
