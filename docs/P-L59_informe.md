# P-L59C-R4 — autoridad prospectiva estructurada de llm_selected

## Dictamen

**`ready_for_integration_rehearsal`** (R4 corregido).

Correcciones acumuladas:

### P-L59C (base)
- `TradeRecommendation.llm_selected`, productor fija True/False, carrier propaga, P-L53 consume sin proxy

### R1: validacion runtime + paridad basica + fail-open
### R2: `normalize_llm_selected` en `decision_context.py` (unica fuente), paridad via payloads v1
### R3: `new_id` congelado, normalizacion minima v1, aserciones negativas

### R4 (actual)
- **Normalizador context-aware**: `_strip_observational_minimal` retira `llm_selected`
  globalmente. Solo dentro de `decision_context_snapshot` y `comparable_control_set`
  retira `content_hash` y `captured_at`. `snapshot_id` conservado en todos los
  bloques. `content_hash`/`captured_at` externos sobreviven.
- **Test unitario del strip**: verifica preservacion de `content_hash`/`captured_at`/`snapshot_id`
  externos; `snapshot_id` en DCS/CCS conservado; `content_hash`/`captured_at` en DCS/CCS retirados.
- **Plan**: duplicado `Siguiente` eliminado.

## Candidato

- **Base**: P-L59B-T-R5 `49059f18`, version `0.4.195`
- **Worktree**: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59c_llm_selection_producer`
- **Rama**: `codex/pl59c-llm-selection-producer`
- **Version**: `0.4.196`
- **Hora**: 2026-07-27 20:30 CEST, XNYS abierto

### Commits

P-L59C: `b6d7c176`, `c599a335`, `0dce08d8`, `a6e23cda`
R1: `86120c43`, `40768a22`, `e777dbd8`
R2: `f9fff29c`, `4508cb70`, `88c10a8d`, `cca19660`
R3: `6ab89896`, `ea42ac26`
R4: test commit + docs commit

## Esquema del normalizador R4

```python
OBS_BLOCKS = {"decision_context_snapshot", "comparable_control_set"}

def _strip_observational_minimal(obj, *, inside_dcs=False):
    # Global: retira llm_selected
    # Dentro de OBS_BLOCKS: retira content_hash, captured_at
    # Conserva snapshot_id, IDs canonicos, campos economicos
```

## Archivos modificados en R4

| Archivo | Cambio |
|---|---|
| `tests/test_market_cycle_timing_integration.py` | strip context-aware + test unitario + CCS |
| `docs/P-L59_informe.md` | actualizado R4 |
| `docs/plan_mejoras_y_tareas.md` | R4, duplicado `Siguiente` eliminado |
| `docs/RELEVO_DIRECCION_TECNICA.md` | R4 |

## Pruebas

- **R2 baseline**: 278 tests (9 archivos disjuntos), 0 fallos
- **R4**: `test_market_cycle_timing_integration.py` **14 passed** (incluye nuevo test unitario del strip)
- **Focales authority** (no repetidas, R3 baseline): 45 passed
- Ruff: 0 errores, NUL: OK, diff: OK

## Gates omitidos (XNYS abierto)

Suite completa, smoke, benchmark, P-L45 33.336, kernel productivo.

## Brecha P-L53 recommendation_id

Sigue abierta. No corregida.

## Siguiente paso

P-L59D: rehearsal de integracion sobre HEAD P-L59C-R4.
