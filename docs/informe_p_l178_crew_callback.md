# P-L178 — callback de tarea CrewAI sin closure (0.4.403)

Fecha: 2026-10-29 (Europe/Madrid). XNYS abierto durante el lote (cierre
21:00). Nivel **N2**: adaptador de crews y telemetría de tareas; sin autoridad
de trading, riesgo ni ejecución.

## 1. Dictamen

`ready_for_integration_rehearsal`. La causa raíz del fallback dominante
`agent_run_fallback_started` (`fallback_reason=direct_llm_decision`) está
reproducida y corregida en el adaptador de crews.

## 2. Causa raíz

Hecho de producción (2026-10-29, 45 `crew_failed` en el día):

```text
1 validation error for Task
callback
  Value error, I/O operation on closed file.
  [type=value_error, input_value=<function build_crew.<loc...lback at 0x...>, input_type=function]
```

Mecanismo verificado:

1. `crew.py` construía el callback de cada `Task` como una closure
   (`build_crew.<locals>.callback`).
2. CrewAI 1.14.7 declara `Task.callback: SerializableCallable`; su
   `BeforeValidator` (`crewai/types/callback.py::string_to_callable`) emite
   `warnings.warn(...)` para closures no serializables.
3. `warnings.warn` escribe en `sys.stderr`. El ciclo redirige stdout/stderr al
   fichero del intento (`cycle_runner.py:3183-3186`) y, cuando ese flujo ya está
   cerrado, la escritura lanza `ValueError: I/O operation on closed file`
   dentro de la validación pydantic: la Task queda inválida y el crew cae a
   decisión LLM directa con `llm_calls=0`.

Reproducción mínima local (misma versión de crewai y pydantic que la imagen):

```text
warnings.warn("closure") con sys.stderr cerrado -> ValueError: I/O operation on closed file
Task(..., callback=<closure>)                   -> UserWarning "function callbacks cannot be serialized"
```

## 3. Arreglo

- `crew.py::_crew_task_callback`: callback **module-level** (sin `<locals>`), sin
  captura de variables. Resuelve el observador desde
  `crew_execution_context()` y la identidad de la tarea desde el propio
  `TaskOutput` (`name`, `agent`).
- `crew_observer.py`: `bind_task_identity` / `resolve_task_identity` traducen el
  rol de CrewAI al clave del catálogo (`technical_analyst`, …), de modo que la
  telemetría conserva exactamente las mismas claves que antes.
- Sin observador o fuera de contexto, el callback devuelve la salida sin tocar
  nada.

Paridad: el contenido de las tareas, los agentes, el LLM, el manifiesto y el
contexto ejecutivo no cambian; solo cambia cómo se registra el callback. No hay
diff en `kernel.py`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py`,
`config.py` ni `.env`.

## 4. Evidencia

```text
pytest tests/test_p178_crew_callback.py
  base 4a178a2c (sin arreglo): 3 failed, 2 passed
  candidato:                  5 passed

pytest tests/test_p178_crew_callback.py tests/test_p147_crew_session_headers.py
       tests/test_oct14_crew_latency.py tests/test_p59c_llm_selected_authority.py
  64 passed

pytest tests/test_agent_run_telemetry.py
  19 passed

ruff check src/agente_bolsa/crew.py src/agente_bolsa/crew_observer.py
  All checks passed

check_no_nulls: OK (610 archivos)
git diff --check: limpio
```

Los dos fallos de Ruff de `web_app.py` son preexistentes en la base y ajenos al
lote.

## 5. Límites

- No se ha ejecutado CrewAI real contra el proveedor desde pruebas (sin red).
- El `logical` contexto puede perderse si CrewAI ejecutase callbacks en otro
  hilo; con `Process.sequential` no ocurre y, en el peor caso, se pierde
  telemetría de esa tarea, nunca se invalida el Task.
- La verificación en producción exige ver `crew_completed` o
  `agent_task_execution` en el siguiente ciclo desplegado.

## 6. Candidato

- Worktree `.worktrees/pl178-crew-callback`, rama
  `codex/pl178-crew-callback`, base `4a178a2c`/`99039445`/0.4.402.
- Commits: `a6ddd218` test, `fb798770` fix, `27b0b05b` versión.
- Versión `0.4.403`.
