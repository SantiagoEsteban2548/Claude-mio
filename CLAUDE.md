# CLAUDE.md — Bot cuantitativo BYMA / Matba Rofex

Bot asíncrono (Python 3.11+) para mercado argentino. Meta operativa: **> 0.4 % neto diario** con kill-switch en **-0.8 %**.
La meta es un objetivo de diseño, **no una garantía**: ver "Límites conocidos".

## Comandos

```bash
pip install -e ".[dev]"                 # dependencias (aiohttp, pydantic v2, rich + pytest/ruff/mypy)
python -m pytest -q                     # tests (48)
ruff check . && ruff format --check .   # lint / formato
python -m mypy src                      # tipado estático

python -m src.main --mode backtest --synthetic-days 3   # humo con datos sintéticos
python -m src.main --mode backtest --db data/bot.db     # backtest sobre libros grabados
python -m src.main --mode paper                         # tiempo real, matching simulado, graba libros
python -m src.main --mode paper --no-ui                 # sin TUI (logs)
python -m src.main --mode live                          # órdenes reales; pide escribir "OPERAR EN REAL"
```

Configuración por variables `BOT_*` o `.env` (ver `.env.example`). `--mode` pisa `BOT_MODE`.

## Arquitectura

```
src/
  core/        modelos pydantic (OrderBook, Signal, Order, Fill...), catálogo de instrumentos, reloj ART (UTC-3)
  config/      Settings (pydantic-settings)
  fee_engine/  FeeEngine (Decimal), tiers del broker, benchmarks ARS / USD MEP
  risk/        RiskManager (kill-switch, fases horarias), sizing (Kelly fraccional + tope de liquidez)
  connectors/  MarketConnector (ABC), IOLConnector, RofexPrimaryConnector, TokenBucket
  strategies/  MarketState + A1 TermArbitrage, A2 RatioArbitrage, B SyntheticRate, C OrderBookImbalance
  execution/   TradingEngine (orquestador), PaperBroker, LiveBroker, PositionManager, Alerts
  storage/     SQLite WAL: books, orders, fills, pnl, audit
  backtest/    runner + generador sintético (solo humo)
  ui/          dashboard rich
  main.py      CLI, wiring, modos
```

Flujo por libro: `state.update` → fills de órdenes en reposo → P&L/kill-switch → ¿flatten? → salidas (TP/SL/tiempo)
→ `strategy.on_book` → por señal: libro sano → **sizing** → **FeeEngine.evaluate** → **RiskManager.check_entry** → ejecución por patas
(si una pata falla se deshacen las anteriores).

## Liquidación

| Plazo | Código | Días | IOL `plazo` |
|-------|--------|------|-------------|
| Contado inmediato | `CI` | T+0 | `t0` |
| 24 horas | `24hs` | T+1 (próximo día hábil; viernes → 3 días corridos) | `t1` |

- `settlement_calendar_days()` usa feriados de `BOT_HOLIDAYS` para prorratear financiamiento.
- Bonos/LECAP cotizan **cada 100 VN** → `multiplier = 0.01`. Futuro DLR: 1 contrato = 1000 USD → `multiplier = 1000`.
- Sufijos: `AL30` ARS, `AL30D` MEP, `AL30C` Cable. MEP implícito = `AL30 / AL30D`.
- Sin venta en corto salvo futuros: vender requiere inventario (`BOT_PAPER_INVENTORY` en paper; portafolio IOL en live).
- Arbitraje de plazos: comprar CI y vender 24hs rinde `bid24/ask_CI - 1` vs caución colocadora × días/365.

## Fórmulas del FeeEngine (por pata, nocional N, todo en `Decimal`)

```
comisión   = N · commission_pct · (1 − descuento)     # descuento sólo en la pata de CIERRE mismo día y plazo
derechos   = N · market_rights_pct                    # BYMA / Rofex, no se bonifica
IVA        = (comisión + derechos) · 21 %
slippage   = N · slippage_bps / 10 000                # reserva adversa, además del spread cruzado
costo_pata = comisión + derechos + IVA + slippage

ida y vuelta intradiaria = pata_entrada + pata_cierre(con descuento)
señal válida ⇔ bruto_esperado − Σcostos/N_base − financiamiento ≥ min_net_edge_pct   (default 0.05 %)
```

Tiers (`BOT_FEE_TIER`): `standard` 0.25 %/pata, `gold` 0.15 % con −33 % en cierre intradiario (~0.10 %), `vip` 0.10 % con −50 %.
**Los porcentajes de derechos de mercado y slippage son supuestos**: reemplazarlos por el cuadro tarifario real en `fee_engine/tiers.py`.
Orden de magnitud con Gold: ida y vuelta ≈ 0.37 % en bonos, ≈ 0.66 % en acciones (sobre el nocional de una pata).

## Riesgo

- Kill-switch: P&L neto del día (realizado + no realizado − costo estimado de salida) ≤ **−0.8 %** del capital → cancela órdenes, cierra todo, bloquea la rueda.
- Fases ART: 11:00–11:05 sin operar · 11:05–16:10 operación · 16:10–16:30 sólo salidas · ≥16:30 flatten (corte de CI) · 16:45 límite duro · 16:55 cierre.
- Tamaño: ≤ **25 %** del volumen de la mejor punta contraria; Kelly fraccional (×0.25) acotado por 20 % del capital por pata; exposición bruta ≤ 60 %.
- Libros con spread > 1 %, cruzados, de un solo lado o con > 5 s de antigüedad no se operan.

## Conectores

- **IOL** (`https://api.invertironline.com`): `POST /token` (password / refresh_token; se renueva 120 s antes de vencer o a los 12 min),
  `GET /api/v2/{mercado}/Titulos/{simbolo}/Cotizacion?model.plazo=t0|t1`, `GET /api/v2/estadocuenta`, `GET /api/v2/portafolio/argentina`,
  `POST /api/v2/operar/Comprar|Vender`, `GET|DELETE /api/v2/operaciones/{n}`, `GET /api/v2/Cotizaciones/cauciones/argentina/Todas`.
  Token bucket (default 3 req/s, ráfaga 5) + reintento ante 429 (respeta `Retry-After`) y 401 (re-login).
- **Primary** (`https://api.primary.com.ar`): `POST /auth/getToken` (header `X-Auth-Token`), WebSocket `smd` con `depth=5`,
  órdenes REST `/rest/order/newSingleOrder|cancelById|id`. Se implementó sobre aiohttp (mismo protocolo que `pyRofex`) para quedar en un único event loop.
  Ruteo FIX nativo **no implementado** (requiere engine FIX y credenciales dedicadas).

## Límites conocidos (leer antes de operar)

1. Los endpoints/payloads de IOL y Primary están escritos desde la documentación pública y **no se probaron contra cuentas reales** (el sandbox no tiene acceso). Validar en paper con credenciales reales antes de live.
2. Con comisiones realistas, el ida y vuelta de acciones cuesta ~0.66 %: el filtro de edge neto rechazará la mayoría de las señales de GGAL. Es el comportamiento buscado.
3. `win_prob` del Módulo C es heurística; calibrar con backtest de libros grabados (`--mode paper` los persiste).
4. El Módulo B opera un futuro de 1000 USD por contrato: requiere capital para ≥ 1 contrato por pata (si no, la señal se descarta por "cantidad < 1").
5. Backtest sintético = prueba de humo; no valida rentabilidad. Una meta compuesta de 0.4 %/día (~2.7× anual) no está garantizada por ningún componente de este código.
6. Antes de live: `BOT_MODE=live` exige escribir `OPERAR EN REAL`; empezar con capital mínimo.
