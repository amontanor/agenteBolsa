# P-L24 - Trazabilidad de duracion del ciclo de mercado

Version: 0.4.149 (P-L24R)

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
