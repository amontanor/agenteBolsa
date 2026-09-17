# P-L140B — comparativa SPY unica y leaderboard a Config (candidato Windows 0.4.243)

Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
push ni escritura productiva.

## Causa

Tres respuestas distintas a "supero al SP500" (tabla apertura→apertura,
baseline acumulado del expander, contadores de sesiones) y un bloque de
leaderboard con escritura publica en mitad del flujo diario.

## Cambio (solo `web_app.py`, N1, sin trading ni broker nuevo)

- Nuevo `_spy_alpha_summary` puro: compone geometricamente solo filas
  `final` + `comparable` con ambos porcentajes; sin filas, todo None.
  Quinta metrica "Alpha acumulado" junto a los contadores, misma
  ventana y serie que la tabla.
- Leaderboard fuera del Dashboard: `page_config` lo renderiza con la
  ganancia que el Dashboard deja en `st.session_state` (cero llamadas
  nuevas); sin visita previa el envio queda deshabilitado con caption
  honesto. Funcionalidad intacta.
- Baseline duplicado retirado del expander (llamada + 3 funciones
  muertas, ~90 lineas menos). `profitability_scoreboard` se conserva.
- Bump `0.4.242` → `0.4.243`; pin `test_p59c` actualizado.

Sin broker nuevo, sin escrituras nuevas, sin trading/config.

## Commits (rama `codex/pl140b-spy-leaderboard`, base `66103e2f`)

- `3664038e` test: 5 tests (rojo por coleccion).
- `10dcd62b` feat + bump 0.4.243 + pin version (incluye fix API
  AppTest `button().disabled` y limpieza de imports).

## QA (XNYS cerrado)

- Focales: 5 passed (+2 renders headless de leaderboard).
- Regresiones: 134 passed con p140a + `test_web_app.py` + p59c.
- `ruff check src tests`: All checks passed (2 auto-fix de imports,
  re-verificado).
- `scripts/check_no_nulls.py`: OK (509 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa: pendiente de integracion conjunta.

## Siguiente paso

Revision → `merge --no-ff` conjunto P-L130→P-L140 a `codex/astra` →
suite completa → verificado visual con el operador → port Jetson.
Sin push.
