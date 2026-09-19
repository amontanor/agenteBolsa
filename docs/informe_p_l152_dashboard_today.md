# P-L152 — dashboard "Hoy", ceros honestos y dedup SPY (candidato 0.4.252)

Dictamen: `ready_for_review`. Sábado 19-sep-2026, XNYS cerrado; trabajo
aislado en worktree, sin broker/red/LLM en pruebas, sin despliegue.

## Causa

El dashboard mostraba datos engañosos fuera de sesión y ocultaba el
desglose de "hoy":

1. "Ganancia/pérdida de la cartera actual hoy: $0.00" con 5 posiciones:
   Alpaca devuelve `unrealized_intraday_pl=0` con mercado cerrado; era
   un cero supuesto, no una medida.
2. `as_of` del P/L diario cruzaba el fin de semana ("17/09 → 19/09"),
   sugiriendo un cierre que no existe.
3. El héroe "Hoy sin dato SPY" se repetía como fila en la tabla.
4. No había desglose realizado/abierto ni compras/ventas de la sesión.

## Cambio

- `position_intraday_pl_reconciliation` (equity_metrics): nuevo campo
  `all_zero`; si todas las posiciones están a 0 y el total es completo,
  el status pasa a `unavailable` (cero de proveedor ≠ ganancia real).
- `_intraday_metric_display`: con mercado cerrado y `all_zero`, muestra
  `n/d · mercado cerrado`; con mercado abierto conserva el `$0.00` real.
- `_outside_trading_session` + `_daily_equity_detail`: fuera de sesión
  etiqueta `cierre {start} · leído {end} (mercado cerrado)`.
- `_today_breakdown` + tarjeta "Hoy": variación de equity, realizado
  hoy (con conocidos/sin P/L), compras y ventas de la sesión vigente,
  reutilizando `history.days`/`history.trades` y la apertura ya cargada.
- `_render_daily_vs_spy_table`: omite la fila en curso no comparable
  (ya responde el héroe).

## QA

- Nuevos: `tests/test_p152_dashboard_today.py` (10 tests).
- Regresiones: web_app, daily equity P-L81, position P-L73, dashboard
  cards P-L87, frescura P-L62, version policy. Total: 151 passed.
- Ajuste de contrato P-L81 (`all_zero` en el dict) y pin de versión
  P-L59C a 0.4.252. Ruff, NUL, diff verdes.
- Omitidos (fin de semana): suite completa, smoke, config/kernel.

## Límites

- No añade fuente nueva ni persistencia; cero llamadas extra al broker.
- El desglose hoy depende de la apertura exacta ya cargada; sin ella,
  `n/d`.
