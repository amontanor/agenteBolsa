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
- El registro documental se consolidó en `aa75e286`; el HEAD/tree final del
  worktree se entrega en el dictamen de este lote.
- Árbol limpio al cierre; no push.

## P-L65B — implementación aislada de composición coherente (28-jul-2026)

### Dictamen

`ready_for_integration_rehearsal`.

La implementación queda limitada a presentación read-only en el worktree
aislado. El panel diario ya no reproduce la semántica dirty de P-L61: usa el
contrato persistido `p-l40b.performance-benchmark.v1`, una fila canónica por
sesión y un único recorte visible compartido por contadores, tabla y gráfico.
No es autorización de merge productivo ni despliegue.

### Referencias y seguridad

- Base exacta: P-L65A-R1 `53b49f71e3acedd9b5ed73f80ff8cb793221df8`, tree
  `2b82824f60756c06a3dad40b05740810c0a1180c`, versión `0.4.199`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl65b_daily_vs_spy_consistency`.
- Rama: `codex/pl65b-daily-vs-spy-consistency`.
- Candidato: versión `0.4.200`.
- Producción comprometida y checkout dirty permanecen sin modificar; no se
  copió ni se integró manualmente `web_app.py` dirty. P-L61 se caracterizó a
  través del diff/hashes documentados en P-L65A-R1 y se reconstruyó el contrato
  sobre P-L63R1.
- XNYS estaba abierto al trabajar. No se ejecutaron suite completa, smoke,
  benchmark largo, broker, red, yfinance, LLM, SQLite productiva, jobs,
  postmarket, reconciliación, despliegue o push.

### Correcciones realizadas

1. `_canonical_daily_vs_spy_row` exige equity y `previous_equity` explícitos;
   SPY se calcula solo con `previous_close` y `close`, ambos positivos. Las
   columnas legacy `pnl_pct`/`spy_pct` no pueden promover una fila a comparable.
2. `source`, `price_basis`, `generated_at`/`captured_at`, `as_of`,
   `consumer_read_at`, `freshness_status` y `freshness_age_seconds` se
   conservan separados. `available` + basis conocido + timestamps válidos son
   necesarios para ganar. `partial`, `stale`, interpolated, missing, futuro o
   mismatch quedan `pending` con `reason_codes`.
3. La freshness histórica se mide respecto a `as_of` y al momento de captura,
   no como antigüedad frente al momento actual del dashboard. Así una fila
   cerrada antigua no queda artificialmente stale solo por pertenecer a una
   ventana de 90 días; una captura tardía respecto a su benchmark sí queda
   pendiente.
4. La métrica primaria es `equity_delta / previous_equity`. La equivalencia
   sobre exposición, cuando existe `avg_exposure`, es secundaria y no entra en
   `winner`. La UI declara `Variación de equity contra SPY comparable; sin
   ajustes de flujos`.
5. `_daily_vs_spy_window` toma las últimas N sesiones canónicas, no N días
   naturales ni filas de gaps/interpolación. `visible_total` se calcula después
   del recorte: `visible_total = comparable + pending` y
   `comparable = system_wins + spy_wins + ties`.
6. El panel utiliza una única lectura `store.performance_daily(limit=0,
   readonly=True)`. No añade llamadas al broker, red ni fuentes fallback.
7. Línea y puntos del panel diario comparten el campo `retorno` con tooltip
   `Fecha`, `% ganancias`, `Serie` y formato `+.2%`. Fondos, conectores y cero
   no tienen tooltip. El campo se mantiene decimal; no se multiplica por 100.
8. P-L63R1 se preserva: el baseline de abril, Resultado del periodo, cabecera,
   P/L hoy y P/L abierto siguen usando sus contratos separados; el nuevo panel
   no lee `trade_history.total_pl` ni suma P/L abierto/hoy al equity.

### Causa reproducida y denominadores

La captura dirty mostraba `13/17/0/9 de 39` con selector 7 porque P-L61
calculaba el total antes de recortar `body[:visible_days]` y después aplicaba un
recorte diferente (`chart_rows[-visible_days:]`) tras insertar gaps. Además,
usaba la equivalencia sobre invertido para `cmp_pct`, permitía filas
interpoladas/partial y dejaba tooltip automático en puntos. P-L65B no reutiliza
ninguno de esos contadores: reconstruye la población desde el contrato
persistido y cuenta únicamente el rowset visible.

| Denominador/estado | Contrato P-L65B |
|---|---|
| sesiones canónicas de entrada | una por `session_date`, deduplicada de forma estable |
| ventana | 7, 15, 30, 90 o `Desde inicio`; huecos no consumen cupo |
| comparables | filas con equity/SPY completos, basis/source/timestamps/calidad válidos |
| pendientes | `partial`, `stale`, missing, interpolated, future o mismatch; no son cero |
| Sistema superior/SP500 superior/empate | solo comparables de la ventana visible |
| exposición-normalizada | secundaria descriptiva; nunca ganador |
| flujo neutralizado | unavailable sin ledger exacto; copy es variación de equity |

La fixture de aceptación usa `equity 71.550 -> 70.700` con agregado de trades
`+106,83`: el resultado de equity permanece `-850,00` y tono negativo, nunca
`+106,83` ni verde. La fixture de `$192,31`, equity previa `70.807,69` e
invertido `$8.041,72` conserva aproximadamente `+0,27%` primario frente a
`+2,39%` descriptivo; con SPY `+0,50%`, gana SPY.

### QA ejecutada y gates omitidos

- Focal integrado P-L65/P-L63/P-L46/UI/performance: `128 passed`.
- Incluye selector/rowset, 39→7, ventanas 7/15/30/90/Desde inicio, gaps,
  deduplicación/orden, dos cierres SPY, basis/source/as_of/freshness,
  pending, falsa victoria normalizada, tooltips de línea/punto y ausencia de
  tooltip en capas auxiliares.
- Ruff focal: `All checks passed`; `py_compile`: OK; `git diff --check`: OK.
- `scripts/check_no_nulls.py`, `validate-agent-config --json` y version policy
  aislados quedan pendientes de ejecutar antes del ensayo cerrado; no se
  ejecutó suite completa ni smoke por XNYS abierto.
- No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
  `config.py` ni `.env`; no cambian trading, señales, ranking, gates, sizing,
  planes, órdenes, riesgo, exposición, scheduler o persistencia.

### Commits

- `8d4deca6` — `feat: add coherent daily system spy UI`.
- `0cb872a9` — `test: verify daily system spy consistency`.
- `02aee0c9` — `test: add daily system spy parity QA`.
- Documentación P-L65B y registro maestro/relevo: commit separado posterior.

Siguiente lote único: ensayo combinado aislado con P-L63/P-L65B y la referencia
P-L66, verificando primero XNYS cerrado y todas las precondiciones de validación
cerrada. P-L66 no se integra en este lote.
