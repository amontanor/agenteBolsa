# P-L24 - Trazabilidad de duracion del ciclo de mercado

Version: 0.4.151 (P-L24R3)

## Correccion P-L24R3

`cycle_runner.py` vuelve a tener una unica implementacion de cada llamada de
produccion: `optional_measure` aplica el segmento si existe registrador y un
contexto nulo si no. Se instrumentan tambien `update_signal_execution_status`
como `persistence/execution_status_updates` y el informe shadow como
`report_generation/learning_shadow_report`.

La integracion aislada ejecuta el flujo real `_auto_paper_trade` y comprueba:
recomendacion estructurada en `llm_decision`, revisiones/gates/planes en
`deterministic_gates`, escrituras en `persistence`, el informe shadow en
`report_generation`, fallo de segmento conservando los anteriores, solape cero
en el recorrido normal y equivalencia observable con `timing=None`. La llamada
`submit_paper_order_plan` se ejecuta pero no se atribuye a gates ni persistencia.
No se produjo una muestra operativa nueva durante el fin de semana.

## Correccion P-L24R2

Sin reescribir `scheduler.py`, se completan los segmentos concretos de CrewAI,
recomendacion estructurada, gates y persistencia. `tracked_duration_seconds` usa la
union de intervalos y `segment_overlap_count` declara solapes; los historicos sin
segmentos siguen `unavailable`. No cambia trading ni se inventa muestra real fuera
de mercado.

## Correccion P-L24R

Se restaura el bloque de scheduler a la referencia P-L23R, preservando mensajes,
payloads, tolerancia a fallos de breakout y comportamiento de noticias. Los hooks
solo inician/finalizan el tramo tecnico y propagan el mismo `cycle_id`.

Las etapas llevan segmentos: la llamada `request_trade_recommendations` se mide
como `structured_recommendations` dentro de `llm_decision`; la revision
determinista y adversarial se registran como segmentos de `deterministic_gates`.
El reporte anade `tracked_duration_seconds` y `unattributed_duration_seconds`,
siempre no negativo. El tiempo no instrumentado permanece explicito en vez de
atribuirse falsamente a gates o informes.

## Instrumentacion

Cada ciclo publica `market_cycle_timing_<cycle_id>.json` y actualiza
`latest_market_cycle_timing.json`. El payload conserva identificador, inicio,
fin, duracion total, estado final y version del sistema. Las etapas observadas
son `data_loading`, `technical_analysis`, `llm_decision`,
`deterministic_gates`, `persistence` y `report_generation`.

Las etapas llevan timestamps UTC, segundos, estado y evidencia de error o motivo
solo cuando corresponde. El cierre de ciclo no borra mediciones previas: ante
fallo, lo ya completado se conserva y lo no ejecutado se marca `skipped`.

## Consumo

`production-health` carga como maximo 20 reportes y muestra muestra disponible,
p50/p95/maximo de duracion total, conteo/porcentaje sobre 600 segundos, etapa
dominante por p50 y p95, y cobertura. El digest diario imprime esa misma lectura
de forma compacta; no propone optimizar ni cambia comportamiento operativo.

## Limites

Los ciclos anteriores a esta entrega no tienen desglose: se declaran
`unavailable`, sin atribuir duraciones retrospectivas. La primera muestra real
solo permite observar; se necesitara acumular ciclos instrumentados para evaluar
una etapa dominante con una muestra representativa.
