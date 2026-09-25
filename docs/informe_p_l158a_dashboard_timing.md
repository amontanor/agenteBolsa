# P-L158-A — temporizador por seccion del dashboard (candidato 0.4.313)

## Dictamen

`ready_for_closed_market_deployment` (N1: solo observacion). Tras el corte,
la primera carga del dashboard debe emitir `dashboard_timing` en el log del
contenedor web con el desglose por seccion.

## Cambio

- `_DashboardTimer` en `src/agente_bolsa/web_app.py`: `start`/`stop` por
  nombre con `time.monotonic`, redondeo a 3 decimales, todo envuelto en
  try/except para no interrumpir jamas el render; `emit()` publica una
  linea `LOGGER.info("dashboard_timing {...}")` con `total_seconds` y
  `sections`, sin persistir nada.
- 14 secciones en `page_dashboard` (marcadores sin reindentar, balanceados):
  total, setup, alpaca_snapshot, trade_history, history_daily,
  history_intraday, opening_context, header, reports, kpis, overview,
  spy_table, sales, advanced.
- Version `0.4.313`. No toca trading, riesgo, ejecucion, broker, LLM,
  SQLite ni UI visible.

## Validacion

- Focales: 81 passed (`test_p158a_dashboard_timing.py` 4 + `test_web_app`
  77). Ruff y `git diff --check` verdes. Compilacion y balance
  start/stop verificados por script.
- Despliegue previsto por port sobre `.312` (solo `web_app.py` + version),
  con snapshot frio, doble validacion y evidencia `dashboard_timing` en
  logs como prueba de funcionamiento.

## Despliegue 25-sep 12:35-12:45 Madrid (dictamen `deployed`)

- Via port sobre `.312` (solo `web_app.py` + version; 3-way verificado).
  Receta: `/opt/agente-bolsa/releases/0.4.313-port/`.
- Imagen `agente-bolsa:0.4.313-arm64` (USER app, labels exactos).
- Corte con XNYS cerrado: stop canonico, snapshot frio receipt v2 OK
  (DB sha256 `b3345059...`, sin escrituras intermedias), flip selector
  (backup `.bak-p158`), `jetson-ops deploy-agente-bolsa` sano
  (init-db Exited correcto).
- Validacion x2 separadas >75 s: 3x healthy, HTTP 200 en `/`, `/health`,
  `/kindle`, lock coherente, kernel `ok` (sello intacto), version `0.4.313`,
  cero jobs/ordenes, leases apareados, sin `database is locked`, listener
  unico, unidad `active`.
- Prueba funcional en produccion: `_DashboardTimer` importa y mide OK en el
  contenedor web desplegado. La linea `dashboard_timing` aparecera en logs
  con la primera carga del dashboard (pendiente de un visitante).

## Despliegue 25-sep ~13:00 Madrid (dictamen `deployed`)

- R1 previo: la linea `dashboard_timing` no llegaba al log (Streamlit fija
  WARNING); fix con `LOGGER.setLevel(INFO)` en `emit()`, version `0.4.314`.
- Via port sobre `.313` (2 ficheros, 3-way verificado). Receta:
  `/opt/agente-bolsa/releases/0.4.314-port/`.
- Corte con XNYS cerrado: stop canonico, snapshot frio receipt v2 OK (DB
  sha256 `b3345059...`), flip selector (backup `.bak-p158`),
  `jetson-ops deploy-agente-bolsa` sano.
- Validacion x2: 3x healthy, HTTP 200 en `/`, `/health`, `/kindle`, lock
  coherente (PID 7), kernel `ok`, version `0.4.314`, cero jobs/ordenes,
  leases apareados, sin `database is locked`, listener unico, unidad
  `active`. Timer verificado en contenedor web (`timer_ok=True`).
- La linea `dashboard_timing` aparece con la primera carga del dashboard
  posterior al despliegue (pendiente de visitante a la hora del corte).
