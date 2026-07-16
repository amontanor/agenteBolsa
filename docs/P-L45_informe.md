# P-L45B1 — fiabilidad y terminales del postmarket

## Estado del candidato

P-L45B1 se implementa únicamente en el worktree aislado
`codex/pl45b-postmarket-reliability`, con versión candidata `0.4.174`.
Producción continúa sin cambios en `0.4.173`. P-L44B queda pospuesto para
`0.4.175` y no forma parte de este candidato.

La compactación de contexto 220k no está expuesta en la interfaz utilizada.
No se modificó configuración por ese motivo.

## Causa raíz abordada

P-L45A demostró cuatro problemas relacionados:

- bootstrap y job programado podían iniciar el mismo postmarket;
- reconciliación programada podía competir con la reconciliación interna;
- `update_signal_outcomes()` se calculaba de nuevo dentro de
  `build_learning_daily_run()`;
- los intentos no tenían un contrato terminal durable y conflict-safe.

El candidato añade `postmarket_coordination.py`, que usa `runtime_state` como
vista operativa de leases y `agent_events` como historial. No crea tablas ni
migraciones.

## Contrato y coordinación

Los eventos nuevos usan `p-l45b1.postmarket-run.v1` y conservan:

`session_date`, `run_id`, `trigger`, `owner_pid`, `owner_token`, `stage`,
`status`, `reason`, `started_at`, `finished_at`, `duration`, `error` y
`content_hash`.

Un lease se adquiere con una transacción SQLite `BEGIN IMMEDIATE` corta. El
lease no expira por tiempo: un propietario vivo no se sustituye. Un propietario
muerto se recupera mediante PID/liveness y recibe un terminal `failed` sintético
con razón `owner_dead_recovered`.

Bootstrap y scheduler compiten por la misma clave de sesión. La reconciliación
programada usa una clave separada: si el postmarket está activo se registra
`skipped/postmarket_already_running`; si hay otra reconciliación activa, la
segunda también queda omitida de forma durable. La reconciliación interna del
postmarket pertenece al propietario adquirido y no vuelve a adquirir el lease.

Los eventos nuevos nunca usan `INSERT OR REPLACE`. Repetir el mismo ID y
contenido es idempotente; el mismo ID con otro hash conserva el original y
publica un evento de conflicto.

`post_market_review_last_session` solo se actualiza después del terminal
`completed`. Un fallo de persistencia de telemetría no altera el resultado del
pipeline ni transforma un fallo operativo en éxito.

## Single outcome update

Una ejecución efectiva de postmarket llama una sola vez a
`update_signal_outcomes()`. El resultado se entrega como `update_result` a
`build_learning_daily_run()`. Los llamadores independientes que no pasan el
argumento mantienen el comportamiento anterior.

La reconciliación interna usa `update_learning=False`; no ejecuta una segunda
actualización. No se cambia la fórmula de outcomes, observaciones, cohortes ni
digest.

## Etapas observables

Se registran etapas `coordination`, `reconciliation`, `outcome_update`,
`daily_learning`, `postmarket_report`, `performance`,
`measurement_pipeline`, `thesis` y `terminal`, con estado iniciado,
completado o fallido y duración cuando existe un par inicio-fin.

La vista `runtime_state` solo indica el propietario y etapa actuales. Los
eventos son la fuente histórica y permiten distinguir `completed`, `failed` y
`skipped` sin contar ticks ni reintentos como una sola ejecución.

## Validación focal

Las pruebas deterministas cubren:

- dos triggers simultáneos y bootstrap frente a scheduler;
- sesión ya completada;
- reconciliación aplazada durante PMR y dos reconciliaciones simultáneas;
- propietario vivo y recuperación de propietario muerto;
- terminal `failed` y reintento posterior;
- idempotencia y conflictos append-only;
- concurrencia SQLite temporal sin pérdida de evento;
- una única actualización de outcomes y compatibilidad legacy de
  `build_learning_daily_run()`.

El batching de observaciones queda explícitamente fuera de B1 y reservado a
P-L45B2. La mejora de duración solo podrá interpretarse tras cinco sesiones
reales posteriores; este candidato no cambia trading, señales, ranking, gates,
stops, takes, exposición, órdenes ni la política shadow de P-L43B.

## Resultado de validación

Las focales P-L45B1 y las regresiones de postmarket, reconciliación, aprendizaje
y performance pasaron: **76 passed**. Ruff, `check_no_nulls.py`, compilación y
`git diff --check` pasaron. El smoke `run-once --skip-crew` con DATA_DIR y
credenciales vacías terminó correctamente.

La suite completa se detuvo en el primer fallo preexistente tras **916 passed y
1 skipped**: `tests/test_promotion.py::test_insufficient_evidence_extends_window`
obtiene `REJECTED_SHADOW` donde la prueba espera `EXTEND`. El mismo fallo se
reproduce contra la rama de integración sin los cambios P-L45B1 y no afecta a
los archivos modificados por este lote. No se corrigió por quedar fuera de
alcance.

## P-L45B1-QA — correcciones del ensayo de integración

La reconciliación del fallo preexistente se resolvió en `b11db6e1`: la fixture
usa `DATA_DIR` temporal, `_env_file=None` y reloj congelado. Se conserva un caso
independiente que demuestra `REJECTED_SHADOW` cuando la ventana supera la gracia
de calendario. La versión candidata permanece en `0.4.174`.

La revisión adversarial encontró además dos huecos reales del candidato. El
`owner_token` era solamente `pid:<pid>` y no distinguía un PID reutilizado;
APScheduler no tenía listener durable para `EVENT_JOB_MAX_INSTANCES` ni
`EVENT_JOB_MISSED`; y el marcador `post_market_review_last_session` podía
retroceder si una sesión antigua terminaba después. Los tres huecos se
corrigieron mínimamente en el worktree de ensayo:
el token ahora identifica el proceso y los skips externos se registran como
`p-l45b1.scheduler-event.v1` mediante `agent_events`, sin cambiar horarios,
`max_instances`, `coalesce` ni la ruta de trading; el marcador solo avanza de
forma monotónica tras un terminal `completed`.

Las pruebas de coordinación y QA cubren 25 procesos concurrentes por escenario,
dos sesiones distintas, recuperación por token, reintento tras `failed`,
idempotencia y eventos APScheduler. El batching de observaciones continúa fuera
de alcance y reservado a P-L45B2.

## P-L45B1-D - desplegado en producción

El 16-jul-2026, con XNYS cerrado y 158 minutos hasta la apertura, se fusionó
`codex/pl45b-integration-rehearsal` mediante merge `--no-ff` productivo
`2dbd02a8`. El tree productivo `a3dba615` coincide con el tree validado del
ensayo y la versión desplegada es `0.4.174`.

Validación detenida: focales P-L45B1/QA y regresiones `160 passed`; suite
completa `1395 passed` con una advertencia deprecada preexistente; Ruff,
`check_no_nulls.py`, `git diff --check`, configuración, kernel y smoke aislado
verdes. El stack arrancó con un único scheduler lógico, lock/PID coherente,
heartbeat fresco y panel HTTP 200. Los avisos de salud son warnings
preexistentes, sin alertas críticas.

Tras el reinicio, el bootstrap publicó un único intento `pmr_9a31399a85c7`
con `coordination:started` y terminal `skipped` (`market_not_ready`); no hubo
reconciliación ni actualización adicional de outcomes, y
`post_market_review_last_session` permaneció en `2026-07-15`. No se reprocesó
la sesión ni aparecieron bloqueos SQLite.

P-L43B conserva `legacy_calendar_days` como política activa y XNYS en
`shadow_only=true`. P-L45B2 queda pendiente; la mejora de duración solo se
interpretará tras cinco sesiones reales posteriores. P-L44B sigue diferido a
`0.4.175`.
