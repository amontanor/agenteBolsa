# P-L79 — tabla de configuración Streamlit segura para PyArrow

## Dictamen

`ready_for_pl79_closed_market_integration`.

La causa reproducida era la entrega directa de un `DataFrame` cuya columna
`valor` mezclaba `str`, `bool`, `int`, `float`, `Path`, secuencias y `None`.
La frontera de presentación ahora convierte cada valor a texto explícito antes
de llamar a `st.dataframe`; no cambia Settings, inputs, guardado ni ninguna
decisión económica.

## Alcance y referencias

- Fecha de ejecución: 2026-08-01, Europe/Madrid; XNYS cerrado, siguiente
  apertura prevista 2026-08-03 15:30 CEST.
- Base exacta: `5e0f41e218a127be070601ba1ebe77d9b591e8a7`, tree
  `d00abe9cb1a423311689e89c12ddda810957e5a1`, versión `0.4.213`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl79_arrow_safe_config_table`.
- Rama: `codex/pl79-arrow-safe-config-table`.
- Producción observada: `ba7d488de5ddb2f0b1174b22ff676e5abba1ac1d`, tree
  `6938d15799c39d760035e1afc8294f614ece0b04`, versión `0.4.211`, tracked
  limpia. Sus untracked del operador permanecen fuera del lote.
- P-L78D y su bloqueo independiente `.env`/kernel no se modifican ni se
  resuelven en P-L79.

## Reproducción y corrección

La caracterización `02fd1f41` construyó la forma real de la tabla y confirmó
que `pyarrow.Table.from_pandas(..., preserve_index=False)` falla con una
`ArrowException` por la columna heterogénea `valor`. Contra la base, cuatro
pruebas de contrato fallaron porque no existía la frontera normalizada; la
prueba de reproducción pasó.

`_config_value_for_display()` aplica reglas deterministas: `true`/`false` para
booleanos, `str()` estable para enteros y floats (incluido `0` y `0.0`), texto
para `Path`, URL y strings, unión legible para listas/tuplas y `n/d` para
`None` o clave ausente. `_config_display_dataframe()` conserva el orden,
`clave`/`valor` y construye solo una vista textual. La tabla no usa
`astype(str)` ciego y no muta las filas ni el objeto Settings.

`page_config()` conserva exactamente el conjunto de claves visible, el copy,
el ancho y `hide_index`; solo cambia `pd.DataFrame(rows)` por
`_config_display_dataframe(rows)`. No se cambió `_safe_streamlit_dataframe`,
no se suprimieron warnings y no se añadió fallback HTML.

## Commits

1. `02fd1f41` — caracterización PyArrow y no mutación.
2. `835ba68d` — helper de presentación, uso en `page_config()` y bump a
   `0.4.214`.
3. `52097d7e` — formato Ruff del test de caracterización.
4. `c6fbacab` — actualización determinista de la expectativa de version policy
   a `0.4.214`.
5. Commit documental pendiente al cerrar este informe.

## QA

- P-L79 + `test_web_app.py` + router/version policy: `95 passed`.
- P-L78B/P-L78C: `19 passed`.
- Flujo de ciclo con fakes como sustituto seguro del smoke operativo:
  `tests/test_market_cycle_timing_integration.py` y
  `tests/test_market_cycle_timing.py`, `22 passed`. No se ejecutó una ruta CLI
  real que pudiera adquirir datos de mercado; no hubo red, broker ni LLM.
- Suite canónica aislada: `2385 passed, 1 skipped, 1 warning` en `800.71 s`.
  El skip es preexistente:
  `tests/test_pre_earnings.py::test_score_study_regression_current_sqlite`,
  condicionado a la SQLite histórica local. La warning es la deprecación
  externa `websockets.legacy`.
- Ruff completo: OK.
- `scripts/check_no_nulls.py`: OK, 465 archivos.
- Compilación de `src`, `tests` y `scripts` con caché temporal: OK.
- `git diff --check`: OK.
- `validate-agent-config --json` con `DATA_DIR` temporal: `ok=true`, sin
  errores ni warnings.
- `kernel-status --json` temporal: `unsealed` esperado por ausencia de
  manifiesto temporal, cero violaciones; no se ejecutó `kernel-seal`.
- La prueba directa de la tabla final vuelve a pasar por
  `pyarrow.Table.from_pandas` sin excepción y verifica que todos los valores
  son `str`.

## Paridad y seguridad

El diff funcional se limita a `web_app.py` y la versión; el resto del lote es
test/documentación. `kernel.py`, `tools/broker.py`, `tools/execution.py`,
`tools/risk.py`, `config.py` y `.env` permanecen idénticos a la base por objeto
Git. No cambian candidatos, scores, ranks, gates, sizing, RiskManager, planes,
precios, stops/takes, órdenes, exposición, límites, persistencia ni scheduler.

No se tocó producción, SQLite productiva, `.env`, manifest, stack, procesos,
locks, leases ni servicios. No hubo broker, red, yfinance, LLM, Telegram,
postmarket, reconciliación, despliegue, reinicio ni push. El bloqueo separado
de procedencia `.env`/kernel de P-L78 continúa pendiente y no queda resuelto
por este candidato.

## Siguiente paso único

Revisar el árbol limpio y ejecutar el ensayo de integración cerrado de P-L79
sobre el candidato exacto mediante `merge --no-ff`; no integrar ni desplegar
desde este worktree sin resolver antes, por su lote propio, el bloqueo
`.env`/kernel de P-L78.
