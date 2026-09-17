# P-L134 — reporte read-only de uplift LLM (candidato Windows 0.4.238)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

El plan R2c exige medir el aporte real del LLM antes de cualquier decision
de politica. El flag causal `llm_selected` (P-L59C) existe en
`decision_context_snapshot`, pero ningun reporte comparaba expectancy de
ejecutadas LLM vs deterministicas. Sin esa medicion, cualquier debate
sobre el LLM es narrativa sin denominadores.

## Cambio (solo lectura, sin politica ni protegidos)

- Nuevo `tools/llm_uplift.py`: `build_llm_uplift_report` lee
  `learning_observations` (flag `executed_buy` + outcome maduro 5d) y
  agrupa por `llm_selected` causal: embebido en features o join exacto
  por `best_signal_id` contra `signal_outcomes`. Texto `source` jamas
  se usa como proxy (leccion P-L59B-T, con test candado).
- Pre-registro en codigo: `MIN_UPLIFT_DECISIONS = 30`,
  `MIN_ARM_DECISIONS = 10`, `MIN_SNAPSHOT_COVERAGE = 0.70`,
  `DEFAULT_COST_RATE = 0.001`. Veredicto `sufficient_sample` solo si
  todo se cumple; si no, `insufficient_sample` con motivos. Sin
  promotion, sin trading, sin config.
- Reporte: brazos con n/expectancy/hit_rate/sesiones/concentracion,
  `uplift_net`, cobertura y veredicto; fichero `llm_uplift_<run>.json`
  + `latest_llm_uplift.json` via `write_json_report`.
- Bump `0.4.237` → `0.4.238`; pin `test_p59c` actualizado.

Sin cambios en kernel/broker/execution/risk/config/`.env`, sin backfill,
sin union por simbolo/fecha, ruta activa intacta.

## Commits (rama `codex/pl134-llm-uplift`, base `06b8e6d1`)

- `d69b0bf5` test+feat: modulo y 4 tests (suficiente, embebido,
  muestra pequena, anti-proxy).
- `5db22b69` bump 0.4.238 + pin version.

## QA (XNYS abierto; solo gates aislados)

- Focales: 4 passed (`test_p134_llm_uplift`).
- Regresiones: 55 passed con p59c + scoreboard.
- Guardia anti-proxy probada directamente: fila solo-source →
  `unattached`.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (503 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, merge y despliegue: OMITIDOS por XNYS abierto.

## Siguiente paso (tras revision del operador, XNYS cerrado)

1. `merge --no-ff` conjunto P-L130→P-L134 a `codex/astra`.
2. Suite completa sobre el arbol mergeado + doble salud.
3. Port mecanico a Jetson.

Sin push salvo peticion explicita. Sizing/politica: sin cambios.
