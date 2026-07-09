# Informe Codex P-L13 - UI panel P/L del dia

Fecha: 2026-07-09
Version entregada: `0.4.136`

## Objetivo

Ajustar solo la UI/presentacion del panel para que:

- `P/L hoy` use como porcentaje principal el rendimiento del dia sobre capital
  invertido.
- desaparezca la tarjeta `P/L realizado` de la fila bajo `Valor de cartera`.

No se toca logica de trading ni fuentes de datos de cartera.

## Cambio aplicado

Archivos:
- `src/agente_bolsa/web_app.py`
- `tests/test_web_app.py`

Detalles:
- Nuevo helper puro `_today_pl_display(today_pl, invested, equity_pct)` para
  construir el texto visible de la tarjeta `P/L hoy`.
- La tarjeta reaprovecha exactamente las mismas entradas que ya usaba el panel:
  - `today_pl`
  - `today_pct`
  - `exposure`
- El porcentaje principal ahora es `today_pl / exposure`.
- Si `exposure <= 0`, el porcentaje principal muestra `n/d`.
- Se mantiene el importe `$` tal cual y se deja la referencia secundaria sobre
  equity total en pequeno.
- La fila compacta bajo `Valor de cartera` pasa de 4 a 3 tarjetas:
  - `P/L desde abril`
  - `P/L ultimos 7d`
  - `P/L abierto`

## Tests

Unitarios nuevos:
- `test_today_pl_display_uses_pct_over_invested_as_primary`
- `test_today_pl_display_returns_nd_when_invested_is_zero`
- `test_today_pl_display_preserves_negative_pct_over_invested`

Cobertura pedida:
- caso normal
- invertido = 0
- P/L negativo

## Verificacion real del panel

Reinicio operativo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_services.ps1
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501
```

Resultado:
- panel respondiendo `HTTP 200`
- captura guardada en:
  - `docs/pl13_ui_panel_2026-07-09.png`

Numeros reales observados en la captura:
- `P/L hoy`: `$47.08`
- `% principal`: `0.90% sobre invertido ($5,254.65)`
- referencia secundaria: `0.07% del equity total`

Comprobacion visual adicional:
- la fila bajo `Valor de cartera` ya no muestra `P/L realizado`
- quedan solo tres tarjetas:
  - `P/L desde abril`
  - `P/L ultimos 7d`
  - `P/L abierto`

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
