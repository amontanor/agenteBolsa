# Informe G0 - suite completa verde

Fecha: 2026-07-07

## Resumen

Se corrigio la bomba de antiguedad en tests que dependen del matching fill->senal con guard de `5` dias en `execution_linking.py`. La suite completa vuelve a verde.

Version: `0.4.115`

## Causa confirmada

El fallo en `tests/test_lab_book_wall.py::test_lab_book_source_is_excluded_from_real_book_consumers` venia de una combinacion de:

- `match_signal_row_for_buy_order(..., max_signal_age_days=5)` en `src/agente_bolsa/tools/execution_linking.py`
- senal hardcodeada en `2026-07-01`
- `broker_order.created_at` generado con la hora real de ejecucion del test

Al llegar el 2026-07-07, la senal quedaba fuera de la ventana y `linked_executed_buys` pasaba a `0`.

## Barrido preventivo

Se hizo barrido con:

```powershell
rg -n '2026-0[4567]-|2026-07-|2026-06-' tests
```

Se limitaron los fixes a los tests que realmente ejercitan ventanas de antiguedad de linking fill->senal:

- `tests/test_lab_book_wall.py`
- `tests/test_broker_reconciliation.py`

El resto de fechas hardcodeadas encontradas son fixtures o pruebas historicas que no dependen del reloj actual para ese matching.

## Cambios

- `tests/test_lab_book_wall.py`
  - ahora usa la ultima sesion de mercado relativa a hoy;
  - fija `signal_date`, `since_date` y `broker_order.created_at` de forma coherente;
  - ajusta `as_of` del estudio de edge a `session_date + 1`.
- `tests/test_broker_reconciliation.py`
  - convierte los timestamps de señales/ordenes a fechas relativas a la ultima sesion de mercado;
  - mantiene la semantica original de “senal antigua vs senal posterior”.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_lab_book_wall.py tests\test_broker_reconciliation.py -q`
  - `3 passed`
- `.\.venv\Scripts\python.exe -m pytest tests -x -q`
  - `978 passed, 1 warning`
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts`
  - OK
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`
  - OK
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`
  - `trading_mode=paper`, `allow_live_trading=false`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`
  - OK, ciclo `20260707-140146`

## Flags operativas confirmadas

- `trading_mode=paper`
- `allow_live_trading=false`
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false` se mantiene sin activar
