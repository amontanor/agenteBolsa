# P-L59B-T — caracterización del contrato `llm_selected` y elegibilidad de controles

## Dictamen

`ready_for_implementation`.

La caracterización confirma que el candidato P-L60R1 (versión `0.4.195`) **puede**
expresar de forma estructurada y causal qué recomendaciones BUY fueron
directamente producidas por el LLM y qué controles elegibles same-cycle
quedaron fuera por `lower_rank` o `capacity_limit`. La respuesta, sin embargo,
es parcial y depende de dos salvedades documentadas:

1. `llm_selected` **no es un booleano independiente**: se deriva del campo
   `decision_source` durante la construcción del ledger (`canonical_selection_ledger.py:383`).
   Cuando `source == "llm"`, `llm_selected` es `True`; para cualquier otra
   fuente normalizada (`deterministic_capacity_fill`, `fallback`, `hold_override`,
   `deterministic`, `other`) es `False`; sin recomendación es `None`. La
   derivación es determinista y correcta, pero un `llm_selected=True` NO
   significa "el LLM eligió este candidato entre los 20 presentados": significa
   "la recomendación fue generada directamente por el agente LLM".

2. Los **controles primarios** (`lower_rank`, `capacity_limit`) están definidos
   en `comparable_controls.py` y son capturados por `build_comparable_control_sets`
   desde los planes finales. Los bloqueados por gates, riesgo, sizing,
   duplicados, posición existente, cuotas o geometría inválida NO son controles
   primarios y se publican separados. La identidad es exacta
   (`cycle_id + action + signal_capture_id/signal_id`), no por símbolo/fecha ni texto.

La causa del `unavailable` reportado en P-L59A es que **producción `0.4.185`
carece de los módulos P-L53/P-L54B/P-L31B** que implementan estos contratos.
El candidato P-L60R1 los contiene completos y funcionales, pero ninguno está
desplegado en producción.

## Alcance y estado

- Fecha de ejecución: 2026-07-27, ~18:40-19:30 Europe/Madrid.
- **XNYS ABIERTO** (sesión 2026-07-27, cierre 22:00 CEST).
- Base exacta: `70de34011b74403281c32673c32947cab0ee0952`, tree `1d960a6723c0f2fbe5bc4afc72c7df08284c43d1`.
- Candidato: P-L60R1, versión `0.4.195`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59bt_llm_selection_contract`.
- Rama: `codex/pl59bt-llm-selection-contract`.
- Solo se modifican `tests/`, este informe, `plan_mejoras_y_tareas.md` y `RELEVO_DIRECCION_TECNICA.md`.
- No se modifica `src/`, configuración, `.env`, datos ni reportes productivos.
- Versión permanece `0.4.195`.

## Contrato caracterizado

### (a) `llm_selected` — respuesta estructurada

La pregunta "¿qué recomendaciones BUY fueron realmente seleccionadas por el LLM?"
se responde en dos capas:

| Capa | Campo | Significado | Productor |
|---|---|---|---|
| Predecisión | `selected_for_llm` | El candidato fue presentado al LLM para ranking | P-L53 fase A (ranking) |
| Decisión | `llm_considered` | El LLM estuvo activo durante el ciclo | `decision_context_snapshot` en `cycle_runner.py:660-687` |
| Decisión | `llm_selected` | La recomendación fue generada directamente por el agente LLM (`source == "llm"`) | P-L53 fase B (`_attach_phase_b`, línea 383) |
| Decisión | `decision_source` | Fuente normalizada: `llm`, `deterministic_capacity_fill`, `fallback`, etc. | `_normalize_source` en `canonical_selection_ledger.py:150` |

**Hallazgo crítico**: `llm_selected` se deriva exclusivamente de `decision_source`:

```python
# canonical_selection_ledger.py:383
"llm_selected": True if source == "llm" else False if source else None,
```

No existe un evento independiente que registre "el LLM eligió explícitamente
estos 5 candidatos de entre los 20 presentados". La derivación es correcta
pero **no distingue** entre:
- Un candidato que el LLM evaluó y recomendó directamente (`source=llm` → True)
- Un candidato que el LLM rankeó pero fue promovido por capacity fill
  (`source=deterministic_capacity_fill` → False)

En P-L59A, de 366 recomendaciones BUY: 59 habrían tenido `llm_selected=True`
(source=llm), 269 `False` (capacity_fill), 25 `False` (fallback), 13 `False`
(hold_override). Esto es inferible pero no está materializado en producción
porque P-L53 no está desplegado.

### (b) Controles elegibles — respuesta estructurada

La pregunta "¿qué controles elegibles del mismo ciclo quedaron fuera únicamente
por menor rango o límite de capacidad?" se responde mediante el módulo
`comparable_controls.py` (P-L31B/P-L31BR):

| Categoría | Razón | ¿Es control primario? |
|---|---|---|
| `lower_rank` | Candidato same-cycle con menor ranking | **Sí** |
| `capacity_limit` | Cupo de órdenes por ciclo agotado | **Sí** |
| `gate_blocked` | Bloqueado por entry-quality, backtest, adversarial, etc. | No (bloqueado) |
| `risk_blocked` | Rechazado por RiskManager | No (bloqueado) |
| `daily_order_limit` | Límite diario de órdenes alcanzado | No (bloqueado) |
| `low_sample_quota` | Cuota de exploración agotada | No (bloqueado) |
| `strategy_paused` | Estrategia en pausa | No (bloqueado) |
| `duplicate_symbol` | Símbolo duplicado en el ciclo | No (bloqueado) |
| `already_held` | Posición existente abierta | No (bloqueado) |
| `invalid_geometry` | Stop/take/sizing inválido | No (bloqueado) |
| `unknown` | Razón no clasificable | Ni primario ni bloqueado |

La captura se realiza en `cycle_runner.py:1965` mediante `build_comparable_control_sets`,
después de `build_buy_order_plans` y antes de persistir órdenes. Los controles
se adjuntan a la recomendación tratada y se persisten en `signal_learning.features`
vía `attach_comparable_control_sets`.

**Requisitos para ser control primario**:
1. Mismo `cycle_id` y `session_date`.
2. Acción `buy`.
3. Misma `strategy` y `setup`.
4. Elegible en la misma `gate_frontier`.
5. Timestamps predecisión válidos y compatibles.
6. Identidad canónica exacta (`signal_capture_id`/`signal_id`).
7. `selected_for_llm=False` y no recomendado postdecisión.
8. Razón de exclusión exclusivamente `lower_rank` o `capacity_limit`.

## Denominadores y separación de poblaciones

Cada denominador es independiente. Las poblaciones no se solapan ni se suman
sin declararlo:

| Denominador | Definición | P-L53 | P-L54B |
|---|---|---|---|
| Recomendaciones BUY raw | Total de candidatos observados | `raw_count` | `observed_count` |
| Canónicas | Con identidad verificada | `canonical_count` | `canonical_count` |
| `llm_selected=True` | source normalizado = `llm` | campo por fila | campo por fila |
| `llm_selected=False` | source normalizado ≠ `llm` y ≠ None | campo por fila | campo por fila |
| `llm_selected=None` | Sin recomendación | campo por fila | campo por fila |
| `selected_for_llm=True` | Presentado al LLM en ranking | `selected_count` | N/A (funnel) |
| Controles primarios | `lower_rank` + `capacity_limit` | N/A | P-L31B `PRIMARY_REASONS` |
| Controles bloqueados | Gates, riesgo, sizing, etc. | N/A | P-L31B `BLOCKED_REASONS` |
| Planes generados | `planned=True` | `planned_count` | `plans` |
| Órdenes enviadas | `ordered=True` | `ordered_count` | `orders` |
| Fills | `order_status=filled` | N/A | `fills` |

## Validación ejecutada

Ejecutado en el worktree con `PYTHONPATH=src`, `DATA_DIR` temporal, sin red,
broker, LLM, yfinance ni SQLite productiva:

- **45 tests** (`test_p59bt_llm_selected_contract_characterization.py`):
  - 11 tests de semántica `llm_selected` (True/False/None/proxy)
  - 13 tests de elegibilidad de controles (PRIMARY_REASONS vs BLOCKED_REASONS)
  - 5 tests de identidad (BUY vs EXIT, cross-cycle, missing)
  - 5 tests de confusión de fuentes (selected_for_llm vs llm_selected vs llm_considered)
  - 3 tests de idempotencia/conflicto (append-only, hash excluye captured_at)
  - 3 tests de no-mutación/paridad de inputs
  - 3 tests de importación de API pública (P-L53, P-L31B, P-L54B)
  - 2 tests de reproducción P-L59A (inferencia de llm_selected, forbidden fields)
- **Ruff**: `All checks passed!`
- **check_no_nulls.py**: `OK (434 archivos)`
- **git diff --check**: verde

Omitidos por alcance con XNYS abierto: suite completa, smoke, P-L45 33.336,
jobs, postmarket, reconciliación, broker, red, LLM. No se añadieron skips ni xfails.

## Seguridad y paridad

No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
`config.py` ni `.env`. No hubo cambio de política activa, ranking, gates,
sizing, planes, órdenes, exposición o límites. No hubo despliegue, reinicio,
SQLite productiva, broker, red, LLM, yfinance ni push.

## Productor → Evento → Consumidor

| Eslabón | P-L53 (selection ledger) | P-L31B (controles) | P-L54B (capital funnel) |
|---|---|---|---|
| Productor | `build_canonical_selection_ledger` | `build_comparable_control_sets` | `build_capital_deployment_funnel_shadow` |
| Evento | `canonical_selection_ledger:<cycle_id>` | `comparable_control_set` en `learning_observations` | `capital_deployment_funnel_shadow:<cycle_id>` |
| Persistencia | `agent_events` vía `Store` | `learning_observations.features` vía `Store` | `agent_events` vía `Store` |
| Consumidor | `read_canonical_selection_ledger`, CLI | `comparable-control-quality`, `edge_shadow_analysis` | `read_capital_deployment_funnel`, CLI |
| Estado en prod 0.4.185 | **no existe** | `collecting` (sin P-L53/P-L54B) | **no existe** |
| Estado en P-L60R1 | **implementado** (shadow, fail-open) | **implementado** (v2, actual_final_plans) | **implementado** (shadow, fail-open) |

## Defectos y contradicciones detectados

1. **`llm_selected` es un proxy, no un evento independiente** (documentado arriba).
   La pregunta "¿qué candidatos eligió el LLM?" se responde indirectamente:
   `llm_selected=True` = la recomendación vino del agente LLM. Pero el LLM
   también influye en capacity fill (los candidatos llegan rankeados por el LLM),
   y esa influencia no se captura en `llm_selected`.

2. **`llm_selected` para source "other" es False, no None**. Si `_normalize_source`
   no reconoce un texto, lo mapea a `"other"`, y entonces `llm_selected = False`
   en vez de `None`. Esto colapsa "fuente desconocida" con "no fue el LLM". El
   contrato pide que missing sea `null`/`unavailable`, pero aquí se convierte
   implícitamente en `False`.

3. **El eslabón P-L53 fase A requiere `all_candidates` del ranking**. Si el
   ranking no se entrega completo (truncado, parcial), el ledger queda `partial`
   con `truncated_count`. Esto es correcto, pero significa que sin un `phase_a`
   completo (como ocurre cuando P-L53 no está cableado en producción),
   `llm_selected` es `unavailable`.

4. **Controles requieren `actual_final_plans`** (P-L31BR v2). Sin planes finales
   (porque no se generaron, o porque la estrategia está pausada), los controles
   quedan `unavailable` o `partially_comparable`. En producción 0.4.185, donde
   no existe P-L31B, los controles exactos son 0.

## Siguiente lote mínimo

**P-L59B-W**: implementar un lector/consumidor que materialice, para la ventana
P-L59A (20-24 jul), `llm_selected` booleano estructurado y controles elegibles
desde datos históricos, sin modificar el productor ni backfill. Esto exige que
P-L53/P-L54B estén primero desplegados en shadow (actualmente solo existen en
el candidato P-L60R1). Alternativa más conservadora: desplegar P-L60R1 con
validación cerrada completa y luego ejecutar P-L59B-W como consumidor read-only
sobre datos nuevos.

**Precondición**: XNYS cerrado, P-L60R1 validado y desplegado, o alternativamente
un worktree que ejecute P-L53/P-L54B en modo dry-run sobre datos históricos
exportados.

No se ejecuta este siguiente lote desde P-L59B-T.

---

## P-L59B-T: evidencia de tests

### Reproducción de la inferencia P-L59A

```text
Fuente P-L59A → llm_selected inferido en P-L60R1:
  59 source=llm          → True  (recomendación directa del agente LLM)
 269 capacity-fill       → False (deterministic_capacity_fill ≠ "llm")
  25 fallback            → False (fallback ≠ "llm")
  13 hold                → False (hold_override ≠ "llm")
```

### Mapeo de PRIMARY_REASONS

```text
lower_rank      → control primario ✓
capacity_limit  → control primario ✓
gate_blocked    → bloqueado, no control ✗
risk_blocked    → bloqueado, no control ✗
daily_order_limit → bloqueado, no control ✗
low_sample_quota  → bloqueado, no control ✗
strategy_paused   → bloqueado, no control ✗
duplicate_symbol  → bloqueado, no control ✗
already_held      → bloqueado, no control ✗
invalid_geometry  → bloqueado, no control ✗
unknown           → ni primario ni bloqueado (requiere clasificación)
```

### Cobertura de tests adversariales

| Contrato | Tests | Verifica |
|---|---|---|
| `llm_selected = True` (source=llm) | 3 | True para llm/LLM/LLM_REAL |
| `llm_selected = False` (capacity/fallback/hold) | 3 | False para todas las fuentes no-llm |
| `llm_selected = None` (sin recomendación) | 1 | None cuando source es None |
| Proxy, no independiente | 2 | Derivación exclusiva de source |
| selected_for_llm vs llm_selected | 1 | Independencia de campos |
| llm_considered vs llm_selected | 1 | Origen en decision_context_snapshot |
| BUY vs EXIT identidad | 1 | Misma señal, distinta acción |
| Cross-cycle | 1 | Distinto cycle_id |
| Identity missing/ambiguous | 3 | Sin signal_id, candidate_id solo |
| PRIMARY_REASONS | 2 | lower_rank, capacity_limit |
| BLOCKED_REASONS | 8 | gate/risk/strategy/duplicate/held/etc. |
| unknown | 1 | Ni primario ni bloqueado |
| Text source mapping | 2 | Normalización completa, string vacío |
| Idempotencia | 1 | Mismo ID + mismo contenido |
| Conflicto | 1 | Mismo ID + distinto contenido |
| Hash excluye captured_at | 1 | Estabilidad temporal |
| Hash detecta cambios | 1 | Diferentes llm_selected |
| JSON order independence | 1 | Claves en distinto orden |
| No mutación de inputs | 2 | Deep copy antes y después |
| Import API pública | 3 | P-L53, P-L31B, P-L54B |
| Reproducción P-L59A | 1 | 59 True, 307 False |
| Forbidden fields | 1 | Sin fills/P&L/MAE/MFE |
| **Total** | **45** | |
