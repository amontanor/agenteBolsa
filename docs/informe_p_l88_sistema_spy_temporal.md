# P-L88 - coherencia temporal Sistema vs S&P 500 y etiquetas de cartera

## Dictamen

`ready_for_closed_market_deployment_truthful_ui`.

El candidato queda preparado en worktree aislado; no se ha integrado ni
desplegado porque XNYS sigue abierto. La UI de Sistema es segura y veraz, pero
el objetivo completo de comparar SPY apertura -> ahora no queda resuelto: el
carrier actual no prueba una observacion intradia del proveedor. Produccion
permanece intacta en v0.4.224. El siguiente paso unico es decidir una fuente o
cadencia que transporte ese timestamp antes de afirmar comparabilidad de SPY.

## Hechos y causa reproducida

- Preflight: 2026-08-10 20:04 CEST. `schedule-status` confirmo XNYS abierto,
  sesion 2026-08-10, cierre 22:00 CEST y scheduler `owner_alive` con token
  coherente. El runtime SQLite se mantuvo `unavailable` por WAL/sidecars,
  segun el contrato read-only; no se reparo.
- Base productiva: `0cf8a5353d5e0fdb77e57b4a09e64d91761d0278`, tree
  `57ad337010f3e1c394f7493c5b0d0f9cf773f445`, v0.4.224, limpia.
- La cabecera usaba el contrato diario oficial `current_equity -
  previous_close_equity`; la tabla de apertura usaba `equity_at_exact_open`.
  Por eso sus ventanas y porcentajes no eran equivalentes. El cambio no
  elimina la metrica diaria: la etiqueta ahora dice explicitamente `desde
  cierre anterior`.
- La auditoria P-L88A encontro que el current SPY procede de caches diarios
  `yfinance` con `created_at`, `interval=1d` y `adjusted_ohlc`, pero sin
  `provider_observed_at`/`market_observed_at`. A las 18:23 UTC el ultimo
  metadata era 18:14:42 UTC (~9 min de lag) y el artefacto dedicado SPY era
  18:01:29 UTC; la secuencia observada es irregular y no demuestra una
  cadencia <=300 s ni semantica intradia del precio diario.
- La caracterizacion roja de P-L88R reprodujo que un cache reciente sin
  timestamp del proveedor se clasificaba `comparable` solo por `created_at`.
  El fix ya no usa `created_at` como observacion de mercado.
- SPY continua siendo el ETF `SPY (ETF S&P 500)`. No se usa el indice SPX de
  TradingView ni se afirma equivalencia entre ambos instrumentos.

## Contrato implementado

- Sistema: `equity_now - equity_at_exact_open`, porcentaje sobre
  `equity_at_exact_open`, con ventana apertura XNYS -> `account_read_at`.
- Benchmark: apertura exacta de SPY -> observacion actual del carrier ya
  existente. Solo se publica en grafica, tabla y tarjeta si el estado es
  `comparable`, el instrumento es SPY, existe un
  `provider_observed_at`/`market_observed_at` explicito y el desfase frente a
  `account_read_at` es de como maximo 300 segundos. El umbral esta
  centralizado en `CURRENT_BENCHMARK_ALIGNMENT_TOLERANCE_SECONDS` y no
  legitima por si mismo la edad de un cache.
- Si el cache solo contiene `created_at`, el current queda `unavailable` con
  razon `current_observation_timestamp_unverified`; la UI muestra `n/d` y no
  hay ganador ni valor SPY visible. Un timestamp explicito valido continua
  siendo comparable dentro de la tolerancia.
- Observacion futura, anterior a la apertura, missing, instrumento distinto,
  timestamp no verificable o desfase superior a 300 s permanece `unavailable`;
  la UI muestra `n/d`, razon y `as_of`, y no calcula ganador.
- El valor SPY crudo puede mantenerse en el carrier para diagnostico, pero no
  entra en la serie visible ni en el conteo de ganadores si la comparacion no
  es valida.
- Las fechas y timestamps internos siguen UTC; la UI los muestra en
  Europe/Madrid. No se mezclan SPX, cierre anterior, apertura exacta ni P/L de
  posiciones.

## Etiquetas de Valor de cartera

El commit N1 separado `7717c20f` añade una etiqueta visible a cada punto de la
serie: positivo verde con signo, negativo rojo, cero gris y missing como
`n/d`. El primer punto sin predecesor no se convierte en cero. La serie
conserva el porcentaje calculado antes del recorte de ventana, de modo que un
predecesor oculto sigue sirviendo para calcular el primer punto visible. Se
añadieron tambien las etiquetas al fallback tabular sin cambiar el resumen ni
la fuente de datos.

## Commits y QA realizada

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl88_system_spy_temporal_ui`.
- Rama: `codex/pl88-system-spy-temporal-ui`.
- Caracterizacion: `81a2bcd0`; la prueba nueva fue roja contra la base en
  alineacion por tolerancia, etiquetas y helper de resumen (`4 failed, 4
  passed`). Las regresiones existentes base fueron `82 passed`.
- N2 temporal: `64bf9b59`; focales y regresiones web/SPY `89 passed`.
- N1 y version: `7717c20f`; focales finales, regresiones y version policy
  `96 passed`.
- QA de frontera: `e04f3ba0`, prueba del limite inclusivo de 300 segundos.
- P-L88R caracterizacion: `7abdfb1f`; el caso de cache reciente sin
  timestamp explicito fue rojo (`1 failed`). Ajuste fail-closed y regresiones:
  `9350f024`; P-L88R `10 passed` y regresiones P-L72/P-L74/P-L75/P-L82/P-L82R
  `40 passed`.
- Version candidata: v0.4.225.
- Ruff afectado: verde. `check_no_nulls.py`: verde (480 archivos).
- `git diff --check`: verde.
- Suite completa, smoke, validate-agent-config productivo, merge, stack
  restart y health checks cerrados: pendientes por XNYS abierto; no se
  lanzaron para no competir con la sesion.

## Paridad y limites

El lote solo cambia presentacion y la comparabilidad observacional del carrier
de apertura. No toca broker, kernel, execution, risk, config, `.env`, SQLite,
scheduler, Kindle, LLM, seleccion, gates, sizing, ordenes, exposicion,
politica ni el cutoff P-L80 `2026-08-02T15:51:41.5484478Z`. No hay llamadas
adicionales al broker, red, yfinance o LLM desde el nuevo codigo; las pruebas
usan fixtures y no SQLite productiva.

## Cierre requerido

Con XNYS cerrado: confirmar PMR/reconciliacion/leases terminales, ausencia de
competidores, paper activo, live y auto-apply desactivados, kernel/config
validos y margen suficiente. Ejecutar una sola suite completa sobre el tree
funcional final, gates proporcionales, ensayo/merge `--no-ff`, reinicio web
gestionado solo si no se requiere reinicio global, y dos health checks >=75 s
incluyendo `/`, `/health` y `/kindle` local/LAN. Ante fallo, `git revert`
auditable. No ejecutar `kernel-seal`, no copiar manifest y no hacer push.
