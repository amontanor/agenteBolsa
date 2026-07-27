# P-L57A — continuidad null-safe del cierre postmarket y del scoreboard

## Dictamen provisional

`ready_for_integration_rehearsal`, sujeto a que la validación cerrada del
candidato termine sin fallos. El cambio corrige una causa reproducida y queda
limitado a continuidad observacional; no está desplegado.

## Estado y alcance

- Fecha de trabajo: 27-jul-2026, Europe/Madrid. XNYS cerrado; siguiente
  apertura observada: 27-jul-2026 15:30 CEST.
- Producción/base: HEAD
  `24537e813ff0905696cda0b3925a212045ee7b09`, tree
  `4747f27f3d5dc152410203bf089baee500440897`, versión `0.4.185`.
- Suciedad productiva observada y preservada: `src/agente_bolsa/web_app.py`,
  `tests/test_web_app.py`, `AGENTS.md`, `.agents/skills/*` y
  `skills-lock.json`. No se copió, limpió, stageó ni modificó.
- Candidato: `C:\Antonio\Bref\agenteBolsa_worktrees\pl57a_pmr_null_safety`,
  rama `codex/pl57a-pmr-null-safety`, versión `0.4.193`.
- Se usó únicamente `DATA_DIR` temporal para pruebas. La SQLite productiva
  solo se consultó con URI `mode=ro` y `PRAGMA query_only=ON`; no hubo escritura.

## Causa reproducida

La evidencia productiva de solo lectura fue:

- PMR `pmr_dbfa382016b8`, sesión 2026-07-23: reconciliación completada y
  `postmarket_report` fallido con terminal `failed`, razón
  `stage_postmarket_report_failed`.
- Error persistido: `TypeError("'<' not supported between instances of
  'NoneType' and 'int'")`.
- No existe fila `performance_daily` para 2026-07-23.
- La fila del 2026-07-24 conserva `pnl_pct=NULL`, `previous_equity=NULL` y
  `alpha=NULL`; su payload contiene `result_metrics.pnl_pct=0.002288`, pero
  también `missing_previous_xnys_session`. El payload no es autoridad para
  rellenar el ledger SQL.

La reproducción temporal contra la base exacta se hizo con una fila válida y
otra fila con `pnl_pct=NULL` y sin `max_dd`. En la base, la cadena era:

`performance_daily` → `_performance_summary` →
`_max_drawdown_from_returns` → operación numérica sobre `None` → `TypeError`.

La prueba de reproducción fue `tests/test_p57a_null_safety.py::test_exact_23_null_pnl_does_not_break_scoreboard` y falló contra la base antes
del fix; la misma prueba pasa en el candidato. La deuda ya estaba registrada
por `test_qa7_preexisting_scoreboard_null_pnl_crash_is_documented` en
P-L48BR1. P-L57A reemplaza esa expectativa de fallo por una garantía
null-safe. No hay indicio de una segunda causa que justifique un parche
especulativo.

## Contrato de continuidad

1. `_num`/`_finite` aceptan solo valores numéricos finitos; `None`, bool,
   strings vacíos/no numéricos, NaN e Infinity son `unavailable`.
2. Drawdown, sumas, alpha, Sharpe, profit factor y agregaciones ignoran
   observaciones no numéricas del denominador correspondiente.
3. Sin observaciones numéricas, la métrica permanece `null` y el estado es
   `unavailable`; con cobertura mixta se publica `partial` con
   `available/total`. No se usa cero como sustituto.
4. Una fila incompleta no descarta las filas válidas de otras sesiones. No se
   rellena `previous_equity`, `pnl_pct`, alpha, costes, flujos o drawdown.
5. El `result_metrics` de un payload no reconstruye las columnas SQL ni hace
   backfill de 2026-07-23.
6. La serie web read-only deja el punto de la métrica faltante como `null` y
   no lo dibuja como cero; la tarjeta no fabrica alpha acumulado si falta una
   de sus dos series.

## Productores y consumidores

El productor de `performance_daily` conserva `pnl_pct=NULL` cuando no existe
una sesión XNYS anterior comparable. El fix protege los consumidores
observacionales: `profitability_scoreboard`, `promotion_readiness`, digest
semanal y la serie de web. Los consumidores devuelven resultado parcial,
`unavailable` o `collecting` con cobertura explícita.

La secuencia PMR no se reordena ni se reejecuta: la corrección impide que una
fila incompleta derribe el informe observacional. La reconciliación, los
outcomes, la decisión activa, RiskManager, gates y el terminal PMR conservan
su semántica. No se reconstruye ninguna fila perdida.

## Pruebas adversariales

La nueva batería cubre:

- caso 23: fila anterior ausente/null y fallo exacto del scoreboard antes del
  fix; resultado parcial después;
- caso 24: `pnl_pct`, `previous_equity` y alpha siguen null mientras SPY se
  mantiene separado;
- mezcla de válidos e inválidos, todos null, `max_dd` omitido/null, cero y
  negativos válidos;
- NaN, Infinity, strings y bool como `unavailable`;
- promoción y digest sin convertir missing en cero;
- serie web con puntos faltantes null-safe;
- orden determinista, no mutación y Store temporal.

Denominadores de cobertura se mantienen por métrica (`available`, `total`,
`status`); no se mezclan equity, P/L realizado, P/L abierto, benchmark ni
alpha.

## Commits

1. `5d05092c88d0b01670d3357280cdd0cd2a712d1b` — `test: reproduce null
   postmarket scoreboard failure`.
2. `1268479060a03e67f00853ff28dafb684fe251d5d5` — `fix: keep postmarket
   scoreboard null-safe`.
3. Commit documental de este informe, plan maestro y relevo: se crea por
   separado al cerrar la validación.

No se usa amend, squash, rebase, cherry-pick ni push.

## Protección y límites

No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
`config.py` ni `.env`. No se modificaron candidatos previos. El cambio no
toca señales, ranking, selección, LLM, gates, sizing, planes, cantidades,
precios, stops, takes, trailing, órdenes, exposición, límites, broker ni
frecuencia de jobs.

No hubo backfill, migración, tabla nueva, escritura productiva, servicio,
job, broker, red, LLM, reconciliación manual, postmarket manual, despliegue,
reinicio ni push.

## Validación pendiente y siguiente paso

Quedan por cerrar en el worktree candidato, con DATA_DIR temporal: suite
completa `tests/ -x -q`, focales de postmarket/performance/scoreboard/
promotion/web, Ruff, `check_no_nulls.py`, `git diff --check`,
`validate-agent-config --json`, version policy y `kernel-status` temporal
interpretado frente a producción sellada. Smoke solo será válido si queda
aislado de red, broker y LLM; en caso contrario se declara
`smoke_unavailable_by_safety`.

Si esos gates pasan, el único siguiente lote es un ensayo de integración
aislado P-L57A. Este informe no autoriza despliegue ni promoción.
