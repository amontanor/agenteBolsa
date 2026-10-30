# Informe único — release 0.4.414 (P-L181, P-L183, P-L184)

Fecha: 2026-10-30, Europe/Madrid. XNYS cerrado en el corte (apertura 14:30).
Dictamen: **deployed**, con doble salud, recibo y verificación en navegador.

## Lotes incluidos

### P-L181 — tarjetas operativas con su comando (N1)

Re-add de P-L176, revertido al reconstruir 0.4.407 desde 0.4.402. Cobertura,
readiness y bloqueos dejan de mostrar «n/d · rancio · sin informe» y dicen qué
informe falta y qué comando lo genera (`market-data-quality`, `live-readiness`,
`weekly-review`). Sin nueva fuente ni autoridad.

### P-L183 — capturas h_capture en una transacción por ciclo (N2)

Propuesta y ejecutada por `[agenteBolsa] Tiempos`; revisada y validada por
dirección. Evidencia: `h_capture_prediction` eran 11.462 de 17.638 eventos en
24 h (65 %), cada uno con conexión, transacción y fsync propios. `storage.py`
extrae el cuerpo append-only a `_record_append_only_event_on` y añade
`record_append_only_events`: una conexión, una transacción y `SAVEPOINT` por
item; misma semántica idempotente/conflicto y fail-open con `lock_timeout=0`.
`signal_learning._persist_signal_prediction_captures` acumula y persiste una
vez por ciclo, con aviso `prospective_capture_persistence_partial`.

Riesgo declarado: el lote es todo-o-nada por ciclo; un lock pierde ese ciclo de
capturas. Aceptado para telemetría shadow.

### P-L184 — panel sin reruns cada 2 s y rango real (N1)

Dos defectos vistos por el operador en producción:

1. El dashboard montaba `_poll_dashboard` con `run_every="2s"` y lanzaba
   `st.rerun()` completo también cuando solo arrancaba una petición. El ajuste
   de refresco de 10 min no gobernaba esa cadencia. Ahora sondea cada 10 s y
   solo repinta cuando hay dato nuevo.
2. «P/L acumulado (%)» decía «Últimos 7 días» pero aplicaba las 7 últimas
   sesiones con fila, de ahí 30/09 → 19/10. La tarjeta muestra el rango real
   (`7 sesiones con dato · 30/09/2026 → 19/10/2026`), el pie explica que el
   selector cuenta sesiones y que los huecos son sesiones sin `performance_daily`,
   y los puntos marcan que la serie no es diaria continua.

## Validación

- Focales del release y vecinos: `189 passed` (P-L179, P-L182, P-L176, web_app,
  P-L152, P-L65B, P-L63, P-L87, P-L140A, P-L183, signal_learning).
- Suite completa sobre el árbol P-L181+P-L183: `3255 passed, 2 failed` en
  1038 s. Los dos fallos son preexistentes y ambientales:
  - `test_web_research::test_search_company_news_without_provider_is_no_provider`
    por contaminación de entorno; pasa aislado.
  - `test_pre_earnings::test_score_study_regression_current_sqlite` por deriva
    de la SQLite local de desarrollo (`v2_actionable_false_positive == 8`);
    se reproduce con el código 0.4.412 y se salta cuando la base no existe.
- P-L184 solo toca `web_app.py`; la suite anterior se hereda y se declara.
- Ruff limpio, `check_no_nulls` OK (616), `git diff --check` limpio,
  `validate-agent-config --json` ok. Smoke `run-once --skip-crew` omitido por
  red/broker (declarado, no aprobado).
- Imagen `agente-bolsa:0.4.414-arm64`
  `sha256:e7d44aba8d4a3e9ab09af020bd8b19f91324072d368adff518bd16009298b3b6`,
  construida desde `0.4.412-arm64`; 5 ficheros verificados byte a byte en
  contenedor temporal (`web_app 25038173…`, `storage f99fbf86…`,
  `h_capture 2f7dec65…`, `signal_learning 00ad523e…`, `__init__ 86e39401…`).

## Despliegue y verificación

- Commit `70ba7137787d56a99eeb42e8201d611cdf977554`, tree
  `0a241755c47fceab9d21f62389d7ac2f73e7639b`, tag `prod-jetson-0.4.414`.
- Selector `runtime.env` con backup `runtime.env.bak-pl414-*`; Compose con
  `docker-compose.yml` + `docker-compose.raspberry.override.yml`, `up -d
  --no-deps scheduler web auxiliary`.
- Salud 1 y salud 2: 3 contenedores `healthy`, `restarts=0`, `oom=false`,
  HTTP raíz y `/_stcore/health` 200, runtime 0.4.414, kernel `ok`, flags
  paper/True/False/False. Arranque lento (~6 min) por I/O del host; sin
  reinicios ni OOM.
- Recibo verificado: 2026-10-30T12:12:44Z (`13:12:44` Madrid).
- Navegador: `v0.4.414` con «Despliegue verificado». Las tres tarjetas
  operativas muestran su comando; el toggle `P/L acumulado (%)` muestra
  `-0,14 % · 7 sesiones con dato · 30/09/2026 → 19/10/2026` con el pie de rango
  real; en 2 minutos solo hubo 1 `dashboard_timing` (el clic) frente al bucle
  de 2 s anterior; cero `traceback` y cero `database is locked`.

## Límites

- El efecto de P-L183 sobre el PMR es esperado, no medido: se valida con el
  PMR de hoy (21:00Z) y la ventana de `whale-copy`.
- La serie «Cartera por sesión» sigue terminando el 19-oct hasta que el PMR
  complete y escriba `performance_daily`.
- `current_observation_timestamp_unverified` es fail-closed del proveedor, no
  un defecto del panel.

## Siguiente paso

1. Ventana 21:55–23:15: parar `whale-copy`, auditar PMR y rearrancar.
2. PMR `completed` → baseline del 30-oct y serie al día. `failed` → P-L185 con
   la traza exacta antes de cualquier otro cambio.
3. Después: LLM/credenciales y P-L178b, límite permanente de `whale-copy`,
   backfill de fills (lote nuevo), PMR colgado del 29-oct.
