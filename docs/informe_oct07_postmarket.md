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

