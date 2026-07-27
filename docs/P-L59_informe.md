# P-L59C-R2 — autoridad prospectiva estructurada de llm_selected

## Dictamen

**`ready_for_integration_rehearsal`**.

Correcciones R2 sobre R1:

1. **Normalizacion antes de persistir snapshot**: `normalize_llm_selected`
   movida a `decision_context.py` (unica fuente). Se aplica dentro de
   `build_decision_context_snapshot` antes del hash/validate. P-L53 importa
   y reutiliza el mismo helper. Malformed (1, "true", [], etc) → None en el
   snapshot. Probado con Store temporal: snapshot malformado nunca persiste
   como autoridad no booleana. Fail-open: invalidez degrada a None sin bloquear.

2. **Paridad economica real (payloads)**: `_StoreSpy` extendido para capturar
   kwargs/payloads de store calls. `_auto_paper_trade` True/False/None
   producen identicos payloads economicos tras retirar `llm_selected`,
   hashes, snapshot IDs, recommendation_id y version. Contador/orden de store
   calls identico. 1 request LLM simulada y 1 submit broker simulado por
   ejecucion. P-L53 spy y fail-open wrapper preservados.

3. **Documentacion**: hora real de direccion (20:30 CEST, 27-jul-2026).
   Placeholders reemplazados con hashes reales. Bloque stale del plan/relevo
   eliminado. Contabilidad 278 tests en comando unico con 9 archivos disjuntos.

## Base y candidato

- **Base exacta**: P-L59B-T-R5, `49059f18`, tree `b29c262c`, version `0.4.195`.
- **Candidato P-L59C-R2**: rama `codex/pl59c-llm-selection-producer`.
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59c_llm_selection_producer`.
- **Version**: `0.4.196`.
- **Hora**: 2026-07-27 20:30 CEST (direccion), XNYS abierto.

### Commits

P-L59C (base):
1. `b6d7c176` — feat: implementacion
2. `c599a335` — test: 24 + adaptacion
3. `0dce08d8` — chore: bump 0.4.196
4. `a6e23cda` — docs: informe, plan, relevo

P-L59C-R1:
5. `86120c43` — fix: `normalize_llm_selected` + consumo
6. `40768a22` — test: 13 + 7 integracion
7. `e777dbd8` — docs: informe corregido

P-L59C-R2:
8. `XXXXXX` — fix: `normalize_llm_selected` → `decision_context.py`, uso en snapshot
9. `YYYYYY` — test: snapshot normalization + economic parity
10. `ZZZZZZ` — docs: placeholders, stale blocks, contabilidad exacta

## Esquema

### `normalize_llm_selected` en `decision_context.py`

```python
def normalize_llm_selected(value: Any) -> bool | None:
    if value is None:
        return None
    if type(value) is bool:
        return value
    return None  # fail-open: non-bool degrades to None
```

Se aplica en `build_decision_context_snapshot` antes de hash/validate.
`canonical_selection_ledger.py` importa y reutiliza el mismo helper (sin duplicacion).

## Archivos modificados en R2

| Archivo | Cambio |
|---|---|
| `decision_context.py` | +`normalize_llm_selected`, uso en `build_decision_context_snapshot` |
| `canonical_selection_ledger.py` | -`normalize_llm_selected`, +import desde `decision_context` |
| `test_p59c_llm_selected_authority.py` | +8 tests snapshot normalization + Store persistence |
| `test_market_cycle_timing_integration.py` | +`_StoreSpy` payloads, `_strip_observational`, `_capture_parity_run`, +1 economic parity test |
| `docs/P-L59_informe.md` | corregido con hashes reales |
| `docs/plan_mejoras_y_tareas.md` | bloque stale eliminado |
| `docs/RELEVO_DIRECCION_TECNICA.md` | bloque stale eliminado |

## Contabilidad exacta (278 tests, 0 solapes)

| Bateria | Archivo | Count |
|---|---|---|
| P-L59C authority + normalization | `test_p59c_llm_selected_authority.py` | 45 |
| P-L59B characterization | `test_p59bt_llm_selected_contract_characterization.py` | 27 |
| Integration (parity + fail-open + economic) | `test_market_cycle_timing_integration.py` | 13 |
| P-L53 characterization | `test_p53b_selection_ledger_characterization.py` | 15 |
| P-L53 shadow | `test_p53b_selection_ledger_shadow.py` | 13 |
| P-L54 characterization | `test_p54bt_capital_deployment_funnel_characterization.py` | 27 |
| P-L54 shadow | `test_p54bw_capital_deployment_funnel_shadow.py` | 7 |
| Trade decision | `test_trade_decision.py` | 129 |
| Version policy | `test_version_policy.py` | 1 |
| **Total** | | **278** |

Comando:
```powershell
$env:PYTHONPATH = "<worktree>/src"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_p59c_llm_selected_authority.py `
  tests/test_p59bt_llm_selected_contract_characterization.py `
  tests/test_market_cycle_timing_integration.py `
  tests/test_p53b_selection_ledger_characterization.py `
  tests/test_p53b_selection_ledger_shadow.py `
  tests/test_p54bt_capital_deployment_funnel_characterization.py `
  tests/test_p54bw_capital_deployment_funnel_shadow.py `
  tests/test_trade_decision.py `
  tests/test_version_policy.py `
  -q
```
Resultado: **278 passed in 64.48s**.

## Gates

| Gate | Estado |
|---|---|
| Ruff (archivos tocados) | 0 errores |
| `check_no_nulls.py` | OK (435 archivos) |
| `git diff --check` | OK |
| `validate-agent-config --json` temporal | `ok=true` |

Omitidos (XNYS abierto): suite, smoke, benchmark, P-L45, kernel productivo.

## Brecha P-L53 recommendation_id

Sigue abierta. No corregida en este lote.

## Siguiente paso

P-L59D: rehearsal de integracion sobre HEAD P-L59C-R2.
