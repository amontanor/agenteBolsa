# P-L121 — par de cierres SPY con autoridad EOD por sesion XNYS

## Dictamen

`ready_for_integration_rehearsal` (L2 de 4). No cambia trading, riesgo,
ejecucion, seleccion ni auto-apply. No hay backfill ni reescritura.

## Causa y contrato

`comparison_status: comparable` era 0/41 sesiones porque ningun cache
pasaba la autoridad EOD de P-L71. Nuevo productor determinista
(`tools/spy_eod_authority.py`, esquema `p-l121.spy-eod-close.v1`) que
construye por sesion el par de cierres de sesiones XNYS estrictamente
consecutivas con `previous_close`, `close`, `price_basis`, `interval`,
`source`, `bars_as_of`, `cache_created_at` y `eod_authority`. Sin par real
el recibo queda `unavailable` con `reason_codes`; los cierres ausentes son
`None`, jamas cero. Recibos en `data/cache/market_data/spy_eod_close_*`
con `content_hash`; idempotentes por contenido.

## Cambios (v0.4.228)

- `overlay_eod_benchmark` y el constructor del benchmark prefieren el recibo
  comparable validado; sin recibo conservan el comportamiento P-L71 exacto.
  UI y Telegram heredan la mejora por la misma frontera read-only.
- `broker_reconciliation_job` captura el recibo tras reconciliar (fail-open;
  nunca tumba reconciliacion ni cambia su resultado).
- Nuevo CLI `spy-eod-coverage --from/--to [--json]` con denominador
  `xnys_sessions` y bandera `provisional`.

## QA

- Caracterizacion roja y verde (3 tests).
- Regresiones: p65a/p68/p81/naive 39 passed; overlay+telegram 23 passed;
  p40b 51 passed por bloques; version policy verde.
- Ruff completo verde, NUL verde (490 archivos), `git diff --check` verde.
- `validate-agent-config --json`: `ok=true`. Paridad de protegidos limpia.
- Smoke aislado verde (`market_state_quality=PARTIAL`, sin crew).

## Limites y siguiente

Sin caches diarias con cobertura, los recibos quedan `unavailable` con
razon: el codigo no inventa cierres. La comparabilidad real crece cuando el
stack capture sesiones con el job activo. Siguiente: L3 bucle de promocion.
