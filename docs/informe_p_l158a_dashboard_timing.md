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
