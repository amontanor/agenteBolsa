# Informe Codex P-L14 - UI fila P/L hoy en Valor de cartera

Fecha: 2026-07-09
Version entregada: `0.4.137`

## Objetivo

Sustituir en la fila de tarjetas bajo `Valor de cartera` la tarjeta
`P/L ultimos 7d` por `P/L hoy (desde cierre de ayer)`, usando exactamente la
misma fuente y el mismo payload visual que la tarjeta hero de `P/L hoy`.

## Cambio aplicado

Archivos:
- `src/agente_bolsa/web_app.py`
- `tests/test_web_app.py`

Detalles:
- Nuevo helper `_today_pl_metric_payload(today_pl, invested, equity_pct)`.
- El helper reutiliza `_today_pl_display(...)` y construye:
  - importe
  - detalle HTML con `% sobre invertido`
  - referencia secundaria sobre equity total
- La tarjeta hero y la tarjeta de la fila compacta consumen ahora el mismo
  payload, por lo que muestran siempre el mismo numero y la misma base.
- La fila queda asi:
  - `P/L desde abril`
  - `P/L hoy (desde cierre de ayer)`
  - `P/L abierto`

## Tests

Actualizados:
- `tests/test_web_app.py`

Cobertura:
- sigue cubierto el helper de `P/L hoy` sobre invertido
- nuevo assert de consistencia:
  - `_today_pl_metric_payload(...)["display"] == _today_pl_display(...)`

## Verificacion real del panel

Reinicio operativo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_services.ps1
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501
```

Resultado:
- panel `HTTP 200`
- captura guardada en:
  - `docs/pl14_ui_panel_2026-07-09.png`

Numeros reales observados en el momento de la captura:
- Hero `P/L hoy`:
  - `$30.77`
  - `0.59% sobre invertido ($5,238.39)`
  - `0.04% del equity total`
- Fila `Valor de cartera`:
  - `P/L hoy (desde cierre de ayer)`
  - `$30.77`
  - `0.59% sobre invertido ($5,238.39)`
  - `0.04% del equity total`

Comprobacion visual:
- la tarjeta `P/L ultimos 7d` ya no aparece
- hero y fila muestran el mismo importe y el mismo porcentaje

## Validacion ejecutada

Focal:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_app.py -q
.\.venv\Scripts\ruff.exe check src tests
```

Completa:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -x -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew
```
