# P-L38B1 - cierre de promocion autonoma no autorizada

Estado: implementado en v0.4.170. P-L38B2 (agregacion postmarket y recuperacion
de candidatos) no forma parte de este lote.

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
