# P-L143 — tolerancia a céntimo en agrupación de aperturas SPY (candidato 0.4.247)

Dictamen: `ready_for_review`. XNYS cerrado (18-sep-2026 ~12:05 CEST);
sin push, sin despliegue, sin broker/red/LLM en pruebas.

## Causa

El dashboard omitía sesiones como `spy_open_conflict` aunque las
aperturas fuesen económicamente idénticas: `_resolve_open` agrupaba por
igualdad exacta de float (`opening_performance.py:581`), de modo que una
revisión de proveedor tras `auto_adjust` (p. ej. `739.969970703125` vs
`739.97`) declaraba conflicto por diseño.

## Cambio (solo comparabilidad, evidencia intacta)

- `_comparison_price` redondea a céntimos SOLO la firma de agrupación en
  `_resolve_open`. El candidato resuelto conserva el precio exacto y la
  regla oldest-authority; los sidecars `spy_open_conflict_*` no se leen
  ni se reescriben.
- Conflictos económicos reales (distinta decena de céntimo entre dos
  autoridades) siguen en `conflicts` y en la lista de omitidas.
- Sin tocar persistencia, scheduler, riesgo, kernel, config ni `.env`.

## QA

- Nuevos: `tests/test_p143_spy_cent_tolerance.py` (2 tests).
- Regresiones: P-L72/P-L74/P-L82/P-L82R/P-L88 (48 tests). Total: 50 passed.
- `test_version_policy` verde tras bump `0.4.246` → `0.4.247`.
- Ruff, `check_no_nulls.py` (512 archivos), `git diff --check` verdes.
- Omitidos (XNYS cerrado, pre-sesión 15:30): suite completa, smoke,
  config/kernel (se repiten en integración).

## Integración (18-sep, `ea0082f3` + `9fc75525`)

- Mergeado con P-L146 a `codex/astra`: HEAD `9fc75525`, versión `0.4.248`.
- Suite por bloques sobre el árbol final: a-d 521, e-g 57, h-m 199,
  r-s 177, t-z 317, todo passed. Focales P-L143+P-L146+version_policy:
  9 passed. Ruff/NUL/diff verdes.
- Excepciones preexistentes, ajenas al lote (módulos no tocados):
  `test_llm_router...zen_profile` (falla también en base `535f94ca`,
  depende del entorno) y 2 tests multiproceso P-L45B1 con barreras
  30/45 s que pasan en solo/subconjunto y flakean bajo carga del
  full-run (4 pytest huérfanos de ayer eliminados en el proceso).
- Dictamen: `ready_for_closed_market_deployment` (Windows). Sin push,
  sin despliegue, sin Jetson todavía.

## Límites pendientes

- `_resolve_current` mantiene igualdad exacta de `paired_open_price`;
  fuera de alcance.
- No re-evalúa cachés ya escritas en producción; el efecto se ve en la
  próxima captura tras el merge.
- Siguiente: P-L144 (fecha estimada), P-L145 (copy rancios), port
  Jetson si se autoriza.
