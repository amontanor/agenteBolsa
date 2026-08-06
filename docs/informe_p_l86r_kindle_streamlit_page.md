# P-L86R — Página Kindle oculta en Streamlit

## Dictamen provisional

`ready_for_closed_market_deployment`. P-L86R implementa una página directa
`/kindle` dentro del mismo proceso Streamlit de `AgenteBolsaWeb`, sin servidor,
puerto, tarea, scheduler, carrier ni persistencia nuevos. El despliegue queda
sujeto a la validación cerrada final y al margen seguro antes de XNYS.

## Causa y contrato

El candidato P-L86 anterior resolvía el requisito mediante una arquitectura
independiente que el operador descartó. La sustitución mínima usa la API
Streamlit 1.58 (`st.Page` + `st.navigation`) con la página `Kindle` oculta y
`url_path="kindle"`; la navegación manual existente sigue siendo la página
raíz y conserva su radio/sidebar.

La página reutiliza las lecturas y contratos existentes:

- `PortfolioSnapshot.previous_close_equity` y `daily_equity_change`:
  `current_equity - account.last_equity`;
- el mismo `BrokerClientFactory`, `alpaca_portfolio_snapshot` y la lectura de
  historial que usa el dashboard para construir el consumidor SPY;
- `comparison_status == comparable` para publicar SPY; cualquier otro estado
  queda como `n/d — no comparable`;
- `PositionSnapshot` para símbolo, cantidad, entrada, precio actual, P/L total
  y P/L de hoy.

No se añade una llamada de broker dentro de la misma renderización, escritura
de estado, SQLite, proceso persistente, tarea Windows, firewall, endpoint
alternativo ni cambio de trading/riesgo/ejecución.

## Presentación y aislamiento

El HTML es una columna compacta, blanco/negro, con escape HTML, sin JavaScript,
gráficos, recursos externos, iconos ni fuentes externas. El enlace `Actualizar`
apunta a `/kindle`. La ruta no aparece en el menú: `st.navigation` se configura
con `position="hidden"` y la página con `visibility="hidden"`. El CSS/fuente
externo del dashboard no se inyecta cuando la página oculta Kindle es la página
activa.

La información visible se limita a cartera diaria, SPY, posiciones y
`as_of`/frescura. Missing permanece `n/d`; posiciones se ordenan por símbolo y
los valores originales no se mutan.

## Evidencia y validación

Base productiva de desarrollo: `faa2e15773c526af66768fe63656dbb0c04292d0`,
árbol `8cfafe5e37d5d8632e9de77ce930131b15116336`, versión `0.4.221`.
Worktree: `codex/pl86r-kindle-streamlit-page`,
`C:\Antonio\Bref\agenteBolsa_worktrees\pl86r_kindle_streamlit_page`.

La caracterización previa reprodujo `6 failed` contra la base por ausencia de
la declaración de ruta y de los helpers Kindle. Después del cambio, los
focales de P-L86R y la regresión de política de versión pasan `54 passed`.
La caracterización incluye ruta oculta, compatibilidad Streamlit 1.58,
contrato diario, SPY comparable/no comparable, posiciones/missing, escape,
lecturas únicas y ausencia de componentes del diseño independiente anterior.

Los commits funcionales y de tests son:

- `a5306521`: caracterización de la ruta oculta;
- `5b7e02d0`: página `/kindle`, navegación oculta y bump a `0.4.222`;
- `83f17d17`: cobertura de enrutado, aislamiento visual, missing/orden y
  actualización de la prueba de política de versión.

La suite completa y los gates de cierre se ejecutan una sola vez sobre el árbol
final, con `DATA_DIR` temporal, `_env_file=None`, proveedores fake y sin
SQLite productiva, red, broker, LLM ni yfinance. La producción permanece en
`v0.4.221` hasta un eventual merge autorizado.

## Límites y siguiente paso

No se modifica `broker.py`, `kernel.py`, `execution.py`, `risk.py`,
`config.py`, `.env`, `scheduler.py`, `main.py` ni los scripts del stack. Los
seis untracked del operador se preservan. El cutoff P-L80 y P-L85 permanecen
intactos.

Siguiente acción única: completar la suite/gates aislados y, si XNYS sigue
cerrado con margen suficiente, realizar `merge --no-ff`, arranque canónico y
dos comprobaciones de salud separadas al menos 75 segundos, incluyendo la
ruta `/kindle`. Sin push.

## Cierre productivo

P-L86R queda `deployed`. Se integró con `git merge --no-ff` mediante
`849feebd773a459418a3b031b4be4f2fb084b4d9`, primer padre
`faa2e15773c526af66768fe63656dbb0c04292d0` y segundo padre
`307658f331f4424cd0a8c107bf7905049c897ec6`; el árbol funcional/documental del
candidato era `bd5e10d45c8b08d0b6104f1b4979abaff6984ad4` y la versión efectiva
es `0.4.222`.

La suite fresca del árbol candidato pasó `2464 passed, 1 skipped` y `1 warning`
externo en `891.60s`; una primera ejecución anterior había pasado `2464/1/1`
en `856.38s`. La segunda ejecución fue necesaria únicamente porque Ruff
detectó y corrigió el orden de imports de un test, sin cambio semántico. Tras
el merge, los focales P-L86R/version pasaron `54`, Ruff/NUL/compile/diff,
config aislada y smoke fake quedaron verdes. No se repitieron suites por
expectativa stale.

Stack up canónico a las `13:33:32` CEST. Salud 1 a
`2026-08-06T11:34:15.8840595Z` y salud 2 a
`2026-08-06T11:36:30.5421722Z`, separadas `134.66s`: raíz, `/health` y
`/kindle` 200; scheduler/listener únicos; PID/lock/token/heartbeat coherentes;
paper activo, live/auto-apply off, kernel `ok`, 0 críticos. El lock_orphan del
helper sigue siendo el falso positivo wrapper/runtime conocido. No hubo
órdenes, broker operativo, backfill, jobs manuales ni push.
