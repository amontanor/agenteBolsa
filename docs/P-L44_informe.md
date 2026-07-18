# P-L44 — observación shadow de penalización de aprendizaje

Estado: desplegado en producción `0.4.177` en modo shadow (17-jul-2026).

## Alcance

P-L44B-W2 añade `p-l44b.learning-penalty-cycle-shadow.v1`. En cada ciclo se
observan los candidatos BUY que ya llegaron al ranking, sin volver a ejecutar
análisis, selección, gates, LLM, sizing ni planes. La política activa sigue
siendo `legacy_double_application`; `single_application` sólo produce
telemetría.

## Captura y límites

El hook está en el scheduler inmediatamente después de obtener el contexto
ranked y registrar señales, antes de persistir el informe técnico y antes de
construir planes. La observación exige `signal_capture_id` o `signal_id` exacto;
`candidate_id` puede enriquecer el linaje posterior, pero no sustituye la
identidad canónica. El denominador conserva todos los BUY rankeados; el detalle persistido es la unión
de top-20 legacy, top-20 shadow, seleccionados y controles comparables. No se
guardan P/L, fills, slippage, retornos forward, MFE/MAE, outcomes maduros ni
prompts.

## Persistencia y lectura

Los snapshots se escriben como un evento por `cycle_id` en `agent_events`.
Repetición idéntica es no-op; un contenido distinto conserva el original y
añade un evento de conflicto auditable. `runtime_state` no interviene. El
digest, operational health y `learning-penalty-shadow-report --json` leen sólo
eventos válidos; sin observaciones publican `collecting` y denominadores
`null`, sin backfill.

## Seguridad

El resultado shadow nunca entra en la selección activa, entry quality, sizing,
microexperimentación, gates, capacidad, planes u órdenes. Los errores de
telemetría se registran como fail-open y dejan continuar el ciclo. P-L43B
mantiene `legacy_calendar_days` activa y XNYS exclusivamente shadow.

La evidencia real queda `collecting` hasta observar ciclos posteriores al
despliegue; no se interpreta como edge ni como autorización para corregir la
fórmula legacy.

## P-L44BR2 — ensayo limpio sobre P-L43B desplegado (15-jul-2026)

La rama `codex/pl44b-shadow-integration` integra mediante `merge --no-ff` el
HEAD `451d774d` sobre producción P-L43B `4dc29f05`. No se detuvieron ni
reiniciaron servicios, no se accedió a SQLite productiva y no se activó la
penalización única. El resultado queda `ready_for_future_shadow_deployment`.

La suite combinada, el volumen sintético 600×2, la persistencia conflict-safe,
el CLI `learning-penalty-shadow-report --json`, el smoke aislado y las
regresiones de P-L43B pasan. La política activa continúa
`legacy_double_application`; `single_application` es exclusivamente
`shadow_only` y los datos reales permanecen `collecting`.

## P-L44BR1 — temporalidad del wiring shadow (15-jul-2026)

La captura se separa en dos fases para evitar atribuir decisiones que todavía
no existen:

1. **Fase A (pre-decisión):** el scheduler entrega la lista BUY ya ordenada
   por el flujo activo. El comparador calcula legacy/shadow una sola vez en
   memoria, conserva ese orden como autoridad de `legacy_rank` y no persiste
   ningún evento provisional.
2. **Fase B (post-selección, pre-orden):** dentro de `run_observable_cycle`,
   después de LLM/fallback, gates, `build_order_plans`, límites, cuotas,
   pausas y `comparable_control_set`, se adjuntan únicamente hechos reales y
   se persiste un único evento por `cycle_id`. No se recalculan scores, ranks,
   gates, selección ni controles.

Autoridad de campos: `selected_by_decision` procede de recomendaciones BUY
finales; `planned_by_active_path` procede de planes BUY finales;
`comparable_control` procede exclusivamente de controles v2 materializados;
`blocked_candidate` y `final_non_execution_reason` requieren un rechazo o
snapshot de gate con `candidate_id`/`signal_id` exacto; `decision_source` solo
se publica cuando está persistido en la recomendación/linaje. La ausencia de
identidad permanece `unavailable` y nunca se resuelve por símbolo o fecha.

Si el ciclo termina antes de la Fase B se conserva como máximo un evento
`partial` con `phase_b_unavailable`; un fallo de persistencia o telemetría es
fail-open y no altera trading. Las repeticiones idénticas son no-op y los
conflictos no sobrescriben el evento original. El detalle sigue acotado a la
unión de top-20 legacy/shadow, seleccionados, planes y controles reales, sin
campos post-decisión.

### Corrección de auditoría P-L44BR1

La fase B exige `cycle_id` exacto en recomendaciones, planes y controles; los
registros de otro ciclo o sin identidad quedan `partial/unavailable` y no se
atribuyen. Los snapshots de gates solo marcan `blocked_candidate` cuando el
enlace del gate es fuerte, y un candidato bloqueado nunca se publica como
control primario. `decision_source` se toma de la recomendación real
(`decision_source`, `source` o `decision_origin`) y las rejections del
productor conservan `candidate_id`, `signal_id` y `cycle_id` cuando existen.
El orden shadow trata el rango cero como un valor válido y no como ausencia.

## P-L44BR3 - corrección del contrato lector (candidato 0.4.181, 18-jul-2026)

La auditoría del ledger confirmó un `reader_contract_gap`: el consumidor
descartaba candidatos antes de evaluar su identidad cuando faltaban
`rank_priority_score` y `learning_prior`; además, el reporter genérico añadía
una segunda fila con el mismo `event_type` y duplicaba los denominadores.

La corrección evalúa primero `signal_capture_id` y después `signal_id` exactos.
Un `candidate_id` aislado no crea identidad. Un candidato identificado sin
inputs de scoring conserva `identity_verified` y se clasifica como
`shadow_inputs_unavailable`; ausentes o ambiguos quedan separados, sin unión
por símbolo/fecha. El `cycle_id` interno, si existe, debe coincidir con el
ciclo exterior.

El lector acepta únicamente eventos canónicos con schema, id y
`content_hash` válidos, deduplica por `cycle_id` y conserva conflictos sin
escoger silenciosamente el último. Las filas genéricas se mantienen por
compatibilidad, pero se publican como `generic_reporter_rows_ignored` y no
entran en digest/health/CLI. Los denominadores separan `identity_verified`,
`identity_unavailable`, `identity_ambiguous`, `shadow_inputs_available`,
`shadow_inputs_unavailable` y `shadow_inputs_invalid`; sin eventos el estado
es `collecting` con denominadores `null`, y con identidad sin inputs es
`partial`.

Los denominadores anteriores quedan invalidados para interpretación histórica;
no se hace backfill. `legacy_double_application` sigue activa y
`single_application` continúa exclusivamente shadow, sin evidencia para
activarla. P-L43BR6 permanece pendiente y prioritario como `0.4.180`.

## P-L44BR3 - despliegue cerrado sobre producción 0.4.176 (17-jul-2026)

El ensayo `codex/pl44b-integration-rehearsal` (`4aebb7e53fb291f6a58c660a1d64cd4564cb6d09`,
tree `730e929a9b159ed6154bd8106e80398eadc37472`) se fusionó en producción
mediante `--no-ff` en `23e4bf4df07292a6f42a2dec566e1be55b769ef9`. La versión
final es `0.4.177`; P-L45B1/P-L45B2 y P-L43BR5 permanecen desplegados, y P-L46B
UI queda reservado para `0.4.178`.

La fase A calcula el comparador sólo en memoria sobre BUY ya rankeados; la fase
B se materializa después de recomendaciones, gates, límites, cuotas, pausas,
planes y controles reales, antes de persistir/enviar órdenes. La identidad
requiere `candidate_id`/`signal_id` y `cycle_id` exactos. El evento es append-only
por ciclo, idempotente y conflict-safe; `runtime_state` sigue siendo únicamente
`latest_view`. El snapshot no contiene P/L, fills, slippage, retornos forward,
MFE/MAE, outcomes maduros ni prompts/LLM.

La suite completa del árbol fusionado pasa con `1535 passed` (sin skips nuevos);
las focales P-L44, P-L43 y P-L45, Ruff, NUL, `git diff --check`, kernel y
configuración también pasan. El stack reiniciado responde HTTP 200 con un único
scheduler y heartbeat fresco. La evidencia real continúa `collecting`;
`legacy_double_application` sigue siendo la política activa y
`single_application` permanece exclusivamente shadow, sin decisiones ni órdenes
atribuibles al comparador.

## Despliegue secuenciado P-L44BR3 (0.4.182)

El lector corregido se desplegó junto con P-L43BR6 sobre P-L47B1 mediante el
merge productivo `7cc432aee3f594d946f5a65d1f86f3e49fa82e4`, tree funcional
`bc2d15ffd0d43f10359761b61efc07b0384c5072` y versión `0.4.182`.

La secuencia es inequívoca: P-L47B1 `0.4.180`, P-L43BR6 `0.4.181` y P-L44BR3
`0.4.182`. `legacy_double_application` sigue siendo la política activa y
`single_application` continúa exclusivamente shadow. La lectura histórica
canónica permanece `partial` con 26 ciclos y 26 eventos; no se hace backfill,
no se reescriben eventos y no se atribuyen decisiones u órdenes al shadow.
