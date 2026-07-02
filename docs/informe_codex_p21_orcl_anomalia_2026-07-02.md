# Informe P21 - Anomalia ORCL en radar Telegram

Fecha: 2026-07-02

## Veredicto

La extension `ext_sma20=-23.35%` y `rsi=11.25` de ORCL en el radar Telegram es
real segun la cache local y una segunda descarga yfinance aislada. No hay evidencia
de simbolo mal extraido, precio de otro activo, split mal tratado ni fila corrupta.

No se purgo el scorecard y no se modifico la logica del radar.

## Mencion investigada

- Post: `5014`
- Fecha/hora: `2026-06-29T13:43:58+00:00`
- Texto: menciona `AAOI`, `ASTS`, Google, META, Reddit y Oracle.
- Extraccion heuristica: `AAOI`, `ASTS`, `GOOGL`, `META`, `ORCL`, `RDDT`.
- En universo: `GOOGL`, `META`, `ORCL`.

## Contraste con cache/yfinance

Recalculo con `add_basic_technical_features` sobre cache
`data/cache/market_data/market_data_63d9a2a7301b8196.pkl`:

| Simbolo | Fecha barra | Close | SMA20 | ext_sma20 | RSI14 | return_20d |
|---|---:|---:|---:|---:|---:|---:|
| ORCL | 2026-06-29 | 147.76 | 192.7750 | -23.35% | 11.25 | -34.56% |
| GOOGL | 2026-06-29 | 353.65 | 359.4251 | -1.61% | 44.40 | -6.96% |
| META | 2026-06-29 | 562.60 | 579.5235 | -2.92% | 42.51 | -10.97% |

Serie ORCL reciente en cache:

| Fecha | Close | SMA20 | RSI14 | return_20d |
|---|---:|---:|---:|---:|
| 2026-06-08 | 211.82 | 204.7735 | 60.13 | 8.10% |
| 2026-06-11 | 184.10 | 205.8105 | 47.96 | -2.98% |
| 2026-06-18 | 184.29 | 205.2170 | 32.25 | -2.06% |
| 2026-06-23 | 165.16 | 203.1360 | 13.91 | -14.01% |
| 2026-06-26 | 148.53 | 196.6760 | 11.10 | -27.08% |
| 2026-06-29 | 147.76 | 192.7750 | 11.25 | -34.56% |

Segunda descarga yfinance sin cache previa (`cache_hit=false`, `missing=[]`,
`alerts=[]`) reproduce:

- ORCL: close `147.76`, SMA20 `192.7750`, `ext_sma20=-23.35%`, RSI `11.25`.
- GOOGL: `ext_sma20=-1.61%`, RSI `44.40`.
- META: `ext_sma20=-2.92%`, RSI `42.51`.

## Decision

La anomalia es una senal extrema real de precio, no contaminacion del scorecard.
Se deja el scorecard como esta.

## Seguridad operativa

- Read-only sobre radar y datos de mercado: no se generaron ordenes.
- `trading_mode=paper`.
- `allow_live_trading=false`.
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- `data/config/core_sleeve.json`: `dry_run=true`.
- No se tocaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py` ni `.env`.

## Verificacion

- `pytest tests\ -x -q`: `912 passed, 1 warning`.
- `ruff check src tests scripts`: limpio.
- `python -m agente_bolsa.main status`: OK, `trading_mode=paper`,
  `allow_live_trading=false`.
- `python -m agente_bolsa.main validate-agent-config --json`: `ok=true`, sin
  errores ni warnings.
- `python -m agente_bolsa.main run-once --skip-crew`: OK, ciclo
  `20260702-224241`, sin LLM ni ordenes automaticas.
- Configuracion real cargada desde `.env`: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`,
  `core_sleeve_dry_run=true`.
