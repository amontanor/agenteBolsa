# Informe Codex - Telegram radar Fase A - 2026-07-01

## Objetivo

Fase A read-only: ingerir la vista publica de `https://t.me/s/bolsazonefreezone`
sin login, persistir posts deduplicados y extraer oportunidades/tickers por post.

No se tocaron ficheros bloqueados ni se cambio trading, riesgo, ejecucion,
kernel, configuracion ni `.env`.

## Diseno

Nuevo subpaquete aislado:

- `src/agente_bolsa/research/telegram_radar/`
- No depende de modulos operativos de decision/ordenes.
- CLI: `python -m agente_bolsa.main telegram-radar ...`

Comandos:

- `telegram-radar ingest [--backfill N] [--force] [--skip-llm] [--json]`
- `telegram-radar list [--days N] [--only-opportunities] [--json]`

La ingesta:

- Descarga la pagina publica con `requests` y timeout.
- Cachea HTML por URL bajo `data/research/telegram/cache`.
- Pagina hacia atras con `?before=<id>` si `--backfill N > 1`.
- Parsea `div.tgme_widget_message`, `data-post`, texto, `time[datetime]`,
  autor, links y `raw_html_hash`.
- Falla limpio con warnings si Telegram no responde.

## Esquema de datos

Almacenamiento dedicado JSONL bajo `data/research/telegram/`:

`posts.jsonl`:

```json
{
  "message_id": 5031,
  "posted_at": "2026-07-01T14:02:09+00:00",
  "author": null,
  "text": "Para mi, hoy NVIDIA muy comprable 194-195$",
  "links": ["https://t.me/bolsazonefreezone/5031"],
  "raw_html_hash": "..."
}
```

`extractions.jsonl`:

```json
{
  "message_id": 5031,
  "extraction_status": "llm_ok|llm_unavailable_heuristic_fallback|heuristic_only",
  "is_opportunity": true,
  "tickers": ["NVDA"],
  "direction": "buy",
  "thesis": "Mencion explicita en radar Telegram: NVDA.",
  "timeframe": null,
  "confidence": 0.35,
  "unresolved_mentions": [],
  "ticker_coverage": [
    {"ticker": "NVDA", "in_universe": true, "out_of_coverage": false}
  ]
}
```

## Extraccion

`extract.py` usa el LLM del proyecto via `chat_for_role("deep")`, temperatura
baja y salida JSON estricta. Si el LLM no esta disponible, registra
`extraction_status=llm_unavailable_heuristic_fallback` y conserva una extraccion
determinista basica.

Normalizacion incluida:

- `$RH` -> `RH`.
- Diccionario pequeno: Palantir -> `PLTR`, Reddit -> `RDDT`, Ferrari -> `RACE`,
  MercadoLibre/MELI -> `MELI`, Google -> `GOOGL`, Oracle -> `ORCL`,
  Micron/Micron con tilde -> `MU`, SanDisk -> `SNDK`, Nvidia -> `NVDA`.
- Heuristica de tickers en mayusculas.
- Menciones no resueltas quedan en `unresolved_mentions`.

Mapeo a universo:

- Cada ticker se marca con `in_universe` usando `universe_as_of`.
- Si no esta en S&P 500 point-in-time queda `out_of_coverage=true`.
- Se registra pero no se estudia en Fase B.

## Ejemplos recientes

Se ejecuto ingesta real de 1 pagina publica: 20 posts parseados. En esta sesion,
el intento con LLM real no completo dentro del timeout de trabajo; se verifico la
ruta LLM con mocks en tests y se usaron extracciones deterministas para ejemplos.

Ejemplos sobre posts reales recientes cacheados:

| Message | Texto resumido | Extraccion |
|---:|---|---|
| 5031 | "hoy NVIDIA muy comprable 194-195$" | `is_opportunity=true`, `tickers=[NVDA]`, `direction=buy`, `NVDA in_universe=true` |
| 5015 | "Micron o Sandisk... puede ser oportunidad" | `is_opportunity=true`, `tickers=[MU,SNDK]`, `direction=watch`, `MU in_universe=true`, `SNDK out_of_coverage=true` |
| 5014 | "ASTS, AAOI, Google, META... Reddit y Oracle..." | `is_opportunity=true`, `tickers=[AAOI,ASTS,GOOGL,META,ORCL,RDDT]`, `direction=buy`; `GOOGL/META/ORCL in_universe=true`, resto fuera de cobertura |

## Limitaciones

- El canal es marketing/hype y puede tener cherry-picking.
- Fase A solo extrae menciones; no mide si las oportunidades funcionan.
- No hay recomendacion operativa ni ordenes.
- La calidad del parser depende de HTML publico de Telegram.
- El marcador honesto llega en Fase B: comparar menciones contra retornos
  posteriores, costes, cobertura, sesgo temporal y universo.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_telegram_radar.py -q -p no:warnings` -> 5 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 833 passed, 1 warning externa de `websockets.legacy`.
- `.\.venv\Scripts\ruff.exe check src tests` -> OK.
- Smoke CLI: `telegram-radar --help` -> OK.
- Ingesta real read-only: 20 posts parseados desde cache/public page.
- Estado operativo: `trading_mode=paper`, `allow_live_trading=false`.
- Version final: `0.4.77`.
