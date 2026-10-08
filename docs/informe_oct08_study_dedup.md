# Estudio duplicado bootstrap/scheduler — 8 octubre 2026

Dictamen: `ready_for_integration_rehearsal`, candidato aislado N2, NO release.
Causa: APScheduler `max_instances` no contabiliza llamadas directas del
bootstrap. Dos entradas del mismo estudio podían atravesar simultáneamente
el calendario y la comprobación latest antes de actualizar la marca final.

## Identidad y alcance

Fecha de cierre local: 2026-10-08 08:46 Europe/Madrid. Coordinador comunicó
`schedule-status` a las 08:33: XNYS cerrado, apertura 15:30 Madrid, lease
postmarket activo. No se consultó ni modificó producción en este lote.

Worktree exclusivo:
`C:/Users/utopi/.codex/worktrees/bolsa-study-dedup-oct08/agenteBolsa`.
Rama `codex/oct08-study-dedup`; base exacta
`1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`, tree
`4d118b504b305e45f45a06d9aaffa063079abaf7`, versión 0.4.321; base limpia.
Bump/reserva diferidos por dirección: candidato no publicable con esta versión.

Commits separados:
- Caracterización `65290cbb`: 10 failed contra base; dos carreras de jobs
  reales terminaron `TimeoutError` esperando la segunda entrada al calendario.
  Ocho fallos restantes caracterizan helper/wrapping todavía inexistentes.
- Implementación `77314391`: único cambio funcional en `scheduler.py`.
- QA `5ed4aeb96affe5150c8ffc4a3b0e6a1e3ac744b5`, árbol funcional validado
  `72a5627726048797bfc419323f748653c0b5090b`.
- Documentación posterior: sólo este informe, plan y relevo; hash final
  comunicado por dirección/entrega, sin autorreferencia circular.

## Contrato

`_single_study_job` protege únicamente `closed_market_technical_study_job` y
`daily_study_job`. Registro `WeakKeyDictionary` por instancia Store y nombre
de job, acceso breve protegido por Lock; desaparece cuando Store queda sin
referencias. Admisión por Lock `acquire(blocking=False)`. Misma instancia y
mismo job concurrentes retornan None; `force=True` tampoco elude exclusión.
Jobs distintos y Stores distintos siguen independientes. No existe protección
entre procesos ni entre dos Stores que apuntan a la misma base.

Entrada aceptada invoca cuerpo original con argumentos intactos, devuelve
resultado original y propaga excepción original. `finally` libera Lock incluso
tras `KeyboardInterrupt`. `functools.wraps` conserva metadatos y firma visible.
Cuerpos, orden bootstrap, calendario, workers, grace y configuración intactos.
Sin cambios en postmarket, coordinador, estrategia o archivos protegidos.

Duplicado genera `study_job_concurrent_skipped` mediante `log_system_event`
en `system.jsonl`, con job_name y reason=`same_store_job_running`. No crea
AgentReporter, no llama SQLite ni `_set_job_status`, no sustituye runtime de
entrada aceptada. OSError/Exception del diagnóstico se absorbe. Escritura de
archivo síncrona existente: puede tener latencia del filesystem; no se afirma
límite de tiempo real, garantía ante disco colgado ni deadlock resuelto.

## Evidencia local

Python `C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe`,
`PYTHONPATH` exacto `<worktree>/src`, `DATA_DIR` temporal, Settings
`_env_file=None`, reloj scheduler doble fijo, calendario/proveedores dobles.
Sin sleeps: concurrencia coordinada mediante threading.Event y futures con
límites de tiempo para detectar bloqueo. SQLite productiva nunca abierta.

Comando focal:
`python -m pytest tests/test_oct08_study_dedup.py tests/test_scheduler_observability.py -q --tb=short`.
Resultado definitivo: **37 passed in 2.97s** (17 nuevos + 20 existentes),
sin skips ni xfails. Baterías previas solapadas, no sumar como tests únicos.

Cobertura: carreras de ambos jobs reales con diagnóstico normal y fallido;
no overwrite de runtime activo ni creación SQLite; duplicado retorna antes de
liberar primer job; aislamiento job/Store; recolección débil; resultados y
argumentos del helper; liberación y misma excepción por ValueError y
KeyboardInterrupt en ambos jobs reales. Trazas aceptadas comparadas con cuerpo
original: daily completado, técnico omitido por mercado abierto y técnico
cerrado completado con dobles; force=False/True en trazas iniciales.
Paridad demostrada sólo de rutas sintéticas indicadas, no economía real.

`ruff check src/agente_bolsa/scheduler.py tests/test_oct08_study_dedup.py`:
All checks passed. `scripts/check_no_nulls.py`: OK (538 archivos).
`git diff --check`: verde. Sin nuevos servicios/dependencias/esquemas/leases.

## Límites y siguiente paso

Omitidos y NO aprobados: fullsuite, smoke, run-once/job-once, validación
operativa, kernel/config gates productivos, broker/red/LLM, reinicio,
despliegue y push. Lease postmarket activo; autorización sólo focal local.
Scheduler/PID/heartbeat/HTTP/kernel/config/hash sensible productivos:
`unavailable` en este lote, no inferidos a partir de dobles.

Dirección puede ensayar integración aislada y revisar diff exacto. Release
requiere reserva/bump, precondiciones cerradas sin lease/trabajos activos y
validación proporcional autorizada. No hay afirmación de deployed ni de
paridad económica real.
