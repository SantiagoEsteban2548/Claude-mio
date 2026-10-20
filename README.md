# tradebot

Bot de trading automatizado en Python para crypto (BTC/USDT, ETH/USDT). Busca un retorno neto de
**~0.5% diario como objetivo**, pero **la prioridad es preservar el capital**: la capa de riesgo manda
sobre la estrategia.

> ## ⚠️ Advertencia
> **Operar con criptomonedas, y más con apalancamiento, conlleva riesgo de pérdida TOTAL del capital.**
> Este software es experimental y se entrega sin garantía de ningún tipo. Ningún resultado pasado ni
> ningún backtest garantiza resultados futuros. **Los backtests actuales (ver
> [`reports/backtest_report.md`](reports/backtest_report.md)) muestran que las estrategias incluidas
> PIERDEN dinero después de costos.** No operes con dinero real algo que no entiendas y que no hayas
> validado vos mismo, y nunca arriesgues dinero que no puedas perder.
>
> Sobre el objetivo: 0.5% diario sostenido equivale a ≈ 517% anual compuesto. Es una meta extremadamente
> ambiciosa que casi ningún operador profesional sostiene. El bot la usa solo como tope ("si llegué, no
> abro más posiciones hoy"), no como algo a forzar.

## Estado actual

| Componente | Estado |
|---|---|
| Estructura, config YAML validada, logging | ✅ |
| Estrategias: mean reversion (BB + RSI) y momentum (breakout), con filtro de tendencia HTF | ✅ |
| Gestión de riesgo (fixed fractional / Kelly fraccional, breaker diario, kill switch, modo conservador) | ✅ |
| Motor de backtesting (backtrader) con comisiones, slippage y stops intrabar | ✅ |
| Tests unitarios (33) | ✅ |
| Backtests reales IS/OOS + informe | ✅ — **resultado: no rentable después de costos** |
| Walk-forward optimization | ⏳ próximo paso |
| Paper / live trading vía ccxt, reconexión automática | ⏳ próximo paso |
| Telegram / FastAPI de monitoreo | ⏳ próximo paso |

## Instalación

Requiere Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # incluye TA-Lib (wheels binarios desde 0.5), backtrader y ccxt
cp .env.example .env                     # secretos: solo acá, nunca en el YAML ni en el código
python -m pytest -q
```

## Uso

```bash
# Backtest con la config (estrategia/timeframe de config/config.yaml)
python -m tradebot backtest --period is            # in-sample
python -m tradebot backtest --period oos           # out-of-sample
python -m tradebot backtest --strategy momentum_trend --timeframe 5m --period all --save

# Pisar parámetros sin tocar el YAML
python -m tradebot backtest --params '{"sl_atr": 2.0, "tp_atr": 3.0}'

# Regenerar la matriz completa y el informe (≈4 min con 4 núcleos)
python scripts/run_matrix.py
```

`--save` deja métricas, trades y la curva de equity en `reports/runs/`.

### Datos

`data/` trae velas reales de BTC/USD de Bitstamp (5m, 15m y 1h, desde 2023), derivadas del dataset público de
1 minuto [ff137/bitstamp-btcusd-minute-data](https://github.com/ff137/bitstamp-btcusd-minute-data)
(CC BY-SA 4.0). Para regenerarlas: `python scripts/prepare_data.py <clone> --since 2023-01-01`.
Todavía no hay ETH/USDT: el entorno donde se construyó no tenía acceso de red a los exchanges.

## Configuración

Todo está en [`config/config.yaml`](config/config.yaml), comentado. Los límites no negociables se validan al
cargar, y la config se rechaza si:

- `risk_per_trade` está fuera de 0.5%–1%;
- `max_daily_drawdown` es mayor que 2%;
- `max_total_drawdown` está fuera de 10%–15%;
- `max_leverage` supera 3x, o es mayor que 1x en spot;
- hay shorts en spot, o aparecen claves desconocidas (para atrapar typos).

## Cómo decide el bot

1. **Señal** (al cierre de cada vela; se ejecuta en la apertura de la siguiente, sin look-ahead):
   - `mean_reversion`: cierre bajo la banda inferior de Bollinger, RSI < 30 y tendencia alcista en 4h
     (cierre 4h > EMA50 4h). Sale al volver a la media, o por SL/TP en ATR, o por tiempo.
   - `momentum_trend`: cierre sobre el máximo de las N velas previas con tendencia 4h alcista. Sale si la
     tendencia se da vuelta, o por SL/TP en ATR, o por tiempo.
   - Shorts simétricos, solo con `allow_short: true` y futuros.
   - El timeframe superior solo se usa cuando su vela ya cerró (hay un test para esto).
2. **Riesgo** ([`tradebot/risk.py`](tradebot/risk.py)):
   - Tamaño = equity × riesgo / distancia al stop (fixed fractional), o Kelly fraccional acotado.
     El nocional queda limitado a equity × `max_leverage`.
   - **Modo conservador**: si el ATR% supera su percentil 80 de los últimos 30 días, el riesgo se reduce a la mitad.
   - **Racha de pérdidas**: tras 3 pérdidas seguidas, la mitad del tamaño hasta la próxima ganancia.
   - **Presupuesto**: una operación nueva nunca arriesga más que lo que queda del límite diario y del total.
   - **Circuit breaker diario** (2%): cierra todo y no opera hasta el día UTC siguiente.
   - **Kill switch** (12%): cierra todo y no opera más; requiere reinicio manual.
   - **Objetivo diario** (0.5%): al alcanzarlo, no abre posiciones nuevas ese día.
3. **Ejecución en backtest**: bracket SL/TP evaluado intrabar, incluso en la misma vela de entrada (se corrigió
   un comportamiento de backtrader que lo posponía una vela). Si SL y TP caen en la misma vela, se asume el
   peor caso. Los gaps se llenan a la apertura.

## Estructura

```
config/config.yaml          configuración (sin secretos)
.env.example                plantilla de secretos (API keys de testnet/live, Telegram)
tradebot/
  config.py                 carga + validación de límites
  data.py                   carga/validación de OHLCV y alineación causal multi-timeframe
  indicators.py             TA-Lib
  strategies/               base (contrato), mean_reversion, momentum_trend
  risk.py                   RiskManager (compartido por backtest y live)
  backtest/engine.py        motor backtrader + broker con stops en la vela de entrada
  metrics.py                Sharpe, Sortino, max DD, PF, win rate, expectancy, % días con objetivo...
  cli.py                    python -m tradebot ...
scripts/prepare_data.py     genera data/ desde el dataset de Bitstamp
scripts/run_matrix.py       corre todos los backtests y escribe reports/backtest_report.md
tests/                      config, causalidad, motor (casos con respuesta conocida), riesgo, métricas
reports/                    informe de backtesting y conclusiones
research/                   notas de una tarea anterior (análisis de @fidetolabs), no las usa el bot
```
