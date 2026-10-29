# P-L174 — sentimiento: por qué no llega al LLM (0.4.405)

Fecha: 2026-10-29. Nivel **N2**: telemetría de productor; no cambia la decisión
de sentimiento ni la política de trading.

## 1. Dictamen

`ready_for_integration_rehearsal`. El «sentimiento sin LLM» no era un fallo del
LLM: el productor no recibía noticias y no lo declaraba.

## 2. Causa raíz doble

Hechos de producción (2026-10-29):

1. `latest_news_sentiment` 15:53Z: **10/10 símbolos con `news_count = 0`** y
   `warnings = []`.
2. `web_search_usage_2026-10.json`: `calls_used 2000/2000`
   (tavily 1000 + brave 1000), `budget_exhaustions 5532`,
   `degradations` tavily 2772 / brave 2760, `last_warning
   web_search_budget_exhausted:brave`. Proyección mensual 2.137,93 con
   presupuesto 2.000: se agota todos los meses.
3. Sin noticias locales (yfinance) y sin web, `_llm_sentiment` retorna
   `no_news` **antes** de llamar al LLM y sin warning. De ahí `6.655` llamadas
   históricas con última el **2026-10-16T16:13:01Z**.
4. Causa histórica distinta y ya corregida: cuando sí había noticias
   (2026-10-21, ABBV con 5), el LLM devolvió `401 api_key_expired` de Zen; P-L169
   lo resolvió con `opencode-go` y la cabecera de sesión.

## 3. Arreglo

- `news_sentiment.py`: nueva `fetch_combined_symbol_news_with_metadata` que
  devuelve noticias y metadatos por proveedor (`local.count/error`,
  `web.enabled/attempted/quality/providers/warnings/cache_hits/provider_calls`).
  `fetch_combined_symbol_news` conserva su contrato de lista.
- `analyze_news_sentiment_for_candidates`:
  - añade `news_source` por símbolo (dato, no texto libre);
  - agrega `news_sources` al informe con `symbols_with_news`,
    `symbols_without_news`, `provider_warnings` y `unavailable_reason`
    (`web_search_budget_exhausted`, `news_provider_unavailable`,
    `no_news_returned`, `no_candidates`);
  - propaga los warnings del proveedor al informe (`web_search:...`).
- **No** cambia la decisión: con 0 noticias el sentimiento sigue siendo
  `no_news`, `risk_flags=["sin_noticias"]`, sin llamada LLM y sin alterar
  `assess_material_news_risk`.

## 4. Evidencia

```text
pytest tests/test_p174_sentiment_sources.py
  base 4a178a2c: 3 failed, 1 passed
  candidato:     4 passed

pytest tests/test_news_sentiment.py tests/test_web_research.py
       tests/test_web_research_budget.py tests/test_p174_sentiment_sources.py
  22 passed
ruff check (ficheros del lote)   All checks passed
check_no_nulls                   OK (610)
git diff --check                 limpio
```

## 5. Límites

- El presupuesto agotado sigue agotado: sin decisión de capacidad (subir
  presupuesto/claves o bajar cadencia) no habrá noticias web. Este lote hace
  visible el motivo, no crea cuota.
- No se ha llamado a los proveedores desde pruebas; la verificación real
  llegará con el primer informe desplegado que muestre `news_sources`.

## 6. Candidato

- Worktree `.worktrees/pl174-sentiment-meta`, rama `codex/pl174-sentiment-meta`,
  base `4a178a2c`.
- Commits: `9e6c5970` test, `d56173a0` fix, `53e4540a` versión.
- Versión `0.4.405`.
