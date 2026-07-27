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

P-L59D: rehearsal de integracion (no iniciado).
