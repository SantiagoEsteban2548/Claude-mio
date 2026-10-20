# Mercados argentinos: qué datos se pudieron conseguir y qué se midió

## Datos
Los dominios argentinos (BCRA, BYMA, Rava, Ámbito, Data912, ArgentinaDatos) y Yahoo/Stooq están bloqueados en el entorno; solo GitHub y PyPI son alcanzables. Se usaron dos repos públicos:

| Dataset | Contenido | Cobertura |
|---|---|---|
| [jonathancalb/dolar-argentina-historico](https://github.com/jonathancalb/dolar-argentina-historico) (CC BY 4.0, fuente Dólar Claro) | oficial, blue, MEP, CCL, mayorista, cripto, tarjeta — diario | 2011 → 2026-10-19 (MEP desde 2018, cripto desde mediados de 2023) |
| [isantolin/Historic_Merval_Scrap](https://github.com/isantolin/Historic_Merval_Scrap) (Stooq) | índice Merval OHLCV diario | 1988 → 2016-08 |

**No se consiguieron**: precios intradía de CEDEARs, acciones o bonos (AL30/GD30 y sus versiones D/C). Por eso no se pudo probar el lead-lag CEDEAR–subyacente ni el arbitraje de bonos.

## A) Merval 1992–2016 (`merval_and_fx.py`, `merval_momentum.py`); retornos nominales en pesos
Descubrimiento 1992–2008, holdout 2009–2016. Ojo: en 2009–2016 la inflación argentina fue alta, así que el buy & hold nominal (+44% anual) está inflado.

| Ensamble de tendencia diario (el mismo de BTC, costo 0,3%/lado) | Sharpe | CAGR | Caída máx. |
|---|---:|---:|---:|
| Descubrimiento: buy & hold | 0,24 | +1,9% | −77% |
| Descubrimiento: ensamble | 0,48 | +7,8% | **−40%** |
| Holdout: buy & hold | 1,27 | +43,8% | −42% |
| Holdout: ensamble | 1,22 | +29,0% | **−30%** |

Mismo patrón que en BTC: la tendencia reduce el drawdown y no agrega retorno sobre el buy & hold.

**Escáner de patrones** (49 hipótesis): 10 pasan FDR en descubrimiento, 5 sobreviven al holdout. Todos son el mismo efecto: **momentum diario de 1 a 3 días** (tras un día alcista, el siguiente rinde en exceso +17 pb en descubrimiento, t=3,7, y +12 pb en holdout, t=1,95; tras un día bajista, −18/−14 pb).
Es un efecto conocido en mercados poco líquidos (precios de cierre desactualizados e información que se difunde con retraso).

**¿Es operable?** Estrategia = signo del retorno de ayer; entrada en la apertura del día siguiente (variantes B y C), costos por lado de 5, 15 y 30 pb:

| | 5 pb/lado | 15 pb/lado | 30 pb/lado |
|---|---|---|---|
| Largo/corto, open→close | Sharpe 0,5–0,6 | ≈ −0,1 a −0,2 | −1,2 a −1,4 |
| Largo/flat, open→open (holdout) | Sharpe 1,38 | 0,82 | ≈ 0 |

El efecto existe, pero **solo sobrevive con costos ≤ 5 pb por lado**, y el rendimiento nominal (≈ 12–15% con largo/corto) es negativo en términos reales con la inflación del período. Con costos minoristas realistas (15–30 pb) no es operable.

## B) Brechas cambiarias (`merval_and_fx.py`)

| Brecha | Observaciones | Media | Mediana | P10 / P90 | Vida media del desvío |
|---|---:|---:|---:|---|---:|
| CCL / MEP − 1 (2019–2026) | 2.849 | +2,39% | +2,17% | −0,15% / +4,95% | ≈ 5 días (AR(1) = 0,86) |
| Cripto / MEP − 1 (2023-06 → 2026) | 1.237 | +3,44% | +2,92% | +0,70% / +6,41% | ≈ 7 días (AR(1) = 0,90) |

- Desde 2024, cripto/MEP supera 3% el **41%** de los días y CCL/MEP supera 3% el 33%.
- **Reversión a la media**: tras un z-score de 60 días > +2, la brecha CCL/MEP se achica en promedio **1,5 pp** en los siguientes 10 días (incondicional: +0,02 pp) y la brecha cripto/MEP **5,2 pp** (n = 58).

**Lo que NO se puede afirmar con estos datos**: que el arbitraje sea rentable. Son cotizaciones diarias de referencia, no precios ejecutables; la brecha existe justamente por fricciones (restricciones cruzadas, plazos de liquidación, topes y comisiones de brokers, bancos y exchanges, impuestos y encuadre legal).
Para saber si queda margen hay que sumar el costo real de cada tramo (ida y vuelta) y verificar la normativa vigente. No es asesoramiento financiero ni legal.
