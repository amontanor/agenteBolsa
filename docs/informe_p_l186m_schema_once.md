# P-L186M: bootstrap de esquema una vez por proceso

## Dictamen

`ready_for_integration_rehearsal`. Cambio N2 de persistencia y rendimiento:
elimina la ejecucion del DDL completo en rutas calientes. No cambia politica,
ordenes, riesgo, sizing ni identidad de trading.

## Causa raiz

`Store.ensure_schema()` ejecuta `executescript(SCHEMA)`, las migraciones
defensivas y un `UPDATE` de normalizacion. Varias rutas lo llamaban en cada
iteracion:

- `continuous_improvement/runtime.py::run_once`: tick del laboratorio cada
  minuto; 770 eventos `lab_market_window_blocked` en la sesion.
- `llm_usage.py::record_llm_response` y `today_llm_spend`: por respuesta y por
  consulta de gasto.
- `tools/trade_decision.py`: por contexto de riesgo, por research y por resumen
  intradia.
- `cycle_runner.py::run_observable_cycle`: por ciclo.
- `tools/learning_scoreboard.py` y `tools/live_readiness.py`: por informe.

Sobre una base de 7 GB, cada llamada vuelve a parsear y ejecutar todo el
esquema. Es un escritor DDL recurrente que compite con `runtime_state` y los
eventos. Evidencia de la sesion 2026-11-03: 14 `database is locked` entre
15:12Z y 15:21Z, 217 `scheduler_job_skipped` (93 fill watch, 60 portfolio
watch, 53 lab) y 1.621 `h_capture_prediction`.

## Cambio

- `ensure_schema()` marca la ruta de la base en `_SCHEMA_READY_PATHS` al
  terminar; un llamador que ya aplico el esquema deja el proceso listo.
- Las rutas calientes usan `ensure_schema_once()`, que aplica el esquema como
  maximo una vez por proceso y base.
- El arranque del scheduler y los comandos CLI de un solo uso conservan
  `ensure_schema()` para crear o migrar la base cuando haga falta.
- No hay cambio de esquema, columnas, tablas ni datos. No hay backfill.

## Paridad

- Trading, riesgo, ejecucion, kernel y configuracion sin diff.
- Los lectores y escritores conservan sus transacciones; solo cambia quien
  aplica el DDL y con que frecuencia.
- `ensure_schema_once` sigue aplicando el esquema completo en el primer uso de
  cada proceso; un proceso nuevo o una base nueva no se saltan la migracion.

## Validacion

- Focales del lote: 3 passed.
- Regresiones de storage, LLM, decisiones, ciclo, lab, scoreboard, readiness,
  P-L186 y learning: 470 passed.
- Ruff, NUL y `git diff --check`: verdes.
- Suite completa y despliegue: pendientes al escribir este informe.

## Verificacion esperada

1. Tras desplegar, contar `database is locked` en logs durante 30-60 minutos de
   sesion y comparar con la linea base de 14 en 6 h.
2. PMR de 2026-11-03 a las 22:00: debe terminar terminal, escribir fila
   `performance_daily` y `executed_short` de ADM.
3. Confirmar que el ciclo no reaplica el esquema: `ensure_schema_once` no debe
   producir DDL recurrente.

## Limites

- No se toca la retencion de `agent_events` ni el tamano de 7 GB.
- No se cambia la cadencia del laboratorio ni su evento de bloqueo; solo se
  elimina el DDL que lo acompañaba.
- No se hace backfill de `performance_daily`.


## Despliegue 0.4.427

- Imagen `agente-bolsa:0.4.427-arm64`
  `sha256:24e951e1248cddd85fe983366ddb8033b69b39ef58dc92d437e925aae9da05e1`,
  commit `d777cba8`, tree `60bda700`, tag `prod-jetson-0.4.427`, recibo
  verificado 2026-11-03T17:07:57Z.
- 3 contenedores healthy, RestartCount 0, OOM false, HTTP 200 en `/` y
  `/health`, kernel `ok` con 0 violaciones, runtime 0.4.427.
- Verificacion en imagen: `ensure_schema` marca la ruta lista y
  `ensure_schema_once` tarda 0,00001 s tras el bootstrap (0,51 s en base
  temporal); `llm_usage` y `trade_decision` usan la variante once.
- Primeros 8 minutos post-corte: 0 `database is locked`, 0
  `terminal_conflict`, 0 tracebacks; `portfolio_watch` completo en 6,424 s
  frente a ejecuciones de ~3 min antes del corte; cero ordenes nuevas.
- Suite final: 3.309 passed, 1 skipped, 1 fallo ambiental aislado
  (`test_web_research`). Focales del lote: 3; regresiones: 470.
- APP sigue corto (-5, entrada 238,24, precio 241,905 a las 17:08Z, P/L
  -18,325).
- Pendiente decisivo: PMR 22:00, fila `performance_daily` 11-03 y
  `executed_short` de ADM. La medicion de locks a 60 minutos queda abierta.
