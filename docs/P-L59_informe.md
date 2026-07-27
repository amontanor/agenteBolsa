# P-L59B-T (corregido) — caracterización del contrato `llm_selected` y elegibilidad de controles

## Dictamen

**`needs_redesign`** para la pregunta (a); **`ready_for_implementation`** para (b).

### Causa

El candidato P-L60R1 (versión `0.4.195`) tiene implementados en shadow los
módulos P-L53 (selection ledger) y P-L54B (capital deployment funnel), que
contienen el campo `llm_selected`. Sin embargo, la caracterización mediante las
APIs reales demuestra que **`llm_selected` es un proxy derivado exclusivamente
de `decision_source`** (`canonical_selection_ledger.py:383`):

```python
"llm_selected": True if source == "llm" else False if source else None,
```

No existe un booleano independiente sellado en la etapa de decisión que registre
"el LLM eligió este candidato de entre los 20 presentados". La derivación es:
- `source == "llm"` → `True` (la recomendación fue generada directamente por el agente LLM)
- `source != "llm"` y `source is not None` → `False` (capacity fill, fallback, hold override)
- `source is None` → `None` (sin recomendación)

Esto **no demuestra selección LLM causal**. Capacity-fill y fallback colapsan en
`False`, aunque son semánticamente distintos (capacity-fill se basa en el ranking
del LLM, fallback no). Fuentes no reconocidas se normalizan a `"other"` y reciben
`False` en vez de `None`/`unavailable`.

Para (b), el contrato de controles elegibles SÍ está correctamente implementado:
`PRIMARY_REASONS = {lower_rank, capacity_limit}` en `comparable_controls.py`
(P-L31B, **desplegado en producción `0.4.185`**) define explícitamente qué
candidatos same-cycle son controles primarios y cuáles son bloqueados por gates,
riesgo, sizing, duplicados, etc. La captura usa identidad exacta
(`cycle_id + action + signal_capture_id/signal_id`), no símbolo/fecha ni texto.

### Diferencia clave con producción

- **P-L31B** (`comparable_controls.py`): **desplegado** en producción `0.4.185`.
  Cableado en `cycle_runner.py:1965`, `main.py:2545` (CLI
  `comparable-control-quality`), y `storage.py:2822`
  (`attach_comparable_control_set`). El digest y health lo consumen.
- **P-L53** (`canonical_selection_ledger.py`): **NO desplegado**. Existe en
  candidato P-L60R1 como shadow. Sin él, `llm_selected` no tiene productor
  durable en producción.
- **P-L54B** (`capital_deployment_funnel_shadow.py`): **NO desplegado**. Existe
  en candidato P-L60R1 como shadow.

En producción `0.4.185`, `llm_selected` es `unavailable` porque P-L53 no existe.
Los controles exactos son 0 porque sin P-L53/P-L54B no hay ledger que los
materialice, aunque P-L31B sí está presente y captura control sets cuando hay
planes finales.

## Alcance y estado

- Fecha de ejecución: 2026-07-27, 19:05 Europe/Madrid (hora real del entorno).
- **XNYS ABIERTO** (sesión 2026-07-27, cierre 22:00 CEST).
- Base exacta: `70de34011b74403281c32673c32947cab0ee0952`, tree `1d960a6723c0f2fbe5bc4afc72c7df08284c43d1`.
- Candidato: P-L60R1, versión `0.4.195`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59bt_llm_selection_contract`.
- Rama: `codex/pl59bt-llm-selection-contract`.
- HEAD final: `a169b2f2` (commits `e32d283d`, `f9e1994c` + `a169b2f2` correctivo).
- Solo se modifican `tests/`, este informe, `plan_mejoras_y_tareas.md` y `RELEVO_DIRECCION_TECNICA.md`.
- No se modifica `src/`, configuración, `.env`, datos ni reportes productivos.
- Versión permanece `0.4.195`.

## Validación ejecutada

Ejecutado con `PYTHONPATH=src`, sin red, broker, LLM, yfinance ni SQLite
productiva:

| Artefacto | Resultado |
|---|---|
| `tests/test_p59bt_llm_selected_contract_characterization.py` | **29 passed** (0.44s) |
| Ruff | 0 errores (auto-fixed) |
| `check_no_nulls.py` | OK (434 archivos) |
| `git diff --check` | verde |

**Cero helpers duplicados**: todas las pruebas invocan exclusivamente APIs
reales del candidato (`build_canonical_selection_ledger`,
`match_same_cycle_controls`, `persist_canonical_selection_ledger`,
`read_canonical_selection_ledger`, `stable_content_hash`,
`build_comparable_control_sets`, `validate_comparable_control_set`,
`build_unavailable_control_set`). Los builders (`_candidate`, `_phase`, `_rec`,
`_lineage`) son fixtures mínimos sin lógica de decisión. Cero asserts
tautológicos.

**Cobertura de tests contra APIs reales**:

| Grupo | Tests | APIs ejercitadas |
|---|---|---|
| (A) `llm_selected` proxy/brecha | 6 | `build_canonical_selection_ledger` con `recommendations` de distintas fuentes |
| (B) Colisión rec_id same-cycle | 1 | `build_canonical_selection_ledger` con dos recs misma señal |
| (C) BUY/EXIT, cross-cycle, missing | 4 | `build_canonical_selection_ledger` con identidades variadas |
| (D) Persistencia Store real | 5 | `persist_canonical_selection_ledger`, `read_canonical_selection_ledger` con `Store(tmp_path)` |
| (E) `match_same_cycle_controls` | 3 | API real con fixtures controladas |
| (F) `build_comparable_control_sets` | 6 | `PRIMARY_REASONS`, `BLOCKED_REASONS`, `validate`, `build_unavailable` |
| (G) Paridad/dimensiones | 4 | Campos independientes, forbidden fields, imports |

## Productor → Evento → Consumidor

| Eslabón | P-L53 (selection ledger) | P-L31B (controles) | P-L54B (capital funnel) |
|---|---|---|---|
| Productor | `build_canonical_selection_ledger` | `build_comparable_control_sets` | `build_capital_deployment_funnel_shadow` |
| Evento | `canonical_selection_ledger:<cycle_id>` | `comparable_control_set` en `learning_observations` | `capital_deployment_funnel_shadow:<cycle_id>` |
| Persistencia | `agent_events` vía `Store.record_canonical_selection_ledger` | `learning_observations.features` vía `Store.attach_comparable_control_set` | `agent_events` vía `Store` |
| Consumidor | `read_canonical_selection_ledger`, CLI, digest | `comparable-control-quality --json` (CLI en `main.py:2545`), `edge_shadow_analysis` | `read_capital_deployment_funnel`, CLI |
| Estado en prod `0.4.185` | **no existe** | **desplegado** (cableado en `cycle_runner.py`, `main.py`, `storage.py`) | **no existe** |
| Estado en P-L60R1 | **implementado** (shadow, fail-open) | **desplegado** (heredado de prod) | **implementado** (shadow, fail-open) |

## Defectos y brechas

1. **`llm_selected` es proxy, no selección causal** (BREACH documentada):
   derivado exclusivamente de `decision_source`. No existe evento independiente
   de selección LLM. `capacity_fill` y `fallback` colapsan en `False`.

2. **Colisión de `recommendation_id` en P-L53**: dos recomendaciones con la
   misma señal y distinto `recommendation_id` colisionan en el ledger
   (sobrescribe). P-L54B-R1 lo corrige añadiendo `recommendation_id` a la
   identidad de decisión.

3. **Source desconocida → `other` → `llm_selected=False`**: fuentes no
   reconocidas se colapsan a `False` en vez de conservarse como
   `None`/`unavailable`.

4. **P-L59A no es reconstruible retrospectivamente**: sin P-L53/P-L54B en
   producción durante la ventana 20-24 jul, no existe evento durable del que
   extraer `llm_selected`. No hay autoridad para materializarlo desde fuentes
   textuales (`source=llm` en texto no estructurado).

## Seguridad y paridad

No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
`config.py` ni `.env`. No hubo cambio de política activa, ranking, gates,
sizing, planes, órdenes, exposición o límites. No hubo despliegue, reinicio,
SQLite productiva, broker, red, LLM, yfinance ni push. Paridad de trading/
riesgo/ejecución preservada.

## Siguiente lote mínimo

Para responder causalmente si una recomendación fue realmente seleccionada por
el LLM, haría falta un evento estructurado independiente de `decision_source`
que registre el acto de selección en la etapa de decisión. Esto requeriría
**rediseño del productor** (nuevo campo booleano sellado en
`decision_context_snapshot` o similar), no solo consumidor. El lote
correspondiente sería un **P-L59C** de implementación con contrato explícito.

Alternativa inmediata: aceptar la semántica actual (`llm_selected` = "fuente de
la recomendación fue el LLM", no "el LLM eligió este candidato") como
suficiente para los fines de observabilidad, y desplegar P-L60R1 para que los
datos nuevos queden registrados. Esto requiere validación cerrada y autorización
del operador.

**No se ejecuta ningún siguiente lote desde P-L59B-T.**
