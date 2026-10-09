# Informe N2 — TypeError por P/L no disponible en postmercado

Fecha de revisión: 2026-10-09. El trabajo se hizo en el worktree aislado
`C:\Users\utopi\.codex\worktrees\oct09-postmarket-null\agenteBolsa`, partiendo de
`7d4f4bc1f54d45fca9f6cc62867f4ddf9b6d80a1` (versión `0.4.352`).

## Dictamen y causa

La causa queda confirmada con confianza alta por evidencia del snapshot y una
reproducción determinista contra la base. `trade_history._daily_groups` deja
`open_unrealized_pl=None` cuando no hay posiciones abiertas. En
`tools/post_market_review.py:_learning_candidates`, la base asignaba ese valor
con `.get(..., 0.0)` y después ejecutaba `unrealized < 0`. El valor explícito
`None` no activa el valor por defecto y producía exactamente:

```text
TypeError: '<' not supported between instances of 'NoneType' and 'int'
```

El snapshot `C:\Users\utopi\.codex\worktrees\ef99\agenteBolsa\audit_oct09_results.json`
registra para `post_market_coordination:session:2026-10-08` el run
`pmr_c4fa3d6cfb6d`, terminado a `2026-10-08T22:25:38.101977+00:00`, con
`reason=stage_postmarket_report_failed`; su evento
`post_market_review_failed` contiene el mismo error literal. La consulta SSH
autorizada y acotada a Docker entre `22:24:00Z` y `22:27:00Z` no devolvió líneas,
por lo que no se afirma un traceback remoto adicional: los logs están ausentes
o rotados.

La reproducción base, sin broker ni red, fue:

```text
PYTHONPATH=<worktree>\src
C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -c \
  "..._learning_candidates([], {'realized_pl': 0.0, 'open_unrealized_pl': None}, ...)"
```

Falla en la línea 357 de la base. La prueba de caracterización se guardó en
`b1d5169d`; antes del arreglo devolvió dos fallos esperados: `None` levantaba
el TypeError y `-inf` generaba una recomendación espuria.

## Cambio mínimo

Se añadió `_metric_number`, que acepta números finitos, descarta `None`,
booleanos, valores no numéricos y no finitos, y deja los datos no disponibles
como `None`. La recomendación `add_entry_quality_filters` solo se evalúa cuando
alguno de los dos P/L es numéricamente negativo. Los negativos válidos siguen
produciendo la misma recomendación; no se imputan ceros ni se alteran históricos,
órdenes, ejecución o aprendizaje. La versión se reservó en `0.4.354`, dejando
libre la `.353` del otro worker.

## Verificación focal

Después del arreglo, el mismo comando de reproducción devuelve `[]`. Con
`DATA_DIR` temporal, `_env_file=None` por la configuración de los tests,
`PYTHONPATH` del worktree y sin proveedores externos:

```text
python -m pytest tests/test_post_market_review.py tests/test_p57a_null_safety.py -q
23 passed
python -m ruff check src/agente_bolsa/tools/post_market_review.py tests/test_post_market_review.py
All checks passed!
git diff --check                         OK
auditoría de NUL en archivos tocados   NUL_OK
```

La matriz cubre P/L válido negativo, `None`, booleanos, `NaN`, `+inf` y `-inf`
en `realized_pl` y `open_unrealized_pl`, además de conservar las regresiones
P-L57A existentes.

## Gates y entrega

XNYS estaba abierto durante esta intervención. Por esa condición se limitaron
las acciones a lectura, caracterización, edición, tests focales y documentación.
No se ejecutaron fullsuite, smoke, build, producción, broker, red, LLM,
órdenes, locks, configuración ni archivos protegidos. No hubo merge ni push.

Commits separados:

- `b1d5169d` — caracterización reproducible.
- `b4ddf194` — arreglo mínimo y versión `.354`.
- commit posterior de documentación — este informe y el relevo.

La entrega debe registrar con `git rev-parse HEAD`, `git write-tree` y
`git status --short` el HEAD/tree/status del checkout final. El estado esperado
es limpio después del commit documental.
