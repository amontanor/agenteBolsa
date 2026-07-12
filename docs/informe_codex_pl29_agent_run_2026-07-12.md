# P-L29 - ciclo de vida central de agent_run

## Alcance y baseline

P-L29B parte de una cobertura normalizada de `agent_run_id` del 0%: 162.800
`AgentEvent`, 718 tareas CI y 1.932 usos LLM historicos carecen de un ciclo de
ejecucion comun. Esos datos permanecen legacy y no se reconstruyen como runs.
La entrega instrumenta solo los puntos centrales acordados: ejecucion CrewAI
completa, ejecutor de tareas CI, conversion `findings_to_proposals`, fallback
central verificable y consulta/digest. No anade hooks a los 23 agentes.

## Fuente unica y persistencia

`agent_run.py` contiene `AgentRunTracker` y la reconstruccion de productividad.
La persistencia reutiliza `Store.record_agent_event` y la tabla existente
`agent_events`; no hay tabla ni migracion nueva. Cada run usa el schema
`p-l29b.agent-run.v1` y emite `agent_run_started` seguido por exactamente un
terminal `succeeded`, `failed`, `timeout`, `skipped` o `blocked`. Las
repeticiones compatibles son idempotentes y los cierres contradictorios se
registran como conflicto sin sobrescribir datos.

Los timestamps son UTC y la duracion se calcula con reloj monotono. La
telemetria es best-effort: un fallo de persistencia se registra localmente, no
altera el resultado principal y nunca oculta la excepcion original. El terminal
solo se emite despues de persistir el resultado principal de una tarea CI.

## Integraciones y procedencia

- CrewAI: un run `crew_orchestrator`, `execution_kind=llm`, conserva `cycle_id`,
  modelo cuando existe y una referencia segura al log; `--skip-crew` es
  `skipped`. Un fallo queda `failed` y el fallback directo se registra como
  evento vinculado al mismo run, sin convertir el intento LLM en exitoso.
- CI: cada intento central recibe un ID distinto; `task_id` y `event_id` son
  referencias, `retry_of` se conserva, y bloqueos/omisiones no se mezclan con
  fallos. El tipo cambia a `llm` solo cuando el resultado existente demuestra
  una llamada real.
- Findings: el tracker se crea antes de medir. `origin_run_id` es exactamente
  `agent_run_id`, `source_event_ids` contiene el evento real de apertura y el
  terminal enumera findings y propuestas. No se inventa un ID fuera del
  entrypoint.

## Privacidad, retencion y diagnostico

No se almacenan prompts ni respuestas completas. Referencias absolutas,
traversal, `.env`, cabeceras y credenciales se rechazan; errores comunes con
tokens o claves se sanea y limita. Tokens, modelo y coste son nullable y no se
estima coste sin una fuente verificable. Los eventos heredan inicialmente la
retencion de 45 dias de `AgentEvent` y no incorporan payloads voluminosos.

La consulta read-only detecta started sin terminal, huerfanos tras una hora,
terminal sin started, aperturas/terminales duplicados y estados incompatibles.
No cierra ni reescribe runs. El digest publica conteos, estados separados,
fallback, p50/p95, outputs, findings, propuestas, roles y cobertura del vinculo
de atribucion. `unavailable` se representa como `null` si no existe denominador.

## Limites de interpretacion

La primera muestra posterior al reinicio solo confirma cobertura operativa; no
permite juzgar productividad ni utilidad. Se requiere como minimo un ciclo de
retencion completo de 45 dias, con operacion semanal y postmercado suficiente,
antes de comparar roles. Impacto demostrado sigue dependiendo del embudo P-L28
y de evaluacion post-apply; actividad, bloqueos correctos o volumen no equivalen
a utilidad. No se modifica trading, prompts, presupuestos, autonomia ni apply.
