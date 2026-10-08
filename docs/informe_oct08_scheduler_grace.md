# Restauración de tolerancia del scheduler — 8 octubre 2026

Dictamen: `ready_for_integration_rehearsal`, NO desplegado. Lote N3 por cambiar
la elegibilidad temporal de ejecución: requiere gates completos y preflight
cerrado antes de producción. No modifica selección, riesgo, sizing ni órdenes;
sí permite al ciclo ejecutarse con retrasos entre 120 y 300 segundos, conforme
al contrato P-L139. No se afirma paridad del número de ciclos ejecutables.

## Causa y referencias

Base `ab28bd86193ef48a18d1f058e2f79492721c1412`, tree
`daa3f125e2da5b0504924dce5a6858764a9aa1f9`, versión 0.4.343, limpia.
Worktree `C:/Users/utopi/.codex/worktrees/bolsa-scheduler-grace-oct08/agenteBolsa`,
rama `codex/oct08-scheduler-grace`. Reserva candidata 0.4.347, independiente
de .344 coordinación, .345 linkage y .346 uplift; ninguna acredita despliegue.
Implementación/QA `0433713b74a87595726d965638d1e3f5019f704f`, tree
`8c419b0c8fb5de21911c03038da4f6f241f45a88`.

El test P-L139 falla también sobre archive de la base productiva exacta
`1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`: `AttributeError: 'Job' object has
no attribute 'misfire_grace_time'`. Evidencia local en ef99:
`goal_fix_lesson_scheduler_base.txt`, batería de dos fallos en 2.99 s.
Los jobs pendientes heredan el default de 120 segundos al arrancar APScheduler;
esa herencia tampoco satisface los 300 del ciclo. La reconstrucción 784e6cd7
eliminó las tres asignaciones explícitas del commit 0baf7aa3. El contrato
documentado en `docs/informe_p_l139_misfire_grace.md` y en el port P-L141 sigue
siendo 300/120/120; no se ha encontrado una decisión posterior que lo sustituya.

## Cambio y límites

Restaura valores explícitos: market_cycle 300 s, portfolio_watch 120 s,
trade_fill_watch 120 s. Conserva pool, cadencias, max_instances=1,
coalesce=True, triggers y funciones de jobs. El default general y la tolerancia
de los jobs de fondo no cambian. El fixture usa `_env_file=None`.
No toca archivos protegidos, configuración, SQLite, históricos ni producción.

Pruebas focales: `1 passed in 2.47s`; regresiones scheduler_observability,
scheduler_lock y pre_earnings_scheduler: `27 passed in 3.01s`. Python del
proyecto, PYTHONPATH exacto, DATA_DIR temporal y bloqueo de red externa.
No se arranca el scheduler ni se ejecutan jobs en estas pruebas. Ruff focal
`All checks passed!`; `git diff --check` verde. Sin fullsuite, smoke, build,
merge productivo, restart, despliegue ni push desde este lote.

La dirección verificó XNYS cerrado a las 14:41 Madrid, siguiente apertura
15:30, paper activo y live/auto-apply false. Ese preflight no se hereda para el
corte. Siguiente: integración revisada, gates completos del árbol definitivo
y nuevo preflight productivo; no cambiar política para ocultar otros fallos.
