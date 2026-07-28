# P-L65A — contrato diario Sistema vs SP500

## Dictamen

`ready_for_p65b_implementation`.

La caracterización deja cerrado el contrato matemático y reproduce las
fronteras que deben corregirse en P-L65B. No se implementó `src/` ni se
modificó la política de trading. En el árbol P-L63R1, la corrección P-L63 de
equity ya está presente: la cabecera y `Resultado del periodo` usan equity
real. El gap restante está en el consumidor del baseline diario y en la
definición de ventanas/contadores de Sistema vs SPY.

## Estado y aislamiento

- Fecha de ejecución: 28-jul-2026, Europe/Madrid.
- XNYS: abierto; `schedule-status` read-only previo informó apertura 15:30 y
  cierre 22:00. Por ello se limitaron las validaciones a focales, estáticos y
  fixtures temporales.
- Base: `cdf2ce6ccfa818df7c3692ccb328a3e468f9a525` /
  `42b48b78867e7ffc9306ade86bcc1027aa32378c`, versión `0.4.198`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl65a_daily_vs_spy_contract`.
- Rama: `codex/pl65a-daily-vs-spy-contract`.
- Version policy: base `0.4.198` -> candidate `0.4.199`; the bump was required
  by the version-policy test after adding this characterization file.
- Solo se modificaron `tests/test_p65a_daily_vs_spy_contract.py` y este
  informe, además de las anotaciones documentales exigidas en plan/relevo.
- Producción, SQLite productiva, servicios, locks/leases, broker, red,
  configuración y archivos protegidos permanecieron intactos.

## Causa y traza real

1. `tools/performance_benchmark.py::build_performance_benchmark` calcula
   `account.daily_return` como `equity / previous_equity - 1` y calcula SPY
   desde `previous_close`/`close`. El contrato canónico también conserva
   `price_basis`, `source`, `as_of` y `data_quality`.
2. `tools/performance_baseline.py::build_daily_performance` proyecta esos
   valores a las columnas legacy `pnl_pct` y `spy_pct` de `performance_daily`.
3. `web_app.py::_render_performance_baseline` lee una vez
   `store.performance_daily(limit=0)` y pasa sus columnas legacy a
   `_performance_baseline_series`.
4. `_performance_baseline_series` acumula `pnl_pct`/`spy_pct`, pero no lee el
   bloque `payload.performance_benchmark`, ni valida `source`, `price_basis`,
   `as_of`, freshness o `data_quality`. Por tanto puede dibujar una pareja de
   números aunque la fila canónica sea `partial`, tenga basis desconocido o
   no tenga fuente.
5. El scoreboard tiene un consumidor distinto que puede completar SPY con
   `build_spy_daily_returns` cuando falta el valor persistido. Ese fallback no
   es la misma fuente que consume el gráfico, así que no puede convertirse en
   ganador visual sin un rowset canónico compartido.
6. `Store.performance_daily` admite `readonly=True`, pero el lector UI del
   baseline no lo solicita explícitamente. Es una deuda de frontera de lectura
   para P-L65B; no se tocó en este lote.

La manifestación histórica de `$192,31 / $8.041,72 = 2,39%` se separa así:
`$192,31 / equity_previa ≈ 0,27%` es la variación primaria de equity; el 2,39%
es solo una equivalencia descriptiva sobre exposición invertida. En P-L63R1
la cabecera ya prioriza `equity_pct`, ignora el denominador invertido para el
porcentaje principal y no presenta “desde apertura”.

## Contrato caracterizado

| Campo | Regla | Estado si falta autoridad |
|---|---|---|
| Sistema primario | `(equity_t - equity_prev_close) / equity_prev_close` e importe `equity_t - equity_prev_close` | `null` / `unavailable` |
| SPY | close-to-close de la misma sesión/ventana, source, basis, `as_of` y calidad compatibles | `pending` / `unavailable` |
| Exposición invertida | Métrica secundaria descriptiva con denominador y timestamp explícitos | Nunca ganador |
| Flujos | Ajuste neutral solo con ledger exacto | No inventar; copy “Variación de equity” |
| Ganador | Comparar únicamente los dos retornos primarios comparables | `pending` para stale, partial, estimated, interpolated o mismatch |
| Ventana | Un rowset visible único alimenta gráfico, tabla, tarjetas, fechas y contadores | Sin contadores globales fuera de ventana |

Ejemplo obligatorio reproducido: Sistema `+0,27%`, exposición-normalizada
`+2,39%`, SPY `+0,50%` ⇒ gana SPY. La cifra 2,39% no puede decidir la
comparación.

Para una selección de siete sesiones reales:

```text
visible_total = comparable + pending
comparable = system_wins + spy_wins + ties
```

La UI debe mostrar “de N sesiones visibles/comparables”. Gaps de calendario no
consumen cupo; sesiones estimadas/interpoladas no entran en el denominador
comparable.

## Denominadores y reproducciones

| Caso | Evidencia de tests | Resultado |
|---|---|---|
| Observación diaria | `$192,31`, equity previa `70.807,69`, invertido `$8.041,72` | `0,27%` primario; `2,39%` secundario |
| Falso ganador | Sistema `0,27%`, exposición `2,39%`, SPY `0,50%` | SPY gana |
| Histórico | 39 filas sintéticas | No se deben publicar 39 al seleccionar 7 |
| Ventana contractual | 7 filas reales, 6 comparables y 1 pending | 6 = 2 Sistema + 2 SPY + 2 empates |
| Selector actual | 39 sesiones espaciadas cada 2 días, `days=7` | Devuelve 4 filas: días naturales, no 7 sesiones |
| Primer punto | Sin equity previa | importe/porcentaje `null`, nunca cero |
| Benchmark parcial | basis `unknown`, source/as_of ausentes | pendiente; no ganador |
| Missing | fila Sistema o SPY nula | conserva `null`; el lector actual no publica estado pending |

La cifra observada “13/17/0/9 de 39” no pudo trazarse en este árbol: no hay
`visible_days`, `system_wins`, `spy_wins` ni selector en
`_render_performance_baseline`; el selector existente pertenece a `Valor de
cartera`. Por tanto no se atribuye causalmente a este código. Sí queda
reproducido el riesgo equivalente: el selector de cartera usa días naturales y
puede devolver menos de siete sesiones reales cuando hay huecos XNYS.

## Tooltips y render declarativo

La inspección del spec Vega-Lite real de `_performance_baseline_chart` confirma
dos capas (línea y puntos), ambas con el mismo tooltip explícito y ordenado:
`Fecha`, `% ganancias` (`retorno_acumulado`, formato `+.2%`) y `Serie`. Ambas
usan el mismo campo Y y no contienen `y0`/`y1` ni tooltip automático en `mark`.
No hay capas auxiliares de banda/conector/corona en este gráfico. El punto
actual del gráfico de cartera es otro componente y no se mezcló con este
contrato.

## Validaciones ejecutadas

- `tests/test_p65a_daily_vs_spy_contract.py`: 12 passed.
- Focal P-L65A/P-L63/UI/performance/version: 111 passed.
- Ruff completo: `All checks passed!`; `check_no_nulls.py`: OK (439 archivos).
- `git diff --check`: OK; `py_compile`: OK; `validate-agent-config --json`
  temporal: `ok=true`, 0 errores y 0 warnings.
- El fichero prueba también la preservación del contrato P-L63 de cabecera y
  resultado negativo para una curva `71.550 → 70.700`, sin leer
  `trade_history.total_pl`.
- Pendientes/omitidos por XNYS abierto: suite completa, smoke, benchmark largo,
  run-once y validación cerrada.
- Pendientes de ejecutar en el cierre: focales UI/P-L46/P-L63 relacionadas,
  Ruff completo, `check_no_nulls.py`, `git diff --check`, `py_compile` y
  `validate-agent-config` temporal; se mantienen como gates de P-L65B/ensayo
  cerrado según corresponda.

## Seguridad y siguiente paso

No hubo broker, red, yfinance, LLM, SQLite productiva, jobs, postmarket,
reconciliación, despliegue, push ni cambios en `kernel.py`, `broker.py`,
`execution.py`, `risk.py`, `config.py` o `.env`. No se modificó ninguna decisión,
gate, sizing, plan, orden, stop, take, exposición o límite.

Siguiente lote único: `P-L65B`, implementación shadow/read-only de un rowset
diario canónico Sistema/SPY con autoridad de equity y benchmark, ventana por
sesiones XNYS, estados pending/unavailable y contadores cerrados; deberá
solicitar `performance_daily(readonly=True)` o una frontera equivalente y no
hacer llamadas adicionales al broker/red.

## Cierre Git

- Commit tests/version: `fe25d05f` (`test: characterize daily system versus
  SP500 contract`).
- Commit documentación: `aa75e286` (`docs: record P-L65A daily versus SP500
  contract`).
- HEAD final: `aa75e286a6c8a1c44f812582cbac2795b18f366b`.
- Tree final: `262fc6d9b0daba4e1aeb62b5e0aceeed48b4e576`.
- Árbol limpio al cierre; no push.
