# Informe final P-L37 — identidad canónica de señal

## Alcance y estado

- P-L37A produjo el dictamen `partially_verified_capture` en solo lectura.
- P-L37B selló una captura inmutable por `signal_capture_id` y propagó la
  identidad literal por el flujo prospectivo.
- La validación P-L41R integra este lote antes de P-L40B, sin tocar la rama
  productiva ni los históricos.

## Contrato y garantías

`signal_id` identifica la señal lógica; `signal_capture_id` identifica una
captura concreta e incluye `schema_version`, señal, source run, fecha y
estrategia. `signal_source_run_id`, `cycle_id`, `candidate_id` y `agent_run_id`
permanecen separados. Un source run posterior añade otra captura y no sustituye
la anterior. El hash excluye timestamps mutables y los conflictos no
sobrescriben la entrada original.

La identidad se crea antes de persistir el informe técnico y se conserva en
`all_candidates`, `selected_candidates`, `top_longs` y `top_shorts`, además de
recomendación, lineage, contexto, gates, controles, plan, payload de broker,
execution quality y learning observation cuando el enlace es exacto. No se
recalcula aguas abajo ni se usan uniones por símbolo/fecha. Los registros
legacy se leen como `legacy_without_capture_history`; no se completa el pasado.

## QA y ensayo de integración

Las pruebas cubren dos ciclos de una señal, dos capturas resolubles tras el
segundo ciclo, ambigüedad de estrategias, copias profundas, merges recursivos,
conflictos y compatibilidad legacy. La validación focal de P-L37B fue verde
(15 pruebas) y el ensayo combinado P-L41R añadió 4 pruebas de integración; el
conjunto focal relacionado P-L30–P-L38 alcanzó 137 pruebas verdes. Las pruebas
usan Store temporal y no llaman red, LLM, broker ni servicios.

La paridad observada exige igualdad de score, ranking, orden de candidatos,
gates, geometría, decisiones, planes, cantidades, stops, takes y órdenes; la
única diferencia permitida son campos de identidad/telemetría. Un fallo de
telemetría es fail-open y no bloquea trading.

## Limitaciones

La captura prospectiva comienza después del despliegue. Históricos anteriores
pueden carecer de historial de captura o tener cobertura parcial y no deben
interpretarse como evidencia nueva. La cobertura, los conflictos y los estados
`collecting`/`unavailable` deben permanecer explícitos en digest y health.

## Integración nocturna

P-L37B se integró mediante merge no destructivo en
`codex/nightly-integration-rehearsal` antes de P-L40B. La resolución conjunta de
`storage.py` conserva tanto el merge recursivo de identidad como la serialización
segura del benchmark. No se modificaron archivos protegidos, `adaptive_config`,
estrategias, gates, límites ni órdenes.
