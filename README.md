# ar-quant-bot

Bot de trading cuantitativo para BYMA y Matba Rofex (IOL + Primary). Documentación técnica completa en [CLAUDE.md](CLAUDE.md).

## Puesta en marcha en `--mode paper`

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # completar credenciales
python -m pytest -q       # verificación
python -m src.main --mode paper
```

`.env` mínimo para paper (sólo datos de mercado IOL; no se envían órdenes reales):

```ini
BOT_MODE=paper
BOT_CAPITAL_ARS=1000000
BOT_IOL_USERNAME=tu_usuario_iol
BOT_IOL_PASSWORD=tu_clave_iol
BOT_FEE_TIER=gold
BOT_CAUCION_COLOCADORA_TNA=0.28
BOT_CAUCION_TOMADORA_TNA=0.34
# Inventario simulado para poder "vender" (JSON): sin esto sólo se compra y se cierra lo comprado
BOT_PAPER_INVENTORY={"AL30": 100000, "GD30": 100000}
```

Para activar el Módulo B (futuros) agregar `BOT_PRIMARY_USERNAME`, `BOT_PRIMARY_PASSWORD`, `BOT_PRIMARY_ACCOUNT`,
`BOT_FUTURE_SYMBOL` y `BOT_FUTURE_EXPIRY=AAAA-MM-DD`. Los LECAPs se declaran con `BOT_LECAPS` (JSON):
`[{"symbol":"S31M7","maturity":"2027-03-31","payoff_per_100":131.5}]`.

Paper graba todos los libros en `data/bot.db`; después: `python -m src.main --mode backtest --db data/bot.db`.
