# P-L158-B — perfil fino de observación del dashboard (candidato 0.4.316)

## Dictamen

`ready_for_integration_rehearsal` (N1: solo observación). No desplegar por mi
cuenta; el siguiente paso exige XNYS cerrado + postmarket terminal + autorización
explícita del operador.

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
