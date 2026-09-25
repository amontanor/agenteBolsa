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

## Despliegue R2 25-sep ~13:10 Madrid (dictamen `deployed`)

- R1 previo necesario: el handler de Streamlit filtra INFO, asi que `emit`
  no llegaba al log; fix con `print(..., flush=True)`, version `0.4.315`.
- Via port sobre `.314` (2 ficheros, 3-way verificado). Receta:
  `/opt/agente-bolsa/releases/0.4.315-port/`.
- Corte con XNYS cerrado: stop canonico, snapshot frio receipt v2 OK,
  flip selector (backup `.bak-p158r2`), `jetson-ops deploy-agente-bolsa`
  sano.
- Validacion x2: 3x healthy, HTTP 200 en `/`, `/health`, `/kindle`, lock
  coherente (PID 8), kernel `ok`, version `0.4.315`, cero jobs/ordenes,
  logs limpios, listener unico, unidad `active`.
- La linea `dashboard_timing` aparece con la primera carga del dashboard
  posterior al despliegue (pendiente de visitante a la hora del corte).

## Primera medicion real 25-sep ~13:15 Madrid (0.4.315, 4 cargas)

Linea representativa (ultima de 4, todas coherentes +-1s):

`dashboard_timing {"sections": {"advanced": 5.875, "alpaca_snapshot": 1.532,
"header": 0.013, "history_daily": 0.423, "history_intraday": 0.76,
"kpis": 9.688, "opening_context": 27.623, "overview": 5.986,
"reports": 0.011, "sales": 0.008, "setup": 9.75, "spy_table": 0.203,
"total": 62.513, "trade_history": 0.64}, "total_seconds": 125.025}`

Lectura correcta (salvedad de medida): `total_seconds` suma la seccion
`total` (62.5s, envolvente de todo el script) mas las parciales; cuenta
doble. Tiempo real de servidor por carga ~= 62s, no 125s.

Ranking (sobre ~62s reales):
1. `opening_context` 27.6s (~44%): `opening_performance_context` +
   `_daily_equity_metric_for_portfolio` + reconciliacion intradia +
   serie equity completa + resumen.
2. `setup` 9.8-10.1s: `_cached_latest_events(store, 400)` +
   `_latest_ci_llm_result` + settings/store/runtime.
3. `kpis` 9.7-9.8s: `_account_group` + `_render_leaderboard_controls`.
4. `overview` ~6.0s: grafico cartera + desglose del dia.
5. `advanced` ~5.9s.
6. Resto rapido: broker snapshot 0.6-1.5s, historicos 0.4-0.8s,
   trade_history 0.6s, header/reports/sales/spy <= 0.2s.

Interpretacion del sintoma (lateral solo ~40s): el sidebar se pinta
pronto (header 0.013s) mientras el area central bloquea en
opening_context/kpis/overview; red sana segun HAR del operador.
Se observaron 4 ejecuciones completas del script (carga + reruns),
todas ~62s: cada rerun de Streamlit repite el coste integro.

Propuesta P-L158-B (no iniciado): perfilar `opening_context`
(funcion por funcion), cachear setup/eventos/leaderboard con TTL,
paginacion/lazy en KPIs/overview/advanced, y corregir `total_seconds`
para no sumar la seccion envolvente.
