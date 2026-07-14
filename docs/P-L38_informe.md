# P-L38 - cierre de promocion autonoma no autorizada y atribucion postmarket

Estado P-L38B1: implementado en v0.4.170. Estado P-L38B2: implementado en
v0.4.171. La frontera de autorizacion de B1 permanece intacta.

## Causa y frontera

`post_market_review` llamaba a `promote_post_market_improvements`, que podia
construir parametros activos y delegaba la escritura en `save_adaptive_config`.
La funcion de escritura no comprobaba `allow_auto_apply_improvements`, por lo
que el bloqueo del apply de codigo no cubria la configuracion adaptativa.

La frontera unica ahora es `adaptive_tuning.save_adaptive_config`. Requiere
`type(settings.allow_auto_apply_improvements) is bool` y el valor literal
`True`. La promocion y el tuning/CLI tambien salen antes de mutar el payload.
Con cualquier otro valor se devuelve `status=blocked_by_policy` y no se crea,
abre, modifica ni activa el archivo.

## Escritores auditados

| Camino | Funcion | Resultado P-L38B1 |
|---|---|---|
| Postmarket | `post_market_review.build_post_market_review` -> `promote_post_market_improvements` | protegido; bloqueo tolerado |
| Tuning/CLI/UI | `update_adaptive_config` | protegido; bloqueo antes de generar/escribir |
| Helper directo | `save_adaptive_config` | frontera fail-closed, tambien sin `settings` |
| `config.get_settings` | `active_adaptive_overrides` | solo lectura; no es escritor |
| Watchdog/factory/codegen | no escriben este JSON | apply de codigo sigue bloqueado por su propia politica |

No se encontraron otros escritores directos de `adaptive_config.json`.

## Estado real preservado

`data/state/adaptive_config.json` no fue escrito ni reserializado. En la lectura
actual hay seis overrides activos, todos con procedencia funcional verificable
en `post_market_review.promote_post_market_improvements` y fechas persistidas:

Huella observada tras las pruebas y el reinicio: SHA-256
`60833B60F83EDB1B5ECBE0785BDACD68F58AF6D5DFB307649749A8DBF6C7F4D0`, mtime UTC
`2026-07-13 20:45:28`, 9295 bytes.

| Parametro | Fecha | Base | Efectivo | Clasificacion | Gobierno |
|---|---|---:|---:|---|---|
| LLM_EXIT_EXCEPTION_MIN_CONFIDENCE | 2026-07-13 | 0.95 | 0.95 | equivalent | preexisting_unauthorized |
| LLM_EXIT_EXCEPTION_MIN_DRAWDOWN | 2026-07-13 | 0.08 | 0.08 | equivalent | preexisting_unauthorized |
| ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE | 2026-07-13 | 0.08 | 0.08 | equivalent | preexisting_unauthorized |
| ENTRY_QUALITY_EXTENDED_MIN_RELATIVE_RETURN | 2026-07-13 | 0.02 | 0.02 | equivalent | preexisting_unauthorized |
| ENTRY_QUALITY_EXTENDED_MIN_VOLUME_Z | 2026-07-13 | 0.00 | 0.00 | equivalent | preexisting_unauthorized |
| MAX_ORDERS_PER_CYCLE | 2026-07-10 | 4 | 2 | stricter | preexisting_unauthorized |

No override `looser` fue observado. Por tanto no hay
`critical_existing_unauthorized_override` en la muestra actual, pero todos los
activos preexistentes quedan marcados como no autorizados mientras la politica
sea falsa. No se retira ni corrige ninguno. `adaptive_auto_apply_authorized` es
`false`; el estado de gobernanza es `degraded_governance`.

## LLM y bloqueo

El campo LLM `minimal_improvements[*].auto_apply` se normaliza a
`requested_auto_apply`; se anade `authorized_auto_apply=false`. El LLM no puede
conceder autorizacion humana. Una promocion bloqueada devuelve motivo estable,
numero de peticiones, `blocked_promotion_attempts` y `write_performed=false`;
postmarket puede continuar y registrar la evidencia.

## Pruebas

Las regresiones cubren valores falsos, ausentes y no booleanos, archivo y mtime
intactos, autorizacion literal `True`, cinco propuestas sin escrituras,
caminos alternativos, clasificacion determinista, normalizacion del LLM y
bloqueo tolerado. En informes anteriores al despliegue, el contador de
intentos bloqueados permanece `unavailable` hasta que un postmarket nuevo lo
emita; no se convierte en cero. La suite completa termino con **1262 passed** y un warning de
dependencia en 250.28 s. Las pruebas existentes del apply de codigo siguen
exigiendo `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.

No se ejecutan LLM, codegen real, apply, broker, red ni ordenes. No cambia
trading, estrategias, gates, ranking, limites ni exposicion.

## P-L38B2 - atribucion y agregacion canonica postmarket

### Causa corregida

El informe trataba cada fila de `trade_memory` como una operacion y llamaba a
`_rebuild_signal_cohorts(include_learning_experiment=False)` para el ledger
obligatorio. Eso produjo tres evaluaciones para dos ordenes reales (AIZ estaba
fragmentada) y ocultó las 83 recomendaciones y siete rechazos de la sesión del
13-jul al excluir globalmente la fuente `learning_experiment`.

### Unidad y procedencia

La evaluación canónica se agrupa exclusivamente por `broker_order_id`. Las
filas de actividad se conservan en `activity_fragments` y
`activity_count`; no se unen filas sin ID por símbolo/fecha. La cadena de IDs
se extrae de la orden local y su payload: `exit_trigger`, `broker_order_id`,
`order_plan_id`, `recommendation_id`, `signal_id`, `candidate_id`,
`lineage_id`, `cycle_id`, `decision_source` y `non_execution_reason`.

`time_stop_v2` se normaliza determinísticamente como `automatic_time_stop`.
Las pérdidas de una venta no cambian su origen a manual: una salida automática
con pérdida usa `venta_automatica_con_perdida`; sin trigger queda
`unknown_exit_origin`. Si el LLM contradice el trigger, se conserva el valor
determinista y se marca `llm_attribution_conflict`.

### Denominadores de sesión

La revisión canónica consume `trade_recommendations` y los eventos
`paper_auto_trade_completed` de la sesión exacta, sin depender del filtro de
cohortes. Publica por separado:

| Campo | Significado |
|---|---|
| `recommendations_raw` / `recommendations_unique` | filas persistidas frente a deduplicación por ID |
| `cycles_unique` | ciclos con recomendación |
| `candidate_signals_unique` | solo signal IDs verificables; placeholders `UNKNOWN` quedan unavailable |
| `rejected_plans_raw` / `rejected_plans_unique` | eventos de rechazo frente a clave de ciclo/plan |
| `executed_treatments` | órdenes con broker ID |
| `non_executed_candidates` | recomendaciones con ID que no enlazan a tratamiento |
| `blocked_candidates` | rechazos únicos, separados de no ejecutados |
| `unavailable_identity_count` / `legacy_unverified_count` | identidad ausente o heredada sin imputación |

La fixture real del 13-jul conserva `83` recomendaciones raw y `7` rechazos
únicos (`14` filas de eventos). `learning_experiment` queda incluido; no se
publica cero por excluirlo.

### Informe, digest y health

El informe añade `execution_attribution`, `candidate_attribution` e
`immature_outcome_count`, incluyendo `canonical_trade_evaluations`,
`activity_fragments`, `duplicate_fragment_count`, cobertura del trigger,
conteos automático/manual/desconocido y conflictos LLM. Digest y health
exponen el mismo bloque compacto con estados `healthy`, `collecting` o
`degraded_attribution`; los denominadores desconocidos permanecen `null`.

Los retornos forward inmaduros siguen siendo `null`. Fill, P/L y memoria de
ejecución no se convierten en `return_1d/3d/5d/10d` ni en features previas.

### Protección de P-L38B1

La nueva revisión solo lee y calcula. `promote_post_market_improvements`
continúa pasando por la frontera fail-closed de B1; con
`ALLOW_AUTO_APPLY_IMPROVEMENTS=false` la ejecución de la revisión no crea ni
modifica `adaptive_config.json`. La regresión temporal verifica bytes y mtime
intactos.

### Pruebas y límites

Se añadió `tests/test_postmarket_canonical_attribution.py` con fixtures
independientes para dos órdenes/tres fragmentos, AIZ/CRWD, conflicto de LLM,
IDs ausentes, 83 recomendaciones/7 rechazos y protección de configuración.
Las pruebas focales pasan (18) y la suite completa termina con **1268 passed** y un warning de dependencia.
No se ejecutan LLM, broker, red, codegen, apply u órdenes. No se modifican
históricos ni archivos protegidos; P-L38B2 no cambia gates, ranking, límites ni
trading.
