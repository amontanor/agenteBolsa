# P-L71 — autoridad EOD y coherencia temporal Sistema vs benchmark

## Dictamen

`ready_for_integration_rehearsal` tras las focales y la suite cerrada. No es un
despliegue ni una corrección histórica: `performance_daily` del 28-jul-2026
conserva su contenido original y la UI solo puede proyectar un overlay
read-only cuando existe una observación EOD posterior verificable.

## Causa reproducida

La ruta productiva de la base `0.4.202` recorría el fallback de
`data/cache/market_data/` en orden lexicográfico de `market_data_<hash>`. El
primer fichero podía contener el SPY de las 13:44Z del 28-jul:

| observación | valor SPY | captura | base | tratamiento P-L71 |
|---|---:|---|---|---|
| cache antiguo | 736,84 | 13:44Z | desconocida | rechazada; no es EOD |
| cache intermedio | 742,09 / 741,58 / 740,76 | 15:50–20:14Z | mutable | rechazada; misma sesión |
| cache posterior | ~740,86 / ~740,94 | 29-jul, posterior | `adjusted_ohlc` explícita | candidata EOD posterior |

Con el par persistido 739,0900268554688 → 736,8400268554688, la base
calculaba `-0,304428%`. La prueba de caracterización conserva esa aritmética
como evidencia del defecto, pero el lector canónico posterior devuelve
`unavailable` para esos caches same-day.

El snapshot de cuenta es otra autoridad: 70.634,91 − 70.534,69 = +100,22
(+0,142086%), capturado a las 20:27:17Z. La cabecera live observó después
aproximadamente 70.640,16 − 70.534,69 = +105,47. Ambos valores pueden ser
correctos en instantes distintos; ahora se muestran con `source` y `as_of`
distintos, sin presentarlos como una misma medición.

La comparación externa comunicada por dirección fue SPX aproximadamente
+0,21% y SPY de cierre aproximadamente +0,25%. No se consultó red en este
lote ni se sustituyó SPY por SPX: el instrumento del contrato es `SPY (ETF
S&P 500)`.

## Contrato implementado

El productor `performance_benchmark` exige, antes de publicar un benchmark
canónico:

- símbolo solicitado, fuente, intervalo diario (`1d`/`1D`) y rango que cubra
  el cierre anterior y la sesión objetivo;
- `created_at` válido, no futuro, y un par `previous/current` de la misma
  serie/campo y `price_basis` explícito (`adjusted_ohlc` o
  `close_unadjusted`);
- caches creados durante el mismo día de la sesión quedan `unavailable` salvo
  una marca durable explícita de finalización EOD; no se infiere una hora
  mágica a partir de una barra `00:00`;
- un cache posterior a la fecha UTC de sesión, con base explícita, puede ser
  `eod_authority=post_session_cache`. Barras futuras, rangos incompletos,
  basis desconocida, metadata ausente, campos incompatibles y timestamps
  futuros se rechazan;
- la selección es determinista por `created_at` semántico descendente y
  nombre solo como desempate. Nunca por el hash/nombre como autoridad.

El productor de nuevos caches declara `interval=1d` y `timeframe=1D`. No
reescribe los caches históricos ni hace backfill.

`overlay_eod_benchmark(row, settings, now=...)` es una proyección de
consumidor: copia el objeto, conserva `stored_benchmark` y el `content_hash`
original, y sustituye el benchmark solo si la lectura EOD pasa el contrato.
Si no pasa, elimina precios/retorno no verificables y deja la comparación
`unavailable`. Nunca escribe SQLite, no llama broker/red y no cambia el
evento canónico almacenado.

La UI usa el rowset proyectado para tabla, contadores y gráfica. La cabecera
de cartera live conserva su propia serie y muestra `cartera actual
(estimación del panel)` junto a su `as_of`; el panel diario se rotula como
cierre EOD y muestra fuente, basis y `as_of`. Telegram consume el mismo bloque
de benchmark, etiqueta `SPY (ETF S&P 500)` y marca `n/d` si no existe una
proyección EOD comparable; no reutiliza el escalar legacy `spy_pct`. SPX
queda como futura fuente/configuración y no se simula.

## Paridad y seguridad

El cambio queda limitado a `market_data` (metadata), `performance_benchmark`
(productor/overlay), `web_app` (consumidor read-only),
`telegram_daily_summary` (proyección semántica) y pruebas/documentación. No
se tocaron kernel, broker, execution, risk, config ni `.env`. No se modifican
señales, ranking, gates, sizing, planes, órdenes, fills, exposición, límites,
reconciliación, cadencia ni política.

El overlay no promueve datos provisionales a comparables. El 28-jul histórico
continúa incorrecto en storage hasta una autorización separada; no se borró,
reescribió ni backfilleó.

## Validación

- Base: producción exacta `87d2901894ed9f3b31000b31ba1cfb974b7c9b88`, árbol
  `fd690a939c9f887fc6929a8badfc1d1b79f76260`, versión `0.4.202`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl71_eod_authority`;
  rama `codex/pl71-eod-authority`; versión candidata `0.4.205`.
- Focales verdes: reproducción/contrato P-L71, P-L40B, P-L68, P-L63,
  P-L65A/R1/B, Telegram y web UI. Las pruebas nuevas cubren caches múltiples,
  basis/intervalo/rango ausentes, same-day, cache posterior, barra futura,
  overlay preservando storage, fuente común UI/Telegram y separación live/EOD.
- Suite final aislada: `2260 passed, 1 skipped, 1 warning` en `tests/ -x -q`.
  El único skip es preexistente, `tests/test_pre_earnings.py:1041`, porque la
  SQLite histórica local no está disponible en el `DATA_DIR` temporal. No se
  añadieron skip/xfail. `ruff check src tests`, `check_no_nulls.py`,
  `git diff --check`, `py_compile` y `validate-agent-config --json` temporal
  quedaron verdes.
- `kernel-status` temporal queda `unsealed` por ausencia normal de manifest;
  el mismo comando desde producción devolvió `ok/status=ok`, sin violaciones.
  Smoke real no se ejecutó: queda omitido por seguridad (no red, broker, LLM ni
  Telegram real); las focales cubren el overlay con caché/Store temporal.
- No se usaron broker, red, yfinance, LLM, SQLite productiva escritora,
  Telegram real, jobs manuales, despliegue, reinicio ni push.

Commits separados: `6e3fe35c` (caracterización/tests), `2dc59c7e`
(implementación), `39e9cc89` (QA de version policy) y el commit documental de
este informe/plan/relevo.

## P-L71-R1 - wiring Telegram corregido

La reproduccion contra `7beeb135` fue concluyente: `build_daily_summary`
tomaba el escalar legacy `row['spy_pct']` (-0,30 %) aunque el bloque
`performance_benchmark.benchmark` ya contenia el overlay EOD autoritativo
(+0,25 %, `post_session_cache`). El mensaje resultante etiquetaba el valor
falso como comparable.

La frontera comun ahora es `publish_daily_summary`: proyecta
`overlay_eod_benchmark` antes de construir el payload. El job de las 22:05 y
el fallback posterior al PMR llaman a esa misma funcion; no dependen de que
el caller copie `spy_pct`. `build_daily_summary` ignora siempre el escalar
legacy y solo publica `benchmark.daily_return` cuando existe un overlay
proyectado con estado comparable, autoridad EOD, source, as_of, price_basis y
quality validos. En cualquier otro caso publica `n/d/unavailable`.

La limitacion de las 22:05 queda documentada: caches same-day sin finality
durable producen `n/d`; el recibo idempotente de la sesion no se actualiza
despues ni se reenvia automaticamente cuando aparece un cache posterior. No
se inventa finality, no se hace backfill ni se reescribe `performance_daily`.

P-L70BR1 (`973d50d6`, schema v2) sigue siendo un candidato paralelo y no se
mezcla en este lote. Un futuro ensayo P-L70+P-L71 debe resolver conflictos
campo a campo y conservar UX, schema e idempotencia de P-L70.

Commits P-L71-R1: `f5095e60` reproduccion, `cad86726` fix y `76dee578`
pruebas de wiring.

## Estado externo y siguiente paso

Al preflight, XNYS estaba cerrado y la siguiente apertura era el 29-jul a las
15:30 CEST. El scheduler lock productivo tenía PID vivo y token coincidente;
los estados operativos observados no alteran este worktree. Producción conserva
su suciedad conocida y no fue modificada.

Siguiente lote único: ensayo de integración cerrado P-L71 con la rama exacta,
preflight seguro, suite completa y smoke exclusivamente temporal. No desplegar
hasta que ese ensayo confirme el árbol y la autoridad EOD.
