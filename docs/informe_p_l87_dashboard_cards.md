# P-L87 — visibilidad diaria de cartera y ventas

Dictamen: `deployed`.

P-L87 añade dos superficies observacionales al dashboard existente. La cuarta
tarjeta reutiliza `position_intraday_pl_reconciliation` sobre el mismo
`PortfolioSnapshot` y muestra USD más cobertura conocida/total; no publica un
porcentaje inventado. El bloque de ventas filtra `history["trades"]` por
`side=sell` y por `account_current.system_start_at`, la apertura XNYS ya
cargada, con una fila por fill y `n/d` para P/L realizado ausente.

No se añadieron llamadas, persistencia, fuentes, schedulers ni procesos. No se
modifican `daily_equity_change`, `PortfolioSnapshot`, broker, Kindle, LLM,
configuración, SQLite ni las fronteras de trading/riesgo/ejecución.

Base: producción P-L86Q en `d6bf37b0`, versión `0.4.223`.
Candidato: rama `codex/pl87-portfolio-today-sales`, worktree
`C:\Antonio\Bref\agenteBolsa_worktrees\pl87_portfolio_today_sales`, versión
`0.4.224`. Commits funcionales: `9ab3c461` (caracterización) y `a48b9285`
(implementación y versión). La documentación de este informe, plan y relevo
queda separada del commit funcional.

QA focal: `133 passed, 1 warning` en UI, contrato diario, P-L82/P-L82R,
P-L83D, Kindle y política de versión. Las 8 pruebas P-L87 cubren cobertura
parcial, ventas en el límite exacto de apertura, fills buy/sell, missing,
orden temporal, zonas horarias y no mutación. Ruff afectado, NUL y
`git diff --check` están verdes. No se ejecutó suite completa ni smoke
productivo: el lote es N1 de presentación aislada y no introduce fuente,
persistencia, proceso ni cambio de autoridad; se deja como gate de cierre si
el preflight exige validación adicional.

Integración productiva: merge `db5a8584`, primer padre `d6bf37b0` y segundo
padre `9ecee304`; HEAD/tree finales son `db5a8584`/`447bbfd0`, versión
`0.4.224`, producción limpia. Se reinició exclusivamente `AgenteBolsaWeb`
mediante la tarea gestionada; el árbol nuevo es `39956` → `28812` y el único
listener es `0.0.0.0:8501`. No se reinició el scheduler.

Salud 1: `2026-08-06T23:25:46.6533928+02:00`. Salud 2:
`2026-08-06T23:27:37.2529625+02:00`, separación 110,6 s. En ambas se
confirmaron raíz y `/health` 200; en la segunda también `/kindle` 200, local y
LAN, con HTML raw sin shell Streamlit. Scheduler owner/token siguió válido,
kernel `ok`, paper activo, live/auto-apply desactivados, un listener y cero
críticos. Persisten únicamente tres warnings preexistentes.

El cierre no ejecutó suite completa ni smoke productivo por la clasificación
N1 documentada; sí ejecutó las regresiones focales (`133 passed, 1 warning`),
Ruff afectado, NUL y diff-check. No hubo broker, LLM, jobs manuales,
reconciliación, cambios de datos, backfill ni push. El cutoff P-L80 permanece
inmutable.
