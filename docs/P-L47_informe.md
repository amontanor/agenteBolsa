# P-L47B1 — leases terminales y ownership del scheduler

> Desplegado en producción como `0.4.180` el 18-jul-2026 mediante el merge
> `f60a3d82`; base previa `39da7c8c`. No autoriza cambios de trading.

## Causa raíz

La vista mutable `runtime_state` conservaba leases de postmarket y
reconciliación después de que el pipeline hubiera dejado un evento terminal.
Además, el lock del scheduler podía conservar el PID de un wrapper ya muerto,
sin un token estable que distinguiera un PID reutilizado del proceso Python
real que ejecuta APScheduler. El efecto observado era `postmarket_already_running`
espurio y `lock_ok=false`, aunque existía evidencia terminal durable.

## Diseño

- `runtime_state` continúa siendo solo una vista operativa.
- `agent_events` es la historia append-only: se registran adquisición,
  liberación, recuperación de lease terminal, recuperación de propietario
  muerto, conflictos y fallos de liberación.
- Cada lease incluye `p-l47b1.lease.v1`, PID, token de proceso, `run_id`,
  sesión, etapa y timestamps. La liberación exige coincidencia exacta de PID,
  token y `run_id`.
- Un propietario vivo nunca se roba. Un propietario muerto, o un PID vivo con
  token distinto, solo se recupera dentro de una transacción corta y deja
  evidencia. Si ya existe un terminal durable, se elimina únicamente la vista
  residual y se conserva el evento original.
- El lock del scheduler usa `p-l47b1.scheduler-lock.v1`, creación atómica y
  token estable de creación del proceso. Los estados legacy/malformed se
  diagnostican y los propietarios muertos pueden recuperarse; un propietario
  vivo genera `ownership_conflict`.
- Los helpers de stack y health identifican el Python gestionado que ejecuta
  `agente_bolsa.main schedule`, no el wrapper que lo lanzó.

## Garantías de operación

La coordinación no crea tablas, migraciones, procesos, hilos ni schedulers.
Las transacciones de lease solo cubren lectura/actualización de la vista y se
cierran antes del pipeline. Los fallos de telemetría son fail-open; un fallo de
la operación de liberación queda registrado como `lease_release_failed` y no
borra un lease ajeno. P-L43 mantiene `legacy_calendar_days` activa con XNYS
shadow; P-L44 permanece `legacy_double_application` activa con
`single_application` shadow; P-L45/P-L46 no cambian.

## Validación prevista

Las pruebas aisladas cubren terminales `completed/failed/skipped`, excepciones,
propietario vivo, propietario muerto, PID reutilizado, 25 competidores,
reconciliación interna/externa, locks legacy/malformed y ausencia de tablas
nuevas. La suite completa y los gates se ejecutan únicamente en este worktree,
con datos temporales y sin servicios productivos.

## Estado de despliegue

P-L47B1 está desplegado como `0.4.180`. La topología Windows verificada es un
único scheduler lógico: wrapper PowerShell → launcher `.venv` → runtime Python
real. El nuevo lock `p-l47b1.scheduler-lock.v1` pertenece al runtime, no al
launcher. En el primer bootstrap normal se recuperó de forma append-only el
lease terminal residual `brkrec_eb45e5acbd6b`; su terminal `completed` original
se conserva y `post_market_coordination:active` quedó vacío. El bootstrap quedó
`skipped/market_not_ready`, sin reprocesar postmarket, reconciliación ni
outcomes. P-L43BR6 y P-L44BR3 conservan los slots futuros `0.4.181` y
`0.4.182`; no se integraron. No hubo limpieza manual ni push.

## Corrección QA del ensayo

Durante la matriz aislada de helpers se detectó que `Get-StackSchedulerLockInfo`
interpretaba un lock legacy numérico como JSON escalar y lo clasificaba como
`malformed_lock`. El ensayo añade únicamente el tratamiento compatible para
locks numéricos: un PID muerto se clasifica `stale_dead_owner`; JSON legacy,
malformed, Python gestionado vivo y wrapper vivo quedan diferenciados. No se
modificó el candidato original ni producción.
