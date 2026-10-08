# Cierre explícito del lector de eventos — 8-oct-2026

Dictamen: candidato N2 `ready_for_closed_market_full_validation`, sin desplegar. Se corrige un defecto reproducido: el context manager de sqlite3 confirma o revierte la transacción, pero no cierra la conexión. El generador de eventos tampoco cerraba su cursor explícitamente. No se atribuyen a este defecto los reinicios o fallos productivos sin evidencia causal.

## Referencias y autorización

Worktree `C:/Users/utopi/.codex/worktrees/bolsa-storage-reads-oct08/agenteBolsa`, rama `codex/oct08-event-reader-lifecycle`. Base exacta `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`, tree `4d118b504b305e45f45a06d9aaffa063079abaf7`, versión base 0.4.321. Checkout inicial limpio. Caracterización `034c60d4`, implementación `38f5d3dd`, QA `501052f94454ee2854573e2d35d679e19e999b4a`, tree funcional probado `48a3b3a10aa4b039e9b1ac83a602cbce971e8798`. Documentación posterior no cambia bytes funcionales. Reserva/bump pendiente: candidato aislado, no release.

El usuario autorizó expresamente resolver errores y optimizar código. Este encargo nuevo permite implementación y focales breves locales; no reanuda ni aprueba la validación operativa bloqueada. schedule-status real de producción a las 08:33 Madrid: XNYS cerrado, apertura 15:30, lease postmarket activo de la sesión 7-oct en outcome_update. No suites largas, smoke operativo, merge productivo, reinicio ni despliegue.

## Cambio y paridad

`Store.iter_agent_events` conserva exactamente SQL, filtros, parámetros, orden cronológico/desempate, límites, tamaño de lote y diccionarios emitidos. Añade `contextlib.closing` a la conexión propia y al cursor: cierra cursor, termina la transacción con su semántica previa y cierra conexión al agotarse, al fallar SQL/JSON o al cerrar expresamente el generador.

No cambia Store.connect globalmente, no toca conexiones de otros consumidores, no introduce esquema/índices, ni cambia operaciones de trading, riesgo, gates o aprendizaje. No acorta el histórico. Un generador todavía referenciado y suspendido sin close continúa reteniendo recursos: el cambio no promete resolver ese caso ni la duración de snapshots mientras se consumen eventos.

## Evidencia

- Base: seis casos fallan por conexión aún utilizable después del agotamiento, close temprano, JSON inválido, selección vacía, consulta filtrada y error SQL. Se retiene referencia a la conexión para no depender del recolector de basura.
- Final: `11 passed in 0.82s`: siete casos de este lote y cuatro de `tests/test_storage_read_connection.py`. Incluye escritura real por otra conexión durante el snapshot lector WAL; el lector conserva su conjunto/orden original, cierra al agotarse y no cierra ni impide seguir usando el escritor.
- Ruff focal y diff --check verdes; `check_no_nulls: OK (538 archivos)`. Sólo Python del proyecto y PYTHONPATH de este checkout, SQLite temporal; sin broker, red, LLM ni datos productivos desde tests.
- Revisión independiente Luna, gpt-6.1-sol/low: sin bloqueantes. Contrastó contextos, rollback/GeneratorExit, consumidores de productividad y capturas, payloads y límites. No ejecutó tests; los resultados anteriores son del coordinador. La revisión vio los mismos bytes funcionales antes del commit; después sólo se amplió QA y documentación.

No se declara suite completa, validación de kernel/configuración, smoke, paridad de un ciclo productivo completo ni salud operativa. Los objetos protegidos no están modificados. Producción sigue sin cambios. La divergencia histórica de versiones y la reserva de release se resuelven antes de integrar.

## Auditoría adicional y cola

Una señal sin contrato de productor completo obliga a `_iter_signal_prediction_events` a recorrer todas las predicciones históricas, sin cap; filtrarlas sólo después preserva integridad pero encarece cada actualización. Con contratos completos se hace una consulta por ciclo. En SQLite temporal con esquema base, EXPLAIN QUERY PLAN del filtro tipo/ciclo y orden created_at/event_id devuelve `SCAN agent_events` y `USE TEMP B-TREE FOR ORDER BY`; el índice existente comienza por agent y no sirve a esa consulta. No se han medido latencias productivas ni extrapolado una mejora porcentual.

Siguiente lote separado: consulta agrupada y/o índice compatible, preservando predicciones legacy con ciclo nulo, identidad exacta, orden y ausencia de cap. Un cambio de esquema necesita revisión específica y no se incluye aquí. También quedan otros métodos con `with self.connect()` sin cierre físico explícito; no se afirma haber reparado todas las conexiones del repositorio.

La optimización de velas por símbolo está en el candidato separado bolsa-outcome-memory-oct08. La carrera bootstrap/intervalos y la transacción global de outcomes siguen pendientes; dividir commits exige definir retry/atomicidad antes de cambiar esa semántica. No subir workers ni recortar señales como sustituto.

La revisión automática rechazó inicialmente un sondeo SSH por script no inspeccionado. Tras leer íntegramente el script, el mismo sondeo read-only fue admitido; no queda acción bloqueada por esa revisión. Gates operativos permanecen bloqueados por lease, independientemente de la aprobación de herramientas.
