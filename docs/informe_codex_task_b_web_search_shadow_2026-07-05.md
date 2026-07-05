# Informe Task B web search shadow - 2026-07-05

## Verificacion de bloqueados

Comando inicial:

```powershell
git diff --ignore-space-at-eol --stat HEAD -- src/agente_bolsa/kernel.py src/agente_bolsa/tools/broker.py src/agente_bolsa/tools/execution.py src/agente_bolsa/tools/risk.py src/agente_bolsa/config.py .env
```

Resultado: salida vacia. No hay cambios reales en bloqueados antes de la entrega.

## Cambios

- `tools/web_research_budget.py`: presupuesto independiente por proveedor con
  `WEB_SEARCH_BUDGET_TAVILY` y `WEB_SEARCH_BUDGET_BRAVE`, manteniendo cache TTL y
  reporte `latest_web_search_budget.json`.
- `tools/web_research.py`: `auto` reparte por menor uso mensual; si
  `WEB_SEARCH_MERGE_PROVIDERS=true`, consulta Tavily y Brave, fusiona y deduplica.
  Si un proveedor falla o agota cap, se degrada al otro.
- `tools/news_sentiment.py`: `MATERIAL_RISK_V2` default OFF. Calcula shadow delta
  material->none exigiendo coocurrencia simbolo/empresa + termino negativo y
  quitando `competitor/rival` como veto por si solos.
- `tools/research_evidence.py`: fiabilidad por dominio curado y delta frente al
  scoring anterior dentro del payload de evidencia.
- `tools/web_evidence_ab.py`: dataset JSONL en `data/research/web_ab/` para medir
  que aporta la web sin llamadas extra.
- `main.py`: CLI `web-evidence-ab`.
- Version: `0.4.112`.

## Estado shadow

No se cambia conducta de compra viva por defecto:

- `WEB_SEARCH_MERGE_PROVIDERS` default OFF.
- `MATERIAL_RISK_V2` default OFF.
- El A/B solo persiste observaciones para analisis posterior.
- La fiabilidad por dominio queda activa como scoring de bajo riesgo y deja delta
  auditable.

## Verificacion

- `pytest tests/ -x -q`: `970 passed, 1 warning`.
- `ruff check src tests`: sin errores.
- `python -m agente_bolsa.main status`: `trading_mode=paper`,
  `allow_live_trading=false`.
- `python -m agente_bolsa.main validate-agent-config --json`: `ok=true`.
- `python -m agente_bolsa.main run-once --skip-crew`: termina sin traceback.
- Verificacion final de bloqueados: salida vacia.

## Higiene pendiente

`.venv_old_codex/` esta trackeado y sigue pendiente planificar limpieza junto con
`.gitignore`/`.gitattributes` para reducir ruido CRLF. No se toca en esta entrega
para evitar mezclar cambios masivos de higiene con Task B.
