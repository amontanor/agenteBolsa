# Informe commit web search + Task A - 2026-07-05

## Verificacion de bloqueados

Comando ejecutado:

```powershell
git diff --ignore-space-at-eol --stat HEAD -- src/agente_bolsa/kernel.py src/agente_bolsa/tools/broker.py src/agente_bolsa/tools/execution.py src/agente_bolsa/tools/risk.py src/agente_bolsa/config.py
```

Resultado: solo `src/agente_bolsa/config.py` muestra cambio real, con `11 insertions`.
No hay cambios reales en `kernel.py`, `tools/broker.py`, `tools/execution.py` ni
`tools/risk.py`.

Diff revisado de `config.py`: las 11 lineas son aditivas y corresponden solo a:

- `web_search_enabled`, default `False`.
- `web_search_provider`, default `auto`.
- `web_search_max_items_per_symbol`.
- `web_search_market_max_items`.
- `web_search_timeout_seconds`.
- `tavily_api_key`, `tavily_base_url`.
- `brave_api_key`, `brave_base_url`.

No se modifica trading live, broker, ejecucion, kernel ni riesgo.

## Commit

Se usara un unico commit por staging explicito. La separacion en dos commits no es
limpia porque Task A modifica los mismos ficheros y funciones que la integracion
base de web search (`web_research.py`, `news_sentiment.py`, `research_evidence.py`).

Mensaje:

```text
feat: web search evidence + budget governor
```

Incluye:

- Integracion base Tavily/Brave default-off y CLI/diagnostico.
- Evidencia web trazable para sentimiento y `research_evidence`.
- Gobernador de cuota mensual, cache TTL, cap seguro y reporte de presupuesto.
- Invocacion dirigida: web solo como fallback cuando la evidencia local falta o
  esta vieja, salvo probes explicitos.
- `WEB_SEARCH_FRESHNESS_V2` en shadow con delta `unknown -> fresh`.
- Dashboard/diagnostico de buscadores.
- Tests sin red y bump a `0.4.111`.

## Verificacion

- `pytest tests/ -x -q`: `964 passed, 1 warning`.
- `ruff check src tests`: sin errores.
- `python -m agente_bolsa.main status`: `trading_mode=paper`,
  `allow_live_trading=false`.
- `python -m agente_bolsa.main validate-agent-config --json`: `ok=true`.
- `python -m agente_bolsa.main run-once --skip-crew`: termina sin traceback.

## Higiene pendiente

`.venv_old_codex/` esta trackeado en Git. Tambien hay ruido potencial de CRLF en
varios ficheros. Queda como tarea separada planificar `.gitignore`/`.gitattributes`
y limpieza del entorno trackeado. No se ejecuta en esta entrega para no mezclar un
cambio masivo de higiene con web search.
