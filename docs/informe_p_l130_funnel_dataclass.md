# P-L130 — funnel dataclass + attachment fail-open (candidato Windows 0.4.234)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

Port a la linea Windows de dos fixes ya validados upstream y nunca
integrados aqui:

1. `canonical_selection_ledger.py:312` usaba `raw = dict(recommendation)`.
   Con recomendaciones dataclass `TradeRecommendation` (ruta real del
   ciclo) eso devuelve fila vacia: decision degradada a `unavailable`
   en vez de `verified`. El resto del fichero ya usaba `_mapping()`
   (25 llamadas); solo `_build_decision_row` quedaba con `dict()`.
2. `capital_deployment_funnel_shadow.py:485/490/495` hacia
   `attachment_counts[f"{label}_attachment_unavailable"] += 1` sobre un
   dict que solo pre-inicializa claves `plan_*`/`order_*`. Cualquier
   label nuevo (`recommendation`, `gate`, `rejection`, `submitted`)
   lanzaba `KeyError`, el `KeyError('recommendation_attachment_unavailable')`
   observado 52 veces en Jetson desde el 20-ago (auditoria P-L95).

## Cambio (2 lineas funcionales, sin politica ni protegidos)

- `canonical_selection_ledger.py:312`: `raw = dict(recommendation)` →
  `raw = _mapping(recommendation)` (`_mapping` ya soporta
  Mapping/dataclass, linea 80). Byte-identico al fix upstream `6d6a8e67`
  (verificado `diff-count=0` contra rama `codex/pl95-funnel-attachment-fix`).
- `capital_deployment_funnel_shadow.py`: contadores con
  `attachment_counts.get(key, 0) + 1`. Byte-identico al fix upstream
  `927e830e` (verificado `diff-count=0`).
- `tests/test_p59c_llm_selected_authority.py:775`: pin de version
  `0.4.230` → `0.4.234`. Defecto preexistente en base: la base
  `c40ac2fd` ya iba en `0.4.233` (P-L126/127/128 no actualizaron el pin).
- Bump `0.4.233` → `0.4.234` (`__init__.py` + comentario P-L130).

Sin cambios en kernel/broker/execution/risk/config/`.env`, sin backfill,
sin union por simbolo/fecha, ruta activa intacta, shadow sigue fail-open.

## Commits (rama `codex/pl130-funnel-dataclass-fix`, base `c40ac2fd`)

- `fb11b7bb` test: 5 tests dataclass portados de upstream; rojo previo
  confirmado 5/5 failed sobre la base.
- `e96f263a` fix ledger + bump 0.4.234 + pin version corregido.
- `5ddcb923` fix contadores funnel + 2 tests fail-open portados de
  upstream (nombre de test adaptado; unica diferencia vs upstream).

## QA (XNYS abierto; solo gates aislados)

- Focales lote: 60 passed
  (`test_p96_selection_ledger_dataclass` 5,
  `test_p54bw_capital_deployment_funnel_shadow` 9,
  `test_p59c_llm_selected_authority` 46).
- Regresiones `selection_ledger|capital_deployment|funnel`: 80-91 passed
  segun filtro (80 con `-k`, 91 con `-k "capital or ledger"`), 0 failed.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (498 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Smoke `run-once --skip-crew` (DATA_DIR temporal): exit=0, sin traceback;
  ledger `collecting/inserted` persistido (esperado: ciclo aislado sin
  recomendaciones reales).
- Suite completa, smoke productivo, merge y despliegue: OMITIDOS por
  XNYS abierto (sesion 2026-09-17, cierre 22:00 Europe/Madrid).

## Siguiente paso (tras revision del operador, XNYS cerrado)

1. `merge --no-ff` a `codex/astra` en ventana cerrada con premarket/postmarket
   terminales y sin jobs activos.
2. Suite completa `tests/ -x -q` sobre el arbol mergeado + doble salud.
3. Port mecanico a Jetson (patron P-L125, `0.4.305+arm64`), preflight con
   `--require-core-restart-zero`, snapshot frio, corte canonico.
4. Verificar desaparicion del `KeyError` en produccion.

Sin push salvo peticion explicita. Sizing/política: sin cambios.
