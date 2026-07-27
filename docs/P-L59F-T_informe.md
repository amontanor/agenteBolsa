# P-L59F-T — Caracterizacion y diseno de la colision recommendation_id en P-L53

## Dictamen

**`ready_for_implementation`** (caracterizacion cerrada; diseno recomendado; sin
implementacion ni cambios en src).

La colision existe, esta reproducida con APIs reales y es una consecuencia
directa del contrato de identidad del CLS (`(cycle_id, action, canonical_id)`)
frente a dos decisiones distintas para el mismo candidato. El diseno B
(`decision_rows` separado) es la opcion recomendada.

## Candidato

- **Base**: P-L59D-D `520559c614a68199cef4a9add982cd5930661757`, tree `e3c80ba158ad3f8b789bf370ba445a0a077257a2`, v0.4.196
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59ft_recommendation_identity_design`
- **Rama**: `codex/pl59ft-recommendation-identity-design`
- **HEAD**: `34a70248` (test commit)
- **Tree**: `unavailable` hasta commit final
- **Version**: `0.4.196` (sin bump; solo tests/docs)
- **Hora**: 2026-07-27 21:37-21:50 CEST, XNYS abierto

## Causa raiz

### Identidad del CLS

En `canonical_selection_ledger.py`, la funcion `_identity` (linea 110) define
la clave canonica como:

```
(cycle_id, action, signal_capture_id or signal_id)
```

Esta es una identidad **candidato-centrica**: un candidato en el universo es
unico por su senal, accion y ciclo. El `by_key` en `_attach_phase_b` (linea
361) indexa las `candidate_rows` por esta misma clave.

Cuando dos recomendaciones del mismo ciclo comparten la misma identidad
canonica de senal y accion (ej. dos BUY para TSLA en el mismo ciclo), ambas
mapean al mismo `target` en `by_key`. La segunda sobreescribe a la primera
mediante `target.update(...)` (lineas 384-393), produciendo un comportamiento
**last-wins silencioso**.

### Donde se asigna recommendation_id

En `cycle_runner.py:1805`: `recommendation_id = new_id("rec")` — se asigna
**antes** de gates, planes y persistencia del ledger. Cada `TradeRecommendation`
en `reviewed_recommendations` tiene su propio `recommendation_id`. La colision
ocurre exclusivamente en el ledger shadow (P-L53), no en la ruta activa de
decision.

### Contraste con P-L54

`capital_deployment_funnel_shadow.py:120-132` define:

```python
signal_key = (external_cycle, action, canonical_signal)
decision_key = signal_key + (recommendation_id,)
```

P-L54 incluye `recommendation_id` en `decision_key`, por lo que **NO sufre esta
colision**. Dos recomendaciones con distinto `recommendation_id` producen dos
`decision_key` distintas y dos filas independientes.

### Contraste con _recommendation_identity

`cycle_runner.py:1873-1879` define otra identidad distinta:

```python
(symbol.upper(), action.lower(), signal_id)
```

Esta usa `symbol` en lugar de `cycle_id`, creando una tercera variante de
identidad para el mismo dominio. La diversidad de claves de identidad es parte
del problema de diseno.

## Caracterizacion (17 tests)

Archivo: `tests/test_p59ft_recommendation_identity_design.py`

### 1. Reproduccion de la colision (3 tests)
- `test_two_recommendations_same_identity_last_wins`: dos BUY mismo candidato
  → solo sobrevive la segunda (`rec:second`, `llm_selected=False`)
- `test_two_recommendations_same_identity_reverse_order_last_wins`: orden
  invertido confirma last-wins, no first-wins ni merge
- `test_first_recommendation_evidence_lost`: sin warning de colision entre
  recomendaciones; la primera decision se pierde en silencio

### 2. ID + contenido (2 tests)
- `test_idempotent_same_recommendation_id_and_content`: mismo ID + mismo
  contenido → `idempotent` en Store
- `test_same_recommendation_id_different_content_creates_conflict`: mismo
  event_id + distinto hash → `conflict` append-only

### 3. BUY vs EXIT (2 tests)
- `test_buy_and_exit_same_signal_preserved_separately`: action es parte de la
  clave → no colisionan
- `test_two_buys_one_exit_same_signal`: 2 BUY colisionan a 1 fila; EXIT separado

### 4. Missing recommendation_id (3 tests)
- `test_missing_recommendation_id_stays_none`: sin ID → `None`
- `test_mixed_legacy_and_new_recommendation_ids`: legacy sin ID + nuevo con ID
- `test_multiple_recommendations_all_missing_ids`: todas sin ID → `None`

### 5. Productor/wiring (2 tests)
- `test_recommendation_id_exists_before_ledger`: `new_id("rec")` en
  `cycle_runner.py:1805` asigna ANTES del ledger
- `test_reviewed_recommendations_preserve_two_decisions_for_same_signal`: la
  lista `reviewed_recommendations` conserva ambas decisiones; la colision es
  solo en la telemetria shadow

### 6. Inventario de consumidores (1 test)
- `test_consumer_inventory_is_documented`: 13 consumidores catalogados con
  modulo, expectativa estructural y riesgo de rotura

### 7. Impacto de expansion (2 tests)
- `test_expanding_candidate_rows_changes_denominators`: expansion 1:1
  duplicaria `canonical_count` y romperia `match_same_cycle_controls`
- `test_overwriting_singular_loses_decision_authority`: sobrescribir pierde
  la autoridad causal (LLM → capacity-fill)

### 8. Stage order (1 test)
- `test_stage_order_recommendation_id_assigned_before_ledger`: el
  `recommendation_id` se asigna antes de gates y planes; la ruta activa no
  se ve afectada por la colision en el shadow

### Diseno (1 test documental)
- `test_design_options_comparison`: compara A/B/C/D y recomienda B

## Diseno recomendado: Opcion B — `decision_rows` separado

### Justificacion

La opcion B es la unica que:
1. Preserva `candidate_rows` con semantica candidato-centrica (1 fila por
   identidad canonica de senal)
2. Anade `decision_rows` como array separado, una entrada por cada
   `recommendation_id` distinto
3. Mantiene compatibilidad hacia atras: los consumidores que solo leen
   `candidate_rows` no se rompen
4. Permite denominadores separados (`candidate_count`, `recommendation_count`,
   `conflict_count`)
5. Sigue el precedente de P-L54 que ya incluye `recommendation_id` en
   `decision_key`

### Schema propuesto (v2)

```json
{
  "schema_version": "p-l53b.canonical-selection-ledger.v2",
  "candidate_rows": [
    {
      "identity_key": "cycle-A|buy|capture:tsla:buy",
      "recommended": true,
      "decision_ids": ["rec:first", "rec:second"]
    }
  ],
  "decision_rows": [
    {
      "decision_id": "rec:first",
      "identity_key": "cycle-A|buy|capture:tsla:buy",
      "llm_selected": true,
      "decision_source": "llm",
      "confidence": 0.90,
      "recommended_at": "..."
    },
    {
      "decision_id": "rec:second",
      "identity_key": "cycle-A|buy|capture:tsla:buy",
      "llm_selected": false,
      "decision_source": "llm",
      "confidence": 0.60,
      "recommended_at": "..."
    }
  ],
  "denominators": {
    "candidate_count": 1,
    "recommendation_count": 2,
    "conflict_count": 0
  }
}
```

### Cambios minimos

Archivos potenciales de implementacion (solo propuesta, sin modificar):

| Archivo | Cambio |
|---|---|
| `canonical_selection_ledger.py` | `_attach_phase_b` construye `decision_rows`; `candidate_rows` retiene `recommended`/`decision_ids` pero no `recommendation_id`/`llm_selected`/`decision_source` |
| `canonical_selection_ledger.py` | `_denominators` anade `candidate_count`, `recommendation_count`, `conflict_count` |
| `canonical_selection_ledger.py` | `read_canonical_selection_ledger` lee ambos arrays; schema v2 |
| `test_p53b_selection_ledger_shadow.py` | Actualizar fixtures y aserciones |
| `test_p59c_llm_selected_authority.py` | Adaptar aserciones a `decision_rows` |
| `test_p59ft_recommendation_identity_design.py` | Anadir tests de implementacion |

### No requiere

- Migracion de datos ni backfill (eventos existentes en v1 permanecen legacy)
- Cambios en `storage.py` (misma tabla `agent_events`, mismo `event_type`)
- Cambios en `cycle_runner.py` (el productor ya genera `recommendation_id`)
- Cambios en P-L54 (ya usa su propio schema con `recommendation_id` en la clave)
- Cambios en gates, planes, ordenes, sizing o politica

### Versioning

- Schema: `p-l53b.canonical-selection-ledger.v2` (nuevo `schema_version`)
- `revision`: 2
- Codigo: version `0.4.197` reservada (NO asignada aqui; solo propuesta)

### Criterios de aceptacion

1. `candidate_rows` preserva 1 fila por `(cycle_id, action, canonical_id)`
2. `decision_rows` contiene 1 fila por `recommendation_id` distinto
3. `recommendation_count == len(decision_rows)`; `candidate_count == len(candidate_rows verified)`
4. `recommended` en `candidate_rows` es `True` si existe al menos una decision
5. `llm_selected`/`decision_source`/`confidence` viven en `decision_rows`, no en `candidate_rows`
6. Consumidores existentes que leen `candidate_rows[*]["recommendation_id"]` se adaptan a `decision_rows`
7. Idempotencia y conflictos por `event_id` sin cambios
8. `match_same_cycle_controls` no se rompe (itera `candidate_rows` sin duplicados)
9. `match_mature_forward_outcome` no se rompe (join por `identity_key` en `candidate_rows`)
10. Tests: 17 de caracterizacion + nuevos de implementacion; Ruff/NUL/diff verdes

## Gates

| Gate | Resultado |
|---|---|
| Ruff test file | All checks passed! |
| `check_no_nulls.py` | OK (436 archivos) |
| `git diff --check` | Sin salida (limpio) |
| P-L59F tests | 17 passed en 0.39s |
| `py_compile` | Omitido (sin cambios en src) |
| `validate-agent-config` | Omitido (sin cambios en src) |
| `kernel-status` | Omitido (XNYS abierto, sin cambios src) |

### Gates omitidos (XNYS abierto)

Suite completa, smoke, benchmark, P-L45 33.336, kernel productivo.
Sin broker, red, LLM, SQLite productiva, reinicio, merge, despliegue o push.

## Archivos modificados

Solo tests y docs en el worktree aislado:

| Archivo | Cambio |
|---|---|
| `tests/test_p59ft_recommendation_identity_design.py` | Nuevo (+692 lineas, 17 tests) |
| `docs/P-L59F-T_informe.md` | Nuevo (este informe) |
| `docs/plan_mejoras_y_tareas.md` | Actualizacion P-L59F-T |
| `docs/RELEVO_DIRECCION_TECNICA.md` | Actualizacion secuencia |

## No broker/red/LLM/SQLite productiva

Confirmado. Tests con `Store` y `DATA_DIR` temporal. Sin SQLite productiva,
sin red, sin broker, sin LLM operativo, sin yfinance, sin escrituras en
produccion.

## Siguiente paso

P-L59F-I: implementacion de `decision_rows` en `canonical_selection_ledger.py`
segun el diseno B, solo en worktree aislado mientras XNYS siga abierto.
Requiere:
- XNYS abierto (trabajo aislado sin despliegue)
- Mismo worktree y base
- Sin cambios en produccion
- Alcance: `canonical_selection_ledger.py` + tests + docs
