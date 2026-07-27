# P-L59B-T-R2 — informe único corregido

## Dictamen único

**`needs_fix`**

### Causa

**(a) `llm_selected`**: el candidato P-L60R1 deriva este campo exclusivamente
de `decision_source` en `canonical_selection_ledger.py:383`. La lógica es:

```python
"llm_selected": True if source == "llm" else False if source else None
```

No existe un booleano independiente sellado en la etapa de decisión. Fuentes no
reconocidas se normalizan a `"other"` y reciben `False` en vez de
`None`/`unavailable`. La derivación es determinista y reproducible, pero
**`llm_selected` no demuestra selección LLM causal**: `True` significa "la
recomendación fue generada por el agente LLM", no "el LLM eligió este
candidato". `False` colapsa capacity-fill (basado en ranking LLM) con fallback
(sin LLM), que son semánticamente distintos.

**(b) Controles elegibles**: `comparable_controls.py` (P-L31B, desplegado en
producción `0.4.185`) define `PRIMARY_REASONS = {lower_rank, capacity_limit}` y
los separa de `BLOCKED_REASONS`. La API `build_comparable_control_sets` produce
control sets verificados con schema, identidad exacta, non_execution_reason y
gate_eligibility. Esto funciona en el candidato P-L60R1 pero **los 0 controles
exactos en P-L59A (ventana 20-24 jul) son un hecho observado cuya causa no está
demostrada**. P-L31B está desplegado; la ausencia de controles puede deberse a
falta de planes finales, estrategias pausadas, o ausencia de rechazos
`lower_rank`/`capacity_limit` en esa ventana — ninguna de estas causas se
atribuye a P-L53/P-L54B, que operan en dominios distintos del de controles.

**(c) Colisión P-L53**: dos recomendaciones con la misma señal y distinto
`recommendation_id` colisionan en el ledger P-L53 (la identidad primaria no
incluye `recommendation_id`). P-L54B maneja `decision_identity` con dominios
propios; si esto repara la colisión en P-L54B no está demostrado en este lote
(sería necesario un test end-to-end con ambos productores). Son dominios
separados.

## Alcance y estado

- Hora real: 2026-07-27 19:20 CEST.
- **XNYS ABIERTO** (sesión 2026-07-27, cierre 22:00 CEST).
- Base exacta: `70de34011b74403281c32673c32947cab0ee0952`, tree `1d960a6723c0f2fbe5bc4afc72c7df08284c43d1`.
- Producción desplegada: HEAD `24537e813ff0905696cda0b3925a212045ee7b09`, versión `0.4.185`.
- Working tree productivo: versión `0.4.186` (P-L61, cambios unstaged, no leído ni modificado).
- Candidato: P-L60R1, versión `0.4.195`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59bt_llm_selection_contract`.
- Rama: `codex/pl59bt-llm-selection-contract`.
- HEAD R2: `06c95f02`.
- Solo tests, este informe, plan y relevo. Versión `0.4.195`.

## Validación

| Artefacto | Resultado |
|---|---|
| `test_p59bt_llm_selected_contract_characterization.py` | **28 passed** (1.01s) |
| Ruff | **All checks passed** |
| `check_no_nulls.py` | **OK (434 archivos)** |
| `git diff --check` | **verde** |
| `src/` modificado | **0 archivos** |
| Archivos protegidos | **0 modificados** |

**Cobertura funcional contra APIs reales**:

| Grupo | Tests | APIs ejercitadas |
|---|---|---|
| (A) `llm_selected` proxy/brecha | 6 | `build_canonical_selection_ledger` + source llm/capacity/fallback/None/unknown |
| (B) Colisión rec_id P-L53 | 1 | `build_canonical_selection_ledger` con 2 recs misma señal |
| (C) BUY/EXIT, cross-cycle, missing | 4 | `build_canonical_selection_ledger` |
| (D) Persistencia Store | 5 | `persist_canonical_selection_ledger`, `read_canonical_selection_ledger`, `Store(tmp_path)` |
| (E) Match con exclusión real | 3 | `match_same_cycle_controls` con recomendada excluida + cross-cycle |
| (F) Controles funcionales | 7 | `build_comparable_control_sets` con `TradeRecommendation`/`OrderPlan`/`RiskDecision` reales, `lower_rank`, `capacity_limit`, gate_blocked, cross-cycle, `validate_comparable_control_set` |
| (G) Stage order | 1 | Inspección de `_persist_selection_ledger_shadow`, `_persist_capital_deployment_funnel_shadow`, `_auto_paper_trade` |
| (H) Paridad | 2 | `selected_for_llm` vs `llm_selected`, forbidden fields |

**Gates omitidos** (XNYS abierto): suite completa, smoke, benchmark largo,
P-L45 33.336, broker, red, LLM, yfinance, postmarket, reconciliación,
despliegue. Sin skips/xfails.

## Stage order observado

El orden real en `cycle_runner._auto_paper_trade` (líneas 1965-2276):

1. **Phase A predecision P-L53**: `selection_ledger_phase_a` captura el universo
   rankeado.
2. **Selección y recomendaciones**: LLM/gates producen `reviewed_recommendations`.
3. **P-L31B controles**: `build_comparable_control_sets` (línea 1965) desde
   `gated_recommendations` y `plans` finales.
4. **Planes finales**: se adjuntan control sets a los planes buy finales.
5. **P-L53 finalización**: `_persist_selection_ledger_shadow` (línea 2255)
   construye el ledger completo con phase A + recomendaciones + planes + órdenes.
6. **P-L54B finalización**: `_persist_capital_deployment_funnel_shadow` (línea
   2266) construye el funnel shadow con los mismos objetos.

P-L31B se ejecuta ANTES de la finalización de P-L53 y P-L54B, y DESPUÉS de
gates/planes. P-L53 y P-L54B son shadows fail-open que ocurren tras la ruta
activa; no afectan decisiones.

## Productor → Evento → Consumidor (corregido)

| Eslabón | P-L53 | P-L31B | P-L54B |
|---|---|---|---|
| **¿Desplegado en prod 0.4.185?** | **NO** | **SÍ** | **NO** |
| Productor | `build_canonical_selection_ledger` | `build_comparable_control_sets` | `build_capital_deployment_funnel_shadow` |
| Evento | `canonical_selection_ledger:<cycle_id>` | `comparable_control_set` en `learning_observations.features` | `capital_deployment_funnel_shadow:<cycle_id>` |
| Persistencia | `agent_events` vía `Store` | `Store.attach_comparable_control_set` | `agent_events` vía `Store` |
| Consumidor | `read_canonical_selection_ledger`, CLI, digest | `comparable-control-quality --json` (CLI en `main.py:2545`) | `read_capital_deployment_funnel`, CLI |
| Estado en P-L60R1 | implementado (shadow) | heredado de prod | implementado (shadow) |

## Defectos y brechas

1. **`llm_selected` = proxy de source** (BREACH): no existe booleano
   independiente de selección LLM causal. Requiere rediseño del productor.

2. **Colisión P-L53 sin `recommendation_id`**: dos recomendaciones distintas
   para la misma señal colisionan. P-L54B maneja esto en su propio dominio de
   `decision_identity`, pero no se ha demostrado end-to-end que lo corrija en el
   ledger P-L53.

3. **Source desconocida → `other` → `False`**: missing colapsa a falso.

4. **0 controles P-L59A**: hecho observado, causa NO demostrada. P-L31B está
   desplegado y es independiente de P-L53/P-L54B. Posibles causas inferidas (no
   demostradas): ausencia de planes finales en esa ventana, estrategias
   pausadas, o rechazos que no mapean a `lower_rank`/`capacity_limit`. No se
   atribuye a P-L53/P-L54B.

## Seguridad y paridad

No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
`config.py` ni `.env`. Sin cambio de política, ranking, gates, sizing, planes,
órdenes, exposición o límites. Sin despliegue, reinicio, SQLite productiva,
broker, red, LLM, yfinance ni push.

## Siguiente lote

Para `llm_selected` causal haría falta un rediseño del productor (P-L59C). Para
los controles, se necesita evidencia real de producción (no sintética) que
demuestre qué poblaciones existen. Ningún lote se inicia desde aquí.
