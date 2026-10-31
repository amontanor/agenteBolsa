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
- `config.py`: settings de la linea corta; `shorts_shadow_enabled` pasa a tener
  consumidor real.
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
