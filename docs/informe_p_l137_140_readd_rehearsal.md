# Ensayo combinado P-L137-R + P-L133-R + P-L140A-R + P-L140B-R (rehearsal 0.4.320, 26-sep-2026)

Dictamen: `ready_for_closed_market_full_validation` (ensayo de
integracion aislado, N2/N1, sin validacion completa ni despliegue).
XNYS cerrado 2026-09-26 16:09 Europe/Madrid (`is_open=false`);
`next_open` 2026-09-28 15:30 Europe/Madrid. Sin suite completa,
smoke, benchmark, produccion, SSH, servicios ni despliegue en este
lote. Sin broker/red/LLM/yfinance, sin SQLite productiva, sin
locks/leases, sin push.

## Base, candidato y merge exactos

- Base: P-L158-B rehearsal/deploy source `85e28447ce65c26beb58702896d28b31ce1f1ad9`,
  tree `70d487e700d4f5eaa5b2d916af23671b9ab7ed84`, v0.4.316.
- Candidato extremo exacto: `0998087599eeb4472e2668142871d5a5ac9bc61b`,
  tree `00e5bdeadf1a7d6cd9340e76fbd9b136c3583412`, v0.4.320, rama
  `codex/pl140b-readd-0320`. Su cadena contiene P-L137 (`26f144fa`),
  P-L133 (`baba2dd9`), P-L140A docs-corrected (`49f3b19f`) y P-L140B.
- Worktree NUEVO exclusivo
  `C:\Antonio\Bref\agenteBolsa_worktrees\pl137_140_readd_rehearsal`,
  rama `codex/pl137-140-readd-rehearsal`, creado desde la base exacta.
- Merge `git merge --no-ff` del candidato exacto sobre la base, sin
  squash/rebase/cherry-pick/amend, sin conflictos (merge limpio por
  ser el candidato descendiente directo de la base):
  `338136fa2e681157787d864edae4ce2bd26c77a9`, parents
  `85e28447ce65c26beb58702896d28b31ce1f1ad9` (P1, base) +
  `0998087599eeb4472e2668142871d5a5ac9bc61b` (P2, candidato).
- Tree del merge `00e5bdeadf1a7d6cd9340e76fbd9b136c3583412`,
  identico al tree del candidato (`git diff HEAD <candidato>`
  vacio): equivalencia funcional exacta salvo la documentacion de
  rehearsal posterior (este informe + entradas de plan/relevo; este
  informe no autorreferencia su propio hash final).
- Alcance: integracion y QA focal/relacionada proporcional. Cero
  cambios en `src`/`tests`/version en este lote (el defecto
  reproducible no aparecio; no se amplio el alcance).
- Protegidos (`kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`): sin diff base→merge.

## Contenido integrado (verificado por fuente en el merge)

- P-L137 (N2): `trim_to_completed_sessions` +
  `last_completed_session` en `tools/signal_learning.py`; recorte
  antes del bucle de outcomes (`update_signal_outcomes` publica
  `bars_trimmed_universe`/`last_completed_session`/
  `session_seal_degraded`).
- P-L133 (N2): `scheduler_skip_summary` +
  `signal_outcome_emptiness` en `tools/operational_health.py`;
  wiring health fail-open (`except Exception` → `unavailable`), sin
  alertas nuevas; `pct_empty=None` con denominador 0, excepciones
  `unavailable`.
- P-L140A (N1): `_invested_day_metric` + `_investments_group` en
  `web_app.py` (4 tarjetas Mis inversiones, misma fuente/
  denominador que exposure/cartera/cash ya cargados, solo lectura).
- P-L140B (N1): `_spy_alpha_summary` puro (filas `final` +
  `comparable`, composicion geometrica, `None` sin filas, nunca
  cero); leaderboard movido a Config via `session_state`
  (`leaderboard_total_pct`); baseline duplicado deja de
  renderizarse (`_render_performance_baseline` definido pero sin
  llamadas en `page_dashboard`); helpers baseline conservados por
  contrato P-L140C.
- Timers P-L158 (`dashboard_timing`/`total_seconds`) intactos en
  `web_app.py`. Denominadores missing/`unavailable` intactos (sin
  ceros inventados). Paridad de trading, riesgo y ejecucion:
  ningun lote toca la ruta activa (cambios observacionales/UI
  read-only + version/pins).

## QA minima (Python del proyecto, `PYTHONPATH=<worktree>/src`)

- Bateria combinada minima del encargo (12 ficheros, una sola
  ejecucion, baterias solapadas declaradas, no sumadas como
  pruebas unicas):
  `tests/test_p137_session_seals.py` +
  `tests/test_p133_misfire_health.py` +
  `tests/test_p140a_mis_inversiones.py` +
  `tests/test_p140b_spy_unico.py` +
  `tests/test_p65a_daily_vs_spy_contract.py` +
  `tests/test_p65a_r1_actual_ui_characterization.py` +
  `tests/test_p158a_dashboard_timing.py` +
  `tests/test_p158b_dashboard_perf.py` +
  `tests/test_operational_health.py` + `tests/test_web_app.py` +
  `tests/test_p59c_llm_selected_authority.py` +
  `tests/test_version_policy.py`: **186 passed en 24.66 s**,
  cero skips/xfails nuevos.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (536 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Gates omitidos: suite completa, smoke, benchmark, kernel-status,
  validacion cerrada completa, despliegue, doble salud. Sin
  broker/red/LLM/yfinance, sin SQLite productiva, sin
  servicios/locks/leases, sin reinicio, sin push.

## Siguiente paso minimo (sin ejecutar)

Una sola validacion completa del arbol funcional definitivo
(`00e5bdeadf1a7d6cd9340e76fbd9b136c3583412`) con XNYS cerrado y
precondiciones frescas (postmarket terminal, leases vacios,
paper/live/auto-apply, kernel, configuracion, margen). Despliegue
solo con evidencia final suficiente y autorizacion explicita del
operador transmitida por `direccion`. Principal (`c0b6578e`) y
produccion Jetson 0.4.316 intactos.
