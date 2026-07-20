# P-L49B-W — implementación shadow del contrato de calidad por candidato

Estado: `ready_for_integration_rehearsal` en worktree aislado, versión `0.4.186`.

P-L49B-W implementa `p-l49b.data-quality-decision-shadow.v1` como telemetría
`shadow_only`, sin autoridad sobre decisiones, gates, riesgo, planes u órdenes.
La Fase A captura en memoria las observaciones exactas ya presentes en el ciclo;
la Fase B reutiliza esa captura después de la ruta activa y antes de registrar o
enviar planes. Los fallos de captura, hash, lectura o persistencia son fail-open
para el ciclo y producen `unavailable`/`partial` con warning, sin repetir ciclos
ni bloquear salidas SELL.

El evento canónico es `data_quality_decision_shadow:<cycle_id>` en
`agent_events`. La inserción usa `BEGIN IMMEDIATE` solo para la comparación e
inserción corta, sin tablas ni migraciones nuevas. Repeticiones con el mismo
hash son idempotentes y el contenido distinto queda como conflicto auditable.
La identidad de mercado combina proveedor, símbolo, intervalo, timestamp de
barra, price basis y OHLCV normalizado; no se reconstruye por símbolo/fecha.

El CLI `data-quality-decision-shadow-report --json` y operational health son
read-only. Sin eventos se informa `collecting` con denominadores `null`; una
base legacy no se reconstruye. `captured_at` queda fuera del hash y la frescura
expone `report_id`, `generated_at`, `as_of`, `consumer_read_at`, `age_seconds`,
`source_path`, `session_date` y `freshness_status`.

Las salidas `time_stop_v2` sanitizadas (DDOG, BNY, JPM y BAC) quedan
`not_applicable_exit`; P-L43, P-L44, P-L45, P-L47 y P-L48 no reciben cambios de
política.

La caracterización anterior queda conservada como antecedente; el candidato
actual es `0.4.186` y este lote sí contiene wiring shadow aislado.

## Alcance

La caracterización anterior definía fixtures y pruebas; P-L49B-W añade ahora el
wiring fail-open en `cycle_runner` y consumidores read-only de health, digest y
CLI. No conecta el contrato con gates ni órdenes como autoridad.
Las pruebas usan `Settings(_env_file=None)`, `DATA_DIR` temporal, reloj congelado y
proveedores locales. No acceden a la SQLite productiva ni a red, broker, yfinance o LLM.

## Flujo legacy caracterizado

`market data → validación OHLC → features → market_state → candidatos → ranking →
recomendaciones → gates → planes → órdenes`.

La reproducción conserva el comportamiento observado: `ohlc_invalid` puede quedar como
telemetría, `market_state=PARTIAL` permite continuar y `affects_operational_scan=true`
no tiene consumidor conectado a la decisión. Un informe generado después del ciclo no
se aplica retroactivamente. La fuente exacta del dato debe seguir siendo distinguible
de la fuente del candidato.

## Contrato propuesto

El snapshot contiene `schema_version`, `cycle_id`, `captured_at`, `content_hash`,
`market_data_snapshot_id`, `source`, `as_of`, `session_date`, denominadores de universo
y detalles por candidato. El detalle conserva la identidad de mercado y la identidad
del candidato por separado, además de la etapa legacy y el resultado shadow.

La identidad de observación incluye proveedor, símbolo, intervalo, timestamp de barra,
price basis y OHLCV normalizado. Distingue proveedores, adjusted/unadjusted, revisiones,
barras intradía y timestamps distintos; no une solo por símbolo/fecha.

`captured_at` queda fuera del hash. Repeticiones idénticas son no-op y contenido distinto
es conflicto auditable. La persistencia se limita al evento canónico append-only;
no se usa `INSERT OR REPLACE`.

## Semántica shadow preregistrada

- `eligible`: observación exacta, temporalmente válida y sin anomalía bloqueante.
- `blocked_exact_quality`: anomalía bloqueante exacta del símbolo/observación de entrada.
- `unavailable_identity`: falta o conflicto de identidad.
- `unavailable_temporal`: timestamp ausente, ingenuo, futuro o posterior a la decisión.
- `not_applicable_exit`: SELL/risk exit, stop-loss, take-profit, trailing o time-stop.
- `conflict`: identidad incompatible o revisión ambigua.

El shadow solo compara entradas. No modifica ranking, recomendaciones, gates, sizing,
microexperimentos, planes, órdenes, exposición ni posiciones. Los símbolos sanos siguen
siendo evaluables; una observación posterior no gobierna una decisión anterior; una
posición existente y sus salidas protectoras quedan fuera del hipotético gate.

## Casos y denominadores

Se cubren OHLC inválido en high/low/close/volume, null, NaN, Infinity, timestamps
ingenuos/futuros, stale, sesión previa, barra intradía incompleta, cierre temprano,
MultiIndex, columnas planas, duplicados, revisiones, proveedores y price basis.

La fixture de 500 símbolos reproduce 37 anomalías bloqueantes: 463 evaluables, 37
`shadow_blocked_count` y 463 sin cambio. EIX, MPC y PSX son finalistas técnicos sin
recomendación, plan u orden. Cuatro SELL `time_stop_v2` permanecen
`not_applicable_exit`.

Los denominadores faltantes permanecen `null`/`unavailable`; no se convierten en cero.

## Health y freshness

Se caracteriza `report_id`, `generated_at`, `as_of`, `age_seconds`, `current_session`,
`consumer_read_at`, `source_path` y `freshness_status`. Se distinguen latest válido,
latest stale, path inexistente, sesión distinta y health leyendo un informe anterior al
fichero latest. No se modifica health productivo.

## Conclusión

La caracterización confirma el hueco observado en P-L49A: `affects_operational_scan`
puede ser telemetría sin autoridad de decisión y `PARTIAL` permite continuar. El
candidato implementa ahora la observación shadow aislada, sin activar ningún gate
ni iniciar P-L48C; queda pendiente el ensayo de integración y cualquier despliegue.

## P-L49BR1 — ensayo aislado y QA adversarial (XNYS abierto)

- Ensayo `pl49br1_shadow_rehearsal`, rama `codex/pl49b1-shadow-rehearsal`, basado
  en producción `24537e81`; merge `--no-ff` del candidato exacto `938580b7` en
  `2ea57983`. QA adicional `b8aee78a` y métrica de persistencia `db6577b2`;
  la versión permanece `0.4.186`.
- La ruta real ejecuta Fase A después de construir `market_snapshot`/`market_state`
  y antes del ranking. El snapshot productivo actual expone calidad agregada y
  no la observación OHLC que alimentó cada feature; por contrato, la candidatura
  queda `unavailable_temporal`/`partial`, nunca `blocked_exact_quality`
  retroactivo. Las fixtures con observación exacta, hash y autoridad temporal
  válidos sí producen `blocked_exact_quality`.
- Fase B se sella después de recomendaciones, gates, controles y planes, y antes
  de persistir el plan/orden. Reutiliza la captura de Fase A, no relee informes
  posteriores, no muta objetos activos y es fail-open.
- QA adversarial: 52 pruebas P-L49B/P-L49BR1 y 431 regresiones focales verdes;
  Ruff, `check_no_nulls.py` y `git diff --check` verdes. La fixture de volumen
  (500 símbolos, 37 anomalías, 20 finalistas, 10 recomendaciones y 4 planes)
  produjo un evento de 35.908 bytes y preparación de Fase A de 77,62 ms en el
  entorno de ensayo; los candidatos planificados quedaron forzados dentro del
  detalle. Dos procesos SQLite dieron `inserted` + `idempotent`, sin conflicto
  ni lock residual.
- La identidad de observación normaliza timestamps equivalentes por zona y
  `-0.0`; duplicados exactos son no-op y revisiones económicas distintas no
  comparten identidad. Los SELL DDOG/BNY/JPM/BAC y los demás risk exits son
  `not_applicable_exit` y no sufren bloqueo ni retraso.
- `daily_learning` solo consume el digest read-only; no usa el shadow como
  feature, prior ni autoridad. Broker, execution y risk no contienen
  referencias P-L49. No se añadieron tablas, migraciones, threads, schedulers,
  órdenes ni backfill.
- La suite completa y el smoke quedan pendientes por XNYS abierto; la prueba
  histórica P-L45B2 de 33.336 filas se excluye únicamente en esta ventana,
  conforme al encargo, sin skip/xfail nuevo. Dictamen: pendiente de validación
  completa con mercado cerrado (`ready_for_closed_market_full_validation`).
