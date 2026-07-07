# Informe Codex P-L5B - restart_services encadena stack_up - 2026-07-07

## Objetivo

Evitar que `restart_services.ps1` deje muertos los 5 supervisores persistentes
despues de matar todos los procesos del proyecto.

## Cambio aplicado

- `scripts/restart_services.ps1` ahora:
  - arranca scheduler + web por tarea programada
  - ejecuta `scripts\stack_up.ps1`
  - muestra `scripts\stack_status.ps1` al final

Con esto el propio reinicio completa la pila persistente en lugar de exigir un
`stack_up` manual posterior.

## Archivos

- `scripts/restart_services.ps1`
- `src/agente_bolsa/__init__.py`

## Verificacion real

- `.\.venv\Scripts\python.exe -m pytest tests -x -q`
  - `1002 passed, 1 warning`
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts`
  - `All checks passed!`
- `powershell -ExecutionPolicy Bypass -File scripts\restart_services.ps1`
  - reinicio limpio ejecutado
  - `Panel HTTP 200 en http://127.0.0.1:8501`
  - `stack_up` ejecutado dentro del propio script
  - `stack_status` mostrado al final del flujo

Estado final mostrado por el script:

- `scheduler: CORRIENDO`
- `web: CORRIENDO`
- `telegram_radar_supervisor: CORRIENDO`
- `overlay_shadow_supervisor: CORRIENDO`
- `ci_digest_supervisor: CORRIENDO`
- `codegen_nightly_supervisor: CORRIENDO`
- `core_sleeve_supervisor: CORRIENDO`

Resultado: `7/7 CORRIENDO`.

## Observacion operativa

La verificacion base del restart sigue mostrando procesos Python hijos del
runtime antiguo en `process_command_lines`, pero el estado final del stack queda
completo y el panel responde HTTP 200. El cambio pedido en B queda cubierto:
tras el restart ya no hace falta un `stack_up` manual para rearmar supervisores.

## Version

- `src/agente_bolsa/__init__.py`
- `0.4.122 -> 0.4.123`
