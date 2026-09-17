# P-L131 — coste calibrado en learning scoreboard (candidato Windows 0.4.235)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

`learning_scoreboard.py` restaba constantes fijas 10/20 bps a todos los
retornos (`_weekly_rows`, `_daily_portfolio_returns`). El coste real de
ejecución (slippage señal→fill) ya se mide en P-L33B
(`execution_quality`, `signal_to_fill_bps` por orden) y
`cost_calibration.calibrate_cost_bps` existe, pero ningún consumidor lo
usaba: la expectancy neta publicada era siempre contra un supuesto,
nunca contra coste observado.

## Cambio (solo observacional, sin politica ni protegidos)

- Nuevo `_calibrated_cost(executed)`: mediana de `signal_to_fill_bps`
  sobre snapshots de ejecución; umbral `MIN_CALIBRATION_SAMPLES = 10`,
  exclusion de no-finitos y `|bps| > 200` (mismo corte que el outlier
  `plan_to_fill_bps` de P-L33B).
- Con muestra suficiente: `cost_basis = "calibrated"` + `cost_bps` +
  `cost_rate` + `calibration_samples`, y cada fila semanal publica
  `expectancy_net_calibrated`.
- Sin muestra suficiente: `cost_basis = "assumption_10bps"`,
  `expectancy_net_calibrated = None` (unavailable, nunca cero ni
  constante silenciosa).
- Bandas legacy `expectancy_net_10bps`/`20bps`, `_evaluation` y criterio
  pre-registrado: intactos. `schema_version` 2 → 3 (solo campos
  aditivos; sin otros consumidores en `src`/tests).
- `format_learning_scoreboard` añade linea `cost_basis/cost_bps/samples`.
- Bump `0.4.234` → `0.4.235`; pin `test_p59c` actualizado.

Sin cambios en kernel/broker/execution/risk/config/`.env`, sin backfill,
ruta activa intacta.

## Commits (rama `codex/pl131-calibrated-costs`, base `e24f34e1`)

- `461ee0dd` test: 4 tests de calibracion (rojo 4/4 confirmado).
- `35958530` feat + bump 0.4.235 + pin version + pin schema v2→v3
  en test existente.

## QA (XNYS abierto; solo gates aislados)

- Focales lote: 9 passed
  (`test_p131_calibrated_costs` 4 + `test_learning_scoreboard` 5).
- Regresiones: `test_execution_quality_snapshot` +
  `test_cost_calibration` + `test_p59c_llm_selected_authority`: verdes
  (19 passed en bateria conjunta, 55 con p59c).
- `ruff check src tests`: All checks passed (1 auto-fix de orden
  de imports, re-verificado).
- `scripts/check_no_nulls.py`: OK (499 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, smoke productivo, merge y despliegue: OMITIDOS por
  XNYS abierto (sesion 2026-09-17).

## Siguiente paso (tras revision del operador, XNYS cerrado)

1. `merge --no-ff` junto con P-L130 a `codex/astra` en ventana cerrada.
2. Suite completa sobre el arbol mergeado + doble salud.
3. Port mecanico a Jetson (`0.4.306+arm64`).

Sin push salvo peticion explicita. Sizing/politica: sin cambios.
