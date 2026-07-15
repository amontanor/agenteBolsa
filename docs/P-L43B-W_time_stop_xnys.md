# P-L43B-W — candidato de time-stop XNYS

Estado: implementación aislada, pendiente de revisión y sin integración.

Base: `821496670b5654f4dc90ca104d21f011d72f423b` · versión `0.4.172`.

## Contrato

El helper `agente_bolsa.tools.time_stop_policy` implementa
`p-l43b.time-stop-xnys.v1` / `time_stop_xnys.v1`.

Una posición long solo es elegible cuando se han cerrado cinco sesiones XNYS
estrictamente posteriores al `entry_fill_at` verificable y se mantiene el
filtro existente `unrealized_return <= 0`.

La sesión de entrada no cuenta. Una sesión solo cuenta después de su cierre
XNYS; una evaluación durante la quinta sesión devuelve `xnys_eligible=false`.
El helper conserva también `legacy_calendar_eligible` y `comparison` como
telemetría (`same`, `legacy_only`, `xnys_only`), sin que la comparación legacy
pueda activar una orden.

## Autoridad temporal y lotes

La prioridad es `first_fill_at`, seguido de `filled_at` agregado únicamente
cuando la orden no es parcial. `created_at` de plan u orden no se utiliza como
fill. Una orden parcial sin `first_fill_at` queda `unavailable`.

La nueva lectura `Store.executed_buy_lots_by_symbol()` conserva todos los
`broker_order_id` y no selecciona silenciosamente la última compra. Varias
compras solo se evalúan cuando existe `open_qty` o `remaining_qty` explícito de
posición para cada lote; en otro caso el resultado es `ambiguous` y el
time-stop no se dispara.

## Integración operativa

`portfolio_watch_job` reutiliza el `MarketCalendar` ya creado y pasa una hora
de evaluación explícita. `_execute_stop_take_exits` conserva sin cambios las
ramas de stop-loss, take-profit, trailing y sus cantidades. Solo se sustituye
la condición temporal de `time_stop_v2`.

Las salidas time-stop incluyen:

- `exit_policy_version=time_stop_xnys.v1`;
- `time_stop_semantics=completed_xnys_sessions_after_fill`;
- evidencia temporal y comparación legacy.

El fallo del helper, del calendario o de la persistencia de telemetría es
fail-open para la operación: no bloquea stop-loss/take-profit ni el scheduler.
El calendario no disponible impide únicamente el time-stop.

## Reproducción de P-L43A

Con fixtures XNYS explícitas:

- AIZ/CRWD: 13-jul `legacy_only`; XNYS no elegible.
- STT/SBUX/EXPE: 14-jul `legacy_only`; XNYS no elegible.
- ALL: 14-jul `legacy_only`; XNYS no elegible.
- EBAY: 15-jul `legacy_only`; XNYS no elegible.
- DDOG/ANET: no elegibles antes del cierre del 21-jul.

No se usan precios, posiciones ni datos productivos en las pruebas.

## Compatibilidad y límites

Los históricos conservan su interpretación legacy de días naturales y no se
reescriben. El trigger sigue llamándose `time_stop_v2`. No se modifica
`config.py`: el valor existente `EXIT_POLICY_V2_TIME_STOP_DAYS=5` se interpreta
como `required_completed_sessions` dentro del candidato.

No se implementa backfill, cambio manual de posiciones, activación shadow en
producción ni despliegue. La activación futura requiere comparar ambos relojes
en shadow y una decisión humana.

## Validación aislada

- Focal time-stop y scheduler: `23 passed`.
- Focales P-L37B/P-L40B, storage, broker reconciliation, risk y execution:
  `128 passed`.
- Ruff sobre archivos modificados: correcto.
- `git diff --check`: correcto.
- Suite completa, `run-once`, servicios, postmarket y broker real: no
  ejecutados en este lote.
