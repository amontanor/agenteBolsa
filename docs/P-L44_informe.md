# P-L44 — observación shadow de penalización de aprendizaje

Estado: candidato aislado `0.4.174`, pendiente de ensayo nocturno e integración.

## Alcance

P-L44B-W2 añade `p-l44b.learning-penalty-cycle-shadow.v1`. En cada ciclo se
observan los candidatos BUY que ya llegaron al ranking, sin volver a ejecutar
análisis, selección, gates, LLM, sizing ni planes. La política activa sigue
siendo `legacy_double_application`; `single_application` sólo produce
telemetría.

## Captura y límites

El hook está en el scheduler inmediatamente después de obtener el contexto
ranked y registrar señales, antes de persistir el informe técnico y antes de
construir planes. La observación exige `candidate_id` o `signal_id` exacto. El
denominador conserva todos los BUY rankeados; el detalle persistido es la unión
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
