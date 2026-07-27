# P-L59B-T-R4 — informe único final

## Dictamen único

**`needs_fix`**

### Causa

**(a) `llm_selected`**: el candidato P-L60R1 deriva este campo exclusivamente
de `decision_source` en `canonical_selection_ledger.py:383`. No existe un
booleano independiente sellado en la etapa de decisión. Fuentes no reconocidas
se normalizan a `"other"` y reciben `False` en vez de `None`/`unavailable`. La
derivación es determinista pero `llm_selected` no demuestra selección LLM
causal: `True` = "la recomendación fue generada por el agente LLM", no "el
LLM eligió este candidato". `False` colapsa capacity-fill con fallback.

**(b) Controles elegibles**: `comparable_controls.py` (P-L31B, desplegado en
producción `0.4.185`) define `PRIMARY_REASONS = {lower_rank, capacity_limit}`.
La API `build_comparable_control_sets` produce control sets verificados. Los 0
controles P-L59A son un hecho observado con causa no demostrada (P-L31B es
independiente de P-L53/P-L54B).

**(c) Colisión P-L53**: la identidad primaria no incluye `recommendation_id`.
Dos recomendaciones con misma señal y distinto rec_id colisionan. P-L54B usa
dominios propios; no demostrada reparación cruzada.

## Stage order real (R4 — precisión corregida)

Verificado ejecutablemente en
`tests/test_market_cycle_timing_integration.py::test_stage_order_full_flow_with_pl53_pl54_spies`.
Ejecuta `_auto_paper_trade` con `_patch_trading_flow` y espía cada paso con
`monkeypatch`. Rama ejecutada: exitosa con plan y submit.

| Orden | Línea real | Componente | Recibe |
|---|---|---|---|
| 1 | 1880 | `build_order_plans` | gated_recommendations → `plans` (OrderPlan) |
| 2 | ~1893 | `_apply_daily_buy_limit` | filtra `plans` |
| 3 | ~1894 | `_apply_low_sample_daily_quota` | filtra `plans` |
| 4 | ~1897 | `_separate_strategy_paused_plans` | separa `plans` |
| 5 | 1965 | **P-L31B** `build_comparable_control_sets` | `plans=plans` (OrderPlan originales) |
| 6 | ~2004 | Attach: `replace(plan, recommendation=...)` → `plans = attached_plans` | — |
| 7 | ~2071 | P-L50 `_persist_learning_penalty_cycle_shadow_final` | `comparable_control_sets` |
| 8 | **2399** | **P-L53** `_persist_selection_ledger_shadow` | `plans=plans` (attached), `plan_records=plan_records`, `recommendations=reviewed_recommendations` |
| 9 | **2412** | **P-L54B** `_persist_capital_deployment_funnel_shadow` | `plans=plan_records or plans`, `recommendations=reviewed_recommendations`, `gated_recommendations=gated_recommendations` |

La rama sin submit (2255/2266) tiene la misma estructura pero sin
`ordered_records`/`failed_records`/`submitted`. El test recorre la rama 2399/2412.

**Contrato de identidad observado**:
- P-L31B recibe los `plans` originales con `plan_id` intacto.
- P-L53 recibe los `plans` después de `replace(plan, recommendation=...)` que
  pierde campos `init=False` como `plan_id`. Las identidades se recuperan vía
  `plan_records` (dicts durables) que sí preservan `plan_id`.
- P-L54B recibe `plans=plan_records or plans` (en rama exitosa, `plan_records`
  existe). No son los mismos objetos que P-L31B/P-L53, pero los `plan_id`
  coinciden con los `plan_record_ids` de P-L53.
- P-L53 y P-L54B comparten `recommendations=reviewed_recommendations` (misma
  lista literal).
- P-L54B recibe adicionalmente `gated_recommendations`.

## Alcance y estado

- Hora real: 2026-07-27 19:33 CEST (R4).
- **XNYS ABIERTO** (sesión 2026-07-27, cierre 22:00 CEST).
- Base exacta: `70de34011b74403281c32673c32947cab0ee0952`, tree `1d960a6723c0f2fbe5bc4afc72c7df08284c43d1`.
- Producción desplegada: HEAD `24537e813ff0905696cda0b3925a212045ee7b09`, versión `0.4.185`.
- Working tree productivo: versión `0.4.186` (P-L61, cambios unstaged, no leído ni modificado).
- Candidato: P-L60R1, versión `0.4.195`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59bt_llm_selection_contract`.
- Rama: `codex/pl59bt-llm-selection-contract`.
- HEAD R4: `ef5835a1`.
- Solo tests, este informe, plan y relevo. Versión `0.4.195`.

## Validación

| Artefacto | Resultado |
|---|---|
| `test_p59bt_llm_selected_contract_characterization.py` | **27 passed** (0.48s) |
| `test_market_cycle_timing_integration.py` (5 tests) | **5 passed** (0.81s) |
| **Total focales** | **32 passed** (1.10s) |
| Ruff (ambos archivos) | **All checks passed** |
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
| (D) Persistencia Store | 5 | `persist`, `read`, `Store(tmp_path)` |
| (E) Match con exclusión real | 3 | `match_same_cycle_controls` con recomendada excluida + cross-cycle |
| (F) Controles funcionales | 7 | `build_comparable_control_sets` reales: lower_rank, capacity_limit, gate_blocked, cross-cycle, `validate` |
| (G) Stage order | 1 | `test_market_cycle_timing_integration.py`: `_auto_paper_trade` + spies P-L31B/P-L50/P-L53/P-L54B |
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
