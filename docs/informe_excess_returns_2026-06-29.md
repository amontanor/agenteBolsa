# Informe: retornos EXCESS (vs benchmark) en study_strategy_edge_compare (v0.4.57)

Fecha: 2026-06-29. Autor: asistente (gestor). Tarea read-only de medición.

## Objetivo
El comparador medía retornos forward **crudos** de `builtin_pullback` vs `builtin_breakout`.
El primer dato a 1d (breakout +0.7% / pullback −0.5%) probablemente reflejaba **beta** (breakout
= alta beta; pullback = baja beta) en un día alcista, no alpha. Para que el veredicto del 6-jul
sea fiable se añade el **retorno EXCESS = retorno_símbolo − retorno_benchmark** al mismo
`signal_date` y horizonte, que aísla el alpha de la dirección del mercado.

## Cambios (scripts/study_strategy_edge_compare.py)
- `benchmark_returns_from_closes(ordered_dates, closes, signal_dates, horizons)` — **función pura**:
  por cada `signal_date`, base = cierre de ese día, objetivo = cierre N sesiones después; emite
  solo claves con datos disponibles. Replica la convención exacta de `signal_learning._outcome_for_signal`
  (entry = cierre del signal_date; `return_Nd = (close[idx+N] − close[idx]) / close[idx]`, redondeo 4).
- `build_benchmark_returns(...)` — descarga precios del benchmark con `download_daily_prices([symbol], since)`
  (import perezoso, aislado de la función pura para que la red no contamine los tests) y delega en
  la función pura. Devuelve `{}` si no hay datos o falla la descarga.
- `summarize_strategy_edge(..., benchmark_returns=None)` — cuando se pasa el mapa, añade
  `excess_horizons` por estrategia y `excess_deltas` (pullback − breakout), con la **misma**
  estadística (mean/median/hit/std/mean_net/coverage/pending). Si una fila no tiene benchmark para
  ese (date, horizon) **se excluye** del excess (no se inventa) y se refleja en coverage.
- CLI `--benchmark` (default `SPY`; `none/off` lo desactiva). `print_report` imprime tabla CRUDA y,
  si hay benchmark, tabla EXCESS + sus deltas.
- Compatibilidad: sin `--benchmark`/`none`, el bloque crudo y las claves previas no cambian.
- Versión: `0.4.56 → 0.4.57`.

## Test (tests/test_strategy_edge_compare.py)
- `test_benchmark_returns_from_closes_uses_forward_window`: ventana forward y exclusión de horizonte
  sin barra suficiente.
- `test_summarize_with_benchmark_reports_excess_and_excludes_missing`: matemática del excess, exclusión
  de filas sin benchmark, delta excess, y que el bloque crudo no se ve afectado.

## Verificación realizada (sandbox, sin red)
Ejecutadas las funciones REALES del fichero (imports pesados stubbeados por falta de pydantic/pip
en el sandbox) con datos sintéticos:
- `benchmark_returns_from_closes`: (2026-06-25,1)=0.01, (2026-06-25,3)=−0.01, horizonte 5 sin clave. OK
- excess: pullback mean −0.005 (n=2), breakout mean 0.02 (n=1, pending=1), delta −0.025. OK
- backward-compat: sin benchmark no aparecen claves excess; bloque crudo intacto. OK
- aserciones del test existente: siguen pasando. OK
- `py_compile`: OK.

## Pendiente (requiere el venv de Windows; no ejecutable desde el sandbox)
1. Suite completa: `.\.venv\Scripts\python.exe -m pytest -q -p no:warnings` (debe seguir verde + los 2 nuevos).
2. Ruff: `.\.venv\Scripts\ruff.exe check src tests scripts\study_strategy_edge_compare.py`.
3. Run real con datos:
   `.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 10 --benchmark SPY`
4. Commit tras validar.

## Qué mirar en el run real
Si el delta EXCESS pullback−breakout es ≈0 o positivo aunque el crudo sea negativo, confirma que
el −1.2% crudo de 1d era **beta, no falta de edge**. El veredicto de fondo se decidirá a 5d/10d.
