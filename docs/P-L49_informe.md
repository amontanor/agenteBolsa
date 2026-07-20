# P-L49B-T — caracterización del contrato de calidad por candidato

Estado: `ready_for_p49b_shadow_implementation` como caracterización aislada.
Versión del worktree: `0.4.185`; no se requiere bump para pruebas y documentación.

## Alcance

Este lote solo define fixtures y pruebas para `p-l49b.data-quality-decision-shadow.v1`.
No conecta el contrato con `cycle_runner`, scheduler, health, digest, gates ni órdenes.
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
es conflicto auditable. No se propone persistencia ni `INSERT OR REPLACE` en este lote.

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
puede ser telemetría sin autoridad de decisión y `PARTIAL` permite continuar. El lote
queda listo para una futura implementación shadow, sin activar ningún gate y sin iniciar
P-L48C.
