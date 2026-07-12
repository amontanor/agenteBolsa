# P-L33 - snapshot prospectivo de calidad de ejecucion

## Entrega P-L33B

Version: 0.4.165. La fuente unica es
`src/agente_bolsa/tools/execution_quality.py`. Construye
`p-l33b.execution-quality.v1` a partir de datos que el flujo ya tiene: plan
persistido, respuesta de submit y reconciliacion. No envia ordenes, no consulta
el broker y no cambia precios, cantidades, tipos de orden ni estados de
`order_plans`.

## Identidad y etapas

La cadena prospectiva conserva `signal_id`, `candidate_id`, `lineage_id`,
`recommendation_id`, `order_plan_id`, `client_order_id` y `broker_order_id`.
El ID de recomendacion se asigna una vez antes de gates y viaja embebido al
plan. El estado es `verified` solo con toda la cadena exacta; simbolo/fecha
nunca crean una union. Los registros previos sin instrumentacion permanecen
legacy.

Las etapas append-only son `planned`, `submitted`, `reconciled` y `terminal`.
Repetir el mismo evento es idempotente; una contradiccion queda advertida. Un
terminal no vuelve a un estado anterior. La reconciliacion registra, sin
corregirla, la divergencia de estado local `EXPIRED`/`SUBMITTED` frente a broker
`filled`.

## Metricas y limites

Para compras y solo con precios positivos/validos calcula
`signal_to_plan_bps`, `plan_to_fill_bps` y `signal_to_fill_bps`. Las ordenes
market conservan `submitted=null`; no se sustituye por el precio del plan. Las
latencias se invalidan al detectar orden temporal invertido. Los limites
pre-registrados de aviso son 300 segundos y 200 bps absolutos.

No hay fills individuales en el proveedor actual: se conserva un precio medio,
qty acumulada y timestamps disponibles, sin inventar `fill_id` ni primer fill.
La telemetria prohíbe retornos forward, MFE/MAE, veredictos, P&L, alpha y
benchmark. El fill nunca se propaga como outcome forward.

## Diagnostico y compatibilidad

`execution-quality-report --json` filtra por fechas, estado y estado de
linaje. El digest diario publica la misma cobertura de lectura. Al desplegar,
los 40 broker orders historicos se muestran como legacy y el estado es
`collecting`; no se completan retrospectivamente ni se consulta Alpaca.
