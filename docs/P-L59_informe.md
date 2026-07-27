# P-L59C — autoridad prospectiva estructurada de llm_selected

## Dictamen

`ready_for_integration_rehearsal`.

La autoridad `llm_selected` nace ahora en el productor que conoce el resultado
estructurado de seleccion LLM, se propaga por `TradeRecommendation` →
`decision_context_snapshot` → carrier (`cycle_runner`) → P-L53
(`canonical_selection_ledger`), y se persiste en `Store` con el contrato
append-only existente. El proxy textual `source="llm" -> True` desaparece.
Telemetria shadow/fail-open; sin cambio de seleccion, prompts, ranking, gates,
sizing, planes, ordenes, exposicion, limites ni politica activa.

## Base y candidato

- **Base exacta**: P-L59B-T-R5, `49059f18`, tree `b29c262c`, version `0.4.195`.
- **Candidato P-L59C**: HEAD `0dce08d8`, rama `codex/pl59c-llm-selection-producer`.
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59c_llm_selection_producer`.
- **Version**: `0.4.196`.

Commits:
1. `b6d7c176` — feat: implementacion (models, trade_decision, decision_context, cycle_runner, canonical_selection_ledger)
2. `c599a335` — test: 24 pruebas P-L59C + adaptacion P-L59B/P-L53 fixtures
3. `0dce08d8` — chore: bump version a 0.4.196

## Esquema y semantica

### Campo `llm_selected` en `TradeRecommendation`

- **Tipo**: `bool | None`, default `None`.
- **True**: el LLM selecciono explicitamente esta recomendacion en su salida estructurada valida. Fijado por `_recommendation_from_dict`.
- **False**: se conoce explicitamente que NO fue seleccionada por LLM (capacity-fill, fallback determinista, hold override). Fijado por `deterministic_trade_fallback_recommendations` y `augment_recommendations_with_deterministic_fallback`.
- **None**: legacy, productor desconocido o evidencia ausente/ambigua. Default para constructores no migrados.

### Propagacion

```
_recommendation_from_dict (llm_selected=True)
  → TradeRecommendation.llm_selected
    → cycle_runner: getattr(recommendation, "llm_selected", None)
      → build_decision_context_snapshot(llm_selected=...)
        → snapshot["llm_selected"]
          → canonical_selection_ledger: snapshot.get("llm_selected")
            → candidate_row["llm_selected"]
              → persist_canonical_selection_ledger (Store)
                → read_canonical_selection_ledger
```

### Consumo en P-L53 (`canonical_selection_ledger.py`)

Antes (proxy, linea 383):
```python
"llm_selected": True if source == "llm" else False if source else None,
```

Ahora (autoridad estructurada):
```python
"llm_selected": snapshot.get("llm_selected"),
```

`snapshot` es el `decision_context_snapshot` del objeto `recommendation`.

## Productor-evento-consumidor

| Frontera | Productor | Consumidor |
|---|---|---|
| LLM parsing | `_recommendation_from_dict()` → `llm_selected=True` | `cycle_runner` lee `recommendation.llm_selected` |
| Fallback determinista | `deterministic_trade_fallback_recommendations()` → `llm_selected=False` | idem |
| Capacity-fill | `augment_recommendations_with_deterministic_fallback()` → `replace()` preserva `llm_selected=False` del fallback | idem |
| Snapshot | `build_decision_context_snapshot(llm_selected=...)` | `canonical_selection_ledger` lee `snapshot["llm_selected"]` |
| Persistencia | `persist_canonical_selection_ledger` | `read_canonical_selection_ledger` |

## Contrato adversarial

1. `source="llm"` **sin** `llm_selected` en snapshot → `None` (no infiere True).
2. `source` no-LLM **con** `llm_selected=True` → `True` (la autoridad manda sobre el source textual).
3. Source desconocida (`"bogus"`) sin `llm_selected` → `None` (nunca colapsa a False).
4. `selected_for_llm`, `llm_selected`, `llm_considered` y `decision_source` son dimensiones separadas.

## Identidad y paridad

- Identidad de decision: `cycle_id + signal identity + action + recommendation_id`.
- BUY y EXIT preservados. `recommendation_id` preservado en persistencia.
- Paridad: antes/despues, ignorando solo el nuevo carrier observacional y version, coinciden recomendaciones economicas, scores/ranks, gates, planes, qty/notional, prices/stops/takes/trailing, submitted/failed y broker request count/order.
- **Brecha P-L53 recommendation_id abierta**: dos recomendaciones de la misma senal colisionan porque la identidad primaria de P-L53 no incluye `recommendation_id`. No se corrige en este lote.

## Archivos modificados

| Archivo | Cambio |
|---|---|
| `src/agente_bolsa/models.py` | Campo `llm_selected: bool \| None = None` en `TradeRecommendation` |
| `src/agente_bolsa/tools/trade_decision.py` | `_recommendation_from_dict`: `llm_selected=True`; fallback: `llm_selected=False` (2 sitios) |
| `src/agente_bolsa/tools/decision_context.py` | Parametro `llm_selected` en `build_decision_context_snapshot` + inclusion en snapshot dict |
| `src/agente_bolsa/cycle_runner.py` | Lee `recommendation.llm_selected` y lo pasa al snapshot builder |
| `src/agente_bolsa/tools/canonical_selection_ledger.py` | Consume `snapshot.get("llm_selected")` en vez de inferir de `source` |
| `tests/test_p59c_llm_selected_authority.py` | NUEVO: 24 pruebas de autoridad |
| `tests/test_p59bt_llm_selected_contract_characterization.py` | Actualizadas 7 pruebas a contrato P-L59C |
| `tests/test_p53b_selection_ledger_shadow.py` | `_recommendation()` incluye `llm_selected` en snapshot; `_build_large()` sincroniza |

## Archivos protegidos

Sin cambios: `kernel.py`, `broker.py`, `execution.py`, `risk.py`, `config.py`, `.env`.

## Pruebas

### P-L59C (24 tests, 24 passed)
- Productor: 2 tests (`_recommendation_from_dict` fija `llm_selected=True`)
- Propagacion snapshot: 3 tests (True/False/None)
- Ledger: 3 tests (True/False/None desde snapshot)
- Adversarial: 3 tests (source sin autoridad → None; source no-LLM con True → True; unknown → None)
- Persistencia Store: 4 tests (insert, idempotent, conflict, non-mutation)
- Fail-open: 2 tests (sin recomendaciones, snapshot roto)
- BUY/EXIT y recommendation_id: 2 tests
- Dimensiones independientes: 3 tests (selected_for_llm vs llm_selected)
- Predecision: 1 test (sin outcomes)
- Version policy: 1 test

### P-L59B characterization (27 tests, 27 passed)
- 7 tests actualizados al nuevo contrato; 20 preservados sin cambios.

### P-L53 (27 tests, 27 passed)
- Characterization: 15 passed. Shadow: 12 passed (excluyendo volume test).

### P-L54 (34 tests, 34 passed)
- Characterization: 27 passed. Shadow: 7 passed.

### Trade decision (129 tests, 129 passed)

### Integration (5 tests, 5 passed)

### Version policy (1 test, 1 passed)

### Total focales: 220 tests, 0 fallos.

## Gates

- Ruff: verde (0 errores).
- `check_no_nulls.py`: OK (435 archivos).
- `git diff --check`: OK.
- `py_compile`: OK.
- `validate-agent-config --json`: `ok=true`, 0 errores, 0 warnings.

### Omitidos por XNYS abierto
- Suite completa
- Smoke `run-once --skip-crew`
- Benchmark P-L53/P-L54
- P-L45 33.336 observaciones
- Kernel-status productivo
- Broker, red, LLM, yfinance, SQLite productiva, jobs, reconciliacion, postmarket

## Siguiente paso unico

P-L59D: integracion de P-L59C en un rehearsal `codex/pl59d-llm-selected-rehearsal`
sobre la base `0dce08d8`, con QA adversarial de paridad (`_auto_paper_trade` sin
llamadas adicionales a broker/LLM), y ensayo de merge `--no-ff` para validacion
cerrada. Sin despliegue ni cambio de politica. Brecha P-L53 recommendation_id
sigue abierta.

---

## P-L59B-T-R5 (caracterizacion cerrada, base de P-L59C)

Ver HANDOFF para el historial completo de iteraciones P-L59B-T-R1 a R5.
