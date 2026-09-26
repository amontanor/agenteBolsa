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

---

## Re-add P-L140B-R (candidato 0.4.320, 26-sep-2026)

Dictamen: `ready_for_integration_rehearsal` (N1 UI, solo presentacion).
XNYS cerrado 2026-09-26; next_open 2026-09-28 15:30 Europe/Madrid.
Worktree exclusivo `pl140b_readd_0320`, rama `codex/pl140b-readd-0320`,
base exacta P-L140A-R docs-corrected `49f3b19f`/tree `041b4bbc`/v0.4.319.
Sin merge, despliegue, reinicio, push ni escritura productiva.

### Causa (reproducida contra la base)

- La reconstruccion `784e6cd7` retiro P-L140B y dejo
  `tests/test_p140b_spy_unico.py` con ImportError:
  `cannot import name '_spy_alpha_summary' from 'agente_bolsa.web_app'`
  (coleccion: 1 error, 0 tests).
- `tests/test_p65a_daily_vs_spy_contract.py::test_spy_comparison_has_single_surface_without_baseline_renderer`
  falla en base: `page_dashboard` todavia invoca
  `_render_performance_baseline(store)` (segunda superficie SPY).
- Referencia historica solo para contrato/diff campo a campo, sin
  cherry-pick: candidato `1b29df23`, feat `10dcd62b`, este informe.

### Cambio (solo `src/agente_bolsa/web_app.py`, +53/-6)

- Nuevo `_spy_alpha_summary` puro (verbatim historico): solo filas
  `final` + `comparable` con ambos porcentajes via `_num`;
  composicion geometrica; sin filas comparables todo `None`
  (`{"n": 0, "system_cum": None, "spy_cum": None, "alpha": None}`).
  Alpha solo si ambos retornos son comparables en la misma ventana;
  missing/conflict/stale quedan `unavailable`/`n/d`, nunca cero.
- Quinta metrica "Alpha acumulado" en `_render_daily_vs_spy_table`
  (4 → 5 columnas) con `_pct_signed_or_na` y tono por signo;
  misma ventana y serie que la tabla.
- Leaderboard fuera del Dashboard: `page_dashboard` guarda
  `st.session_state["leaderboard_total_pct"] = account_total_pct`
  y ya no renderiza el bloque (ni su timer `kpis.leaderboard`);
  `page_config` lo renderiza al final via
  `st.session_state.get("leaderboard_total_pct")` con caption
  honesto. Solo cambia ubicacion/estado UI: sin mutar autoridad,
  datos, ranking ni llamadas (cero broker/red nuevas).
- Baseline duplicado sin render: retirada la llamada
  `_render_performance_baseline(store)` del expander "Rendimiento
  avanzado" (comentario P-L140B); `profitability_scoreboard` se
  conserva. Divergencia documentada respecto al historico: las 3
  funciones baseline (`_performance_baseline_series`,
  `_performance_baseline_chart`, `_render_performance_baseline`) se
  conservan sin tocar para preservar el contrato P-L140C y los
  imports de `test_p65a_daily_vs_spy_contract.py`; solo la llamada
  muere, y el guard de superficie unica pasa.
- Sin P-L139, scoreboard, politica, persistencia, fuente nueva ni
  llamadas broker/red. P-L140A (`_invested_day_metric`,
  `_investments_group`), P-L137, P-L133 y timers P-L158 intactos
  (solo cae el sub-timer del leaderboard movido).

### Commits conocidos (rama `codex/pl140b-readd-0320`)

- `cb2f6808` feat: re-add alpha SPY unico, leaderboard a Config,
  baseline sin render (P-L140B, N1 UI).
- `2a88081f` test: pin version policy P-L59C a 0.4.320 (P-L140B-R).
- Bump `0.4.319` → `0.4.320` + pin `test_p59c` actualizado
  (slot 0.4.320 verificado libre en plan). HEAD/tree finales del
  commit documental en la entrega a `direccion` (este informe no
  autorreferencia su propio hash final).

### QA (XNYS cerrado, Python del proyecto, `PYTHONPATH=<worktree>/src`)

- Causa reproducida en base antes del fix (ImportError + guard rojo).
- Focales lote: `tests/test_p140b_spy_unico.py` +
  `tests/test_p65a_daily_vs_spy_contract.py`: 17 passed.
- Combinada: + `test_p59c_llm_selected_authority.py` +
  `test_p140a_mis_inversiones.py` + `test_web_app.py`: 147 passed.
- Regresiones: `test_p152_dashboard_today.py` +
  `test_p153_spy_authority.py` + `test_p158a_dashboard_timing.py` +
  `test_p158b_dashboard_perf.py` + `test_version_policy.py` +
  `test_p140a_mis_inversiones.py`: 37 passed (baterias solapadas
  declaradas, no sumadas como pruebas unicas).
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (536 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Protegidos (`kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`): sin diff.
- Gates omitidos: suite completa, smoke, benchmark, kernel-status,
  integracion final. Sin broker/red/LLM/yfinance, sin SQLite
  productiva, sin servicios/locks/leases, sin merge/deploy/push.
- `page_dashboard` verificado por fuente: contiene
  `_render_daily_vs_spy_table` y `leaderboard_total_pct`; no
  contiene `_render_performance_baseline` ni
  `_render_leaderboard_controls`.

### Siguiente paso

Ensayo combinado de integracion con P-L140A-R (y P-L133/P-L137)
en mercado cerrado; despues validacion cerrada completa. Sin
merge a principal, despliegue ni push. Produccion Jetson 0.4.316
y principal intactos.
