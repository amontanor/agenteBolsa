# P-L86 — página Kindle read-only en LAN

## Dictamen del candidato

`ready_for_closed_market_full_validation` hasta completar la suite cerrada y
el despliegue gestionado. El cambio es exclusivamente observacional/UI: no
adquiere autoridad sobre trading, riesgo, selección, gates, sizing, exits,
órdenes, ejecución, LLM ni la cohorte P-L80.

## Contrato y causa

La ruta existente que ya obtiene una única `PortfolioSnapshot` es
`scheduler.portfolio_watch_job`. No existía un carrier portable que pudiera
leer una página independiente sin volver a llamar al broker. P-L86 añade un
carrier JSON sanitizado en `data/state/kindle_snapshot.json`, publicado
atómicamente desde esa foto ya cargada. El lector HTTP solo abre ese fichero;
no importa `BrokerClientFactory`, `Store`, Streamlit ni LLM.

La cartera usa el contrato canónico `portfolio_value - previous_close_equity`
(`account.last_equity`) y su porcentaje sobre el cierre previo. Las posiciones
transportan únicamente símbolo, cantidad, precio de entrada, precio actual,
P/L total porcentual y P/L diario porcentual. No se incluyen account ID, cash,
buying power, órdenes, stops, takes, rutas ni diagnósticos.

El benchmark SPY solo se proyecta desde un contrato EOD canónico ya validado,
con autoridad, basis, fuente y `as_of`. Durante mercado abierto no se
promueve el intervalo apertura→ahora como P/L diario: si el SPY disponible no
es temporalmente comparable, la página muestra `n/d — ...`.

## Arquitectura LAN

- `agente_bolsa.kindle_server`: `http.server` de la biblioteca estándar,
  independiente de Streamlit.
- `/kindle`: único contenido HTML server-rendered, blanco/negro, una columna,
  responsive para viewport estrecho, sin JavaScript, canvas, SVG, fuentes o
  recursos externos.
- `/health`: JSON mínimo del servicio y disponibilidad del snapshot.
- Otras rutas: `404`; métodos mutadores: `405` con `Allow: GET, HEAD`.
- `Cache-Control: no-store`, escape HTML y enlace normal `Actualizar`.
- Bind gestionado: `0.0.0.0:8502`; no se abre ni modifica firewall.
- `AgenteBolsaKindle` se registra mediante `scripts/install_kindle_task.ps1`
  y se incorpora a `stack_up.ps1`, `stack_down.ps1` y `stack_status.ps1` a
  través de `stack_common.ps1`.

## Preflight caracterizado

El 06/08/2026 a las 11:47 CEST XNYS estaba cerrado y la próxima apertura era
15:30 CEST. Producción era v0.4.221, HEAD
`eba2faa2643b6e46c059c518599635af430775bc`, tree
`8cfafe5e37d5d8632e9de77ce930131b15116336`, limpia. Scheduler owner_alive,
PMR del 05/08 terminal en sus artefactos, sin pytest/deploy/reconciliación
competidores, paper activo, live y auto-apply desactivados. Kernel P-L85
seguía `ok`; las dos warnings históricas de setup edge y adaptive governance
se mantienen fuera de alcance.

La caché local SPY tenía observaciones, pero también conflictos históricos y un
`as_of` distinto del instante de cartera. No se trató como dato diario
comparable. No se ejecutó broker ni red para caracterizarlo.

## QA del worktree

Base exacta: `eba2faa2643b6e46c059c518599635af430775bc`.
Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl86_kindle_local_page`.
Rama: `codex/pl86-kindle-local-page`.

La caracterización focal inicial pasó `6 passed`. Cubre cálculo diario con y
sin `previous_close_equity`, benchmark comparable y fail-closed/no comparable,
orden estable y campos mínimos de posiciones, hash/idempotencia y publicación
atómica, escape HTML, ausencia de JavaScript/recursos externos y viewport
estrecho, GET `/kindle`, GET `/health`, 404 de otras rutas y 405 de POST.

Ruff focal quedó verde tras ordenar imports. Falta la validación cerrada
completa, la suite, smoke/gates, integración y dos health checks; por tanto no
se marca `deployed` en este informe de candidato.

## Protegidos y límites

No se modifican `broker.py`, `kernel.py`, `execution.py`, `risk.py`,
`config.py`, `.env`, datos de P-L80 ni el cutoff
`2026-08-02T15:51:41.5484478Z`. La única frontera compartida nueva es una
publicación fail-open desde el `PortfolioSnapshot` ya adquirido por
`portfolio_watch`/postmarket; no hay una llamada broker adicional.

## Siguiente secuencia

Con XNYS cerrado y margen suficiente: suite aislada y gates completos, ensayo
`merge --no-ff`, preflight renovado, registro de la tarea gestionada sin
firewall, stack down/up canónico y dos comprobaciones de `/kindle` y `/health`
separadas al menos 75 segundos. Si falta margen o falla una precondición,
mantener producción v0.4.221 y devolver `ready_for_closed_market_deployment` o
`precondition_not_met`; no hacer backfill, jobs manuales, cambios P-L85 ni
push.
