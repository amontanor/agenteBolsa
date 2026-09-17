# P-L127 — Telegram recibe el SP500 (Jetson 0.4.300 / Windows 0.4.232)

## Causa

El gate P-L71 invalidaba con cualquier warning; los caches siempre traen
barras futuras o son same-day: 0/48 comparables aunque habia 50 caches SPY.

## Cambios

- `_series_through_session`: recorta barras posteriores a la sesion (se
  cuentan como `future_bars_ignored`); el par sale del mismo cache.
- `refresh_and_capture_spy_eod`: descarga la ventana exacta [previa, sesion]
  y persiste el recibo, fail-open, desde el job de reconciliacion.
- `backfill_spy_eod_receipts` + CLI `spy-eod-backfill` (solo caches, sin red).
- Same-day sin finality y par ausente siguen `unavailable` con razon.

## Despliegue Jetson 0.4.300

- Patch limpio 4/4 sobre 0.4.299, smoke con recorte real, salud 1+2.
- Backfill 03->16 sep: **9/9 comparables, provisional=false**.
  Ejemplo 16-sep: SPY -0,441% comparable. Telegram de esta noche ya lleva SP500.
- Lote B: proveedor de contratos activo desde 0.4.298; sin admisiones aun
  (mercado cerrado, el lab opera en ventana); verificacion pendiente en
  sesiones reales + sync semanal. Lote C: pendiente de 2 ventanas medibles.
