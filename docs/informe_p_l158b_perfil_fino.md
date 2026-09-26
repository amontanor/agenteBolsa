# P-L158-B — perfil fino de observación del dashboard (candidato 0.4.316)

## Dictamen

`ready_for_integration_rehearsal` (N1: solo observación). No desplegar por mi
cuenta; el siguiente paso exige XNYS cerrado + postmarket terminal + autorización
explícita del operador.

Estado tras el rehearsal del 25-sep-2026 (ver sección "Rehearsal de integracion"):
merge `--no-ff` verificado en worktree aislado (`7ad1d2e9`, tree `69be2dc5`,
parents `708f0e46`/`17cf9de1`, v0.4.316, QA verde) -> dictamen
`ready_for_closed_market_full_validation`, **sin desplegar**.

## Causa

El temporizador P-L158-A (producción 0.4.315) agrupa en una única sección
`opening_context` cinco llamadas con distinto coste, y su `total_seconds` suma
la sección envolvente `total` (que ya contiene todo el script) junto a las
parciales, duplicando el tiempo real (~125 s frente a ~62 s). Este lote:
(1) abre sub-secciones por función dentro de `opening_context`, `setup` y
`kpis`; (2) corrige `total_seconds` para no sumar `total`.

## Hechos (verificados)

- XNYS **cerrado** 2026-09-25 13:51 Madrid: `schedule-status` -> `is_open=false`,
  `next_open=2026-09-25T15:30:00+02:00`. Trabajo aislado, sin red/broker/LLM.
- Principal `C:\Antonio\Bref\agenteBolsa`: HEAD `a0b18d66`, tree `184e7f27`,
  v0.4.253, árbol sucio preexistente (AGENTS.md, plan, `estudio_dashboard_*`,
  untracked). **No tocado.**
- Candidato timer grueso `pl158a_dashboard_timing`: HEAD `708f0e46`, tree
  `585a7557`, limpio. **No tocado.**
- Producción Jetson: imagen `agente-bolsa:0.4.315-arm64`, sana. **No tocada.**
- Worktree propio `pl158b_dashboard_perf`, rama `codex/pl158b-dashboard-perf`:
  base `708f0e46` (tree `585a7557`), HEAD `2bd92f4b`, tree `9f9363c2`,
  v0.4.316, árbol limpio salvo commits propios.

## Cambio

`src/agente_bolsa/web_app.py` (solo medición con `_DashboardTimer`, sin tocar
lógica, trading, riesgo, UI, caché ni firmas):

- `emit()`: `total_seconds = sections["total"]` si existe la sección envolvente;
  en su defecto, suma de las secciones distintas de `total`. Fórmula documentada
  en `tests/test_p158b_dashboard_perf.py`.
- `setup` sub-secciones: `setup.cached_latest_events`,
  `setup.latest_ci_llm_result`. Refactor equivalente: la llamada compuesta
  `_latest_ci_llm_result(_cached_latest_events(store, 400))` se parte en dos
  sentencias con variable intermedia `latest_events` (semántica idéntica).
- `opening_context` sub-secciones: `opening_context.opening_performance_context`,
  `opening_context.daily_equity_metric_for_portfolio`,
  `opening_context.position_intraday_pl_reconciliation`,
  `opening_context.portfolio_value_series_from_alpaca`,
  `opening_context.portfolio_equity_summary`.
- `kpis` sub-secciones: `kpis.account_group`, `kpis.leaderboard`.

`src/agente_bolsa/__init__.py`: bump mínimo 0.4.315 -> 0.4.316 (exigido por
`tests/test_version_policy.py` al cambiar `src/agente_bolsa/web_app.py`).

`tests/test_p158b_dashboard_perf.py`: 4 tests nuevos (ver abajo).

## Paridad (diff de lógica nula fuera del timer)

`git diff` de `web_app.py` frente a base `708f0e46` contiene únicamente
marcadores `timer.start`/`timer.stop` y el fix de `emit()`. El único cambio de
forma es el split en `setup` (idéntico en semántica). Cero cambios en órdenes,
scores, gates, sizing, stops/takes, exposición, caché o firmas de funciones.
No se tocó `kernel.py`, `tools/broker.py`, `tools/execution.py`,
`tools/risk.py`, `config.py`, `.env`, ni SQLite.

## Pruebas exactas (aisladas, DATA_DIR temporal, sin red/broker/LLM/yfinance)

- `python -m pytest tests/test_p158b_dashboard_perf.py tests/test_p158a_dashboard_timing.py tests/test_web_app.py -q`
  -> **85 passed** (19.98 s).
- `python -m ruff check src tests` -> **All checks passed!**
- `python scripts/check_no_nulls.py` -> **OK (536 archivos)**
- `git diff --check` -> limpio.

Los 4 tests nuevos cubren: `total_seconds == sections["total"]` con sección
envolvente; fallback a suma sin `total`; timer anidado (sub-secciones dentro de
`opening_context`, cada una subintervalo del padre) sin romper el render;
stop-sin-start tolerado y `emit` que nunca lanza.

## Gates omitidos (declarados, no aprobados por omisión)

- Suite completa `tests/ -x -q`: omitida (preapertura; no competir con sesión).
- Smoke productivo `run-once --skip-crew`: omitido (sin autorización).
- Despliegue / merge a producción / port Jetson: omitidos (prohibidos).
- `validate-agent-config --json`, `kernel-status --json`: no ejecutados (no
  aplican a un lote N1 de solo observación en UI; se ejecutarán en la
  integración cerrada).

## Qué función domina `opening_context`

`unavailable`. No reproducible localmente: mis tests ejercitan la clase
`_DashboardTimer` con reloj monotónico y duraciones ~0, no las cinco funciones
reales de producción (que requieren broker/red/SQLite productiva). La única
evidencia de desglose es la medición real de P-L158-A (0.4.315):
`opening_context` 27.6 s de ~62 s. La atribución fina a una de las cinco
funciones queda para la primera carga real tras desplegar este lote; no se
especula.

## Rehearsal de integracion (25-sep-2026, N1, solo observacion)

Fecha/hora: 2026-09-25 ~21:45-22:00 UTC (23:45-24:00 Madrid). XNYS **cerrado**;
`next_open` 28-sep-2026 15:30+02:00. Sin red/broker/LLM/yfinance; sin tocar
produccion, datos, config, locks ni leases.

Fase 1 (read-only, Jetson por SSH con clave existente). SQLite productiva
`/data/state/agente_bolsa.sqlite3` abierta con URI `mode=ro` y
`PRAGMA query_only=ON` (via `docker exec`, sin escritura):

- `post_market_coordination:session:2026-09-25`: `status=completed`,
  `reason=pipeline_completed`, `run_id=pmr_a2c364c6dbc5`,
  `finished_at=2026-09-25T20:28:09.240459+00:00`,
  `updated_at=2026-09-25T20:28:09.240459+00:00` (terminal).
- Lectura 21:46:33Z: `post_market_coordination:active` con `status=active`,
  `stage=reconciliation`, `run_id=brkrec_40a7e3f65ca5`, `owner_pid=8`,
  `updated_at=2026-09-25T21:37:31.586684+00:00` (lease activo, run en curso).
- Lectura 21:47:35Z: **sin** claves `post_market_coordination:active` ni
  `:reconciliation`. Evento
  `lease_released:brkrec_40a7e3f65ca5:completed` en
  `2026-09-25T21:46:49.517423+00:00` con
  `released_keys=["post_market_coordination:active","post_market_coordination:reconciliation"]`;
  terminal de reconciliacion `completed` en `21:46:45Z` (duracion 553.9 s).
- Comprobacion adicional: 0 claves `runtime_state` con `"status": "active"` y
  0 claves que contengan `lease`. Cadencia de reconciliacion ~15 min
  (arranques 20:52/21:07/21:22/21:37Z; ~9,5-10 min por corrida).
- Resultado: sesion terminal y leases vacios/terminales. Precondicion de
  integracion satisfecha. Nota: por la cadencia, otro lease puede aparecer en
  cualquier ventana de ~15 min; el corte final debe re-verificar en el momento.

Fase 2 (rehearsal de integracion, aislado):

- Worktree NUEVO
  `C:\Antonio\Bref\agenteBolsa_worktrees\pl158br_integration_rehearsal`, rama
  `codex/pl158b-integration-rehearsal`, base exacta `708f0e46` (tree
  `585a7557`).
- `git merge --no-ff 17cf9de1` -> commit de merge `7ad1d2e9`, tree
  `69be2dc5` (identico al arbol del candidato `17cf9de1`). Parents: P1
  `708f0e46`, P2 `17cf9de1`. Sin squash/rebase/cherry-pick/amend; `git diff
  17cf9de1 HEAD` vacio. Version `0.4.316`; arbol limpio.
- Protegidos: `git diff 708f0e46 HEAD` vacio para `kernel.py`, `tools/broker.py`,
  `tools/execution.py`, `tools/risk.py`, `config.py`; blobs identicos
  (kernel `eb0a71f938`, broker `951b7d61ff`, execution `018c52f075`, risk
  `75c1242c2f`, config `e8c8fea58d`). Unicos `src` cambiados: `web_app.py` y
  `__init__.py`.
- Paridad: el diff de `web_app.py` solo contiene marcadores
  `timer.start`/`timer.stop`, el arreglo de `emit()` (`total_seconds` = seccion
  envolvente `total`) y el split equivalente de `setup`. Cero cambios de
  trading, riesgo, ejecucion, UI, cache o firmas.

QA aislada (DATA_DIR temporal, reloj/servicios fuera; sin red/broker/LLM):

- focales del lote
  `tests/test_p158b_dashboard_perf.py tests/test_p158a_dashboard_timing.py tests/test_web_app.py`
  -> **85 passed** (14.90 s).
- regresiones relacionadas
  `tests/test_version_policy.py tests/test_p152_dashboard_today.py tests/test_dashboard_llm_helpers.py tests/test_p83d_dashboard_temporal_dates.py tests/test_p87_dashboard_cards.py tests/test_p123_dashboard_characterization.py`
  -> **31 passed** (3.83 s).
- `python -m ruff check src tests` -> **All checks passed!**
- `python scripts/check_no_nulls.py` -> **OK (536 archivos)**
- `git diff --check` -> limpio.

Gates omitidos (declarados, no aprobados por omision): suite completa
`tests/ -x -q`, smoke `run-once --skip-crew`, benchmark, `validate-agent-config
--json`, `kernel-status --json`, despliegue/corte y doble healthcheck.

Dictamen del rehearsal: `ready_for_closed_market_full_validation` (solo
observacion N1). No desplegado; el corte exige suite completa aislada + port
Jetson + snapshot frio + doble healthcheck, con XNYS cerrado, leases/jobs
ausentes y autorizacion explicita del operador.

## Validacion completa aislada y smoke (26-sep-2026)

Fecha/hora: 2026-09-26 ~10:25 Madrid (08:25Z), sabado; XNYS **cerrado**
(`schedule-status`: `is_open=false`, `next_open=2026-09-28T15:30:00+02:00`).
Worktree aislado `pl158br_integration_rehearsal`, sin `DATA_DIR`/SQLite
productiva y sin red/broker/LLM/yfinance. No se toco produccion, principal,
datos, config, locks ni leases. La evidencia procede de la sesion
`ses_f23616655ffe3pmtziGgijpUWb`; no se re-ejecuto nada en este lote.

Suite completa aislada (lanzada **sin** `-x` y con
`--continue-on-collection-errors`: el `-x` abortaba en la coleccion
preexistente):

| Arbol | HEAD | Tree | Resultado | Duracion |
| --- | --- | --- | --- | --- |
| Candidato | `6aab5028` | `0de7b35c` | 46 failed, 2586 passed, 1 skipped, 105 warnings, 4 errors | 1437.59 s |
| Base | `708f0e46` | `585a7557` | 46 failed, 2582 passed, 1 skipped, 105 warnings, 4 errors | 886.98 s |

- Conjuntos de fallos y errores **identicos** entre candidato y base
  (comparados uno a uno). Delta `+4 passed` = los 4 tests nuevos
  `tests/test_p158b_dashboard_perf.py` aportados por el candidato.
- 4 errores de coleccion **preexistentes** (base y HEAD): `test_p133`,
  `test_p137`, `test_p140a` y `test_p140b` (simbolos ausentes en `src` en
  ambos arboles).
- 1 skip **preexistente**: `test_score_study_regression_current_sqlite`.
- Benchmark P-L45 (33.336 observaciones) **omitido** por coste declarado.

Smoke aislado `run-once --skip-crew` (exit 0): ciclo `20260926-080243`,
`used_crew=false`, `broker_orders=0`, `order_plans=0`, `agent_events=52`.

Gates estaticos: Ruff, `scripts/check_no_nulls.py`, `git diff --check` y
validacion de configuracion **verdes**. `kernel-status` = `unsealed`
**esperado** en `DATA_DIR` temporal (no describe produccion; no hay manifiesto
productivo en ese entorno).

Fase 1 productiva (read-only): postmarket de la sesion 25-sep `completed` a las
20:28Z (`run_id=pmr_a2c364c6dbc5`); 0 leases activos en la relectura.

Dictamen de la validacion completa: `ready_for_closed_market_deployment`
**con reserva**: la deuda de suite (46 failed + 4 errores de coleccion) es
preexistente e identica en la base 0.4.315, se documenta aqui y se repara en
lotes aparte; no se oculta con skip/xfail ni se aprueba por omision. Este lote
no propone corte.

## Límites y siguiente paso

Siguiente paso único (sin ejecutarlo): integrar `codex/pl158b-dashboard-perf`
con `merge --no-ff` en una ventana cerrada, suite completa aislada, y después
port Jetson + corte con snapshot frío y doble healthcheck, **solo** con:
XNYS cerrado, postmarket terminal, leases/jobs ausentes, y autorización
explícita del operador. Nunca desplegar por mi cuenta.

## Nota de entorno (no bloqueante)

`git commit` emite un aviso `fatal: bad object refs/codex/turn-diffs/...` con
`geometric-repack` fallido en cada commit; los commits se completan y el árbol
queda limpio. Es un ref interno del harness (Codex/OpenCode), ajeno al lote;
no se reparó ni limpió.
