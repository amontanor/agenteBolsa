# P-L65A-R1 — caracterización del checkout UI real

## Dictamen provisional

`ready_for_p65b_implementation`, condicionado a que P-L65B se base en la
composición exacta **P-L63R1 + el parche dirty P-L61/P-L62 identificado aquí**.
Este lote no implementa esa composición ni copia el `src` dirty. La evidencia
reproduce el defecto de alcance y deja separado lo que ya está corregido en
P-L63R1.

## Estado y fuentes

- Fecha de auditoría: 28-jul-2026; XNYS abierto (apertura local 15:30 CEST,
  comprobada antes de actuar).
- Producción comprometida: HEAD
  `24537e813ff0905696cda0b3925a212045ee7b09`, tree
  `4747f27f3d5dc152410203bf089baee500440897`.
- Checkout productivo leído sin mutar: `C:\Antonio\Bref\agenteBolsa`, mismo
  HEAD/tree, versión dirty `0.4.187`.
- P-L63R1: HEAD `cdf2ce6ccfa818df7c3692ccb328a3e468f9a525`, tree
  `42b48b78867e7ffc9306ade86bcc1027aa32378c`.
- P-L65A: HEAD `24c3e56c5df84b99334039f70ca4d5c47dd140a8`, tree
  `34e45b80e8cc31fb16f4a407c49a4de895a242ec`, versión `0.4.199`.
- Worktree de este lote: `C:\Antonio\Bref\agenteBolsa_worktrees\pl65a_r1_actual_ui_characterization`.
- Rama: `codex/pl65a-r1-actual-ui-characterization`.

La producción dirty tenía, antes de este lote, estos cambios de usuario:

```text
M docs/plan_mejoras_y_tareas.md
M src/agente_bolsa/__init__.py
M src/agente_bolsa/web_app.py
M tests/test_web_app.py
?? .agents/skills/backtesting-frameworks/
?? .agents/skills/pandas-pro/
?? .opencode/
?? AGENTS.md
?? opencode.json
?? skills-lock.json
```

No se limpiaron, copiaron, stagearon ni modificaron.

## Identidad del objeto que produce la captura

Los hashes SHA-256 observados en el checkout dirty son:

| Objeto | SHA-256 dirty |
|---|---|
| `src/agente_bolsa/web_app.py` | `FC6ABAD9D799077D402866194A93D939657CC16CAC6943BC40B139A608D8205A` |
| `tests/test_web_app.py` | `9580147B3E0C8F0E264A1721AA95D13C5EFF3E14F75634517E25C1C551EA1E1B` |

P-L63R1 y P-L65A tienen los mismos hashes para esos dos archivos, porque
P-L63R1 no contiene el panel diario dirty:

| Base comprometida | `web_app.py` | `test_web_app.py` |
|---|---|---|
| P-L63R1/P-L65A | `33E5DE1F223080872F734CE389B8164409E99EDF4B29095E4164AC9BA1CC5FD1` | `9376DB04F4AB229DD3E2B3B7C4B013E63AD00F2099079600752B2B77FA859CB8` |

La diferencia no es una inferencia por nombre: en el dirty existen
`_fetch_spy_today_return`, `_spy_historical_returns`,
`_render_daily_vs_spy_table` y la llamada desde `page_dashboard`; en P-L63R1 y
P-L65A no existe `_render_daily_vs_spy_table` ni la key
`daily_vs_spy_days`.

## Matriz exacta de cambios

| Frontera | Producción HEAD | Dirty observado | P-L63R1/P-L65A |
|---|---|---|---|
| Panel diario Sistema/SP500 | ausente | añadido, aproximadamente 405 líneas de función + llamada de dashboard | ausente |
| Selector diario | ausente | `[7, 15, 30, None]`, key `daily_vs_spy_days` | ausente |
| Comparador | no aplica | prioriza `pnl_invested_pct`, fallback a equity | no aplica |
| SPY fallback | no aplica | yfinance intradiario/histórico sin `basis/source/as_of` en la fila | no aplica |
| P-L63 cartera | no aplica en el dirty diff | coexistente con modificaciones previas | equity series y `full_equity_summary` |
| Frescura P-L62 | ausente | `_latest_report_json` añade `generated_at` y helpers de edad | ausente en esta base |
| Tests dirty | no panel caracterizado | 34 líneas sobre rango de cartera; no fijan el panel diario | tests P-L65A del contrato comprometido |

El diff dirty completo frente a producción fue `525` líneas modificadas en
`web_app.py` (`510` añadidas, `15` eliminadas) y `34` añadidas en
`tests/test_web_app.py`. El diff incluye cambios UI previos además de P-L61 y
P-L62; por eso no se presenta el archivo dirty completo como implementación.
El bloque P-L61 que explica la captura está localizado en el working tree
observado entre `def _render_daily_vs_spy_table` y la llamada de dashboard
(aprox. líneas 2844–3202 y 4343–4351 del archivo dirty en esta lectura).
P-L62 está en `_latest_report_json` y `_report_age_text/_report_age_days`
(aprox. líneas 704–753 del diff respecto a HEAD).

## Reproducción exacta del alcance dirty

Las pruebas de este worktree conservan un fragmento textual mínimo del
productor observado y lo ejercitan con fixtures puras:

1. Con 39 filas: 13 ganadoras del Sistema, 17 de SP500, 0 empates y 9
   pendientes. El dirty calcula contadores antes del recorte y publica
   `13/17/0/9 de 39` aunque el selector esté en 7; solo `body` se recorta a
   siete filas.
2. Con delta de equity `$192,31`, equity previa aproximada `$70.807,69` y
   capital invertido previo `$8.041,72`, la UI obtiene `0,27%` sobre equity y
   `2,39%` sobre invertido. El dirty usa `pnl_invested_pct` como comparador y
   puede declarar ganador al Sistema frente a SP500 `+0,50%`, aunque la
   comparación canónica de equity daría ganador al SP500.
3. La fila live calcula `live_dollar / prev_invested`; no es el retorno de la
   cuenta sobre `previous_equity`.
4. La tabla usa `body[:visible_days]`, mientras el gráfico recorta
   `chart_rows[-visible_days:]` después de insertar filas de hueco. Con huecos
   el mismo selector no representa el mismo rowset.
5. Filas `interpolated` y SPY `partial` siguen entrando en el comparador si
   tienen números; no se convierten en `pending` por calidad.
6. Las capas auxiliares crean campos `y0/y1`; las líneas tienen tooltip
   `Retorno`, pero la capa `points` no declara tooltip explícito. El spec dirty
   deja abierta la ruta de hover raw y no implementa una etiqueta homogénea de
   `% ganancias` para ambas capas.
7. El subtítulo promete una “línea secundaria” de equity, pero la fila del
   gráfico solo contiene `Sistema` y `SP500`; no existe una serie secundaria
   diferenciada.
8. El lector llama `store.performance_daily(limit=0)` sin expresar
   `readonly=True`. El contrato de caracterización debe exigir una lectura
   read-only explícita donde la API lo soporte.

## Contrato cerrado para P-L65B

- La composición de implementación debe partir de P-L63R1/P-L65A y añadir el
  panel P-L61/P-L62 solo tras resolver sus conflictos; no se puede implementar
  P-L65B sobre P-L63R1 como si ya contuviera la captura.
- Un único rowset visible, ordenado por sesión XNYS real, alimenta tabla,
  gráfico, tarjetas, fechas y contadores.
- Métrica primaria: variación de equity contra cierre anterior, con importe y
  porcentaje sobre equity previa. La exposición-normalizada es secundaria,
  etiquetada y nunca decide Sistema frente a SP500.
- `estimated`, `interpolated`, `partial`, `stale` o `source-mismatch` son
  `pending`; no ganan y no consumen el cupo de sesiones comparables.
- `visible_total = comparable + pending` y
  `comparable = system_wins + spy_wins + ties`, por ventana visible.
- El selector debe incluir las ventanas requeridas por el producto (incluido
  7 días) sin traducir “Desde inicio” a 30 ni mezclar días naturales con el
  cupo de sesiones XNYS.
- Las capas auxiliares no tienen tooltip. Líneas y puntos de Sistema/SP500
  comparten campo, título `% ganancias`, formato `+.2%`, fecha y serie.
- La fuente de SPY debe declarar `source`, `price_basis`, `as_of`, calidad y
  frescura; fallback sin esos campos queda pending/unavailable.
- La UI debe conservar la lectura Store read-only y no hacer llamadas broker o
  red durante la presentación.

## Validación y límites

Ejecutar en este worktree solo pruebas focales y gates estáticos seguros,
usando DATA_DIR temporal. Con XNYS abierto se omiten suite completa, smoke,
benchmark largo, jobs, broker, red, yfinance y SQLite productiva. No se toca
trading, riesgo, ejecución, configuración, locks/leases ni producción.

Resultado de esta caracterización: `22 passed` (P-L65A + P-L65A-R1), Ruff,
`check_no_nulls.py`, `git diff --check` y `py_compile` verdes. El test de
`version policy` detecta correctamente que añadir un archivo bajo `tests/`
exigiría cambiar `__version__`; no se hace ese bump en este lote porque
`0.4.200` está reservado explícitamente para P-L65B. Por tanto esta rama es
evidencia de caracterización, no un candidato publicable; P-L65B deberá resolver
el bump al implementar.

El siguiente lote único es P-L65B: implementar esta composición exacta en un
worktree nuevo, con versión reservada `0.4.200` y validación cerrada posterior.
