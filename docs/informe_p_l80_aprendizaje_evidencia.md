# P-L80A — auditoría del embudo de aprendizaje y controles contrafactuales

## Dictamen

`ready_for_implementation` para un único lote posterior P-L80B: cierre del
carrier de control same-cycle. La causa dominante está reproducida: la
actividad de agentes e investigación sí se persiste, pero la frontera que
alimenta el matcher de controles no transporta una decisión de capacidad
elegible hasta las observaciones canónicas. No se debe cambiar el matcher ni
sustituir el control por SPY o por un pool de régimen.

La auditoría no implementa el arreglo ni cambia política, trading, riesgo,
ejecución, configuración, datos históricos o auto-apply.

## Alcance, identidad y seguridad

- Fecha de coordinación: 2026-08-02, Europe/Madrid. XNYS está cerrado; la
  siguiente apertura observada es 2026-08-03 15:30 CEST.
- Producción auditada: `eb662c0760c77aae58067c18a9cbcdb06651b719`, árbol
  `2ee61f285eaa5293a4daab07de793cb9cdbae16c`, versión `0.4.214`, tracked
  limpia. Se preservaron los untracked conocidos del operador.
- Worktree de auditoría: `C:\Antonio\Bref\agenteBolsa_worktrees\pl80a_learning_funnel_audit`,
  rama `codex/p-l80a-learning-funnel-audit`, basado exactamente en el HEAD
  anterior. El HEAD/tree final se entrega junto con el commit documental.
- `schedule-status` productivo se consultó como evidencia operativa inicial:
  XNYS cerrado, lock vivo/token coherente y jobs estáticos disponibles. Su
  `runtime_state` devolvió `available=false`, razón estable
  `wal_mode_or_sidecar_present`; no se repararon sidecars ni se hizo
  checkpoint. Las consultas SQLite del informe se ejecutaron con URI
  `mode=ro` y `PRAGMA query_only=ON`.
- Kernel/configuración productiva permanecieron válidos. No se usaron broker,
  red, yfinance, LLM operativo, Telegram, jobs, postmarket, reconciliación,
  smoke ni suite completa.

## Método y denominadores

Se separaron dos ventanas de señal XNYS, usando fechas de señal inclusivas y
fecha final exclusiva:

- 4 semanas: `2026-07-06` → `2026-08-02` (datos disponibles hasta 31-jul).
- 8 semanas: `2026-06-08` → `2026-08-02`.

Para tablas de mercado se usó el ID canónico de la propia tabla y para CI el
ID primario de cada etapa. No se dedujo identidad por símbolo, fecha o texto.
Los conteos de `created_at` de CI son actividad de la etapa en esa ventana;
los de `signal_date` son la cohorte de señal. No se suman como si fueran el
mismo denominador.

| Etapa | Identidad y productor | 4 semanas | 8 semanas | Consumidor / límite |
|---|---|---:|---:|---|
| Señal/candidato | `signal_outcomes.signal_id`, `signal_learning.record_signal_candidates` | 14.600 / 14.600 únicos | 96.245 / 96.245 | `daily_learning._rebuild_signal_cohorts`; señal fechada |
| Observación de aprendizaje | `learning_observations.observation_id`, materialización de `daily_learning` | 12.428 / 12.428 | 34.812 / 34.812 | `learning_scoreboard`; observación canónica |
| Recomendación | `trade_recommendations.recommendation_id` | 1.564 / 1.564 | 2.166 / 2.166 | decisión/plan; `created_at` |
| Plan | `order_plans.plan_id` | 50 / 50 | 51 / 51 | ejecución/reconciliación; `created_at` |
| Orden de broker | `broker_orders.broker_order_id` | 78 / 78 | 82 / 82 | reconciliación; 78/78 y 82/82 figuran `filled` localmente |
| Resultado maduro | `outcome_json.matured_horizons` de la fila canónica | 1d 14.005; 3d 12.848; 5d 11.650; 10d 8.600 | 1d 95.650; 3d 94.350; 5d 93.152; 10d 90.102 | Madurez de observaciones generales; no equivale a madurez del tratamiento ejecutado |
| Hallazgo | No hay tabla/ID durable de findings equivalente | unavailable | unavailable | `measured_findings()` es una lista determinista estática de 4 findings más un finding de prosa reciente; los eventos `lab_*` son telemetría |
| Hipótesis | `continuous_improvement_hypotheses.hypothesis_id` | 0 creadas | 0 creadas | 15 históricas, todas `OPEN`; `hypothesis_saved` (864 eventos/IDs en 8 semanas) es actividad y no sustituye la tabla canónica |
| Propuesta | `continuous_improvement_proposals.proposal_id` | 521 | 1.573 | gobierno/validación; `created_at` |
| Validación | `continuous_improvement_validations.validation_id` | 516 | 1.837 | contrato y tests; `created_at` |
| Experimento | `continuous_improvement_experiments.experiment_id` | 524 | 718 | resultado/artifact; `created_at` |
| Decisión CI | `continuous_improvement_decisions.decision_id` | 793 | 1.173 | actor/estado; `created_at` |
| Cambio aplicado | `continuous_improvement_applied_changes.applied_change_id` | 2 `APPLIED` | 3 `APPLIED` + 1 `ROLLED_BACK` | persistencia de cambio; `created_at` |
| Evaluación post-aplicación | identidad/tabla canónica de evaluación no separada | 0/unavailable | 0/unavailable | digest: 3 cambios activos, 0 evaluados, cobertura 0 |

Estados complementarios observados en las mismas ventanas: planes 48/48
`SUBMITTED` y 2/3 `EXPIRED`; propuestas 4 semanas `REJECTED=518`,
`PENDING=2`, `READY_TO_APPLY=1`, y 8 semanas `REJECTED=1554`,
`READY_TO_APPLY=12`, `APPLIED=5`, `PENDING=2`; experimentos 4 semanas
`COMPLETED=367`, `FAILED=93`, `PASSED=64`, y 8 semanas `COMPLETED=497`,
`FAILED=126`, `PASSED=95`.

Los 718 experimentos y los 95 `PASSED` son filas históricas de la base, no
prueban admisión contractual ni una ejecución reciente. El digest diario
del 31-jul, con su propia ventana, publica 0 experimentos de evidencia
admitidos y 0 cambios aplicados; no se mezclan ambas proyecciones.

No existe una tabla separada de `candidate_id` en este tramo: el productor
persiste la señal/candidato en `signal_outcomes` y el candidato se representa
por `signal_id` más `source_run_id`. Por eso la primera fila es un conteo
combinado auditable y no una afirmación de que señal y candidato sean la
misma entidad de dominio.

## Productor → evento → consumidor

1. `signal_learning.record_signal_candidates()` crea la fila de señal y
   conserva `signal_id`, `source_run_id` y un `gate` inicial. La observación
   aún no es una ejecución.
2. La actualización posterior de decisión/capacidad pasa por
   `signal_learning.update_signal_execution_status()`, que conoce
   `source_run_id`, símbolos aprobados, planes rechazados y razón/estado de
   capacidad; su payload puede contener `approved_not_planned`,
   `max_orders_per_cycle_reached`, `max_daily_buy_orders_reached` o
   `low_sample_daily_quota_exhausted`.
3. `counterfactual_analysis._rebuild_signal_cohorts()` y
   `daily_learning._rebuild_signal_cohorts()` consumen `signal_outcomes`,
   enlazan órdenes por identidad exacta y conservan el `gate` recibido. La
   materialización agrupa por `(signal_date, symbol, source_family)` y genera
   `observation_id`; no inventa una razón ausente.
4. `learning_scoreboard` filtra la cohorte `learning_experiment` y empareja
   controles por misma fecha, intersección de `source_run_ids`, decisión
   `approved_buy*` y razón/estado de capacidad allowlisted. Ordena por rank,
   score e `observation_id` y limita el resultado a tres controles.

En las 43 ejecuciones auditadas el consumidor recibió `decision=executed_buy`
y `gate.execution={}`. Por tanto el vacío es una pérdida de carrier entre el
productor de decisión/capacidad y la observación canónica, no un fallo del
criterio exacto del matcher.

## Control same-cycle: 0/43 reproducido

El scoreboard corresponde a `run_id=pmr_dfe5e200c9cc_measure_scoreboard`,
`as_of=2026-07-31T20:36:36.448914+00:00`, periodo 07-jul → 31-jul. Tiene 43
ejecuciones elegibles, 36 con linaje verificado y 0 controles emparejados.
Para cada una de las 43:

- existen 493–496 controles de la misma fecha;
- existen 489–496 filas con intersección de `source_run_ids`;
- existen rank/score para la ejecución y las filas candidatas;
- hay 0 controles que superen la elegibilidad de capacidad;
- la fila ejecutada conserva `gate.execution={}` y `decision=executed_buy`.

La clasificación mutuamente excluyente de la ausencia de control es:

| Causa primera | Casos | Evidencia |
|---|---:|---|
| `decision_not_eligible` | 43 | Ninguna fila control recibida para esos pares es `approved_buy*`; las 43 ejecuciones son `executed_buy` |
| sin control de misma fecha | 0 | Hay 493–496 por ejecución |
| `source_run_ids` ausentes/no coincidentes | 0 | Todas las 43 tienen source IDs y hay 489–496 intersecciones |
| razón de capacidad no allowlisted | 0 no alcanzados | El filtro de decisión falla antes; no se debe inventar esta causa |
| rank/score ausente | 0 | Los 43 tienen rank/score; no es la pérdida observada |
| identidad ambigua | 0 como causa del matching | Los 7 linajes legacy se reportan aparte, no se usan como control |
| resultado inmaduro | 0 como causa del matching | La madurez se evalúa después del emparejamiento |
| otra | 0 | No necesaria en esta reproducción |

Hay un control `approved_buy_micro` con `approved_not_planned` el 07-jul,
pero no existe una ejecución de las 43 en esa fecha con la que pueda formar
pareja. SPY y el pool de régimen (`9396` observaciones) quedan como diagnóstico
secundario, nunca como control causal.

Conclusión: el algoritmo de matching es conservador y correcto contra datos
incompletos; el contrato de transporte está incompleto. P-L80B debe reparar
el carrier desde el productor hasta `signal_outcomes`/`learning_observations`
sin cambiar el matcher.

## Linaje 36/43

Los siete casos no verificados son:

`2026-07-08:AIZ:learning_experiment`,
`2026-07-08:ALL:learning_experiment`,
`2026-07-08:CRWD:learning_experiment`,
`2026-07-09:EXPE:learning_experiment`,
`2026-07-09:SBUX:learning_experiment`,
`2026-07-09:STT:learning_experiment`,
`2026-07-10:EBAY:learning_experiment`.

Los 7 tienen `signal_id` y `cycle_id`, pero campos de
`decision_lineage`/`candidate_rank` ausentes y se clasifican
`legacy_unverified`; los otros 36 tienen `lineage_status=verified`. La
ausencia de linaje reduce la verificabilidad, pero no explica 0/43: todos
los 43 conservaron `source_run_ids` y el vacío del matcher se reproduce en
las 36 verificadas.

## Qué mide `duplicate_ratio=0,8433`

`daily_learning._observation_payload()` agrupa filas crudas por
`(signal_date, symbol, source_family)`, crea una observación canónica y
calcula `duplicate_count=max(0, len(group)-1)`. El health calcula
`duplicate_signals / total_signals`. No es una tasa de eventos reintentados,
IDs duplicados, órdenes duplicadas ni una tasa económica por símbolo.

El artefacto diario del 31-jul, `as_of=2026-07-31T20:35:30.457961+00:00`,
publica `signals_raw=200000`, `canonical_observations=31348`,
`duplicate_signals=168652` y `duplicate_ratio=0,8433`. La consulta directa de
SQLite, con otra proyección/retención, devuelve:

- 4 semanas: 12.428 observaciones y 2.168 repeticiones calculadas, ratio
  `0,1485`.
- 8 semanas: 34.812 observaciones y 123.679 repeticiones, ratio `0,7804`.
  Por familia en 8 semanas: `intraday_scan 110.083`,
  `opportunity_snapshot 11.424`, `learning_experiment 1.801`,
  `closed_market_study 371`.

La diferencia `0,8433` frente a `0,7804`/`0,1485` es una discrepancia de
identidad de snapshot/proyección, no un dato para promediar. La auditoría no
reescribe ni deduplica historia; P-L80G queda como deuda posterior de
reconciliación de retención y denominador.

## Prosa, experimentos y gobierno

La muestra de calidad del digest tiene 200 propuestas: 199 `PROSA` por
`no_deterministic_execution_spec` y 1 `EJECUTABLE`. La base completa tiene
2.241 propuestas: `REJECTED=2222`, `READY_TO_APPLY=12`, `PENDING=2`,
`APPLIED=5`, con tipos `MONITORING_CHANGE=1358`, `CODE_CHANGE=353`,
`DATA_QUALITY_CHANGE=269`, `RISK_RULE_CHANGE=139`, `PARAMETER_CHANGE=117` y
`PROMPT_CHANGE=5`.

El flujo observado es:

`findings_to_proposals.measured_findings()` (4 findings deterministas y un
finding reciente) → candidatos de código de baja peligrosidad → límite de
cola `[:2]` → `validate_experiment_contract` → validación/human review →
experimento si tiene contract y validaciones → decisión → aplicación solo si
la gobernanza lo autoriza.

En este runtime `improvement_dry_run` está activo y `allow_auto_apply` es
falso. La cola de findings se ejecuta como preview/no-op para nuevas
propuestas, el puente de learning no aporta candidatos actuales y el contrato
requiere `change_class`, origen con IDs/eventos, hipótesis, métrica, baseline,
target, `min_sample >= 30`, paths permitidos, rollback y freshness. El estado
`READY_TO_APPLY` es un estado de cola/validación; no equivale por sí solo a
contrato válido ni a autorización de aplicación. Por eso puede coexistir con
prosa, revisión humana pendiente o auto-apply desactivado.

Hay 718 experimentos históricos (`strategy_edge_compare=96`, además de
backtest, baseline, shadow, paper y risk review). El clasificador los puede
identificar como experimentos de evidencia por forma, pero el digest actual
admite 0 porque la evidencia contractual/propuesta no es válida. No se debe
traducir `PASSED` histórico en cambio aplicado.

La tabla canónica contiene 15 hipótesis históricas, todas `OPEN`, creadas en
mayo/junio y fuera de las ventanas auditadas; no hay `KILLED` ni `PROMOTED`.
Los 864 eventos `hypothesis_saved` de 8 semanas demuestran actividad de
agentes, no cierre de hipótesis. Las 48 investigaciones/estudios semanales
del digest son una proyección de estudios, no un denominador de hipótesis
canónicas.

## Anomalías de market-data y valor económico

El digest generado el 01-ago conserva 37 bloqueos. El artefacto de calidad
más reciente disponible está fechado `2026-07-20T13:59:32Z` y clasifica los
37/37 como `ohlc_invalid`, severidad bloqueante, proveedor yfinance y
`affects_operational_scan=true`. Existen artefactos del 18-jul con cero
anomalías, por lo que el número 37 es una señal persistida/stale y no una
medición actual de 02-ago. Sin ejecutar el productor no puede declararse el
estado vigente; se clasifica `stale/unavailable` para decisión operativa.

La anomalía bloquea medición/selección de datos de mercado y puede impedir
admitir evidencia, pero no demuestra por sí sola un cambio de órdenes, gates
de riesgo o política. No se atribuyen P/L, slippage, MFE/MAE, drawdown o
concentración a una sesión sin outcome maduro, identidad exacta y benchmark
comparable.

La magnitud de actividad está confirmada por eventos de 8 semanas: 30.403
`continuous_improvement_completed`, 23.731 `lab_market_window_blocked`,
6.228/6.226 `portfolio_watch_started/completed`, 1.467 consolidaciones de
propuestas, 945 validaciones registradas, 864 ciclos de hipótesis y decisión,
136 registros de experimentos, 65 fallos de mejora continua, 39 inicios de
postmarket y 31 `performance_daily_recorded`. La pérdida de valor se produce
en carriers, calidad, contrato y madurez; no es falta de actividad bruta.

## Hechos, inferencias y unavailable

**Hechos verificados:** 43 tratamientos elegibles, 0 controles, 36/43 linaje
verificado; las 43 tienen fecha/source IDs/rank/score; `decision=executed_buy`
y `gate.execution={}`; 199/200 prosa; 0 experimentos de evidencia admitidos
en el digest vigente; WIP 14; 37 anomalías stale; el loader de control filtra
por identidad exacta; no se sustituyó SPY.

**Inferencia causal de alta confianza:** el carrier de decisión/capacidad se
pierde antes de la observación canónica; corregir el productor/propagación,
manteniendo el matcher, tiene mayor valor de información que ampliar el
matching o promover propuestas.

**Unavailable/conflicto:** estado runtime actual por WAL/sidecars; freshness
actual de las 37 anomalías; tabla durable de findings; evaluación
post-apply por observación separada; procedencia que reconcilie exactamente
el ratio del artefacto diario con la lectura directa; causalidad económica de
los resultados inmaduros.

## Único siguiente lote recomendado: P-L80B

**Pregunta:** ¿Puede el productor de decisión/capacidad persistir, con la
misma identidad de `source_run_id` y ciclo, el carrier `approved_buy*` más
`gate.execution.reason/status` hasta `signal_outcomes` y
`learning_observations`, de modo que el matcher existente forme controles
same-cycle sin falsos emparejamientos?

**Fronteras probables:** `src/agente_bolsa/tools/signal_learning.py`,
`src/agente_bolsa/tools/daily_learning.py`,
`src/agente_bolsa/tools/counterfactual_analysis.py`, almacenamiento del
carrier solo si es imprescindible, `learning_scoreboard.py` únicamente para
instrumentación/tests, y tests focales. No tocar `trade_decision`, broker,
execution, risk, sizing, planes, órdenes, scheduler ni política. No cambiar
el matcher salvo para demostrar que continúa igual.

**Precondiciones:** XNYS cerrado para la validación larga, PMR terminal y
lease vacío; worktree limpio desde el HEAD productivo vigente; fixtures sin
red con dos filas del mismo día/source-run (una ejecutada y una
`approved_not_planned`/razón allowlisted); fixtures de source IDs ausentes,
fecha distinta, conflicto de identidad y outcome inmaduro; `DATA_DIR`
temporal y `_env_file=None`.

**Aceptación:** la cadena productor → `signal_outcomes.gate_json` →
`learning_observations.gate_json` conserva el carrier sin reconstruirlo por
símbolo/fecha; una pareja exacta aparece en el matcher; faltas/conflictos
siguen 0/unavailable; no se usa SPY/régimen; append-only/idempotencia y
linaje histórico permanecen intactos; la ruta económica produce exactamente
los mismos candidatos, ranks, gates, sizing, planes, cantidades, precios,
órdenes, exposición y límites.

**Parada:** si el carrier no existe en el productor, exige frontera humana
explícita; si requiere modificar trading/risk/execution o sustituir el
control, se detiene. La corrección no autoriza auto-apply ni promoción.

**Versión:** no se reserva número en esta auditoría. Si hay cambio funcional,
la política de versión deberá asignar el siguiente slot libre; si el lote
fuera tests/docs solamente no requiere bump.

La cola provisional posterior (no autorizada ni ejecutada) es: P-L80C,
linaje de los 7 legacy; P-L80D, contrato finding→proposal para eliminar
prosa; P-L80E, admisión de experimentos y evaluación post-apply; P-L80F,
freshness/autoridad de market-data; P-L80G, reconciliación de duplicate ratio
y retención. Solo P-L80B es el siguiente lote recomendado.

## Validación y cambios realizados

En la auditoría P-L80A no se ejecutaron tests largos, suite completa, smoke, jobs, servicios o
proveedores externos por el alcance y las restricciones de mercado. Se
realizaron lecturas de código, artefactos y consultas SQLite estrictamente
read-only; se creó únicamente este worktree y la documentación del lote.
No se modificó producción, SQLite, configuración, locks, leases, `.env`,
manifest, kernel, broker, red, LLM operativo, Telegram ni Git de producción.

El commit de entrega es documental/audit-only; no hay bump de versión. El
HEAD/tree concretos de cierre se consignan en el dictamen final junto con la
limpieza del worktree y la confirmación de producción intacta.

## P-L80B - cierre prospectivo del carrier same-cycle

**Dictamen:** `ready_for_integration_rehearsal`.

**Causa y frontera reparada:** el productor activo conocía el
`decision_lineage.signal_id`, pero `update_signal_execution_status()` solo
recibía `approved_symbols`; Store buscaba por `source_run_id + symbol`. La
primera pérdida verificable era por tanto la llamada
`run_observable_cycle` → `update_signal_execution_status` →
`Store.update_signal_gate`, antes de `signal_outcomes.gate_json`. Dos señales
del mismo símbolo y source-run podían contaminarse y el carrier de capacidad
no llegaba a `learning_observations`.

El candidato introduce una ruta exacta y una compatibilidad legacy separadas:

```text
recommendation.decision_lineage.signal_id
  -> update_signal_decisions(signal_id, source_run_id)
  -> update_signal_execution_status(approved_recommendations, cycle_id)
  -> signal_outcomes.gate_json.execution
  -> daily_learning._materialize_observations()
  -> learning_observations.gate_json
  -> learning_scoreboard._cohort_rows()
```

La ruta exacta transporta `signal_id`, `source_run_id`, `cycle_id`,
`decision_lineage`, límites efectivos y el estado `submitted`,
`submit_failed`, `plan_rejected`, `plan_created` o `approved_not_planned`.
Una identidad ausente no cae silenciosamente a símbolo. La ruta anterior por
símbolo permanece solo para callers legacy que no entregan el carrier.
`learning_scoreboard` y sus condiciones de matching no se modificaron.

**Caracterización y pruebas deterministas:** contra la base P-L80A,
`tests/test_p80b_same_cycle_control_carrier.py` falló con
`TypeError` porque el API no aceptaba `approved_recommendations`. Tras el
fix, las pruebas demuestran:

- la pareja exacta de la misma fecha/source-run produce un único control
  `approved_not_planned`;
- fecha distinta, source-run distinto, decisión `candidate`, razón no
  allowlisted e identidad ausente producen `0` controles;
- dos filas del mismo símbolo se actualizan por `signal_id` sin
  contaminación;
- `signal_outcomes` → `learning_observations` conserva el gate y el matcher
  devuelve solo el control exacto;
- reintento con el mismo contenido es idempotente; contenido distinto
  conserva el original y registra `signal_execution_carrier_conflict` en
  `agent_events` mediante inserción append-only.

Se ejecutaron 147 pruebas focales de carrier, signal-learning, daily-learning,
scoreboard, counterfactual, ciclo, storage e identidad. La suite completa
aislada terminó en **2392 passed, 1 skipped preexistente y 1 warning** en
819 s. El primer intento de suite tuvo 1540 passed y una única aserción
obsoleta que esperaba 0.4.214; se corrigió solo esa expectativa de
`test_version_policy_requires_bump` y la repetición quedó verde. El warning
es la deprecación externa de `websockets.legacy`.

Ruff, `scripts/check_no_nulls.py`, compilación temporal, `git diff --check`
y `validate-agent-config --json` (`23` agentes, `6` tareas, sin warnings)
quedaron verdes. `kernel-status --json` del entorno temporal fue
`unsealed` sin violaciones, esperado por ausencia de manifest. El smoke
`run-once --skip-crew` usó DATA_DIR temporal, snapshots fake y un broker que
fallaba si era invocado: terminó con `used_crew=false`, calidad de mercado
degradada controlada y sin red, broker ni LLM.

**Paridad y seguridad:** la única versión funcional candidata es 0.4.215.
Los objetos de `kernel.py`, `broker.py`, `execution.py`, `risk.py` y
`config.py` son idénticos a la base; `.env` no está en el árbol del candidato
y no fue leído ni modificado. Las pruebas de ciclo/identidad conservan
candidatos, scores, ranks, gates, sizing, planes, cantidades, precios,
stops/takes, órdenes, exposición y límites; este cambio solo añade
observabilidad prospectiva. No hay backfill ni reescritura de las 43 filas
históricas.

**Cutoff prospectivo:** no se fija una fecha artificial. Tras un eventual
despliegue, el cutoff será `deployment_activation_at` UTC; la ventana de
cinco sesiones será la primera sesión XNYS posterior al cutoff y las cuatro
siguientes, todas completadas y con carrier exacto. Las filas anteriores al
cutoff, incluida la muestra 43/43 auditada por P-L80A, quedan históricas y no
se rellenan. El resultado de cinco sesiones solo podrá evaluarse con outcomes
maduros e identidad canónica.

**Base y entrega:** worktree `pl80b_same_cycle_control_carrier`, rama
`codex/p-l80b-same-cycle-control-carrier`, base
`b89bef4790f357d0afea95dc6ec8fdbac4ef84e3`. Commits separados:
`39ac28c6` (caracterización), `e089f7f3` (implementación y bump) y
`a57c0f67` (corrección QA de versión). El commit documental de este apartado
se añade después de cerrar el informe. Producción permanece en
0.4.214/`eb662c07`/tree `2ee61f28`, sin merge, deploy, reinicio, jobs
manuales, broker/red/LLM operativo, SQLite escritora ni push.

## P-L80B-QA1 - aislamiento y razón de capacidad allowlisted

La revisión QA añadió cobertura exclusivamente en
`tests/test_p80b_same_cycle_control_carrier.py`. Los fixtures construyen
`Settings(_env_file=None, DATA_DIR=tmp_path)` y eliminan las seis variables
`TRADE_FILL_WATCH_*` del entorno mediante `monkeypatch`; una variable externa
activa se prueba antes de sanearla y no altera el default del fixture. No se
lee ni modifica `.env`.

El positivo pasa `rejected_order_plans` con identidad exacta por `signal_id` y
razón real `max_daily_buy_orders_reached`. Después de materializar conserva
`decision=approved_buy*`, `gate.execution.status=plan_rejected`, la razón
allowlisted, `signal_date` y `source_run_id`, y el matcher existente forma el
control. El gemelo con `operator_note` no forma pareja. También se verificó el
helper común `_rejection_payload_for_plan`: las rutas reales de daily limit y
low-sample quota ya le pasan `signal_id` y `cycle_id`; no se amplió código.
El fallback `approved_not_planned` sigue sin habilitar una decisión que no sea
`approved_buy*`.

QA1 focal: **9 passed** en el fichero P-L80B. Suite completa final sobre el
árbol definitivo: **2395 passed, 1 skipped preexistente y 1 warning** en
755 s. El warning sigue siendo la deprecación externa de
`websockets.legacy`; no hay skips/xfails nuevos. Ruff, NUL y
`git diff --check` permanecen verdes. El commit QA es `14c22e5a`.

El candidato actual incorpora además `b2645dfe`, que hace la idempotencia del
carrier independiente del orden de claves JSON mediante hash canónico. El
HEAD/tree exactos finales se consignan tras el commit documental; producción,
SQLite, stack, `.env`, manifest y archivos protegidos siguen intactos.

**Identidad del árbol funcional/QA antes del último commit documental:** rama
`codex/p-l80b-same-cycle-control-carrier`, HEAD
`27c43c216f6385d5fd435d32c21cbcb416cb7903`, tree
`16dae762367fe204aaf4ce0baf8a9c15830835c2`, versión `0.4.215`. El commit
documental de cierre no modifica código ni tests; el HEAD/tree finales constan
en la entrega. Producción sigue en HEAD
`eb662c0760c77aae58067c18a9cbcdb06651b719`, tree
`2ee61f285eaa5293a4daab07de793cb9cdbae16c`, versión `0.4.214`, con solo los
untracked conocidos del operador.

## P-L80BR - ensayo aislado de integración del carrier same-cycle

Dictamen del ensayo: **ready_for_closed_market_deployment**; no desplegado.
El worktree `pl80br_integration_rehearsal`, rama
`codex/pl80br-integration-rehearsal`, parte de producción
`eb662c0760c77aae58067c18a9cbcdb06651b719` y fusiona exclusivamente con
`git merge --no-ff` el candidato `b0ff0d94212828aad8a427b694d59f955f64db9a`.
El merge `5d7ea285143f6e16ba416fde7c885ffdc4202ef2` tiene como padres exactos
producción y candidato; termina en versión `0.4.215`, tree
`e3e75910efdf6933fe66afc0ed85a3b97c411ee5`, idéntico al tree del candidato.
No hubo conflictos ni deltas funcionales adicionales.

Los focales combinados del productor, materialización, matcher, identidad,
idempotencia, conflictos, legacy y paridad dieron **110 passed**. Se reutiliza
la suite completa previa (**2395 passed, 1 skipped preexistente y 1 warning**)
porque el tree integrado es idéntico objeto-a-objeto al candidato ya validado;
no se repitió por actividad. Ruff, NUL, compilación y `git diff --check` fueron
verdes. `validate-agent-config --json` aislado fue `ok=true`; el kernel temporal
fue `unsealed` con `violations=[]`, mientras el kernel productivo permanecía
`ok`. El smoke real del parser `run-once --skip-crew` usó `DATA_DIR` temporal,
snapshot/estado fake y fronteras broker/órdenes que fallan si se alcanzan; pasó
sin red, broker ni LLM.

La pareja positiva y sus negativos conservan `signal_id`, `source_run_id`,
decisión/capacidad y las condiciones exactas del matcher. No se relajó el
matcher, no se hizo backfill y no se alteran candidatos, scores, ranks, gates,
sizing, planes, órdenes, exposición ni límites. Los objetos protegidos
`kernel.py`, broker, execution, risk y config coinciden con producción.
Producción, stack, SQLite, `.env`, manifest, locks y leases permanecen intactos;
no hubo merge productivo, reinicio, job manual, broker/red/LLM operativo ni
push.

## P-L80H2 - health canónico OpenCode Go / DeepSeek V4 Flash

**Dictamen: `blocked_external_provider`.** La implementación aislada queda
validada, pero la única llamada real autorizada al proveedor devolvió HTTP 403
clasificado como `region_forbidden`. No se hizo fallback, no se reintentó y no
se cambió proveedor, modelo, endpoint, credencial ni configuración. La ventana
de auditoría fue el 02-ago-2026, Europe/Madrid; la salida se registró sin
contenido de respuesta, credenciales ni identificadores de workspace.

### Candidato y alcance

El worktree es `C:\Antonio\Bref\agenteBolsa_worktrees\pl80h2_opencode_go_health`,
rama `codex/pl80h2-opencode-go-health`, basado en el candidato P-L80BR
`095f5cb59267c9d3c702b76b8481e9d708cff14c` (tree
`d0b2ed035a253bc420196292a945c6c2bb1e4fcc`, v0.4.215). El resultado final del
worktree y sus commits se consignan al cerrar esta sección; la versión de este
lote es **0.4.216**. Producción sigue en `eb662c07`/tree `2ee61f28`, v0.4.214,
con únicamente los untracked conocidos del operador.

El script `scripts/check_opencode_go_deepseek.py` es una frontera independiente
del runtime: no importa scheduler, broker, trading, Store ni SQLite; resuelve
la credencial mediante `Settings`, lee el `.env` existente del checkout productivo
hermano cuando el worktree no lo contiene, y nunca lo copia, escribe o imprime.
Por defecto exige exactamente `provider=opencode-go`,
`model=deepseek-v4-flash` y
`https://opencode.ai/zen/go/v1/chat/completions`. Envía una única petición
OpenAI-compatible, `temperature=0`, `max_tokens=16`, timeout acotado y sin
reintentos ni fallback. La salida solo expone host/path, estado HTTP,
latencia, `finish_reason`, `fallback_used=false`, contador de peticiones y
errores sanitizados. Un endpoint/modelo/selector distinto falla cerrado sin
hacer la petición.

### Resultado sanitizado de la única probe real

```text
provider=opencode-go
model=deepseek-v4-flash
endpoint_host=opencode.ai
endpoint_path=/zen/go/v1/chat/completions
status=failed
http_status=403
error_type=region_forbidden
fallback_used=false
requests_made=1
finish_reason=n/d
```

La causa es externa al repositorio: el endpoint oficial rechaza la región del
modelo. El resultado es coherente con los 403 `RegionError` históricos del
31-jul. No hay evidencia de endpoint divergente, alias GLM/Kimi, respuesta
inválida ni fallo de autenticación; el proveedor no llegó a producir una
respuesta de chat.

### Auditoría estática de rutas

| Ruta | Productor/consumidor | Identidad efectiva configurada | Fallback | Estado |
|---|---|---|---|---|
| Primaria, decisión, sentimiento | `llm_router.py`, `trade_decision.py`, `news_sentiment.py` | `opencode-go/deepseek-v4-flash`, base `/v1` que el cliente completa con `/chat/completions` | Qwen local; decisión conserva fallback determinista | coherente |
| `deep`, radar, estrategia, lesson y retrospectiva | `chat_for_role("deep")` y consumidores de investigación/CI | hereda DeepSeek de mejora/OpenCode Go | Qwen local o salida segura de la ruta | coherente |
| Mejora continua y overnight | `ImprovementLLMClient`, rutas `agents`/`orchestrator` | `opencode-go/deepseek-v4-flash`, base oficial | `openai-local/qwen3.6-27b`; errores no adquieren autoridad | coherente |
| Healthcheck nuevo | `scripts/check_opencode_go_deepseek.py` | identidad oficial exacta | ninguno, fail-closed | implementado |
| Healthcheck histórico | `scripts/llm_health_check.py` | lee varios roles y puede ejecutar cinco probes | diagnóstico legacy | no usar para este contrato de una llamada |

Los modelos GLM/Kimi que permanecen en UI, fixtures, pruebas de overrides o
documentación histórica no son defaults ni fallback silencioso. Qwen es el
único fallback técnico local configurado. El cambio de identidad LLM no otorga
autoridad sobre candidatos, scores, ranks, gates, sizing, planes, órdenes,
exposición, límites, readiness o auto-apply.

### QA

- Tests nuevos del script: **15 passed**.
- Focales de routing/config/DeepSeek, health legacy, mejora continua, codegen,
  overnight/retrospectiva, sentimiento y decisión: **288 passed**.
- Ruff focal y completo, NUL, compilación y `git diff --check`: verdes.
- `validate-agent-config --json` aislado: `ok=true`, sin warnings.
- `kernel-status --json` aislado: `unsealed` esperado por falta de manifiesto
  temporal, `violations=[]`; el kernel productivo ya estaba `ok` y no se tocó.
- Suite completa omitida justificadamente: el script es standalone y no se
  importa desde el runtime; las rutas importadas quedaron cubiertas por los
  focales. No se ejecutó smoke para no producir una segunda llamada LLM.

La producción, `.env`, SQLite, stack, locks, leases y archivos protegidos
permanecen intactos; no hubo broker, órdenes, trading, jobs, reinicio, merge,
deploy ni push. Siguiente precondición única: que el operador habilite el
opt-in regional oficial de OpenCode Go para la cuenta/workspace; después debe
repetirse el mismo script una sola vez, sin cambiar el contrato.

**Entrega del candidato:** commits `8a0a9a8a` (script/tests/version),
`ddcf3087` (resolución read-only del `.env` existente desde worktree aislado) y
`fc25f79f` (guard de endpoint oficial y test). El HEAD/tree finales y el estado
de limpieza se reportan en el dictamen final.

## P-L80H4 - causa raiz y fix minimo del gate del rollback

Dictamen: `ready_for_closed_market_redeployment`. Este candidato no se ha
integrado ni desplegado; produccion permanece en el estado seguro restaurado.

La reproduccion contra produccion v0.4.214 (`b1c4cc0f`, tree `2ee61f28`)
paso el test `test_version_policy_requires_bump`: la expectativa activa en esa
base es `0.4.214`. La reproduccion contra el candidato P-L80H2
`7e6e782c`/tree `6493d7e4` fallo porque la prueba seguia esperando `0.4.215`
despues del bump funcional a `0.4.216`. Es una regresion de test del candidato,
no un cambio de trading ni un leak de entorno.

El fix unico es el commit `338d0cc0`: actualiza la expectativa y su comentario
para `0.4.216` en `tests/test_p59c_llm_selected_authority.py`. No cambia
runtime, seleccion, gates economicos, sizing, riesgo, ejecucion, proveedor,
modelo, endpoint ni credenciales.

### QA P-L80H4

- Focales P-L80B/H2/P-L59C: **70 passed**.
- Suite completa: **2410 passed, 1 skip preexistente, 1 warning externo**,
  **815.69 s**. El skip y la warning son los preexistentes de la suite.
- Ruff: verde; `check_no_nulls.py`: **468 archivos OK**; compilacion temporal:
  **452 archivos**; `git diff --check`: verde.
- `validate-agent-config --json` aislado: `ok=true`, sin warnings.
- `kernel-status --json` aislado: `unsealed`, `violations=[]`, esperado sin
  manifiesto temporal.
- Smoke CLI real `run-once --skip-crew` aislado: verde con DATA_DIR temporal,
  snapshot/estado fake, `used_crew=false`, sin ordenes enviadas y sin broker,
  red o LLM. El primer arnes fallo antes de invocar el CLI por usar una firma
  incorrecta; se corrigio el arnes, no el codigo productivo, y el smoke final
  paso.
- Objetos Git protegidos (`kernel.py`, `broker.py`, `execution.py`, `risk.py`,
  `config.py`) iguales a la base.

### Probe DeepSeek recuperada

No se repitio la llamada en P-L80H4. La reprobe aislada posterior ya existente
fue: `provider=opencode-go`, `model=deepseek-v4-flash`, endpoint
`https://opencode.ai/zen/go/v1/chat/completions`, HTTP 200, `ok=true`,
latencia `1.774 s`, `finish_reason=stop`, `fallback_used=false`,
`requests_made=1`. El timestamp no fue emitido por la salida sanitizada.
La sonda canonica anterior con `max_tokens=16` habia terminado en
`response_invalid`/`finish_reason=length`; no se usa como evidencia verde.

Base de trabajo: `7e6e782c`; worktree
`C:\Antonio\Bref\agenteBolsa_worktrees\pl80h4_gate_fix`; rama
`codex/pl80h4-gate-fix`; commit funcional `338d0cc0`; version `0.4.216`.
Produccion, `.env`, SQLite, stack, untracked del operador y el candidato
original permanecen intactos; no hubo probe adicional, merge productivo,
despliegue, jobs manuales, kernel-seal ni push.
