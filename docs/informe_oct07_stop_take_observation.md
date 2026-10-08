# Diagnóstico del vigilante de salidas, 7 de octubre de 2026

Dictamen: `ready_for_integration_rehearsal`, candidato aislado N2, sin despliegue. El vigilante pasa ahora a explicar la ausencia de origen o niveles locales sin cambiar sus decisiones. Es diagnóstico, no reparación de APO ni certificación de protección en el broker.

## Identidad

Worktree exclusivo `C:/Users/utopi/.codex/worktrees/bolsa-exit-observation-oct07/agenteBolsa`, rama `codex/oct07-exit-observation`. Base exacta `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`, tree `4d118b504b305e45f45a06d9aaffa063079abaf7`, versión base 0.4.321. Árbol inicial limpio. No se reserva versión ni se publica una release: la divergencia .321/.340 y los gates de integración siguen pendientes.

XNYS abierto según schedule-status real del Jetson a las 20:49:36 Europe/Madrid; cierre 22:00, scheduler lock vivo. Runtime view `unavailable/wal_mode_or_sidecar_present`, que no equivale a jobs inactivos. La comprobación fue solo de lectura; el candidato no se ejecutó en producción.

## Cambio y contrato

`_execute_stop_take_exits` conserva su retorno y añade un argumento keyword opcional `observation`. Reutiliza la cartera y la selección de planes que la ruta ya cargaba. No consulta nuevamente broker ni SQLite. El bloque se incorpora al evento existente `portfolio_watch_completed` o `portfolio_watch_heartbeat_completed`; no hay nuevo evento, servicio, tabla, archivo operativo ni alerta externa.

La observación distingue por posición `source_unavailable`, `skipped_open_order`, `local_levels_available`, `local_levels_absent` y `levels_unavailable`. Una orden abierta hace que la ruta local omita ese símbolo; no demuestra que sea un stop protector. Valores booleanos, texto inválido, NaN o infinito producen niveles `unavailable`. Niveles positivos locales disponibles tampoco demuestran que estén alojados o armados en el broker.

Todas las filas declaran `broker_protection_status=unavailable`. `source_lookup_basis=legacy_latest_registered_buy_by_symbol` identifica expresamente el lookup que usa la ruta vigente; no se reconstruyen IDs, fills ni el origen histórico de una posición. No se usa la observación como autoridad para modificar órdenes.

El contrato es una unión por `status`: `observed` incluye `schema_version=local_stop_take_observation.v1`, scope, base del lookup y filas; `unavailable`, `not_required` y `not_evaluated` incluyen reason y posiciones null o vacías según corresponda. Snapshot fallido permanece `unavailable/portfolio_unavailable`; cartera válida vacía es `not_required/no_positions`; ejecución desactivada o precondiciones paper no cumplidas permanecen `not_evaluated`.

El cálculo está protegido por captura de excepción antes de ejecutar la ruta de stops; su fallo no impide enviar una salida válida. Los gates, orden de evaluación, niveles, cantidades, precios, identidad y persistencia de órdenes no cambian. No se modifica ningún archivo protegido ni configuración.

## Evidencia y revisión

Caracterización: seis casos nuevos fallan sobre la base, cuyo contrato no admite el sink ni ofrece el helper. Esto demuestra la ausencia de diagnóstico, no un fallo demostrado en la ejecución original de stops.

Final: **62 passed en 7.83 s**, sin skips/xfail: `tests/test_oct07_stop_take_observation.py`, `tests/test_time_stop_policy.py`, `tests/test_scheduler_observability.py`. Python del proyecto, PYTHONPATH de este checkout, `_env_file=None` y DATA_DIR temporal en los casos nuevos; reloj fijado en las pruebas de paridad. Sin red, broker real, LLM o datos productivos.

La prueba del stop real usa Store temporal, callbacks locales y reloj/IDs fijados: compara el plan completo enviado, client_order_id, resultado y eventos entre llamada legacy sin sink, observación normal y fallo del cálculo. Los tres son idénticos. El job real con dobles cubre snapshot fallido, cartera vacía y posición sin origen, conservando una sola lectura broker y el mismo número de consultas de planes.

Ruff focal, NUL (538 archivos) y diff verdes. Revisión independiente por fuente sin bloqueantes; su recomendación de cubrir datos inválidos está incorporada y pasa. No encontró consumidores específicos de los eventos completed que rechacen el nuevo bloque. Los focales no equivalen a validación operativa completa.

Pendientes: integración, paridad combinada, gates proporcionales de release y versión. Suite completa, smoke, configuración/kernel y despliegue no se ejecutan durante mercado abierto. Producción sin cambios; no se añaden stops ni se venden las acciones APO en este lote.

## Seguimiento

La validación aislada de las 23:00 del 7-oct y el estudio del 12-oct a las 10:00 Europe/Madrid ya incluyen este lote y el de cobertura de símbolos. Conservan sus precondiciones y restricciones, sin permiso de despliegue. La revisión debe comprobar qué está realmente desplegado antes de buscar estos campos en runtime. La mejora siguiente, si la evidencia lo justifica, sería un contrato estructurado para tratar posiciones heredadas sin origen; no una asociación heurística ni un stop inventado.

Commits separados: caracterización `415bb0f1`, implementación `d6b8a9b2`, QA `e3976d7c3f4e28f21e56f9bf6efa6165fcf2e429`; tree funcional `490dbe67ec6dbd9a7a04a61ab2fb6fd4d37ae6b4`. Los commits posteriores de documentación no cambian los bytes funcionales probados. Sin mantenimiento automático Git durante commits para evitar la referencia ajena inválida ya observada; no se reparó esa referencia.

## Intento anticipado de validación — 7-oct-2026, 22:37 Madrid

Dictamen: `precondition_not_met`. El operador pidió ejecutar inmediatamente la automatización prevista para las 23:00; se ejecutó su preflight en este chat, sin esperar al horario.

Hechos verificados en producción, solo lectura: XNYS cerrado a las 22:37:01 Madrid, próxima apertura 8-oct15:30; paquete activo0.4.321, paper true, live false. No hay eventos post_market_review_started/completed/failed del7-oct en la consulta acotada. Estado latest postmarket `skipped`, pmr_78fd692e3f98, actualizado21:51:38 Madrid, motivo mercado aún no apto. post_market_review_last_session sigue2026-10-05. La sesión7-oct no cumple terminal completed/failed; un skipped previo al cierre no lo sustituye.

Candidatos: los cuatro worktrees estaban limpios al iniciar este intento, con los HEAD/tree previamente documentados. Se detuvo antes de suites, smoke, integración o versión. Imagen/diferencia.340, kernel, configuración completa, leases y ausencia de procesos de validación no se declaran comprobados en este intento: el preflight terminó por la precondición anterior. El campo auto-apply del sondeo resultó unavailable, no false verificado.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_preflight_live.json; SQLite mediante Store.read_connection, mode=ro/query_only; sin reparaciones ni mutación productiva. No se fuerza postmarket, reconciliación o ciclo; sin órdenes, reinicios, despliegue ni promoción. Sólo se añaden estas notas documentales.

La automatización `validar-mejoras-bolsa-tras-cierre` quedó PAUSED tras este intento, tal como ordena su prompt; no volverá a ejecutarse a las23:00. La revisión del12-oct sigue programada. Siguiente condición: diagnosticar por qué no consta terminal de postmarket y volver a comprobarlo junto a los demás gates; no marcar completada la validación ni los candidatos como desplegados.

## Validación de las 23:05 — 7-oct-2026

Dictamen: `precondition_not_met`. Sondeo a las 23:05:22–23:05:24 Madrid: XNYS cerrado, próxima apertura 8-oct 15:30. Producción 0.4.321, paper=true, allow_live_trading=false, allow_auto_apply_improvements=false. Imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, running, arranque 22:52:55, RestartCount=2; causa de reinicios unavailable, sin intervención desde este intento. Lock vivo PID6/token305725. schedule-status no acredita jobs inactivos: runtime unavailable/wal_mode_or_sidecar_present.

Bloqueo confirmado por Store.read_connection mode=ro/query_only: lease post_market_coordination:active, sesión 2026-10-07, run pmr_b2deee2ab986, bootstrap, stage=outcome_update, actualizado 22:54:32. Started a las 22:54:15, sin terminal completed/failed en últimas 3000 filas (ventana 20:36–23:02 Madrid); last_session sigue 5-oct. Otros started a las 22:47:59 y 22:51:22 no prueban procesos simultáneos. Lease persistido activo no demuestra progreso, pero incumple el gate de ausencia de leases.

Cuatro candidatos limpios antes de esta nota, separados sobre 1adc3cec/.321: postmarket HEAD d4956030705933d32c062b347658d9eb4e795d73/tree 1e22c25327414be9e2751508b5b5732bc32374e7; exit-audit HEAD 8bece4d45de1d9f00e463e2b512d8553e407e443/tree 01f7db8cd76d6cd261ac314a6498acb6b4e40fa4; cobertura HEAD 5cdc9d83f7ffd392c6479d518301256a7d2588f9/tree 5559ac5ed76420359d98312c13fc1b7751df884d; observación HEAD 2cd1425fd728105c04a40843518f6937a7dbbb54/tree e638955373e2f052f8b76a4e0b3ff886eae1884c. Sin bump/release. Divergencia histórica .340 no resuelta; checkout C:/Antonio/Bref/agenteBolsa observado ahora b411e9a7445bfa4da6de8329e668d30864090522, paquete .253, cambios ajenos preservados; no representa identidad del Jetson.

Detenido antes de asignar validaciones, suites, smoke, integración o cambios funcionales. Focales anteriores no repetidos ni declarados validación operativa. Kernel/configuración completa, exclusividad de procesos y demás gates no aprobados. Sólo lectura productiva y documentación local, diff --check; sin órdenes, broker/LLM desde tests, protegidos, históricos, locks, producción, reinicios, merge, promoción o despliegue. Automatización validar-mejoras-bolsa-tras-cierre PAUSED tras este intento; estudio del 12-oct sin cambios. Siguiente: terminal de sesión y ausencia de lease/job/retry antes de reprogramar; no forzar cierre ni borrar leases.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_2305_live.json y audit_validation_2305_image.txt; timestamps originales UTC.
