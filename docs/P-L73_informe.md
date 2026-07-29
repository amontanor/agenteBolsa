# P-L73 — P/L total y diario por posición abierta

## Dictamen

`ready_for_integration_rehearsal`

La cartera abierta solo publicaba el P/L no realizado acumulado desde la
entrada. El `PortfolioSnapshot` de Alpaca ya transportaba, en la misma respuesta
de posiciones, los cuatro campos canónicos necesarios:

- `unrealized_pl`;
- `unrealized_plpc`;
- `unrealized_intraday_pl`;
- `unrealized_intraday_plpc`.

La UI descartaba los dos campos intradía al proyectar el snapshot en
`trade_history`.

## Contrato

- `P/L total`: P/L no realizado desde la entrada, en USD y porcentaje.
- `P/L día`: P/L no realizado del día publicado por Alpaca, en USD y
  porcentaje.
- Ambos valores proceden del mismo objeto `PositionSnapshot`.
- La ausencia de un campo diario se presenta como `n/d`; nunca se sustituye por
  cero.
- La UI no reconstruye el valor por símbolo, precios históricos ni texto.
- `build_trade_history()` reutiliza el `PortfolioSnapshot` ya cargado por cada
  página y no realiza una segunda lectura de posiciones.

La documentación oficial de Alpaca denomina
`unrealized_intraday_pl`/`unrealized_intraday_plpc` P/L no realizado del día.
Este dato no se presenta como retorno exacto apertura XNYS → ahora: el sistema
no conserva todavía un precio de apertura canónico por posición. La comparación
Sistema/SP500 P-L72 mantiene su contrato separado de apertura a apertura.

## Presentación

- `Cartera abierta` muestra columnas distintas `P/L total` y `P/L día`.
- Cada columna combina USD y porcentaje con el mismo color.
- La página detallada de cartera expone también las cuatro columnas numéricas.
- La compra, stop, take y orden por fecha conservan el comportamiento previo.

## Seguridad y paridad

- Sin cambios en broker, execution, risk, kernel, config o política.
- Sin llamadas nuevas al broker.
- Sin escrituras, tablas, migraciones o backfill.
- Sin cambios en órdenes, gates, sizing, exposición, stops o takes.
- Telegram no cambia: ya consumía esos mismos campos intradía.

## Validación

- Focales de P-L73, UI, cartera, Telegram, P-L72 y trade history:
  `129 passed`.
- Suite completa: `2289 passed, 1 skipped`; un warning de deprecación
  preexistente.
- Ruff completo: correcto.
- `check_no_nulls.py`: correcto, 452 archivos.
- `validate-agent-config --json` con `DATA_DIR` temporal: `ok=true`, sin errores
  ni warnings.
- `git diff --check`: correcto.
- El smoke CLI real permanece `smoke_unavailable_by_safety` porque construiría
  proveedores configurados sin garantizar ausencia de broker/red. El sustituto
  aislado del entrypoint pasó con `DATA_DIR` temporal, proveedores
  monkeypatched y `use_crew=False`.
- Archivos protegidos idénticos a la base productiva.
