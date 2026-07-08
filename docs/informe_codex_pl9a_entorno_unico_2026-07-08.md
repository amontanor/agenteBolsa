# Informe Codex P-L9A - Entorno unico blindado

Fecha: 2026-07-08

## Objetivo

Blindar scheduler y web para que solo arranquen desde el `.venv` gestionado del repo, detectar procesos ajenos y endurecer `restart_services`/`stack_up`/`stack_status`.

## Cambios aplicados

- Nuevo helper [src/agente_bolsa/runtime_paths.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/runtime_paths.py) para resolver `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe` y fallar de forma visible si no existe.
- [src/agente_bolsa/main.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/main.py) ya no lanza Streamlit con `sys.executable`; usa el python gestionado.
- [src/agente_bolsa/web_app.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/web_app.py) ya no relanza el scheduler con `sys.executable`; usa el python gestionado.
- [scripts/stack_common.ps1](/C:/Antonio/Bref/agenteBolsa/scripts/stack_common.ps1), [scripts/stack_status.ps1](/C:/Antonio/Bref/agenteBolsa/scripts/stack_status.ps1), [scripts/stack_up.ps1](/C:/Antonio/Bref/agenteBolsa/scripts/stack_up.ps1), [scripts/check_services.ps1](/C:/Antonio/Bref/agenteBolsa/scripts/check_services.ps1) y [scripts/restart_services.ps1](/C:/Antonio/Bref/agenteBolsa/scripts/restart_services.ps1) ahora:
  - identifican procesos raiz de `scheduler`/`web` ajenos al `.venv`,
  - los matan antes de levantar la pila,
  - hacen fallar el estado si aparece una raiz no gestionada,
  - incluyen PID y command line en el reporte,
  - toleran `taskkill` idempotente cuando un hijo ya cayó con el padre.

## Causa raiz encontrada

La tarea programada `AgenteBolsaScheduler` ya llamaba correctamente a `scripts/run_scheduler_supervisor.ps1`, y ese supervisor ya invocaba `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`.

La fuga estaba en dos sitios de relanzado interno:

1. `command_web()` lanzaba Streamlit con `sys.executable`.
2. `_start_schedule()` desde la web relanzaba `schedule` con `sys.executable`.

Además, `restart_services.ps1` solo mataba `agente_bolsa.main schedule|web` y dejaba fuera `streamlit ... web_app.py`. Si quedaba vivo un Streamlit antiguo, este podía volver a levantar scheduler/web usando su propio intérprete.

## Evidencia

Tareas programadas:

- `AgenteBolsaScheduler` -> `powershell.exe -File scripts\run_scheduler_supervisor.ps1`
- `AgenteBolsaWeb` -> `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -m agente_bolsa.main web --host 127.0.0.1 --port 8501`

Antes del fix, el árbol observado incluía:

- raíz `.venv\Scripts\python.exe -m agente_bolsa.main schedule`
- hijo `C:\Users\utopi\AppData\Local\Programs\Python\Python311\python.exe -m agente_bolsa.main schedule`
- `streamlit ... web_app.py` no estaba cubierto por el patrón de kill de `restart_services.ps1`

Verificación real tras el restart:

- `scripts/restart_services.ps1`: completado sin error.
- `scripts/stack_status.ps1 -Json`: `ok=true`, `foreign_processes=[]`.
- Servicios `CORRIENDO`: 7 de 7.
- Web: HTTP 200 en `127.0.0.1:8501`.

Salida relevante de `stack_status -Json`:

```json
{
  "ok": true,
  "foreign_processes": []
}
```

## Nota operativa importante

En Windows, el wrapper del `.venv` sigue mostrando hijos `Python311` en el árbol del proceso. Tras el fix siguen apareciendo como descendientes del wrapper gestionado, pero ya no quedan raices ajenas: `stack_status` las clasifica correctamente como parte del arbol del `.venv`, no como intrusos independientes.

## Verificacion

- `pytest tests/test_web_launch.py tests/test_web_app.py -q` -> verde.
- `ruff check src tests` -> limpio.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/restart_services.ps1` -> verde.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack_status.ps1 -Json` -> `ok=true`, `foreign_processes=[]`.
