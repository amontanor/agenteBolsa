# P-L59C-R6 — autoridad prospectiva estructurada de llm_selected

## Dictamen

**`ready_for_integration_rehearsal`** (R6 corregido).

Correcciones acumuladas:

### P-L59C (base)
- `TradeRecommendation.llm_selected`, productor, carrier, P-L53 sin proxy

### R1: validacion runtime + paridad basica + fail-open
### R2: `normalize_llm_selected` en `decision_context.py`
### R3: `new_id` congelado, normalizacion minima v1, aserciones negativas
### R4: normalizador context-aware con CCS (propagacion recursiva incorrecta corregida en R5)
### R5: strip solo en raiz DCS/CCS (no propaga a subbloques nested)

### R6 (actual)
- **List branch `inside_dcs=False`**: items dict en listas anidadas dentro de
  DCS/CCS conservan sus `content_hash`/`captured_at` intactos. `llm_selected`
  global sigue retirandose. Test unitario explicito de listas (`controls`
  dentro de DCS con items que tienen `content_hash`/`llm_selected`/`captured_at`).
- **Docs**: titulo R6, commits reales R5 (`4b1c1982`, `c50f23ae`), archivos R6,
  cifras R6 (15 integration), hora obtenida al ejecutar.

## Candidato

- **Base**: P-L59B-T-R5 `49059f18`, version `0.4.195`
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59c_llm_selection_producer`
- **Rama**: `codex/pl59c-llm-selection-producer`
- **Version**: `0.4.196`
- **Hora**: 2026-07-27 CEST (20:30 direccion), XNYS abierto

### Commits

P-L59C: `b6d7c176`, `c599a335`, `0dce08d8`, `a6e23cda`
R1: `86120c43`, `40768a22`, `e777dbd8`
R2: `f9fff29c`, `4508cb70`, `88c10a8d`, `cca19660`
R3: `6ab89896`, `ea42ac26`
R4: `d4acf339`, `cad0592f`
R5: `4b1c1982`, `c50f23ae`
R6: `26496ba2` (test), `e00dbb5a` (docs), R6D commit (docs final)

## Archivos modificados en R6

| Archivo | Cambio |
|---|---|
| `tests/test_market_cycle_timing_integration.py` | list branch `inside_dcs=False` + test unitario listas |
| `docs/P-L59_informe.md` | R6 titulo, commits R5 reales, cifras R6 |
| `docs/plan_mejoras_y_tareas.md` | R6 |
| `docs/RELEVO_DIRECCION_TECNICA.md` | R6 |

## Pruebas

- **R2 baseline**: 278 tests (9 archivos disjuntos), 0 fallos
- **R6 post-cambio**: `test_market_cycle_timing_integration.py` **15 passed**
  (incluye strip unitario dicts + nested blocks + listas + paridad completa)
- Ruff: 0 errores, NUL: OK, diff: OK

## Gates omitidos (XNYS abierto)

Suite completa, smoke, benchmark, P-L45 33.336, kernel productivo.

## Brecha P-L53 recommendation_id

Sigue abierta. No corregida.

## Siguiente paso

P-L59E: validacion cerrada de P-L59D (requiere XNYS cerrado + precondiciones).

---

# P-L59D — rehearsal de integracion (ejecutado)

## Dictamen

**`ready_for_closed_market_full_validation`**.

Merge `--no-ff` del candidato P-L59C-R6D sobre la base P-L60R1 sin conflictos.
La ruta activa de P-L60R1 (UI portfolio + measurement) se conserva intacta;
los cambios de P-L59C conviven sin sobreescribir ni colisionar.

## Candidato

- **Base**: P-L60R1 `70de34011b74403281c32673c32947cab0ee0952`, version `0.4.195`
- **Integrado**: P-L59C-R6D `30b6b76b05b55f6b879b5218d8094fef2f6ece29`, version `0.4.196`
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59d_llm_selected_rehearsal`
- **Rama**: `codex/pl59d-llm-selected-rehearsal`
- **HEAD**: `4524cbe38896b5d451f0ff34450855f4b3f7988b`
- **Tree**: `661216b322138324475c0aa989d0ce42a586b822` (final documental; tree del merge `9009c7f2`: `ad69264e`, identico a P-L59C-R6D)
- **Merge `9009c7f2`**: tree `ad69264ecbbc0d8764a5a5ce722e38d117d98e8f`, padres `70de3401` (P-L60R1) y `30b6b76b` (P-L59C-R6D)
- **Hora**: 2026-07-27 ~21:32 CEST, XNYS abierto
- **Version**: `0.4.196`

### Commits

| Commit | Tipo | Descripcion |
|---|---|---|
| `9009c7f2` | merge | P-L59D: rehearsal de integracion --no-ff de P-L59C-R6D sobre P-L60R1 |
| `4524cbe3` | docs | P-L59D informe, plan, relevo y QA evidence |

### Parents

- Parent 1 (base): `70de34011b74403281c32673c32947cab0ee0952` (P-L60R1)
- Parent 2 (candidato): `30b6b76b05b55f6b879b5218d8094fef2f6ece29` (P-L59C-R6D)

## Archivos fusionados

| Archivo | Cambio vs P-L60R1 |
|---|---|
| `src/agente_bolsa/__init__.py` | version 0.4.196 + linea P-L59C |
| `src/agente_bolsa/cycle_runner.py` | +2 lineas: `llm_selected` en DCS |
| `src/agente_bolsa/models.py` | +1 campo: `llm_selected: bool\|None` |
| `src/agente_bolsa/tools/canonical_selection_ledger.py` | +8/-3: consumo desde snapshot, `normalize_llm_selected` |
| `src/agente_bolsa/tools/decision_context.py` | +18: `normalize_llm_selected`, inclusion en `build_decision_context_snapshot` |
| `src/agente_bolsa/tools/trade_decision.py` | +3: productor fija True/False |
| `docs/P-L59_informe.md` | nuevo (P-L59C) |
| `docs/plan_mejoras_y_tareas.md` | actualizaciones P-L59C |
| `docs/RELEVO_DIRECCION_TECNICA.md` | actualizaciones P-L59C |
| `tests/test_market_cycle_timing_integration.py` | +613: paridad, strip, listas |
| `tests/test_p53b_selection_ledger_shadow.py` | +22: fixtures con llm_selected |
| `tests/test_p59bt_llm_selected_contract_characterization.py` | nuevo (+603) |
| `tests/test_p59c_llm_selected_authority.py` | nuevo (+774) |

Ningun archivo de P-L60R1 fue sobreescrito. Los cambios de P-L60R1 (`web_app.py` para UI portfolio, etc.) no aparecen en el diff porque P-L59C no los toca.

## Protegidos

Los 5 archivos versionados son objetos Git identicos contra base P-L60R1 (`70de3401`) y contra produccion (`24537e8`):

- `src/agente_bolsa/kernel.py` ✓
- `src/agente_bolsa/tools/broker.py` ✓
- `src/agente_bolsa/tools/execution.py` ✓
- `src/agente_bolsa/tools/risk.py` ✓
- `src/agente_bolsa/config.py` ✓

`.env`: no modificado por el lote; hash/equivalencia unavailable (no se lee ni revela contenido del secreto).

## QA

### Bateria focal (10 archivos, 300 tests)

Comando: `pytest tests/test_p59c_llm_selected_authority.py tests/test_p59bt_llm_selected_contract_characterization.py tests/test_market_cycle_timing_integration.py tests/test_p53b_selection_ledger_shadow.py tests/test_decision_context_snapshot.py tests/test_version_policy.py tests/test_comparable_controls.py tests/test_comparable_controls_p31br.py tests/test_gate_evaluation_snapshot.py tests/test_trade_decision.py`

- **Resultado**: 300 passed en 65.53s
- **PYTHONPATH**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59d_llm_selected_rehearsal\src`
- **DATA_DIR**: temporal, sin SQLite productiva

### Pruebas especificas

1. **Productor LLM/fallback/capacity True/False/None**: cubierto por `test_producer_llm_dict_sets_llm_selected_true`, `test_producer_confidence_missing_still_true`, `test_ledger_llm_selected_true/false/none_from_snapshot`
2. **Malformed -> None antes de hash/persist**: cubierto por `test_normalize_llm_selected_*` (9 variantes: int, str, list, dict, float, etc.) y `test_snapshot_malformed_int_string_degrades_to_none`
3. **P-L53 Store idempotencia/conflicto**: cubierto por `test_persist_and_read_llm_selected_*`, `test_persist_conflict_different_llm_selected`
4. **`_auto_paper_trade` paridad IDs/hashes anidados**: cubierto por `test_market_cycle_timing_integration.py` con strip context-aware + nested block preservation
5. **Fail-open del ledger**: cubierto por `test_fail_open_selection_ledger_does_not_block_route` (fuerza fallo interno del build mediante wrapper real, preserva submit/store)
6. **Version policy**: `tests/test_version_policy.py` 1 passed en 0.20s

### Gates estaticos

| Gate | Resultado |
|---|---|
| Ruff `src tests` | All checks passed! |
| `check_no_nulls.py` | OK (435 archivos) |
| `git diff --check` | Sin salida (limpio) |
| `py_compile` (6 archivos afectados) | OK |
| `validate-agent-config --json` | `ok: true`, 0 errors, 0 warnings |
| `kernel-status` | Omitido (XNYS abierto, kernel productivo) |

### Gates omitidos (XNYS abierto)

Suite completa, smoke, benchmark P-L53/P-L54, P-L45 33.336, kernel productivo, postmarket, reconciliacion, broker, red, LLM, yfinance, SQLite productiva, despliegue, reinicio, push.

## Brecha P-L53 recommendation_id

Sigue abierta. P-L53 colisiona dos `recommendation_id` de la misma senal/accion. No corregida en este rehearsal. Documentada en linea 64 de este informe.

## No broker/red/LLM/yfinance/SQLite productiva / no escrituras en produccion

Confirmado. Los tests usan `Store` con `DATA_DIR` temporal, sin SQLite productiva. Sin escrituras en produccion. Sin conexiones externas. Sin jobs operativos lanzados. El worktree recibio merge y docs (escrituras aisladas en el candidato, no en produccion).

## Siguiente paso

P-L59E: validacion cerrada completa de P-L59D. Requiere:
- XNYS cerrado
- Postmarket terminal `completed` o `failed`
- Sin leases ni jobs activos
- Suite completa, smoke aislado, benchmark P-L53/P-L54, P-L45 33.336
- Kernel productivo sellado
- Sin despliegue aun (solo validacion)

---

# P-L59F-T-R2 — caracterizacion final y contrato de implementacion (27-jul-2026)

## Dictamen

**`ready_for_implementation`** (R2 final).

## Candidato

- **Base**: P-L59D-D `520559c6`, tree `e3c80ba`, v0.4.196
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59ft_recommendation_identity_design`
- **Rama**: `codex/pl59ft-recommendation-identity-design`
- **HEAD R2 tests**: `7af01727`
- **Version**: `0.4.196` (sin bump; solo tests/docs)
- **Hora**: 2026-07-27 CEST, XNYS abierto

## Correcciones acumuladas (R1 + R2)

### 1. Same recommendation_id real
4 tests: same/different-content dentro de un build, conflicto Store entre
builds, idempotencia entre builds.

### 2. Wiring real con _auto_paper_trade (R2)
`test_wiring_two_recs_same_lineage_ids_assigned_ordered`: DOS TradeRecommendation
entran SIN recommendation_id preasignado y con MISMO decision_lineage.
`_auto_paper_trade` asigna IDs via `new_id("rec")`. `build_order_plans`
construye desde los gated recibidos (con IDs ya asignados). Registra orden:
request -> review -> entry/backtest gates -> plans -> 2 submits -> P-L53 -> P-L54.
Afirma coherencia: IDs en gated == IDs en P-L53 == IDs en P-L54.

### 3. P-L54 API real
3 tests: distinto rec_id -> 2 filas; same rec_id same content -> 1 fila;
same rec_id different content -> ambiguous.

### 4. Tests tautologicos eliminados (R2)
`test_recommendation_id_assigned_before_gates_and_ledger` eliminado; el wiring
test es la evidencia. Inventario en informe.

### 5. Expansion real sin cambiar identidad (R2)
`test_expansion_same_identity_duplicated_inflates_counters`: construye una
candidate_row, duplica LA MISMA desde el resultado del ledger (misma identity_key,
distinto recommendation_id). Demuestra recommended_count inflado (1 vs 2) y
exclusion same_treatment en match_same_cycle_controls.

### 6. Contrato de implementacion completo

#### candidate_rows v2 — resumen candidato-centrico

Cada candidato tiene UNA entrada. Campos singulares
(`recommendation_id`/`llm_selected`/`decision_source`/`confidence`) solo se
rellenan cuando hay exactamente una decision canonica y cero
legacy/conflict/ambiguous.

| Estado | decision_summary_status | Singular fields | decision_ids | decision_rows count |
|---|---|---|---|---|
| 0 observed | `unavailable` | null | [] | 0 |
| 1 canonical | `canonical` | valor real | [id] | 1 |
| >1 canonical, distinto rec_id | `ambiguous` | null | [id1, id2, ...] | >=2 |
| 1 missing-ID | `partial` | null (sin ID) | [] | 1 (unavailable) |
| multiple missing-ID | `ambiguous` | null | [] | >=2 (unavailable) |
| 1 canonical + 1 missing-ID | `ambiguous` | null | [id, null] | 2 |
| same-ID duplicate (idempotent) | `canonical` | valor real | [id] | 1 |
| same-ID conflict (different content) | `ambiguous` | null | [id] | 1 canonical + 1 conflict |

Booleans agregados en candidate_rows: `recommended`/`planned`/`ordered` = True
si AL MENOS una decision asociada tiene esa etapa.

#### decision_rows — una entrada por decision

Cada decision es una fila independiente. Clave: `(cycle_id, action, canonical_signal, recommendation_id)`.

Campos:

| Campo | Origen | Nota |
|---|---|---|
| `decision_id` | recommendation_id | PK de decision |
| `cycle_id` | lineage | mismo que candidate_row |
| `action` | lineage | buy/exit |
| `signal_capture_id` | lineage | identidad canonica |
| `signal_id` | lineage | fallback canonico |
| `candidate_id` | lineage | vinculo con candidate_row |
| `llm_selected` | P-L59C producer | bool, null=legacy |
| `decision_source` | source normalizado | llm/capacity_fill/fallback |
| `confidence` | TradeRecommendation | float |
| `decision_context_snapshot` | snapshot completo | hash, market_state, gates |
| `plan_id` | plan_record | unido por recommendation_id |
| `plan_status` | plan_record | PENDING/SUBMITTED/REJECTED |
| `broker_order_id` | ordered_record | unido por plan_id |
| `order_status` | ordered_record | accepted/filled/rejected |
| `rejection_reason` | rejected_order_plans | unido por recommendation_id/plan_id |
| `decision_lineage_status` | `verified`/`partial`/`unavailable` | calidad de identidad |

Nunca unir por simbolo o fecha.

#### Hash de decision row

- `content_hash`: SHA256 de decision_row completo excluyendo `captured_at` y
  `content_hash` propio.
- Mismo ID + mismo hash semantico -> idempotente (no-op en persistencia).
- Mismo ID + distinto hash -> conservar original, crear conflict row separada
  (no canonica), `conflict_count++`.
- `captured_at` no rompe idempotencia (excluido del hash).

#### Bounded memory

- `detail_total`: total de decision_rows antes de truncar.
- `detail_persisted`: filas persistidas (<= limit).
- `truncated_count`: `detail_total - detail_persisted`.
- `conflict_count`: conflict rows (mismo ID, distinto hash).
- Orden estable: por identity_key + decision_id.
- Reutilizar DEFAULT_DETAIL_LIMIT (actualmente en P-L54, ~1000).
- No backfill ni VACUUM.

#### Denominadores separados (v2)

| Denominador | Definicion |
|---|---|
| `candidate_count` | candidate_rows con identity_status=verified |
| `recommendation_observed` | recomendaciones procesadas (total) |
| `recommendation_canonical` | decision_rows con decision_identity=verified |
| `recommendation_conflict` | same-rec_id different-content |
| `recommendation_unavailable` | sin recommendation_id o identidad parcial |

#### Readers v1/v2 y consumidores

| Consumidor | Lee | v2 Adaptacion |
|---|---|---|
| `read_canonical_selection_ledger` | candidate_rows, decision_rows | Nuevo array decision_rows; candidate_rows mantiene API |
| `canonical_selection_ledger_digest` | via read | Transparente |
| `match_same_cycle_controls` | candidate_rows identity_key | Sin cambio (candidate_rows 1:1) |
| `match_mature_forward_outcome` | candidate_rows identity_key | Sin cambio |
| CLI `canonical-selection-ledger` | digest JSON | Transparente |
| P-L59C authority tests | candidate_rows llm_selected | Leer de decision_rows en v2 |
| `test_llm_selected_*` (tests) | candidate_rows llm_selected | Adaptar aserciones a decision_rows |
| P-L54 funnel shadow | decision_key propio | YA independiente |
| P-L48B telemetry | SQL trade_recommendations | Sin cambio |
| Post-market review | SQL trade_recommendations | Sin cambio |
| Exec quality P-L33B | payload recommendation_id | Sin cambio |

Consumidores que **si requieren adaptacion** a v2:
- `test_p59c_llm_selected_authority.py`: lee `candidate_rows[0]["llm_selected"]`;
  debe leer `decision_rows[0]["llm_selected"]`.
- `test_p59bt_llm_selected_contract_characterization.py`: idem.

#### P-L54 evidencia limitada a tests reales

- IDs distintos: dos filas en details, recommendations_generated=2.
- Same-ID same-content: una fila (idempotente).
- Same-ID different-content: dos filas identity_ambiguous.

## Pruebas R2

- **17 passed** en 0.92s (colision + same-rec_id + BUY/EXIT + missing IDs
  + wiring real + P-L54 API + expansion)
- Ruff: All checks passed
- NUL: OK (436 archivos)
- git diff --check: clean

## Gates omitidos (XNYS abierto)

Suite completa, smoke, benchmark, P-L45 33.336, kernel, validate-agent-config,
py_compile. Sin cambios en src. Sin broker/red/LLM/SQLite productiva.

## Archivos modificados

| Archivo | Cambio R2 |
|---|---|
| `tests/test_p59ft_recommendation_identity_design.py` | R2: wiring sin rec_id preasignado, expansion misma identidad, stage local eliminado |
| `docs/P-L59_informe.md` | Contrato de implementacion completo (R2) |
| `docs/plan_mejoras_y_tareas.md` | Limpiado (R2 final) |
| `docs/RELEVO_DIRECCION_TECNICA.md` | Limpiado (R2 final) |
| `docs/P-L59F-T_informe.md` | ELIMINADO (consolidado en R1) |

## Siguiente paso (sin ejecutar)

P-L59F-I: implementacion de `decision_rows` en `canonical_selection_ledger.py`
segun este contrato completo, en worktree aislado. Version `0.4.197` propuesta
sujeta a verificacion de que ningun otro candidato use ese numero.
