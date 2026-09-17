# P-L132 — cobertura same-cycle por semana y cost_basis del control (candidato Windows 0.4.236)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

El scoreboard ya apareaba controles same-cycle (`_cohort_rows`: misma
fecha + fuente + motivo de capacidad, espejo de la elegibilidad P-L31B),
pero la cobertura solo existia agregada (`control_coverage` top-level) y
el coste aplicado al control (10 bps fijos) no estaba etiquetado: una
semana podia mostrar `control_expectancy` sin que se viera cuantos
ejecutados tenian control ni con que coste se calculo.

## Cambio (solo observacional, sin politica ni protegidos)

- `_weekly_rows` recibe `matches` y publica por semana:
  `matched_executed`, `unmatched_executed` (solo ejecutados maduros),
  `control_cost_basis = "assumption_10bps"`.
- Los controles no se ejecutan y no tienen fills: el coste calibrado
  P-L131 no les aplica; queda declarado como supuesto, no medido.
- Criterio, bandas, `_evaluation` y schema (v3, aditivo): intactos.
- Bump `0.4.235` → `0.4.236`; pin `test_p59c` actualizado.

Sin cambios en kernel/broker/execution/risk/config/`.env`, sin backfill,
sin union por simbolo, ruta activa intacta.

## Limite conocido (no bloqueante, fuera de alcance)

El matcher preexistente comparte un mismo control entre varios
ejecutados del mismo ciclo (`matched_by_id` lo deduplica a 1 control).
No se cambia su semantica en este lote; `matched_executed` cuenta
ejecutados con control bajo las reglas vigentes. Si R2c (uplift LLM)
necesita apareamiento 1:1, sera lote separado con pre-registro.

## Commits (rama `codex/pl132-same-cycle-controls`, base `5f7035e6`)

- `2e148fa2` test: 3 tests de cobertura (rojo 3/3 confirmado; el caso
  mixto revelo el control compartido y se corrigio la expectativa,
  no el codigo).
- `81bae8ff` feat + bump 0.4.236 + pin version.

## QA (XNYS abierto; solo gates aislados)

- Focales: 12 passed (p132 3 + p131 4 + scoreboard 5).
- Regresiones: 68 passed con p59c + execution_quality + cost_calibration.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (500 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, merge y despliegue: OMITIDOS por XNYS abierto.

## Siguiente paso (tras revision del operador, XNYS cerrado)

1. `merge --no-ff` conjunto P-L130+P-L131+P-L132 a `codex/astra`.
2. Suite completa sobre el arbol mergeado + doble salud.
3. Port mecanico a Jetson.

Sin push salvo peticion explicita. Sizing/politica: sin cambios.
