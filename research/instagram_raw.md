# Instagram @fidetolabs — registro de extracción (Fase 1)

**Estado: BLOQUEADA.** No se pudo leer ninguna pieza del perfil. No hay contenido inventado en este archivo.

## Intentos (2026-10-20)
| Destino | Resultado |
|---|---|
| `https://www.instagram.com/fidetolabs/` (curl vía proxy) | `CONNECT 403`: la política de red del entorno no permite el host |
| Mismo URL vía fetch de página | `ENOTFOUND www.instagram.com` |
| `www.fidetolabs.com`, `fidetolabs.substack.com` | `ENOTFOUND` (también bloqueados) |
| APIs de mercado (`api.binance.com`, `data-api.binance.vision`, `testnet.binance.vision`, Yahoo, Kraken, Coinbase, CoinGecko, Stooq) | bloqueadas; solo PyPI y GitHub son accesibles |

No se intentó evadir el bloqueo (sin proxies alternativos, sin scrapers de terceros).

## Fuentes secundarias accesibles (NO son el Instagram)
- **GitHub `fidetolabs`**: bio "Building data products and ai agents for systematic traders". 1 repo público, link a Instagram.
- **Repo `fidetolabs/qanat`** (Python, MIT, beta): plataforma de datos para investigación de inversiones. Ingesta (SEC EDGAR, Yahoo Finance, HTTP, SQL, CSV), guarda cada dato con fecha de período y fecha de publicación, y sirve *screens* de métricas fundamentales "as of" cualquier fecha pasada **sin look-ahead**, vía servidor MCP. Su carpeta `audit/` documenta un caso donde un paso "tramposo" con fuga de datos daba 1292% contra un 3.40% honesto; también usa `purge`/`embargo`.
- Búsqueda web: describen el proyecto como "AI agents for quant trading", con Discord y Substack.

**Lectura provisoria:** lo visible del autor es infraestructura de datos y screening fundamental point-in-time (acciones, EE.UU.), no una estrategia de trading técnica con indicadores/entradas/salidas. Si el Instagram enseña otra cosa, solo se sabrá leyéndolo.

## Pendiente para el usuario
Habilitar en *Network access* del entorno: `www.instagram.com` (y opcionalmente `www.fidetolabs.com`, `fidetolabs.substack.com`), más una fuente de datos de mercado y testnet (p. ej. `data-api.binance.vision`, `testnet.binance.vision`). O exportar/pegar los posts aquí.
