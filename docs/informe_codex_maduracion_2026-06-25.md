# Informe Codex maduracion 2026-06-25

## Objetivo

Verificar que las filas SHADOW de `builtin_pullback` guardadas en `signal_outcomes` maduran forward returns igual que las filas ACTIVE, para que la medicion pullback-vs-breakout sea util cuando pasen 1/3/5/10 sesiones.

## Proceso encontrado

La maduracion vive en `src/agente_bolsa/tools/signal_learning.py`, funcion `update_signal_outcomes`.

Flujo:

1. `store.signal_outcomes(limit=..., since_date=...)` lee filas de `signal_outcomes`.
2. No filtra por `source_run_id`, `decision`, `strategy_status` ni `shadow_candidate`.
3. Descarga precios diarios para los simbolos de esas filas.
4. Para cada fila, `_outcome_for_signal` calcula `return_1d`, `return_3d`, `return_5d`, `return_10d`, `mfe_10d`, `mae_10d` y `verdict`.
5. Persiste por `signal_id` con `store.update_signal_outcomes_bulk`.

Callers relevantes:

- `tools/post_market_review.py`: `update_signal_outcomes(..., since_date="2026-04-01", limit=200000)`.
- `tools/broker_reconciliation.py`: `update_signal_outcomes(..., since_date="2026-04-01", limit=200000)`.
- `tools/daily_learning.py`: `update_signal_outcomes(..., since_date=since_date, limit=LEDGER_LIMIT)`.
- CLI `learning-status --update`: usa `update_signal_outcomes(settings, store, since_date=args.start)`.

## Veredicto

No habia gap funcional de filtrado: las filas SHADOW entran en la maduracion porque `store.signal_outcomes` solo filtra por fecha y limite. El sufijo `:shadow` en `source_run_id` evita decision/ejecucion accidental, pero no bloquea la maduracion de outcomes.

Riesgo residual: el parametro `limit` puede recortar filas si se llama con un limite bajo. Los jobs importantes usan limites altos (`200000` o `LEDGER_LIMIT`), por lo que el riesgo practico para el pipeline programado es bajo.

## Test agregado

Se agrego `test_update_signal_outcomes_matures_pullback_shadow_candidate` en `tests/test_signal_learning.py`.

El test crea una fila:

- `source_run_id="scan-shadow:shadow"`
- `strategy_name="builtin_pullback"`
- `strategy_status="SHADOW"`
- `shadow_candidate=True`
- `signal_date="2026-04-27"`

Luego monkeypatchea datos diarios con barras futuras y ejecuta `update_signal_outcomes`. Resultado esperado y validado:

- `updated == 1`
- `return_5d == 0.05`
- `matured_horizons["5d"] is True`
- la fila conserva `source_run_id=:shadow` y `strategy_name=builtin_pullback`

La cobertura previa para ACTIVE ya existia en `test_deduped_signal_keeps_decision_and_outcome_matching`: una fila ACTIVE deduplicada madura `return_5d` y mantiene el matching de decision por `source_run_id` reciente.

## Muestra de salida esperada

La muestra se valida con fixture sintetico, no contra la BD real, porque las filas reales de `2026-06-25` aun no tienen barras futuras suficientes. En el fixture:

```text
signal_id: test:2026-04-27:BUILTIN_PULLBACK:AAPL
source_run_id: scan-shadow:shadow
strategy_name: builtin_pullback
shadow_candidate: true
return_5d: 0.05
matured_horizons.5d: true
```

Cuando haya barras reales, `scripts/study_strategy_edge_compare.py --since 2026-06-25` deberia empezar a mostrar coverage > 0 primero en `return_1d`, luego `return_3d`, `return_5d` y `return_10d`.

## Validacion

- `py_compile`: OK para `tests/test_signal_learning.py` y `src/agente_bolsa/__init__.py`.
- Test focalizado: `tests/test_signal_learning.py` -> `24 passed`.
- `ruff check src tests scripts/study_strategy_edge_compare.py`: OK.
- Suite completa: `759 passed in 154.71s`.
- `status`: `trading_mode=paper`, `allow_live_trading=false`.
- `kernel-status --json`: `ok=true`, `violations=[]`.

No se reiniciaron servicios porque no se toco el proceso de runtime: el codigo de maduracion ya incluia SHADOW y el cambio de esta entrega es test/documentacion/version. Tampoco se ejecuto `kernel-seal` porque no se toco `.env`.

## Tarea opcional 2

No ejecutada en esta entrega. El scoreboard por ciclo de `shadow_candidates` sigue siendo una mejora read-only separable.
