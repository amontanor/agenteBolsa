# Informe Codex - Fase 3 minima firma - 2026-07-02

## Objetivo

Entrega P2: digest diario programable, KPI funnel visible y medicion
determinista de calidad de propuestas. No cambia conducta de trading, no aplica
propuestas y no activa enforcement.

No se tocaron `src/agente_bolsa/kernel.py`, `src/agente_bolsa/tools/broker.py`,
`src/agente_bolsa/tools/execution.py`, `src/agente_bolsa/tools/risk.py`,
`src/agente_bolsa/config.py` ni `.env`.

## Implementacion

Se extendio `continuous-improvement-lab digest` para:

- escribir markdown con `--out`;
- incluir KPI funnel de las ultimas 4 semanas;
- medir calidad de las ultimas 200 propuestas con clasificador determinista;
- terminar con la seccion **PIDE APROBACION**, listando artefactos
  `code_diff_preview` con `status=READY_FOR_HUMAN_REVIEW` y `tests_ok=true`.

Scripts aislados del runtime de trading:

- `scripts/run_ci_digest_daily.ps1`: one-shot diario, escribe
  `data/reports/ci_digest_<fecha>.md`.
- `scripts/run_ci_digest_supervisor.ps1`: supervisor sin admin, mismo patron que
  Telegram radar. No se arranco en esta tarea.

Comando para Antonio:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ci_digest_supervisor.ps1 -RunAt 08:30 -Days 1
```

## Digest Real Generado

Artefacto real contra la BD actual:

`data/reports/ci_digest_2026-07-02.md`

Resumen del digest:

- Propuestas creadas ultimas 24h: 11.
- READY_TO_APPLY: 7.
- Applied changes ultimas 24h: 1 (`ROLLED_BACK=1`).
- Experimentos ultimas 24h: 53 corridos, 8 PASSED, 9 FAILED.
- PIDE APROBACION: 1 propuesta con diff validado:
  `ci_prop_codegen_demo_de3a43fac9bc`, target `docs/ci_codegen_demo.md`.

## KPI Funnel

Definicion: semanas ISO; conversiones por `proposal_id` dentro de cada semana.
WIP actual excluye estados terminales (`APPLIED`, `ARCHIVED`, `BLOCKED`,
`DUPLICATE`, `REJECTED`, `REJECTED_BY_TESTS`).

| Semana | Propuestas | Experimentos | Applied | % prop->exp | % exp->aplicado | Mediana dias a decision | Rollbacks |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-06-08 | 587 | 0 | 0 | 0.00% | n/d | 6.92 | 0 |
| 2026-06-15 | 329 | 0 | 0 | 0.00% | n/d | 6.55 | 0 |
| 2026-06-22 | 56 | 0 | 0 | 0.00% | n/d | 2.20 | 0 |
| 2026-06-29 | 48 | 146 | 1 | 54.17% | 0.00% | 0.01 | 1 |

WIP actual: 14 (`PENDING=1`, `READY_TO_APPLY=13`).

Lectura: el funnel ya muestra movimiento en experimentos, pero la conversion a
aplicado sigue practicamente bloqueada. El unico cambio aplicado historico aparece
como rollback, por lo que no hay evidencia de throughput sano todavia.

## Calidad De Propuestas

Clasificador determinista:

- **EJECUTABLE** si hay parametro con valor actual y propuesto, spec de
  diff/targets, o regla shadow con entrada/salida/stop/take-profit medible.
- **PROSA** si no hay especificacion determinista suficiente.
- No rechaza nada: solo mide.

Resultado sobre ultimas 200 propuestas:

- EJECUTABLE: 136.
- PROSA: 64.
- Distribucion global: 68.0% ejecutable, 32.0% prosa.

Ejemplos literales EJECUTABLE:

1. `ci_prop_codegen_demo_de3a43fac9bc` - `CODE_CHANGE docs docs/ci_codegen_demo.md No existe una nota de demo para codegen manual...`
2. `ci_prop_8ec6df9615bd` - `PARAMETER_CHANGE entry_quality_filter shadow_entry_quality_threshold_review sin cambio aplicado cola humana...`
3. `ci_prop_3968675d2ec9` - `CODE_CHANGE OBSERVATION_SCHEDULER gradual_observation_execution The system has 160 pending observations...`
4. `ci_prop_cf84c37fa91f` - `CODE_CHANGE OBSERVATION_SCHEDULER auto_execute_pending_observations Forzar ejecucion inmediata de las 160 observaciones pendientes...`
5. `ci_prop_258da7aad8e3` - `RISK_RULE_CHANGE VALIDATION_GATE auto_approve_low_risk_pending_after_12h Reducir cooldown de auto-approve a 12 horas...`

Ejemplos literales PROSA:

1. `ci_prop_712ea5e73d18` - `RISK_RULE_CHANGE risk_manager ci_prop_862f4196e8a3 apply | reject Reducing cooldown hours to 4...`
2. `ci_prop_a490c5529a93` - `PARAMETER_CHANGE settings max_daily_buy_orders Increased daily buy orders will generate more paper trades...`
3. `ci_prop_de1b749d340e` - `PARAMETER_CHANGE settings allow_auto_apply_improvements The continuous improvement pipeline is stalled because automatic application...`
4. `ci_prop_c22b977d2085` - `PARAMETER_CHANGE settings max_orders_per_cycle Currently, max_orders_per_cycle is set to 4...`
5. `ci_prop_de09ffd6eb0e` - `PARAMETER_CHANGE settings allow_auto_apply_improvements The system has multiple proposals in READY_TO_APPLY...`

Lectura: la cifra de ejecutables sube al reconocer `current_value`/`target_value`
en payloads de metricas, pero eso no significa que sean aplicables sin revision:
varias propuestas "ejecutables" siguen siendo operacionalmente peligrosas o de
gobierno. El clasificador mide concrecion, no aprobacion.

## Limitaciones

- El agente proponente se infiere desde `initiative_key -> owner_agent` cuando la
  propuesta no guarda `agent_name` directo.
- Las conversiones semanales no prueban causalidad entre propuesta, experimento y
  apply; solo emparejan por `proposal_id` dentro de la semana.
- El clasificador es deliberadamente simple y debe validarse con los ejemplos
  antes de usarlo para enforcement.
- El digest lista propuestas listas para aprobacion humana, pero no ejecuta
  `review` ni `approve`.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_ci_phase3_digest.py tests\test_continuous_improvement.py::test_lab_digest_counts_synthetic_categories -q` -> 5 passed.
- `.\.venv\Scripts\ruff.exe check src\agente_bolsa\continuous_improvement\digest.py src\agente_bolsa\main.py tests\test_ci_phase3_digest.py` -> OK.
- Ejecucion real: `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days 1 --out data\reports\ci_digest_2026-07-02.md` -> OK.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 855 passed, 1 warning externa de `websockets.legacy`.
- `.\.venv\Scripts\ruff.exe check src tests scripts` -> OK.
- Version actualizada: 0.4.83.
- Estado operativo: `.\.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`.
- `.env`: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `TRADING_MODE=paper`, `ALLOW_LIVE_TRADING=false`.
- Supervisor no arrancado; queda documentado el comando para Antonio.
