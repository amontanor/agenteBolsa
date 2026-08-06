# P-L87 — visibilidad diaria de cartera y ventas

Dictamen de candidato: `ready_for_closed_market_deployment`.

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

La producción no ha sido integrada ni reiniciada en P-L87. Siguiente paso
único: renovar preflight cerrado y, si PMR/leases/procesos/margen siguen
verdes, merge `--no-ff`, reiniciar exclusivamente `AgenteBolsaWeb` y hacer
dos comprobaciones de salud separadas al menos 75 segundos. Sin push.
