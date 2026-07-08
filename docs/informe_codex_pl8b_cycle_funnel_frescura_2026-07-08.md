# Informe Codex PL8B - cycle funnel con flujo fresco - 2026-07-08

## Problema

El comando `cycle-funnel` solo leía el último `paper_auto_trade_completed`. Si los ciclos recientes acababan en `trade_execution_summary` sin ordenes o en `paper_auto_trade_blocked`, el lector seguía viendo un embudo viejo y no el flujo real del día.

## Cambio aplicado

- `src/agente_bolsa/tools/cycle_funnel.py`
  - El embudo ahora busca el último evento observable del flujo entre:
    - `trade_execution_summary`
    - `paper_auto_trade_completed`
    - `paper_auto_trade_blocked`
    - `scheduled_market_cycle_skipped`
  - Expone `event_type`, `status` y `status_reason`.
  - Si el flujo reciente está bloqueado o saltado, el cuello refleja ese motivo.
  - El histórico ahora deduplica por `cycle_id` y usa el último evento por ciclo, para no contar dos veces `paper_auto_trade_blocked` + `trade_execution_summary`.
  - Los motivos del `operational_kill_switch` ya entran en el agregado del histórico.

## Tests

- `tests/test_cycle_funnel.py`
  - Nuevo caso: el embudo prefiere un `trade_execution_summary` reciente frente a un `paper_auto_trade_completed` antiguo y muestra el motivo de bloqueo.
  - Nuevo caso: el histórico usa el último evento por ciclo y agrega el bloqueo de `operational_kill_switch`.

## Verificacion dirigida

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cycle_funnel.py -x -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

Resultado:

- `6 passed`
- `ruff check src tests`: OK
