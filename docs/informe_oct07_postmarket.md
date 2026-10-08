# Postmarket: cartera ausente explícita (7-oct-2026)

Dictamen: `ready_for_closed_market_full_validation`, condicionado a revisión del coordinador, reserva/bump de versión e integración. Lote N2. La ausencia de snapshot debe fallar antes de leer historial, calcular aprendizaje o publicar el informe; nunca equivale a una cartera vacía ni a una revisión completada.

## Referencias y alcance

Worktree exclusivo: `C:/Users/utopi/.codex/worktrees/bolsa-oct07-321/agenteBolsa`. Rama `codex/oct07-postmarket`. Base: `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`; tree base `4d118b504b305e45f45a06d9aaffa063079abaf7`; versión `0.4.321`. Árbol inicial limpio; árbol final contiene únicamente implementación, test e informe de este lote. Bump pendiente por coordinación; commits separados autorizados posteriormente, sin reescribir historia.

XNYS abierto según comprobación del coordinador a las 20:08 Europe/Madrid del 7-oct. Solo trabajo aislado y pruebas focales. No se ejecutó una comprobación operativa propia ni se consultó producción.

## Causa y evidencia

`audit_week_extra.json` registra dos eventos `post_market_review_failed` para sesión `2026-10-06`: `evt_0dbf81a5697f`, `2026-10-06T21:03:58.144228+00:00`; `evt_fe99f7c99b09`, `2026-10-06T21:52:52.355129+00:00`. Ambos contienen `AttributeError("'NoneType' object has no attribute 'positions'")`. No incluyen traceback: la atribución exacta del frame productivo permanece `unavailable`.

Ruta verificada en código: `scheduler.post_market_review_job` conserva `portfolio=None` cuando falla la adquisición del snapshot y lo pasa explícitamente al builder. `build_post_market_review` acepta `None` pero no lo valida; `build_trade_history` llega a `_open_positions_summary`, que requiere `.positions`. También `_build_trade_evaluations` requiere `.positions` mediante `_position_by_symbol`. Ninguno puede operar con ausencia.

Reproducción sobre implementación base: dos casos (snapshot None explícito y adquirido como None) fallaron con el AttributeError exacto en `_position_by_symbol`, al sustituir el historial por un doble local. Esta reproducción demuestra el contrato roto; no identifica por sí sola el frame del incidente real.

## Cambio mínimo y garantías

Dos líneas añadidas en `src/agente_bolsa/tools/post_market_review.py`, inmediatamente después de resolver el snapshot: si es `None`, lanzar `RuntimeError("post_market_portfolio_unavailable")`. No reintenta broker ni transforma ausencia en posiciones vacías. No cambia firma ni acepta datos parciales como válidos.

El error precede `build_trade_history`, `Store.ensure_schema`, aprendizaje, promociones y escritura de informes. El directorio de informes puede crearse, como antes; no se escribe contenido. Las escrituras de coordinación/reconciliación previas del scheduler mantienen su semántica: no son revertidas ni reescritas por este lote. El handler existente registra etapa y terminal `failed`, libera coordinación y no avanza `post_market_review_last_session`. Un reintento sigue posible y vuelve a fallar si persiste la ausencia.

Cartera válida con cero posiciones conserva el camino anterior. No cambian candidatos, scores, ranks, gates, sizing, planes, órdenes, cantidades, precios, stops, exposición o límites. Sin archivos protegidos, cycle_runner, esquema, dependencias, configuración ni política activa modificados.

## Validación

Python: `C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe`; `PYTHONPATH=<worktree>/src`. Settings con `_env_file=None`, `DATA_DIR` temporal; fecha de sesión explícita y calendario del scheduler fijado por doble. Sin broker real, red, LLM, yfinance ni datos productivos.

- Caracterización base: `pytest tests/test_oct07_postmarket_missing_portfolio.py -q`: **2 failed**, AttributeError esperado antes de corregir.
- Final: `pytest tests/test_oct07_postmarket_missing_portfolio.py tests/test_post_market_review.py tests/test_p45b_postmarket_reliability.py tests/test_postmarket_canonical_attribution.py -q`: **24 passed in 4.31s**, sin skips/xfail.
- Cuatro casos nuevos: None explícito, None adquirido, cartera vacía válida, scheduler con dos intentos fallidos sin avance de sesión ni informe publicado. Para None se verifica que historial no se consume y DB no se crea desde el builder.
- Ruff focal: `ruff check src/agente_bolsa/tools/post_market_review.py tests/test_oct07_postmarket_missing_portfolio.py`: **All checks passed!**
- `scripts/check_no_nulls.py`: **OK (538 archivos)**.
- `git diff --check`: verde antes del informe; se repite al cierre.

Gates omitidos y no aprobados: suite completa, Ruff completo, smoke, validate-agent-config, kernel-status, paridad dinámica completa e integración/despliegue. Mercado abierto y alcance focal del encargo. Producción, scheduler/PID/lock/heartbeat/HTTP/kernel/configuración y lease productivo: no inspeccionados por este worker. No SSH, broker, red, reinicios, merge, push ni ejecución postmarket productiva.

Siguiente paso: coordinador contrasta traceback operativo si está disponible y revisa el diff. Tras cierre XNYS y precondiciones operativas, reservar versión y ejecutar validación proporcional/integración; no interpretar estos 24 tests como suite completa ni como autorización de despliegue.

El guard mejora integridad y diagnóstico; no resuelve la causa de adquisición del snapshot ni reconstruye la sesión del 6-oct. La ausencia permanece un fallo recuperable mediante los reintentos existentes, nunca un éxito. Versión global sin bump: candidato no desplegado; coordinación informa de líneas posteriores .340.


Commits: caracterización 4a78370495bea78bdce56228cc8f075a34b94ca5; implementación 9d9c78b70ea99f21e404effc4b2e045b94399fad, tree fa8d59bb6b2ae1f53dcf49d6c8063750dd4b3797. Los tests se validaron sobre los mismos bytes funcionales antes de los commits. Git emitió durante mantenimiento automático 'fatal: bad object refs/codex/turn-diffs/captures/1786628847747/4ee266fa-eceb-479d-a4a7-b513226192d9/base' y 'failed to perform geometric repack'; ambos commits se crearon y resolvieron correctamente. No se reparó ni modificó esa referencia ajena.


## Intento anticipado de validación — 7-oct-2026, 22:37 Madrid

Dictamen: `precondition_not_met`. El operador pidió ejecutar inmediatamente la automatización prevista para las 23:00; se ejecutó su preflight en este chat, sin esperar al horario.

Hechos verificados en producción, solo lectura: XNYS cerrado a las 22:37:01 Madrid, próxima apertura 8-oct15:30; paquete activo0.4.321, paper true, live false. No hay eventos post_market_review_started/completed/failed del7-oct en la consulta acotada. Estado latest postmarket `skipped`, pmr_78fd692e3f98, actualizado21:51:38 Madrid, motivo mercado aún no apto. post_market_review_last_session sigue2026-10-05. La sesión7-oct no cumple terminal completed/failed; un skipped previo al cierre no lo sustituye.

Candidatos: los cuatro worktrees estaban limpios al iniciar este intento, con los HEAD/tree previamente documentados. Se detuvo antes de suites, smoke, integración o versión. Imagen/diferencia.340, kernel, configuración completa, leases y ausencia de procesos de validación no se declaran comprobados en este intento: el preflight terminó por la precondición anterior. El campo auto-apply del sondeo resultó unavailable, no false verificado.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_preflight_live.json; SQLite mediante Store.read_connection, mode=ro/query_only; sin reparaciones ni mutación productiva. No se fuerza postmarket, reconciliación o ciclo; sin órdenes, reinicios, despliegue ni promoción. Sólo se añaden estas notas documentales.

La automatización `validar-mejoras-bolsa-tras-cierre` quedó PAUSED tras este intento, tal como ordena su prompt; no volverá a ejecutarse a las23:00. La revisión del12-oct sigue programada. Siguiente condición: diagnosticar por qué no consta terminal de postmarket y volver a comprobarlo junto a los demás gates; no marcar completada la validación ni los candidatos como desplegados.

## Diagnóstico del retraso postmarket — 7-oct-2026, corte 22:44 Madrid

Dictamen: retraso reproducible en la coordinación del scheduler; validación permanece `precondition_not_met`. Auditoría exclusivamente de lectura. No se declara recuperado ni terminado el postmarket del 7-oct.

Hechos: proceso iniciado a las 22:02:54 Madrid tras arranque del contenedor a las 22:02:27 (causa de ese reinicio unavailable). Estudio cerrado `closed_523dac115aed` empezó 22:04:32 y terminó su ciclo 22:40:16. Mientras seguía activo arrancó `closed_0b9f7358249e` a las 22:17:56. El estudio diario `daily_655975c9bb97` empezó 22:17:58 y terminó 22:42:29; otro, `daily_3df5ffc3734f`, empezó 22:40:17 antes de terminar el anterior. El postmarket programado registró `max_instances` a las 22:32:54 y `missed` a las 22:42:29. No constan started/completed/failed de postmarket en la ventana capturada; la coordinación de hoy conserva skipped/market_not_ready de las 21:51 y last_session sigue 5-oct. El calendario confirma should_run_daily_study=true y mercado cerrado a las 22:44:26, siguiente apertura 8-oct 15:30.

Causa contrastada con fuente .321: run_scheduler_forever arranca el scheduler antes del bootstrap; en cerrado ejecuta sincrónicamente estudio técnico, estudio diario y sólo después postmarket. Los intervalos comparten un pool de dos trabajadores; los tres jobs tienen max_instances=1 y grace de 300 s, pero las llamadas directas del bootstrap quedan fuera de ese contador. Los marcadores de deduplicación de estudio cerrado y diario se escriben al final, permitiendo el solapamiento observado. Los eventos missed demuestran que al menos un intento programado de postmarket perdió su ventana; no prueban que todos los intentos futuros vayan a fallar. La atribución exacta de cada hilo no se ha capturado, por lo que cola ocupada por esos jobs es inferencia fuerte apoyada por código y cronología, no un stack dump.

Factores adicionales: errores LLM 402/Insufficient account funds con activación de fallback; ejecuciones crew de unos 24 minutos en los dos ciclos terminados. SQLite emite database is locked en capturas observacionales, pero esa ruta usa lock_timeout_seconds=0.0 y falla abierta; no acredita una espera de 30 s ni un deadlock. Los eventos posteriores prueban progreso. No se ha demostrado que esos errores sean la causa primaria. Tampoco se atribuyen pérdidas económicas a estos retrasos sin comparación causal.

Siguiente lote único pendiente: caracterizar en aislamiento la carrera bootstrap/intervalo; impedir duplicados por sesión entre ambas entradas y proteger el cierre operativo frente a estudios LLM largos, con límites y degradación explícitos. Exigir pruebas de no duplicación, progreso postmarket y conservación de trading/riesgo/ejecución, manteniendo coordinador y leases. No aumentar trabajadores ni grace a ciegas. Resolver identidad .321/.340 antes de integración. No hay implementación de este lote ni autorización inferida para reiniciar, forzar jobs o desplegar. Automatización de validación sigue PAUSED.

Evidencia local: `C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_postmarket_queue_live.json` (últimas 3000 filas por rowid, ventana 20:34–22:44 Madrid; timestamps originales UTC); `audit_postmarket_stall_live.json`; `audit_postmarket_runtime_logs.txt`. Consultas SQLite con Store.read_connection, mode=ro/query_only. Fuentes: scheduler.py líneas 137–145, 2505–2512, 2741, 2938–2954, 4488, 4528–4562, 4694–4720; tools/h_capture.py línea 669. Sin suites, broker, LLM manual, órdenes ni mutación productiva. Sólo documentación; revisión por Luna de implementación no aplicable: no se asigna validación con precondiciones fallidas.

## Validación de las 23:05 — 7-oct-2026

Dictamen: `precondition_not_met`. Sondeo a las 23:05:22–23:05:24 Madrid: XNYS cerrado, próxima apertura 8-oct 15:30. Producción 0.4.321, paper=true, allow_live_trading=false, allow_auto_apply_improvements=false. Imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, running, arranque 22:52:55, RestartCount=2; causa de reinicios unavailable, sin intervención desde este intento. Lock vivo PID6/token305725. schedule-status no acredita jobs inactivos: runtime unavailable/wal_mode_or_sidecar_present.

Bloqueo confirmado por Store.read_connection mode=ro/query_only: lease post_market_coordination:active, sesión 2026-10-07, run pmr_b2deee2ab986, bootstrap, stage=outcome_update, actualizado 22:54:32. Started a las 22:54:15, sin terminal completed/failed en últimas 3000 filas (ventana 20:36–23:02 Madrid); last_session sigue 5-oct. Otros started a las 22:47:59 y 22:51:22 no prueban procesos simultáneos. Lease persistido activo no demuestra progreso, pero incumple el gate de ausencia de leases.

Cuatro candidatos limpios antes de esta nota, separados sobre 1adc3cec/.321: postmarket HEAD d4956030705933d32c062b347658d9eb4e795d73/tree 1e22c25327414be9e2751508b5b5732bc32374e7; exit-audit HEAD 8bece4d45de1d9f00e463e2b512d8553e407e443/tree 01f7db8cd76d6cd261ac314a6498acb6b4e40fa4; cobertura HEAD 5cdc9d83f7ffd392c6479d518301256a7d2588f9/tree 5559ac5ed76420359d98312c13fc1b7751df884d; observación HEAD 2cd1425fd728105c04a40843518f6937a7dbbb54/tree e638955373e2f052f8b76a4e0b3ff886eae1884c. Sin bump/release. Divergencia histórica .340 no resuelta; checkout C:/Antonio/Bref/agenteBolsa observado ahora b411e9a7445bfa4da6de8329e668d30864090522, paquete .253, cambios ajenos preservados; no representa identidad del Jetson.

Detenido antes de asignar validaciones, suites, smoke, integración o cambios funcionales. Focales anteriores no repetidos ni declarados validación operativa. Kernel/configuración completa, exclusividad de procesos y demás gates no aprobados. Sólo lectura productiva y documentación local, diff --check; sin órdenes, broker/LLM desde tests, protegidos, históricos, locks, producción, reinicios, merge, promoción o despliegue. Automatización validar-mejoras-bolsa-tras-cierre PAUSED tras este intento; estudio del 12-oct sin cambios. Siguiente: terminal de sesión y ausencia de lease/job/retry antes de reprogramar; no forzar cierre ni borrar leases.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_2305_live.json y audit_validation_2305_image.txt; timestamps originales UTC.

## Continuación del diagnóstico — 8-oct-2026, 08:26–08:30 Madrid

Dictamen: `precondition_not_met` para validar; diagnóstico ampliado, sin reparación productiva. XNYS cerrado, próxima apertura hoy 15:30. Runtime 0.4.321, imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, paper=true/live=false/auto-apply=false. Contenedor iniciado 05:29:42 Madrid, RestartCount=4; lock PID6/token2686539 vivo. Causa de reinicios no demostrada.

Hechos nuevos: sesión 7-oct registró failed a las 02:25:59 (`pmr_b2deee2ab986`, LearningObservationBatchError: fallo persistiendo learning_observations en chunk 0: database is locked) y 05:06:25 (`pmr_c8ffd44c108d`, OperationalError: database is locked). El fallo de SQLite ya no es sólo telemetría: figura explícitamente como error terminal. Un nuevo bootstrap `pmr_150611d46dd9` empezó 05:31:43 y conserva lease activo en outcome_update actualizado 05:32:00. last_session sigue 5-oct. Latest event observado 07:56:13; esto no demuestra progreso del postmarket. Aunque existen terminales failed de intentos previos, el lease/reintento posterior activo impide validar.

Recursos: docker stats muestra scheduler 1.998 GiB/2 GiB. Cgroup memory.current=2147278848 y memory.max=2147483648 bytes, max=278082, oom=0, oom_kill=0: presión al límite observada, sin prueba de muertes OOM ni atribución de los cuatro reinicios. Contadores pressure unavailable en este host. Muestreo /proc/locks sólo capturó locks SQLite de lectura; no identifica un escritor culpable ni demuestra deadlock permanente. Un proceso con descriptores de esa SQLite estaba en folio_wait_bit_common; requiere correlación temporal para atribuir la espera a un archivo concreto. BlockIO de docker stats es acumulado, no tasa ni causalidad. Logs muestran persistencia de eventos y runtime también fallando por database is locked y jobs missed/max_instances.

Fuente .321: tools/post_market_review.py:832 solicita update_signal_outcomes con since_date=2026-04-01 y limit=200000. signal_learning.update_signal_outcomes carga señales, descarga barras, conserva outcome_cache y outcomes_to_save; storage.update_signal_outcomes_bulk ejecuta todos los UPDATE recibidos en una única transacción. Es carga potencialmente grande y sin memoria/transacción acotadas; no se ha medido aquí el número exacto de señales ni demostrado que esa función retuviera el lock en el instante auditado. La persistencia de learning_observations ya usa chunks y timeout 30 s, por lo que no basta con repetir la propuesta de dividir esa ruta existente.

Siguiente lote mínimo propuesto, separado del guard de cartera y de la carrera scheduler: caracterizar consumo y atomicidad de update_signal_outcomes; diseñar lectura/procesamiento acotados y transacciones cortas conservando conjunto de señales, IDs, outcomes, temporalidad y aprendizaje. No reducir histórico/limit para aparentar éxito, no cambiar umbrales ni ampliar workers/memoria a ciegas. Antes de implementar, definir explícitamente recuperación y retry ante commits parciales: pasar de transacción global a chunks cambia atomicidad y requiere contrato/revisión, no sólo optimización. Ensayo aislado con fixtures temporales, paridad legacy, fallo entre chunks y retry idempotente; no validación ni promoción con lease activo. No se ha implementado este lote ni asignado trabajo con precondiciones fallidas.

Evidencia local en C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/: audit_validation_oct08_live.json, audit_oct08_scheduler_logs.txt, audit_oct08_host_locks.json, audit_oct08_resources.txt, audit_oct08_cgroup.txt. Sólo SSH/lecturas, Store.read_connection mode=ro/query_only; sin broker/LLM manual, órdenes, limpieza, checkpoint, VACUUM, locks, históricos, configuración, restart, merge o despliegue. Automatización de validación permanece pausada. Este añadido N0 se revisa con diff --check; no se repiten suites. HEAD previo b83010d5dcd5b37cade344638d18af839e4183f2, tree d591de7bc9afe9e87df41603cea74ae07a00bf4d, checkout inicialmente limpio.
