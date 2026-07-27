# P-L59C-R3 — autoridad prospectiva estructurada de llm_selected

## Dictamen

**`ready_for_integration_rehearsal`** (R3 corregido).

Correcciones acumuladas P-L59C → R3:

### P-L59C (base)
- `TradeRecommendation.llm_selected: bool|None`
- Productor fija True/False; carrier propaga; P-L53 consume sin proxy de source

### R1
- `normalize_llm_selected` runtime (bool|None via `type(v) is bool`)
- Paridad `_auto_paper_trade` basica (conteo de llamadas)
- Fail-open (build ledgershadow falla, ruta completa)

### R2
- `normalize_llm_selected` movida a `decision_context.py`, uso en `build_decision_context_snapshot`
- Paridad economica via payloads (v1: stripping agresivo)

### R3 (actual)
- `new_id` congelado → IDs deterministicos en True/False/None
- `_strip_observational_minimal`: retira SOLO `llm_selected`, `content_hash`, `snapshot_id`, `captured_at`
- Conserva TODOS los IDs canonicos + `decision_context_snapshot` (salvo obs)
- `submitted`/`failed` completos, no booleanos
- Aserciones negativas: IDs y campos economicos preservados

## Candidato

- **Base**: P-L59B-T-R5 `49059f18`, version `0.4.195`
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59c_llm_selection_producer`
- **Rama**: `codex/pl59c-llm-selection-producer`
- **Version**: `0.4.196`
- **Hora**: 2026-07-27 20:30 CEST, XNYS abierto

### Commits

P-L59C: `b6d7c176`, `c599a335`, `0dce08d8`, `a6e23cda`
P-L59C-R1: `86120c43`, `40768a22`, `e777dbd8`
P-L59C-R2: `f9fff29c`, `4508cb70`, `88c10a8d`, `cca19660`
P-L59C-R3: test commit + docs commit (siguientes)

## Esquema

### `normalize_llm_selected` en `decision_context.py` (unica fuente)

```python
def normalize_llm_selected(value: Any) -> bool | None:
    if value is None: return None
    if type(value) is bool: return value
    return None  # fail-open
```

Usada en `build_decision_context_snapshot` (antes del hash) e importada por
`canonical_selection_ledger.py`.

### Normalizacion de paridad (solo test)

```python
_OBSERVATIONAL_LEAF_KEYS = {"llm_selected"}
_OBSERVATIONAL_RECURSIVE_KEYS = {"content_hash", "snapshot_id", "captured_at"}

def _strip_observational_minimal(d):
    # Solo retira las claves de arriba (recursivamente en dicts/listas)
    # Conserva recommendation_id, plan_id, broker_order_id, signal_id,
    # decision_context_snapshot, action, schema_version, signal_link_status,
    # y todos los campos economicos
```

`new_id` congelado via monkeypatch: `iter(f"ID-{i:04d}" for i in range(100))`

## Archivos modificados en R3

| Archivo | Cambio |
|---|---|
| `tests/test_market_cycle_timing_integration.py` | `_strip_observational_minimal`, `new_id` freeze, negative assertions |
| `docs/P-L59_informe.md` | R3 actualizado |
| `docs/plan_mejoras_y_tareas.md` | R3 actualizado |
| `docs/RELEVO_DIRECCION_TECNICA.md` | R3 actualizado |

## Pruebas

El test de paridad economica pasaba antes de R3 (278/278) y sigue pasando tras R3.

Comando:
```powershell
$env:PYTHONPATH = "<worktree>/src"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_market_cycle_timing_integration.py -q
```
Resultado: **13 passed** (integration suite).

## Gates

| Gate | Estado |
|---|---|
| Ruff (archivos tocados) | 0 errores |
| `check_no_nulls.py` | OK |
| `git diff --check` | OK |

Omitidos (XNYS abierto): suite, smoke, benchmark, P-L45, kernel productivo.

## Brecha P-L53 recommendation_id

Sigue abierta. No corregida.

## Siguiente paso

P-L59D: rehearsal de integracion sobre HEAD P-L59C-R3.
