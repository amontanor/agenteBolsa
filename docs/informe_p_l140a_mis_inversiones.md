# P-L140A — franja Mis inversiones (candidato Windows 0.4.242)

Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
push ni escritura productiva.

## Causa

La tarjeta global mostraba el % sobre equity total (`_today_pl_display`
ignora el invertido): con ~92% en cash, la rentabilidad real de las
acciones quedaba invisible. El operador no podia responder "son
rentables mis inversiones" con el Dashboard.

## Cambio (solo `web_app.py`, N1, sin trading ni broker nuevo)

- Nuevo helper puro `_invested_day_metric`: primario % sobre
  invertido, secundario % sobre equity etiquetado, importe, tono y
  cobertura `known/total`. Sin invertido o sin dato → `n/d`, nunca
  division por cero.
- Nueva franja "Mis inversiones" tras la tira de cuenta, con la misma
  fuente ya cargada por `page_dashboard`: Invertido (+% del equity),
  P/L dia sobre invertido, P/L total abiertas (mismo `_portfolio_open_pl`
  que la tarjeta del grafico), Cash.
- Bump `0.4.241` → `0.4.242`; pin `test_p59c` actualizado.

Sin llamadas broker nuevas, sin escrituras, sin cambios de trading,
config o contratos. Clases CSS reutilizadas.

## Commits (rama `codex/pl140a-mis-inversiones`, base `a6655e10`)

- `587f711e` test: 6 tests del helper (rojo por coleccion) + render
  headless AppTest.
- `e7244de2` feat + bump 0.4.242 + pin version (incluye fix de sintaxis
  del ternario y closure del AppTest).

## QA (XNYS cerrado)

- Focales: 7 passed (6 helper + 1 render headless con asserts
  `Mis inversiones`, `+1.00%`, `+0.07% sobre equity`).
- Regresiones: 128 passed con `test_web_app.py` + p59c.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (508 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa: pendiente de integracion conjunta.

## Siguiente paso

P-L140B (comparativa SPY unica + Leaderboard a Config) sobre esta rama
→ revision → `merge --no-ff` conjunto P-L130→P-L140 a `codex/astra` →
suite completa → port Jetson. Sin push.
