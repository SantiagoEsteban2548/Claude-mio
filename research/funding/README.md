# Funding carry (cash-and-carry) con datos reales

Datos: funding real de perpetuos (Binance y otros 6 exchanges, BTC y ETH, 2020–2023) del repo público
[supervik/historical-funding-rates-fetcher](https://github.com/supervik/historical-funding-rates-fetcher) (`raw/`, con su licencia).
Los datos terminan el 2023-12-31: **no cubren 2024–2026**. Script: `carry.py`.

Estrategia: comprar spot y vender un perpetuo por el mismo nocional (delta-neutral). Se cobra el funding cuando es positivo y se paga cuando es negativo.
Costos: spot 0.10% + perp 0.05% + slippage 0.02% por lado, abrir y cerrar ambas patas (≈0.34% por ciclo). Capital = nocional spot + margen del perp (nocional/L).

## Es un patrón real, estable y de muy bajo riesgo

El funding de Binance fue positivo en el 78–97% de las liquidaciones de 8h (BTC y ETH; la excepción fue ETH 2022, 66%).

| Año | BTC anualizado | BTC % positivas | ETH anualizado | ETH % positivas |
|---|---:|---:|---:|---:|
| 2020 | 17.2% | 86% | 27.4% | 97% |
| 2021 | 30.6% | 93% | 37.5% | 96% |
| 2022 | 4.2% | 78% | 0.8% | 66% |
| 2023 | 7.9% | 90% | 8.3% | 91% |

## Pero el retorno es bajo y decae con el régimen

| Estrategia (neto de costos, sobre el capital total) | 2020–21 | 2022–23 |
|---|---:|---:|
| BTC carry permanente, margen x2 | +15.8%/año (+0.043%/día) | +3.9%/año (+0.011%/día) |
| ETH carry permanente, margen x2 | +21.5%/año (+0.059%/día) | +2.9%/año (+0.008%/día) |
| BTC carry condicional (solo si el funding de 3 días > 0) | +13.8%/año | +0.8%/año |
| ETH carry condicional | +20.8%/año | −1.1%/año |

- Caída máxima del P&L del carry: −0.3% a −1.8% (frente a −29% a −83% de las estrategias direccionales).
- El mejor día del que hay registro: BTC +0.51%, ETH +0.80%. Días con ≥0.7%: 0 de 1461 en BTC, 2 de 1461 en ETH. La mejor ventana de 30 días: +7.6% (BTC) y +9.6% (ETH).
- Filtrar por umbral de funding no ayuda: en 2022–23 queda casi todo el tiempo fuera de posición y el rendimiento cae a ≈0.

## Riesgos que el cálculo NO incluye

- **Liquidación del perpetuo corto**: BTC subió hasta +19% en 1 día, +31% en 3 días y +39% en 7 días (2020–2023). Con margen x3 hay que reponer margen dentro de ese rango; con x2 mucho antes. Requiere vigilar y mover capital entre spot y derivados.
- Riesgo de base (spot vs perp) al abrir y cerrar, riesgo de contraparte del exchange, cambios en las reglas de funding.
- Datos de 2024–2026 no disponibles aquí: no se sabe cómo se comportó el funding en el último ciclo.

## Conclusión

El carry de funding es el patrón más "explotable" de los encontrados en el sentido de rendimiento con riesgo muy bajo: del orden de 4%–22% anual,
es decir 0.01%–0.06% diario. Mucho menos que el 0.7% diario buscado (≈12 veces/año), que no aparece en ninguna parte de los datos.

## Carry apalancado (`levered_carry.py`)

Con colateral cruzado, el nocional del carry puede ser K veces el capital (retorno = K·funding − (K−1)·costo de financiamiento). Resultados en `../hft/README.md` §6:
**≥ 0,7% diario solo en 2021 con K ≈ 8–10** (BTC+ETH: +0,65% a +0,81%); 2020 +0,39–0,49%; 2022 negativo; 2023 ≈ +0,1%. Promedio 2020–23 con K = 8–10: +0,27% a +0,34% diario, caída máxima del P&L −17% a −21%.
No incluye riesgo de base, liquidación de cuenta, ADL ni contraparte, y no hay datos de funding posteriores a 2023-12-31.
