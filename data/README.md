# Datos históricos

`BTCUSD_bitstamp_{5m,15m,1h}.csv.gz` (desde 2023-01-01): velas OHLCV BTC/USD de **Bitstamp** (spot real),
resampleadas desde el dataset público de 1 minuto
[ff137/bitstamp-btcusd-minute-data](https://github.com/ff137/bitstamp-btcusd-minute-data)
(derivado del dataset de Kaggle de mczielinski). Licencia de los datos: **CC BY-SA 4.0**.

Regenerar: `python scripts/prepare_data.py <clone_de_ese_repo> --since 2023-01-01`. Timestamps en UTC, etiqueta = apertura de la vela.
