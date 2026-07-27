# P-L59C-R1 — autoridad prospectiva estructurada de llm_selected

## Dictamen

**`ready_for_integration_rehearsal`** (corregido desde `needs_fix` tras R1).

Correcciones P-L59C-R1 sobre el dictamen rechazado de P-L59C:

1. **Validacion runtime**: `normalize_llm_selected(value)` centralizada en
   `canonical_selection_ledger.py`. Solo `type(value) is bool` o `None`;
   `1`, `0`, `"true"`, list, dict → `None` (fail-open, nunca lanza).

2. **Paridad real `_auto_paper_trade`**: True/False/None producen identicas
   llamadas activas y store. 1 `request_trade_recommendations` y
   1 `submit_paper_order_plan` por ejecucion (sin llamadas extra de P-L59C).
   P-L53 recibe `llm_selected` literal del `TradeRecommendation`.

3. **Fail-open**: `build_canonical_selection_ledger` forzado a fallar;
   ruta activa completa, store calls intactas,
   `selection_ledger.status == "unavailable"`.

4. **QA/documentacion**: contabilidad exacta (268 tests, conjuntos disjuntos),
   hora real, comandos precisos. Brecha P-L53 recommendation_id fuera de alcance.

## Base y candidato

- **Base exacta**: P-L59B-T-R5, `49059f18`, tree `b29c262c`, version `0.4.195`.
- **Candidato P-L59C-R1**: rama `codex/pl59c-llm-selection-producer`.
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59c_llm_selection_producer`.
- **Version**: `0.4.196`.
- **Hora**: 2026-07-27 ~22:00 CEST, XNYS abierto.

### Commits

P-L59C:
1. `b6d7c176` — feat: implementacion
2. `c599a335` — test: 24 + adaptacion P-L59B/P-L53
3. `0dce08d8` — chore: bump 0.4.196
4. `a6e23cda` — docs: informe, plan, relevo

P-L59C-R1 (siguientes):
5. `src` commit — feat: `normalize_llm_selected` + uso
6. `test` commit — 13 validacion + 7 integracion + adaptacion
7. `docs` commit — informe corregido, plan, relevo

## Esquema y semantica

### `normalize_llm_selected(value: Any) -> bool | None`

- `None` → `None`
- `type(value) is bool` → `value` (True o False literal)
- Cualquier otro tipo → `None` (fail-open, nunca lanza)

Se consume en `_attach_phase_b` de `canonical_selection_ledger.py`:
`snapshot_llm_selected = normalize_llm_selected(snapshot.get("llm_selected"))`

### Propagacion

```
_recommendation_from_dict (llm_selected=True)
  → TradeRecommendation.llm_selected
    → cycle_runner: getattr(recommendation, "llm_selected", None)
      → build_decision_context_snapshot(llm_selected=...)
        → snapshot["llm_selected"]
          → canonical_selection_ledger: normalize_llm_selected(snapshot.get("llm_selected"))
            → candidate_row["llm_selected"]
```

## Archivos modificados

| Archivo | Cambio P-L59C | Cambio P-L59C-R1 |
|---|---|---|
| `models.py` | +`llm_selected: bool\|None` en TradeRecommendation | — |
| `trade_decision.py` | +`llm_selected=True/False` en 3 constructores | — |
| `decision_context.py` | +parametro `llm_selected` en `build_decision_context_snapshot` | — |
| `cycle_runner.py` | +lectura y paso de `llm_selected` | — |
| `canonical_selection_ledger.py` | consumo de snapshot en vez de proxy de source | +`normalize_llm_selected` + uso |
| `test_p59c_llm_selected_authority.py` | 24 tests authority | +13 tests normalizacion |
| `test_p59bt_*_characterization.py` | 7 tests actualizados | — |
| `test_p53b_selection_ledger_shadow.py` | adaptacion fixture | — |
| `test_market_cycle_timing_integration.py` | — | +7 tests paridad/fail-open + adaptacion `_StoreSpy` |
| `docs/P-L59_informe.md` | informe P-L59C | corregido R1 |
| `docs/plan_mejoras_y_tareas.md` | +P-L59C | actualizado R1 |
| `docs/RELEVO_DIRECCION_TECNICA.md` | +P-L59C | actualizado R1 |

## Contabilidad exacta (268 tests, 0 solapes)

| Bateria | Archivo | Count |
|---|---|---|
| P-L59C authority + normalization | `test_p59c_llm_selected_authority.py` | 37 |
| P-L59B characterization | `test_p59bt_llm_selected_contract_characterization.py` | 27 |
| Integration (incl. parity + fail-open) | `test_market_cycle_timing_integration.py` | 12 |
| P-L53 characterization | `test_p53b_selection_ledger_characterization.py` | 15 |
| P-L53 shadow | `test_p53b_selection_ledger_shadow.py` | 13 |
| P-L54 characterization | `test_p54bt_capital_deployment_funnel_characterization.py` | 27 |
| P-L54 shadow | `test_p54bw_capital_deployment_funnel_shadow.py` | 7 |
| Trade decision | `test_trade_decision.py` | 129 |
| Version policy | `test_version_policy.py` | 1 |
| **Total** | | **268** |

Conjuntos disjuntos (archivos distintos, sin baterias solapadas).

Comando: `pytest <9 archivos> -q` con `PYTHONPATH=<worktree>/src`.

## Gates

| Gate | Estado |
|---|---|
| Ruff (archivos tocados) | 0 errores |
| `check_no_nulls.py` | OK (435 archivos) |
| `git diff --check` | OK |
| `validate-agent-config --json` temporal | `ok=true` |

### Omitidos (XNYS abierto)
Suite completa, smoke, benchmark, P-L45 33.336, kernel productivo, broker/red/LLM/yfinance/SQLite productiva.

## Paridad

Demostrada via `test_parity_all_three_yield_identical_calls_and_store`:
True/False/None → identicas `calls` y `store.calls`.
1 `request_trade_recommendations`, 1 `submit_paper_order_plan` en todos los casos.

## Brecha P-L53 recommendation_id

Sigue abierta (dos recomendaciones de la misma senal colisionan).
No corregida en este lote. P-L54B tiene dominios separados pero no se verifica aqui.

## Siguiente paso

P-L59D: rehearsal de integracion sobre HEAD P-L59C-R1, worktree nuevo
`codex/pl59d-llm-selected-rehearsal`. QA adversarial de paridad con
`_auto_paper_trade` sin llamadas adicionales broker/LLM. Brecha P-L53
recommendation_id sigue fuera de alcance.
