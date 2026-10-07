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
