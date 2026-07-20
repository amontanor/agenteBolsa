# P-L50T — caracterización de la frontera de linaje e inputs

Fecha de la ejecución: 20-jul-2026, con XNYS abierto. Este documento describe
una caracterización aislada y no propone activar ninguna política de aprendizaje.

## Alcance y aislamiento

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl50t_lineage_characterization`
- Rama: `codex/pl50t-lineage-characterization`
- Base: `24537e813ff0905696cda0b3925a212045ee7b09` (producción, 0.4.185)
- Cambios permitidos: fixtures sanitizadas, pruebas y este informe.
- No se leyó SQLite productiva para construir fixtures ni se ejecutaron ciclos,
  broker, red, LLM, reconciliación, postmarket, smoke o scheduler.

La producción conservaba exclusivamente los cambios ajenos declarados en
`src/agente_bolsa/web_app.py` y `tests/test_web_app.py`. Se clasificaron como
`external_preexisting_dirty_worktree` (cambio UI “Desde inicio”); no se tocaron,
copiaron, stagearon ni incluyeron.

## Frontera observada

La siguiente matriz usa solo IDs exactos. Una ausencia no se completa por
símbolo, fecha o texto libre.

| Frontera | cycle_id | signal_capture_id / signal_id | candidate_id | recommendation_id | plan_id | action | Hallazgo |
|---|---|---|---|---|---|---|---|
| technical/raw candidates | producido por el ciclo | depende del productor | depende del productor | — | — | — | objeto técnico inicial |
| contexto anotado con aprendizaje | heredado si la copia lo conserva | aparece en la copia enriquecida cuando existe | idem | — | — | — | inputs de prior/rank pueden estar disponibles |
| contexto rankeado / fase A P-L44 | `cycle_id` exterior conocido; interno no uniforme | en la evidencia P-L44 no llegó de forma utilizable | no uniforme | — | — | — | P-L44 recibe el objeto equivocado para identidad: 5.312 `identity_unavailable` |
| recomendación | presente en linaje cuando se construye | `signal_capture_id`/`signal_id` canónicos en 48/51 recomendaciones del día | presente en esas 48 | producido aquí | — | BUY/HOLD/EXIT | el linaje se completa después de la fase de shadow |
| gate/rechazo | presente cuando se persiste | parcial en rechazos | candidate/signal/cycle parciales | no uniforme | no uniforme | decisión/reason | 12 filas raw, 6 identidades exactas |
| plan | heredado | heredado si el plan enlaza el linaje | heredado | heredado | producido aquí | acción del plan | `plan_id` solo existe después de decidir |

Código consistente con esta secuencia: `_selected_candidates()` crea la copia
anotada y la guarda temporalmente en `_learning_penalty_ranked_context`; la fase
P-L44 se prepara en `_prepare_learning_penalty_cycle_shadow()` leyendo
`all_candidates`/`ranked_candidates`. La recomendación construye posteriormente
decision lineage. Por tanto, que el lector de P-L44 vea cero IDs no demuestra que
el productor técnico jamás los tuviera: demuestra una frontera de wiring que no
propaga el mismo objeto enriquecido hasta fase A.

## Caso masivo P-L44

La fixture contiene 443 candidatos y prueba por separado identidad e inputs:

| Clasificación | Fixture |
|---|---:|
| `identity_verified` | 425 |
| `identity_unavailable` | 8 |
| `identity_ambiguous` (duplicado o `cycle_id` interno distinto) | 10 |
| `shadow_inputs_available` | 420 |
| `shadow_inputs_unavailable` | 23 |

La lectura productiva del 20-jul tuvo 12 ciclos completos. El ledger P-L44
contabilizó 5.312 candidatos como `identity_unavailable`, todos también sin
inputs shadow. El hallazgo reproducible es un **defecto de productor/wiring**:
la fase A consume el contexto rankeado sin la identidad canónica que sí aparece
en la ruta de recomendación. No es una ausencia real de IDs en todos los
candidatos ni un problema que pueda resolverse con un join por símbolo/fecha.

La caracterización separa explícitamente:

- `identity_verified`: `signal_capture_id` o `signal_id` verificable y
  `cycle_id` coherente;
- `identity_unavailable`: ambos IDs canónicos ausentes;
- `identity_ambiguous`: duplicación o conflicto de ciclo;
- `shadow_inputs_available`: identidad válida y rank/prior estructurados;
- `shadow_inputs_unavailable`: identidad válida pero inputs ausentes, o
  identidad no verificable.

## Colisión VTRS

Fixture sanitizada: mismo `cycle_id`, `signal_capture_id` y `candidate_id`, con
dos `recommendation_id` distintos y acciones BUY y EXIT. La identidad de señal
colisiona (`ambiguous`), mientras que las decisiones pueden distinguirse por
`recommendation_id` + `action`. El resultado correcto es **conflict/ambiguous**,
sin deduplicar silenciosamente ni escoger la última recomendación. La señal no
es por sí sola una unidad de decisión.

## Rechazos duplicados

Se reprodujeron 12 filas raw como 6 rechazos únicos por la clave exacta
`(cycle_id, candidate_id, signal_id, reason_code, stage)`. Cada rechazo canónico
tiene un `event_id` `rejection:<cycle>`; su copia genérica usa un `evt_*` distinto.

| Medida | Valor |
|---|---:|
| filas raw | 12 |
| canónicas | 6 |
| genéricas ignorables por denominadores | 6 |
| únicas por identidad exacta | 6 |

La deduplicación segura requiere el evento canónico y la clave exacta; reason
text, símbolo o fecha no son sustitutos. Si digest/health suman ambas familias,
duplican denominadores; el lector debe contar una sola fila canónica e informar
las genéricas ignoradas.

## Score, prior y controles

`candidate_rank` llega como campo estructurado. En las 43 BUY del 20-jul,
`score_rank` no está estructurado; 34 razones contienen un número que se parece
a score, pero el texto libre no es fuente válida. Los 9 BUY restantes tampoco
tienen score numérico estructurado.

El prior no es uniforme: la observación del día contiene 44 decisiones con
prior; 35 tienen `expected_edge_3d=-0.0507`, penalización 0.05 y muestra 27.957,
y 9 tienen edge 0.002, penalización 0 y muestra 3.309. Campos ausentes se
mantienen `null`; nunca se convierten en cero ni se parsea el texto.

La cobertura de controles se reproduce con 51 recomendaciones:

| Estado | Cantidad |
|---|---:|
| control explícitamente `unavailable` | 1 |
| sin registro de control | 50 |
| control verificado | 0 |

Con esta evidencia no puede distinguirse en las 50 ausencias si el control no
se generó, no se persistió o perdió identidad; se clasifica como
`unavailable`, no como control comparable.

## Freshness

Fixture descriptiva de una compra: `signal_at → submitted_at = 8603.999671 s`
(aprox. 143,4 min), precio de señal/recomendación/plan idéntico y sin timestamp
verificable de una cotización nueva. Resultado:

```text
stale_signal=true
price_refresh_status=unverified
decision_unchanged=true
```

Es telemetría descriptiva: no crea gate, no cambia sizing y no usa P/L,
fills posteriores ni retornos futuros.

## Paridad y seguridad

Las pruebas trabajan sobre copias profundas en memoria. No invocan ranking,
gates, RiskManager, planes u órdenes; no escriben SQLite y no añaden campos a
objetos enviados a consumidores activos. No contienen P/L, fills posteriores,
retornos forward, MFE/MAE ni prompts/LLM. P-L43, P-L44 activo, P-L45, P-L47,
P-L48 y P-L49 quedan fuera del helper y sin cambios.

## Dictamen y alcance mínimo futuro

**Dictamen: `mixed_contract_gap`.** Hay una causa primaria de productor/wiring
(objeto sin linaje en la frontera P-L44) y defectos contractuales secundarios
(identidad de decisión VTRS, scores/prior no uniformes y controles ausentes).

El único lote futuro mínimo sería un **P-L50B shadow-only** que transporte una
estructura inmutable con IDs exactos y `action` desde el contexto anotado hasta
fase A; valide `cycle_id`, separe identidad de inputs, marque colisiones de
decisión y reporte controles ausentes sin inferencia. El mismo lote puede
deduplicar solo eventos de rechazo canónicos por identidad exacta y exponer
freshness `stale_signal`/`unverified` como telemetría. No debe modificar ranking,
selección, gates, sizing, planes, órdenes ni activar políticas.

No se cambió la versión: P-L50T no requiere bump; P-L50B queda reservado como
mínimo para 0.4.188.

## P-L50B - propagación shadow de linaje e inputs (candidato 0.4.188)

P-L50B corrige la causa determinista observada por P-L50T: el scheduler copiaba
el contexto rankeado antes de que `record_signal_candidates` incorporase la
identidad canónica, por lo que la fase A de P-L44 recibía el objeto anterior al
enriquecimiento. La identidad se prepara ahora una sola vez en la frontera del
productor, antes de la anotación y el ranking, y se reutiliza al persistir la
captura. La fase A recibe una proyección profunda, acotada e independiente; no
recalcula aprendizaje ni muta los objetos del camino activo.

El evento pasa a `p-l44b.learning-penalty-cycle-shadow.v2`. El lector conserva
compatibilidad explícita con v1 para identidad e inputs, mientras decisiones,
controles, rechazos y freshness se publican solo cuando el contrato v2 los
demuestra. La identidad de señal mantiene `signal_capture_id -> signal_id`;
`candidate_id` es auxiliar. La identidad de decisión añade `action` y
`recommendation_id`, por lo que BUY y EXIT de VTRS permanecen separados y
auditables.

La fixture masiva de 443 candidatos produce exactamente: 425
`identity_verified`, 8 `identity_unavailable`, 10 `identity_ambiguous`, 420
`shadow_inputs_available` y 23 `shadow_inputs_unavailable`. Doce filas raw de
rechazo se reducen a seis eventos canónicos; seis filas genéricas se ignoran en
denominadores. Los controles distinguen `comparable`, `unavailable`,
`not_generated`, `identity_unavailable` y `persistence_missing`. Freshness es
descriptiva: 8603.999671 segundos produce `stale_signal=true` y
`price_refresh_status=unverified`, sin gate ni efecto operativo.

La persistencia sigue append-only en `agent_events`, prepara y serializa fuera
de SQLite y usa `BEGIN IMMEDIATE` solo para la inserción/conflicto corto. Una
repetición idéntica es idempotente y un contenido distinto conserva el original
y registra conflicto. No hay tablas, migraciones, backfill ni uso de
`runtime_state` como historia.

Validación durante XNYS abierto: 28 pruebas dedicadas P-L50/P-L44 y una batería
focal amplia de 451 pruebas pasaron; Ruff completo, `check_no_nulls.py` (400
archivos), `git diff --check` y `validate-agent-config` aislado quedaron verdes.
La suite completa y el smoke no se ejecutaron por la restricción operativa.
Dictamen del candidato: `ready_for_integration_rehearsal`; no autoriza despliegue
ni activación de `single_application`.

## P-L50BR1 - convivencia con P-L49B y P-L46BR3

El worktree combinado integra P-L49B (0.4.186) y P-L46BR3 (0.4.187) antes de
este lote (0.4.188). P-L49 conserva su identidad de observación OHLCV exacta;
P-L50 conserva `signal_capture_id -> signal_id`, `cycle_id` y la identidad de
decisión por acción/recomendación. Ningún shadow usa la identidad del otro ni
se unen por símbolo/fecha. La batería combinada cubre 500 símbolos, 37
anomalías, 443 candidatos, BUY/EXIT, planes, controles y rechazos; obtuvo 607
pruebas focales y 3 pruebas específicas de interacción.

Fallos aislados de cualquiera de los dos shadows son fail-open para el camino
activo. La persistencia es append-only y no colisionan los event IDs. P-L46BR3
permanece lectura/presentación únicamente. Suite completa, smoke y despliegue
quedan pendientes para XNYS cerrado.

## Validación ejecutada

- Pruebas nuevas P-L50T: **9 passed**.
- Focales permitidos (P-L44 shadow, lineage, controls, gate snapshots, daily
  learning, operational health y digest): **66 passed**.
- `py_compile` del test: OK.
- `check_no_nulls.py`: OK (399 archivos).
- `git diff --check`: OK.
- Ruff: no disponible en el entorno aislado (no existe ejecutable ni módulo
  `ruff`); no se sustituyó por una descarga durante mercado abierto.
- Suite completa, smoke y jobs reales: no ejecutados por la restricción de
  XNYS abierto.
