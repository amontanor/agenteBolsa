# P-L89B — observabilidad del funnel de capital y snapshot EOD

## Dictamen

`ready_for_closed_market_deployment`.

El carrier observacional mínimo queda validado para integrar y desplegar con
XNYS cerrado. No cambia sizing, gates, riesgo, selección, ejecución, LLM,
credenciales, política activa ni live. El snapshot EOD mejora su cobertura de
equity y la coherencia temporal, pero permanece `unavailable` cuando faltan
ventana XNYS exacta, flows, costes o benchmark comparable.

## Referencias y alcance

- Fecha: 11/08/2026, Europe/Madrid; XNYS cerrado, próxima apertura
  12/08/2026 15:30 CEST.
- Producción/base: `eb9d6bede5a5aa55de10441fb442430028d1fb47`, árbol
  `250dfa2c527d53c1d3d13ecda1ea5027f496e149`, v0.4.225, tracked limpia.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl89b_capital_observability`.
- Rama: `codex/pl89b-capital-observability`.
- Commits funcionales/QA: `e028a3cd` caracterización roja,
  `b8c84d70` implementación y bump, `c2d221db` corrección de expectativa
  stale de versión.
- Versión candidata: 0.4.226. El HEAD/tree exactos finales se registran en
  el cierre Git posterior a este commit documental.
- Cutoff P-L80 preservado: `2026-08-02T15:51:41.5484478Z`.

## Causa reproducida y contrato corregido

La base ya tenía el contrato append-only y las tablas necesarias, pero el
proyector del funnel solo conservaba algunos notionales planos. Los payloads
de plan/riesgo ya persistidos contenían, sin llegar al evento consumidor,
`proposal_notional`, `max_position_exposure`, `position_sizing`,
`available_buying_power`, `max_position_notional` y `size_multiplier`.
Además, `_auto_paper_trade` cargaba un `PortfolioSnapshot` válido pero no lo
pasaba al funnel; por eso equity, cash, buying power y exposición quedaban
vacíos. También podía publicarse un evento con `cycle_id` vacío.

El cambio lee únicamente observaciones ya producidas y las transporta por
identidad exacta: `cycle_id`, acción, `signal_id`/`signal_capture_id` y
`recommendation_id`. Conserva denominadores separados para candidatos,
recomendaciones, planes, órdenes y fills. El detalle añade, cuando existe,
requested/approved/planned/submitted/filled notional, cash floor, cap por
posición, multiplicador, buying power, concentración y razón primaria. Los
campos ausentes siguen `null`; no se calcula ni se vuelve a evaluar ninguna
política.

La cuenta se proyecta una sola vez desde el `PortfolioSnapshot` ya cargado:
equity, cash, buying power, gross/net exposure y concentración por posición.
El cálculo es read-only y la ruta de órdenes no recibe ningún dato nuevo.
Si falta identidad de ciclo, el observador devuelve `unavailable` y omite la
persistencia; no crea `capital_deployment_funnel_shadow:`.

Para EOD, `previous_close_equity` ya transportado por el snapshot se conserva
como `equity_start` con fuente explícita `account.previous_close_equity`.
`account_read_at` conserva la lectura oficial y `as_of`/`window_end_at` usa el
máximo UTC entre las fuentes capturadas y el momento de captura, evitando
`source_timestamp_after_as_of`. No se inventa el timestamp del cierre previo:
si `window_start_at` no existe, el snapshot sigue estructuralmente
`unavailable`. Flows, costes, exposición temporal y benchmark permanecen
`null`/parcial cuando no hay carrier exacto.

La persistencia existente de `Store` no se modifica: mismo ID y contenido es
idempotente; mismo ID con contenido distinto conserva el original y registra
conflicto. No hay migración, backfill, reescritura, checkpoint ni VACUUM.

## Evidencia de base y preflight

Se verificó antes del cambio:

- `schedule-status`: XNYS cerrado; owner del scheduler vivo PID 12200 con
  token coherente. `runtime_state` quedó `unavailable` por WAL/sidecars y no
  se reparó.
- PMR/reconciliación de sesión 11 terminales; sin pytest, deploy,
  postmarket, reconciliación, leases o jobs competidores.
- `paper=true`, `live=false`, `auto-apply=false`,
  `allow_position_adds=false`.
- `validate-agent-config --json`: `ok=true`, sin warnings.
- `kernel-status --json`: `ok=true`, `violations=[]`; kernel, broker,
  execution y `.env` coinciden con el sello productivo.
- `operational-health --json`: 0 críticos y 3 warnings preexistentes
  (setup edge, atribución postmarket y governance adaptativa). La propia
  consulta solicitada refrescó el artefacto de health; no modificó código,
  configuración, locks, leases ni SQLite operativa.
- `stack_status` mostró falsos positivos históricos `lock_orphan`; la
  reconstrucción wrapper → launcher → runtime confirmó scheduler único y
  lock perteneciente al runtime efectivo. No se mató ni reinició ningún
  proceso.
- SQLite productiva: lecturas mediante URI `mode=ro` y
  `PRAGMA query_only=ON`; no hubo escritura productiva.

## QA reproducible

- Caracterización base antes del parche: 2 tests rojos, uno por pérdida de
  campos anidados/account y otro por descarte de `previous_close_equity` y
  timestamps posteriores al `as_of`.
- Focales del lote y regresiones funnel/EOD/cycle: `36 passed, 1 warning`.
- Policy y archivo de autoridad: `47 passed` tras corregir la expectativa
  stale de `0.4.225` a `0.4.226`.
- Suite completa final: `2497 passed, 1 skipped preexistente, 1 warning
  externo` en `797.61s`.
- Ruff completo: verde.
- `scripts/check_no_nulls.py`: verde, 481 archivos.
- Compilación temporal de `src`, `tests` y `scripts`: verde.
- `git diff --check`: verde.
- `validate-agent-config --json` aislado: `ok=true`.
- `kernel-status --json` temporal: `unsealed` esperado por ausencia de
  manifiesto, `violations=[]`; no se ejecutó `kernel-seal`.
- Smoke aislado `run-once --skip-crew --quiet`: verde, `crew_result=null`,
  `used_crew=false`, `market_state_quality=PARTIAL`, con `DATA_DIR` temporal
  y sin SQLite productiva.
- Paridad: `kernel.py`, `broker.py`, `execution.py`, `risk.py`, `config.py` y
  `.env` idénticos objeto-a-objeto a la base; no se modifica la autoridad
  económica.

El primer intento de suite se detuvo en `1567 passed, 1 failed, 1 warning`
por la expectativa stale de versión. Tras la corrección exclusiva del test y
la anotación de versión, la suite final anterior es la evidencia definitiva.

## Límites y siguiente paso

El funnel ahora permite medir cobertura prospectiva; no convierte los 9
rechazos `position_adds_disabled` en evidencia de sizing, no fabrica controles
same-cycle y no backfillea las 54 ejecuciones históricas. El EOD sigue sin
ser apto para causalidad si faltan flows, costes completos, ventana exacta,
exposición temporal o benchmark comparable.

Siguiente paso único: renovar preflight, hacer ensayo/integración
`merge --no-ff` del candidato, repetir gates con stack detenido y desplegar
solo si quedan margen, kernel/config y salud doble verdes. Después esperar al
menos dos ventanas maduras con controles same-cycle, EOD/costes/exposición
válidos antes de elegir, como máximo, una dimensión shadow de capital con
revisión humana. No activar experimento en este lote.

No se ejecutaron broker operativo, red, LLM real, jobs manuales, postmarket,
reconciliación manual, backfill, cambios de configuración, kernel-seal,
stack productivo, merge productivo ni push.

## Cierre productivo P-L89B

Dictamen: `deployed`.

El preflight cerrado se renovo el 11/08/2026. XNYS estaba cerrado y la
proxima apertura era 12/08/2026 15:30 Europe/Madrid. PMR y reconciliacion
estaban terminales (`session_already_completed` y `completed`, con 0 cambios y
0 errores); no habia pytest, deploy, lease ni competidor operativo activo.
`runtime_state` continuo `unavailable` por WAL/sidecar, sin reparacion. La
configuracion permanecia en paper, con live y auto-apply desactivados.

Se ejecuto `stack_down.ps1 -IncludeScheduled`, se integro exactamente el
candidato `6a87c589dd6106e26f5221b70da9aaa0f0800f80` mediante
`merge --no-ff`, y se arranco con `stack_up.ps1`. El merge productivo es:

- HEAD funcional: `4efd58ffc72239f75148014d4a17c21a869d6315`;
- primer padre: `eb9d6bede5a5aa55de10441fb442430028d1fb47`;
- segundo padre: `6a87c589dd6106e26f5221b70da9aaa0f0800f80`;
- tree funcional: `505c3ee88cd5c902e3ce7e9debbb4100e6b88f8e`;
- version: `0.4.226`.

Los gates post-merge fueron verdes: focales `83 passed, 1 warning`, Ruff,
NUL (`481 archivos`), compilacion, `git diff --check`, configuracion aislada,
kernel productivo y smoke aislado. La suite completa definitiva se reutilizo
por identidad exacta del tree y conserva `2497 passed, 1 skipped preexistente,
1 warning externo` en `797.61s`; no se repitio por actividad inercial del
despliegue. El kernel productivo quedo `ok=true`, `violations=[]`, con los
hashes protegidos y `.env` sin cambios.

Salud 1: `2026-08-11T23:51:33.9799274+02:00`. Salud 2:
`2026-08-11T23:53:37.2454445+02:00` (123.27 s despues). En ambas, `/`,
`/health` y `/kindle` respondieron HTTP 200; hubo un unico listener
`0.0.0.0:8501`. La cadena scheduler wrapper -> launcher -> runtime quedo
viva con PID/token coherentes (runtime 33092); la cadena web quedo viva con
un unico listener (PID 39100). `operational-health` informo 0 criticos y las
3 advertencias preexistentes (setup edge, atribucion postmarket y governance
adaptativa), sin repararlas ni mezclarlas.

Produccion y el worktree candidato quedaron limpios; los untracked del
operador permanecen presentes y excluidos por sus rutas exactas. El cutoff
P-L80 `2026-08-02T15:51:41.5484478Z` permanece intacto. No hubo backfill,
jobs manuales, broker operativo, red, LLM real, escritura SQLite productiva,
kernel-seal, cambios de `.env`, reinicios fuera de los helpers, ni push.

El siguiente unico paso es observar al menos dos ventanas maduras con
controles same-cycle y EOD/costes/exposicion validos antes de valorar una
dimension shadow de capital con revision humana. No se activa ningun
experimento en este lote.
