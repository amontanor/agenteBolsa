# P-L187 — observabilidad operativa y lecciones del periodo (0.4.430)

Dictamen: `deployed`. Sabado 7-nov-2026, XNYS cerrado. Imagen
`agente-bolsa:0.4.430-arm64` (`sha256:d14dfc9a342c...`), commit `a9e15298`,
tag `prod-jetson-0.4.430`, recibo 2026-11-07 (Europe/Madrid).

## Que se observo (30-oct → 7-nov)

Exitos verificados:

- **Locks eliminados**: 0 `database is locked` en 7 dias en web y scheduler
  (antes: 5 y 8 en 2 h). Funcionaron P-L180 (esquema una vez), P-L183 (capturas
  en una transaccion) y P-L184..186.
- Sin reinicios ni OOM (`restarts=0`, `oom=false`), kernel `ok`, HTTP 200.
- PMR volvio a terminar: `pipeline_completed` el 3, 5 y 6-nov; los fallos ya
  tienen causa (`owner_dead_recovered` x3, `stage_postmarket_report_failed` x2).
- 27 ordenes `filled` desde el 30-oct; `performance_daily` con filas 3-6 nov.
- Host: load 2,5 (antes ~20); dashboard servidor 2,8-4,7 s.

Fallos verificados:

- PMR ruidoso: 2.154 eventos `postmarket_run` en 7 dias (464
  `market_not_ready`, 107 `session_already_completed`, 104
  `postmarket_already_running`, 132 terminales sin motivo) y 140
  `ownership_conflict`. El lease evita doble ejecucion, no el ruido.
- Panel: 37 `dashboard_fills_sync_failed error=OperationalError` sin mensaje;
  varios `dashboard_snapshot_attempt_failed`.
- Reloj: 24 eventos con `created_at=1970-01-01` (scheduler_started,
  scheduler_lock_acquired, portfolio_watch_sleeping, estudios). Ninguna orden,
  plan ni fila de performance afectada.
- Memoria: scheduler 1,63 GiB de 2 GiB (81 %), estable; baseline de imports
  142 MB. Swap 725 MB.
- Base: 7,38 GB (+116 MB/dia); `spy_pct` en 1 de 11 filas desde 1-oct.

## Cambios desplegados (0.4.429/0.4.430)

- `dashboard_loading.py`: los dos avisos de error incluyen el mensaje
  (`error=%s: %s`).
- `scheduler.py`: `_persist_scheduler_control_event` deduplica skips por
  `(job_id, reason)` a uno por hora (`_CONTROL_EVENT_LAST`,
  `_reset_control_event_throttle` para tests).
- `_utils.require_sane_clock`: el arranque espera hasta 30 s a un reloj >= 2020
  y aborta con error explicito si no llega. Llamado desde `command_schedule` y
  `command_web`.
- `web_app`: `_emit_page_timing` + `_render_timed_page` en el despacho real de
  navegacion (`page_timing {page, seconds}`); el dashboard conserva su
  `dashboard_timing`.

## Efecto medido

- `page_timing` ya emite: `page_portfolio` 9,79 s y `page_cycle_decisions`
  11,94 s (antes invisibles).
- 0 locks y 0 skips en los 20 min posteriores al despliegue.
- 3 contenedores healthy, kernel `ok`, HTTP 200, `restarts=0`.

## Lecciones

1. Las escrituras escondidas en rutas de lectura eran la causa de los locks;
   con 0 en 7 dias, la regla "leer no escribe" queda demostrada.
2. Un lease correcto evita trabajo duplicado, pero no el ruido: el perdedor de
   la carrera debe espaciarse (ahora, una fila por hora y job/motivo).
3. Un `error=Clase` sin mensaje es deuda de observabilidad: ya se registra el
   texto.
4. El reloj es precondicion de identidad: guard de arranque >= 2020.
5. 81 % del limite de memoria no es fallo, pero es riesgo: presupuesto y aviso
   al 85 %.
6. 116 MB/dia exige plan de retencion de `agent_events` (sin backfill sin
   autorizacion).
7. Solo se mide lo instrumentado: Cartera y Decisiones ya tienen timing y son
   el siguiente cuello (9,8 s y 11,9 s de servidor).
