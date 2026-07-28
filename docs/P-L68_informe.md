# P-L68 — comparabilidad y visibilidad Sistema vs SP500

## Dictamen

`ready_for_integration_rehearsal`

P-L68 corrige dos defectos de contrato que dejaban en blanco el bloque
`Rendimiento diario: Sistema vs SP500` y conserva como `pending` cualquier
sesión que no pueda decidir un ganador de forma auditable.

## Causa raíz

1. `market_data` descarga yfinance con `auto_adjust=True`, pero no persistía
   `auto_adjust` ni `price_basis`. El benchmark terminaba con
   `price_basis=unknown`.
2. El lector calculaba `as_of - captured_at`. Las barras diarias de yfinance
   usan un timestamp de fecha a medianoche, mientras el snapshot se captura
   tras el cierre. Esa secuencia válida se clasificaba erróneamente como
   `generated_at_after_benchmark_as_of`.
3. Cuando todas las filas quedaban `pending`, el gráfico descartaba los
   valores numéricos y devolvía `None`.
4. El baseline acumulado sumaba retornos diarios; debe componerlos.

## Contrato corregido

- Las nuevas descargas yfinance declaran:
  `auto_adjust=true`, `price_basis=adjusted_ohlc`.
- `benchmark.as_of` distingue precisión `date` de `instant`.
- Para precisión diaria no se inventa una hora intradía ni una latencia.
- Para una instantánea exacta, la latencia es
  `captured_at - benchmark_as_of`; un benchmark posterior a la captura es
  `unavailable`.
- Un warning global ajeno, como `position_side_invalid`, no invalida una
  pareja completa si `benchmark.data_quality=available`.
- Las sesiones incompletas mantienen `comparison_status=pending`: no cuentan
  como victorias, derrotas ni empates.
- Si una sesión pendiente conserva ambos números, se dibuja como línea
  discontinua `Provisional`. La línea continua queda reservada a datos
  comparables. La tabla publica los valores provisionales y sus motivos.
- Los retornos acumulados se componen con
  `(1 + acumulado) * (1 + diario) - 1`.

No hay backfill, reescritura histórica ni inferencia por símbolo/fecha.

## Evidencia productiva read-only

Las siete sesiones visibles del 17 al 28 de julio siguen teniendo
`0 comparables`, lo cual es correcto porque las filas históricas declaran base
desconocida. Seis sesiones conservan al menos un valor numérico y el nuevo
lector construye el gráfico provisional en vez de dejar el panel en blanco.
El 24-jul carece de pareja de equity y el 27-jul carece de pareja SPY; ambas
ausencias permanecen visibles y no se rellenan.

La lectura se realizó con SQLite `mode=ro` y `PRAGMA query_only=ON`.

## Validación

- Caracterización P-L68: 7 passed.
- Focales P-L40/P-L65/market data/UI/version: 173 passed.
- Suite completa: 2249 passed, 1 skip y 1 warning preexistentes.
- Ruff completo: OK.
- `check_no_nulls.py`: OK, 447 archivos.
- `git diff --check`: OK.
- `validate-agent-config --json`: `ok=true`, sin errores ni warnings.
- Kernel productivo: sellado, `ok=true`, 0 violaciones.
- Archivos protegidos: sin diferencias frente a producción.
- Smoke CLI real: no ejecutado; el comando no garantiza ausencia de
  broker/red en este contexto. La suite y los tests focales usan datos
  temporales y dobles locales.

## Telegram

P-L66 publica las notificaciones cuando una reconciliación detecta el cambio
durable a `filled`; no garantiza el instante del fill del broker. No se ha
mezclado esa corrección con P-L68.

Siguiente lote mínimo P-L69:

- detectar fills durante mercado abierto con una fuente canónica del broker;
- persistir primero el estado local `filled`;
- publicar después, fail-open e idempotente por `broker_order_id`;
- BUY: cantidad y precio real de entrada;
- SELL: entrada exacta por `source_plan_id`, salida real y P/L bruto;
- nunca enviar una ejecución al mero `submit` ni bloquear trading;
- revisar explícitamente paridad y archivos protegidos si la solución toca
  broker o execution.

## Estado

- Worktree: `pl68_benchmark_comparability_fix`.
- Rama: `codex/pl68-benchmark-comparability-fix`.
- Base productiva: `f015428f669b76a4f39b4c0eddaff76202638503`.
- Versión candidata: `0.4.202`.
- Producción, stack, SQLite, configuración y secretos no fueron modificados.
- Sin despliegue, reinicio, broker, red, LLM ni push.

