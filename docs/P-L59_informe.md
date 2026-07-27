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
- **HEAD**: `9009c7f21f43a9136822f4fbaba383773e3f3051`
- **Tree**: `ad69264ecbbc0d8764a5a5ce722e38d117d98e8f` (identico a P-L59C-R6D)
- **Hora**: 2026-07-27 ~21:15 CEST, XNYS abierto
- **Version**: `0.4.196`

### Commits

| Commit | Tipo | Descripcion |
|---|---|---|
| `9009c7f2` | merge | P-L59D: rehearsal de integracion --no-ff de P-L59C-R6D sobre P-L60R1 |
| (proximo) | docs | P-L59D informe, plan y relevo actualizados |

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

Los 6 archivos protegidos son identicos contra base P-L60R1 y contra produccion `24537e8`:

- `src/agente_bolsa/kernel.py` ✓
- `src/agente_bolsa/tools/broker.py` ✓
- `src/agente_bolsa/tools/execution.py` ✓
- `src/agente_bolsa/tools/risk.py` ✓
- `src/agente_bolsa/config.py` ✓
- `.env` ✓

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
5. **Fail-open del ledger**: cubierto por `test_ledger_idempotent_fail_open`, `test_source_llm_without_llm_selected_yields_none`
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

## No broker/red/LLM/yfinance/SQLite productiva

Confirmado. Los tests usan `Store` con `DATA_DIR` temporal. Sin conexiones externas. Sin jobs operativos lanzados.

## Siguiente paso

P-L59E: validacion cerrada completa de P-L59D. Requiere:
- XNYS cerrado
- Postmarket terminal `completed` o `failed`
- Sin leases ni jobs activos
- Suite completa, smoke aislado, benchmark P-L53/P-L54, P-L45 33.336
- Kernel productivo sellado
- Sin despliegue aun (solo validacion)
