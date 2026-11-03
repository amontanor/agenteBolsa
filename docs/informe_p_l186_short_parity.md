# Informe P-L186 — paridad long/short (0.4.416)

## Dictamen

`implemented_pending_closed_market_validation`. La linea corta existe de punta a
punta en codigo: senal, contrato de accion, planes, riesgo, kernel, ejecucion,
monitor de stop/take, contabilidad FIFO, replay y UI. No se ha desplegado en el
momento de escribir este informe.

## Causa y alcance

La auditoria previa (`short_not_supported`) demostro que el sistema producia
setups bajistas y los media, pero no podia ejecutarlos: `sell` significaba
cerrar largo, el plan exigia posicion positiva, la ejecucion convertia todo no
compra en SELL y el kernel dejaba pasar cualquier `sell` sin gates. P-L186
separa intencion (`position_effect`) de lado bruto del broker y anade la linea
corta como capacidad de primera clase.

## Contrato

- Acciones canonicas: `buy`, `sell` (cerrar largo), `short` (abrir corto),
  `cover` (cerrar corto), `hold`; `reduce`/`exit` se normalizan por direccion.
- `position_effect`: `open_long`, `add_long`, `close_long`, `reduce_long`,
  `open_short`, `add_short`, `close_short`, `reduce_short`.
- Un simbolo no puede tener largo y corto a la vez. Rotacion en dos ciclos.
- Corto sin stop, sin geometria invertida o sin borrow verificado no existe.
- Cierres y reducciones no consumen cupo y no se bloquean por exposicion.

## Limites (escalon guarded por defecto)

| limite | valor |
|---|---|
| `MAX_SHORT_EXPOSURE` | 0.10 |
| `MAX_SHORT_POSITION_EXPOSURE` | 0.03 |
| `MAX_GROSS_EXPOSURE` | 0.80 |
| `MAX_OPEN_SHORT_POSITIONS` | 2 |
| `MAX_DAILY_SHORT_ORDERS` | 1 |
| `MAX_SHORT_RISK_PER_TRADE` | 0.005 |
| `MAX_TOTAL_SHORT_OPEN_RISK` | 0.010 |

Kernel absoluto: corto 0.60, corto por nombre 0.15, bruto 1.20, R:R corto 1.5.
El kernel ya no devuelve `True` por `side=sell`: distingue cierre de apertura.

## Cambios por fichero

- `models.py`: `direction` y `position_effect` en `OrderPlan` y recomendacion.
- `config.py`: settings de la linea corta; `shorts_shadow_enabled` queda
  reservado al shadow book del siguiente lote (hoy sin consumidor).
- `kernel.py`: gates por efecto, caps absolutos de corto y bruto, borrow
  obligatorio, geometria invertida.
- `tools/risk.py`: geometria por direccion, caps por lado y bruto, riesgo corto.
- `tools/execution.py`: orden por efecto (abrir corto SELL entero, cubrir BUY),
  cierre con `close_position`, borrow verificado antes del kernel.
- `tools/broker.py`: `shorting_enabled`, `shortable`, `easy_to_borrow`,
  `marginable` con cache por proceso; nunca se asume borrow.
- `tools/position_sizing.py`: sizing corto entero con caps y buying power.
- `tools/trade_decision.py`: acciones `short`/`cover`, seleccion y gate de
  entrada por direccion, plan de corto, salidas de corto, prompt y limites.
- `scheduler.py`: monitor de stop/take invertido, cobertura con BUY, plan de
  salida con efecto, lotes por direccion.
- `storage.py`: `latest_entry_plans_by_symbol`, conteo diario de cortos.
- `tools/trade_history.py`: FIFO con lotes cortos y P/L de cobertura.
- `tools/portfolio_replay.py`: replay con posiciones negativas y lotes cortos.
- `tools/canonical_selection_ledger.py`: acciones `short`/`cover` sin colapsar.
- `tools/earnings_window.py`: blackout de earnings compartido.
- `web_app.py`: direccion en la tabla de posiciones y en Kindle.

## Pruebas

- `tests/test_p186_short_parity.py`: 17 passed. Cubre contrato, seleccion,
  riesgo, kernel (borrow, caps, cierre), ejecucion (SELL/BUY, fracciones),
  sizing entero, storage y planes end-to-end de corto y cobertura.
- Regresiones focales de trade history, kernel, riesgo y ejecucion: 51 passed.

## Limites declarados

- La evidencia de borrow depende del broker en tiempo de ejecucion; en tests se
  inyecta y se declara `pending_broker_verification` en el plan.
- El linkage de aprendizaje de cortos (marcar la senal como `executed_short`) y
  la superficie completa de metricas por direccion quedan como siguiente lote
  P-L186B; no bloquean la ejecucion ni el riesgo.
- Sin datos reales de borrow/fee en el entorno local: `unavailable`.


## Despliegue 0.4.416/0.4.417 (2026-10-31)

- 0.4.416 imagen `sha256:ff5e95d8ea84f2d4708dafa899af69267d4da5c02cc1078a9422a2bb2cedaba2`,
  commit `7b2c6623`, tree `ce7eca2f`, recibo 19:03:11Z. Detectado en smoke que
  `_recommendation_from_dict` dejaba `direction="long"` en short/cover; corregido
  en 0.4.417.
- 0.4.417 imagen `sha256:29aec1c72cd08af611ab425982a50ab805e9f047596457f49283138d9c8d9a9d`,
  commit `4a173d7f`, tree `48452fb6`, tag `prod-jetson-0.4.417`, recibo
  19:07:02Z. Version runtime 0.4.417.
- Salud doble: 3 contenedores healthy, RestartCount 0, OOM false, HTTP 200 en
  `/`, `/health`, `/_stcore/health`; kernel `ok` 0 violaciones con manifiesto
  resellado 18:59:50Z; flags paper/true/false/false; cero ordenes y planes.
- Entorno activo guarded: corto 10% cartera, 3% por nombre, 2 posiciones, 1/dia,
  riesgo 0.5%, bruto 80%. `application.env` hash `48904fdd...`; selector
  `agente-bolsa:0.4.417-arm64`.
- Snapshot pre-corte `cold-pre-0.4.416-20261031T183409Z`, db sha256
  `9a4db105...`; `quick_check`/`integrity_check` `unavailable` por timeout de
  120 s bajo los timeouts NVMe conocidos. Copia con escritores parados.
- Lease stale del PMR 2026-10-30 recuperado por `stale_lease_recovered` al
  reiniciar; sin limpieza manual.
- Smoke funcional en produccion: `short`/`cover` derivan direccion correcta;
  risk aprueba corto acotado; kernel aprueba con borrow verificado y bloquea sin
  el.
- Pendiente: shadow book de cortos, linkage `executed_short`, metricas completas
  por direccion y validacion de una orden corta real (apertura 2026-11-02).


## Cierre 0.4.418 (exposicion bruta)

- 0.4.418 imagen `sha256:20749531c71a5554139bb66c6659aaccf1e7c77432d88a915fd1ae9156e60575`,
  commit `d322c416`, tree `e60c1fcc`, tag `prod-jetson-0.4.418`, recibo
  19:13:17Z. Corrige `_current_statistics`: la exposicion es bruta
  (`|market_value|`) y publica `short_exposure`, `short_exposure_pct` y
  `net_exposure`; una posicion corta ya no reduce el capital invertido.
- Smoke en produccion: exposicion 1500 (largo 1000 + corto 500), short 500,
  net 500, short_pct 0.005; `short`/`cover` derivan direccion correcta; caps
  guarded activos; cero ordenes y leases activos.


## Cierre 0.4.419 (fallback determinista short)

- 0.4.419 imagen `sha256:adf6df62259fa1f988a8073064b500aa5396e930192258d77f6114170efd18fc`,
  commit `e3f3d5eb`, tree `06083f6a`, tag `prod-jetson-0.4.419`, recibo
  19:19:14Z. Anade `deterministic_short_fallback_recommendations`: un setup
  short strong valido puede convertirse en recomendacion operable con cupo
  propio (1 por ciclo) cuando el LLM no propone ninguno, igual que el fallback
  de compras.
- Smoke en produccion: el fallback devuelve 1 short, direccion short y source
  `deterministic_fallback_short`; caps guarded activos; cero ordenes y leases.
- Con esto la senal corta no depende solo del LLM. La primera orden real sigue
  pendiente de la apertura del lunes 2026-11-02.


## Cierre 0.4.420 (UI de exposicion corta)

- 0.4.420 imagen `sha256:8376e260c7d294393d553b1a6129b404f7d40192c68c8044fc842cbffa70fcc7`,
  commit `14ac4021`, tree `69c0de9d`, tag `prod-jetson-0.4.420`, recibo
  19:27:13Z. La franja de cuenta muestra `Corto` con importe y porcentaje
  cuando hay exposicion corta, ademas de la direccion en la tabla de posiciones.
- Tests web/UI+P186: 110 passed; Ruff/NUL limpios.


## P-L186G (0.4.421): ejecucion corta enlazada al aprendizaje

- `learning_observations` incorpora `executed_short` mediante migracion
  idempotente (`ALTER TABLE ... ADD COLUMN ... DEFAULT 0`), sin reescritura ni
  backfill.
- `broker_reconciliation` resuelve el `position_effect` del plan y marca
  `executed_short` (senal y learning) cuando el fill es `open_short`; los
  cierres y compras conservan `executed_buy`.
- La UI lee `executed_short` en el contexto LLM y en el cruce por señal.
- Test de extremo a extremo: fill SELL de corto deja `executed_short=True`,
  `executed_buy=False` y `execution.direction="short"`.
- Pendiente de despliegue y validacion cerrada en el momento de escribir.


## Despliegue 0.4.421 (executed_short)

- 0.4.421 imagen `sha256:0c8c69983d26c45d041a335651cbdc28caabca94378f13a702167f46d79aa7b8`,
  commit `048657bf`, tree `df850f29`, tag `prod-jetson-0.4.421`, recibo
  19:49:29Z. `init-db` aplico la migracion aditiva sobre 69.145 observaciones
  (exit 0); `executed_short` presente y 0 filas marcadas aun.
- Suite completa: 3.282 passed, 1 skipped, 1 fallo ambiental aislado
  (`test_web_research`). Focales P-L186: 24 passed. Ruff/NUL/diff limpios.
- Salud: 3 contenedores healthy, HTTP 200 x3, kernel ok, cero ordenes.


## P-L186H (0.4.422): shadow book observacional de cortos

- Nuevo `tools/short_shadow_book.py`: entradas virtuales de setups short strong
  con stop/take/tiempo, cierre por `stop_loss`, `take_profit` o `time_stop`,
  P/L porcentual y resumen (win rate, media, conteo por motivo). Se persiste en
  `data/reports/latest_short_shadow_book.json` con escritura atomica.
- No crea ordenes, no toca broker ni Store, no alimenta la decision. Se ejecuta
  en el ciclo de mercado y cualquier fallo se registra sin bloquear.
- Un simbolo cerrado no se reabre en la misma sesion.
- Tests: apertura y cierre por stop, y disabled sin escritura.


## Despliegue 0.4.422 (shadow book)

- 0.4.422 imagen `sha256:9fe1aad610fa668ea4c91e4704b4ea03269264cb3738ee60780507c52df8cba5`,
  commit `597466c8`, tree `b79fef05`, tag `prod-jetson-0.4.422`, recibo
  2026-11-01T00:02:12Z. Suite completa: 3.284 passed, 1 skipped, 1 fallo
  ambiental aislado. Smoke en produccion: shadow book crea una entrada virtual,
  escribe `latest_short_shadow_book.json` y declara
  `observational_only_no_orders`.
- Con esto el flag `SHORTS_SHADOW_ENABLED` tiene consumidor real y la linea
  corta acumula evidencia stop/take/tiempo sin tocar ordenes.


## Hotfix 0.4.423 (fallback_reason y R:R exacto)

- Ciclo `mkt_80f57b0fc5e9` fallo con `fallback_reason_required` tras 1.828 s:
  una recomendacion `deterministic_fallback_short` normaliza a `fallback` y el
  snapshot exigia razon aunque el LLM hubiera respondido.
- TTWO quedo sin plan por R:R exacto 1,5 (`1.4999999999999987`) contra un gate
  sin epsilon.
- 0.4.423 imagen `sha256:09af880b...`, commit `dc05c45c`, tree `d5c93257`, tag
  `prod-jetson-0.4.423`, recibo 16:03:04Z. Desplegado con mercado abierto y
  autorizacion del operador; 3 healthy, HTTP 200 x3, kernel ok, 0 reinicios.
- Gates ejecutados: 169 focales, Ruff, NUL, diff. Suite completa omitida por
  mercado abierto y presupuesto de validacion; se declara.


## 0.4.424: fix visual y primer corto real

- La franja de cuenta insertaba `{short_exposure_item}` en una linea propia; con
  la exposicion corta a cero, Markdown la trataba como linea en blanco y el
  resto del HTML salia como bloque de codigo. Se mueve inline y se elimina el
  HTML crudo. Verificado en navegador: `Corto $1.191,10 1,71%` renderizado.
- Primer corto real: APP, plan `open_short` 5 acciones, entrada 238,45, stop
  261,3766, take 204,0601, orden SELL filled 2026-11-02T16:53:22Z
  (`broker_order_id=7d783471-2605-4079-880f-31de00bb50af`). Posicion -5.
- 0.4.424 imagen `sha256:a86dd49c...`, commit `9b4e54e2`, tree `56020c06`,
  tag `prod-jetson-0.4.424`, recibo 17:02:37Z. UI/validacion: 115 focales.
- `executed_short` aun en 0: la reconciliacion de fills no habia procesado el
  corto en el momento de la comprobacion; queda pendiente verificarlo tras el
  postmarket.


## P-L186K (0.4.425): P0 de integridad, PMR y calendario

- `save_signal_outcome` y bulk fusionan `gate_json`; una captura posterior con
  `{}` ya no borra `executed_short`, `broker_order_id` ni evidencia de fill.
- `post_market_review` y `operational_learning` dejan de llamar
  `ensure_schema()` en la ruta del PMR; el esquema queda para arranque/init-db.
- El PMR reintenta hasta 3 veces solo ante `database is locked` (30/60/120 s),
  con evento `postmarket_lock_retry`; otros errores fallan igual.
- `MarketCalendar` reconstruye la instancia una vez si `pandas_market_calendars`
  pierde `_holidays` o lanza `DateOffset`; si falla, usa fallback conservador y
  no mata `portfolio_watch`.
- Tests P0: 8 passed; regresiones focales: 86 passed.


## Despliegue 0.4.425 (P0)

- 0.4.425 imagen `sha256:38047f6f7381438b3ec21945ff7ecee21baf3c3b55135d5959f4e2dc527c686f`,
  commit `5d785695`, tree `01756a4e`, tag `prod-jetson-0.4.425`, recibo
  2026-11-03T10:39:59Z. 3 healthy, HTTP 200, kernel ok, 0 reinicios.
- Suite completa: 3.294 passed, 1 skipped, 1 fallo ambiental aislado
  (`test_web_research`). Focales P0: 8 passed; regresiones focales: 86 passed.
- Smoke de produccion: gate merge conserva `executed_short` y `broker_order_id`
  tras una segunda captura con `{}`; helper de reintento importable; PMR solo
  crea esquema si la base no existe.
- `portfolio_watch` publica `portfolio_watch_sleeping` con mercado cerrado y no
  reproduce `_holidays`.
- Verificacion pendiente: PMR de la sesion 2026-11-03 al cierre; no se ejecuta
  manualmente. APP sigue corto (-5, 231,87, +31,85).


## P-L186L (0.4.426): salida corta con plan propio y geometria valida

- Causa raiz del cierre de ADM: `_execute_stop_take_exits` leia
  `latest_executed_buy_plans_by_symbol` y añadia el plan corto con
  `setdefault`. ADM conservaba un plan largo legado (`plan_6d4ae4b73011`,
  2026-09-02) con stop 79,1801 y take 92,5928; el plan corto real
  (`plan_608d63c46dc9`, stop 76,7186 / take 67,1971) no sustituyo al largo.
  El trigger corto `precio <= take` se cumplio al instante (71,60 <= 92,5928)
  y cerro 28 titulos a 71,60. P/L bruto +36,68 USD, positivo por azar y no por
  la estrategia.
- Fix: una posicion corta usa exclusivamente
  `latest_entry_plans_by_symbol` con `direction=short`; nunca un plan largo
  legado. Guarda de geometria: el take debe quedar por debajo del precio de
  referencia y el stop por encima; los niveles invalidos se ignoran y no se
  copian al plan de salida. Los largos conservan el lector legacy.
- `_stop_take_observation` se alinea con la direccion de la posicion.
- `reconcile_broker_orders` deja de ejecutar `ensure_schema` sobre una base
  existente; solo hace bootstrap si la base no existe. Cierra el hueco que
  quedaba tras 0.4.425, porque el PMR llama a esta funcion.
- Evidencia de produccion antes del fix: APP corto abierto (-5, entrada
  238,24, precio 231,87 a las 16:40, +31,85) con geometria correcta
  (stop 261,3766 / take 204,0601). ADM ya cerrado.
- Tests: 6 focales nuevos, 124 focales relacionados y 45 de reconciliacion en
  verde. Suite completa y despliegue en curso.


### P-L186L: espejo largo y grafica de evolucion

- Espejo del mismo defecto: `latest_executed_buy_plans_by_symbol` devuelve
  cualquier compra, incluida una cobertura de corto. Un largo abierto despues
  de una cobertura podia heredar stop/take invertidos. Ahora la fuente se elige
  por direccion: corto exige plan `open_short`; largo prefiere `open_long` y
  solo acepta el lector legacy si el plan no es una cobertura.
- Grafica "Evolucion de la cuenta": ultima fila de `performance_daily`
  2026-10-30 (acumulado -0,19 %). Faltan 2026-11-02 (PMR fallo 21:22Z por
  `database is locked`) y 2026-11-03 (PMR aun no ejecutado). La ventana
  acumulada tomaba las ultimas 7 filas con dato, no 7 dias naturales; por eso
  "Ultimos 7 dias" mostraba 10-01 a 10-30.
- Fix UI: ventana calendario anclada a la ultima sesion con baseline, metrica
  P/L acumulado por defecto y copy que declara cuantos dias cubre la ventana.
  No se rellena ningun hueco ni se inventan sesiones; el PMR sigue siendo la
  unica fuente de filas.


### P-L186L: un exito de crew no se degrada por telemetria tardia

- Evidencia: `mkt_53b092604b78` (inicio 15:23:31Z, `cycle_started` 15:26:29Z)
  termino `failed` a las 15:57:40Z con
  `agent_run_terminal_conflict:succeeded->failed`, sin evento `cycle_failed`.
  El run `agent_run_b53a0d456587` (`crew_orchestrator`/`crew_cycle`) ya habia
  emitido `agent_run_succeeded`; el `reporter.emit(crew_completed)` posterior
  fallo y el `except` llamo `fail()` sobre un run terminal. El `ValueError`
  aborto el ciclo completo.
- Fix: el `crew_completed` de exito es fail-open y el manejador de excepcion
  no degrada un run ya `succeeded`; conserva el resultado del crew. Un conflicto
  real sigue auditandose con `agent_run_conflict`.
- Coste observado: 34 min de ciclo y cero recomendaciones en esa pasada. El
  siguiente ciclo arranco a las 16:11:43Z.


## Despliegue 0.4.426 (P-L186L)

- Imagen `agente-bolsa:0.4.426-arm64`
  `sha256:66e2afce17252d0e689bcac0a57bb486fa7774fd0f3923c5fe4073da7f9f4761`,
  commit `8ee6274f`, tree `2b1f9cd9`, tag `prod-jetson-0.4.426`, recibo
  verificado 2026-11-03T16:37:03Z.
- 3 contenedores healthy, RestartCount 0, OOM false, HTTP 200 en `/`, `/health`
  y `/_stcore/health`, kernel `ok` con 0 violaciones, runtime 0.4.426.
- Verificacion funcional en la imagen: corto ADM devuelve stop 76,7186 / take
  67,1971; largo tras cobertura usa su plan largo; sin plan largo valido no hay
  salida automatica; `reconcile_broker_orders` ya no ejecuta `ensure_schema`
  sobre base existente; `_cumulative_window` usa calendario; P/L acumulado es
  la metrica por defecto.
- Suite final: 3.306 passed, 1 skipped, 1 fallo ambiental aislado
  (`test_web_research`). Focales del lote: 114 passed.
- Cero ordenes desde el corte. APP sigue corto (-5, entrada 238,24, precio
  241,96 a las 16:40Z, P/L abierto -18,60). ADM quedo cerrado antes del fix.
