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

No se ejecutaron tests largos, suite completa, smoke, jobs, servicios o
proveedores externos por el alcance y las restricciones de mercado. Se
realizaron lecturas de código, artefactos y consultas SQLite estrictamente
read-only; se creó únicamente este worktree y la documentación del lote.
No se modificó producción, SQLite, configuración, locks, leases, `.env`,
manifest, kernel, broker, red, LLM operativo, Telegram ni Git de producción.

El commit de entrega es documental/audit-only; no hay bump de versión. El
HEAD/tree concretos de cierre se consignan en el dictamen final junto con la
limpieza del worktree y la confirmación de producción intacta.
