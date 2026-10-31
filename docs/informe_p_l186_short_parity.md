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
