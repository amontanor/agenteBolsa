# P-L43BR1 — observación shadow XNYS

Estado: candidato aislado, pendiente de integración y autorización posterior.

Base: `821496670b5654f4dc90ca104d21f011d72f423b` · versión `0.4.172`.

## Alcance restaurado

La regla legacy de `time_stop_v2` basada en días naturales continúa siendo la
única ruta activa que puede crear una orden. P-L43BR1 restaura el alcance
shadow/paridad del contrato original: la semántica XNYS calcula evidencia,
pero nunca autoriza, bloquea, retrasa ni modifica una orden.

`stale_guard_v2` permanece independiente e intacto.

## Evidencia shadow

El helper `agente_bolsa.tools.time_stop_policy` publica:

- `legacy_eligible` y `xnys_eligible`;
- `comparison_status` (`both_ineligible`, `both_eligible`, `legacy_only`,
  `xnys_only`, `xnys_unavailable`);
- sesiones XNYS completadas y requeridas;
- autoridad y timestamp del fill;
- `logical_eligibility_at` (cierre de la quinta sesión posterior);
- `first_actionable_market_time` (apertura de la sesión siguiente, porque
  `portfolio_watch` no evalúa posiciones con el mercado cerrado);
- `shadow_only=true`, `active_policy=legacy_calendar_days` y
  `shadow_policy=time_stop_xnys.v1`.

Los fallos de calendario, fill o lotes son `unavailable`/`ambiguous` para la
observación y fail-open para la operación legacy. Stop-loss, take-profit y
trailing continúan funcionando.

## Lotes y temporalidad

La autoridad es `first_fill_at`, seguida de `filled_at` agregado únicamente
cuando la orden no es parcial. Las órdenes sin fill se excluyen de los lotes.
Las compras múltiples requieren cantidades abiertas verificables; no se elige
silenciosamente la última compra.

Una sesión XNYS cuenta solo después de su cierre. La entrada no cuenta y no se
usan fines de semana, festivos ni el fallback lunes–viernes.

## Persistencia, digest y health

La evidencia se reutiliza en `runtime_state` bajo
`time_stop_v2_evidence:<symbol>`, con actualización idempotente por clave. No
se crean tablas ni se reescriben históricos. El digest diario y
`operational_health` publican un resumen compacto `time_stop_shadow` con
evaluaciones, discrepancias, cobertura de fill y freshness; sin muestra el
estado es `collecting` y los denominadores permanecen `null`.

La telemetría no contiene retornos posteriores, P&L futuro, MFE/MAE,
`first_hit` ni outcomes maduros.

## Evidencia histórica descriptiva

Las fixtures de AIZ, CRWD, STT, SBUX, EXPE, ALL y EBAY quedan como
`legacy_only` en sus fechas históricas. DDOG y ANET alcanzan la quinta sesión
lógica al cierre del 21-jul; la primera oportunidad operativa garantizada es
la apertura del 22-jul si no existe un tick exacto al cierre.

Estos casos no seleccionan una política ni constituyen evidencia suficiente
para cambiar `time_stop_v2`.

## Validación aislada

- Focal P-L43B/P-L43BR1 y scheduler: se ejecuta tras este cambio.
- Regresiones de portfolio watch, stop/take/trailing, storage,
  reconciliation y execution quality: incluidas en la suite.
- No se ejecutan broker real, postmarket real, reconciliación real, red, LLM,
  servicios ni despliegue.

Cualquier activación futura de la política XNYS requiere un lote separado,
fecha efectiva y autorización humana explícita.
