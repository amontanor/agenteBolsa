# Informe Codex P-L11 - hotfix restart_services

Fecha: 2026-07-08
Version: 0.4.134
Rama: `codex/mejora_continua`

## Incidente

`scripts/restart_services.ps1` fallaba en Windows PowerShell 5.1 con:

`No se puede sobrescribir la variable Pid porque es de solo lectura o constante.`

La causa era un parametro `param([int]$Pid)` en `Invoke-TaskKill`, que colisiona
con la variable automatica `$PID`.

## Cambio aplicado

- `scripts/restart_services.ps1`
  - `Invoke-TaskKill` pasa de `-Pid` a `-TargetPid`.
  - Se actualizan todos los call sites del script.
- Auditoria de `scripts/*.ps1`
  - Busqueda de usos conflictivos de nombres de variables automaticas:
    `Pid`, `Host`, `Input`, `Args`, `Error`.
  - Resultado: no se detectan mas parametros o asignaciones invalidas.
- `tests/test_stack_common_supervisor.py`
  - Test de regresion que carga el script en `powershell.exe`, comprueba que no
    existe `param([int]$Pid)` y valida que el script puede parsearse.

## Verificacion

- Auditoria PowerShell:
  - busqueda en `scripts/*.ps1` de parametros/variables automaticas conflictivas
    (`Pid`, `Host`, `Input`, `Args`, `Error`)
  - resultado: solo existia el caso de `restart_services.ps1`; no se detectan mas
    parametros invalidos.
- Test focal:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_stack_common_supervisor.py -q`
  - `3 passed`
- Suite completa:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\ -x -q`
  - `1028 passed, 1 warning`
- Lint:
  - `.\.venv\Scripts\ruff.exe check src tests`
  - `All checks passed!`
- Config/runtime base:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json` -> `ok=true`
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main status` -> paper, broker configurado, stack operativo
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew` -> ciclo completo sin traceback

## Ejecucion real obligatoria

Comando ejecutado:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart_services.ps1
```

Resultado observado:

- termina con `exit code 0`
- no aparece el error `No se puede sobrescribir la variable Pid`
- no aparecen lineas residuales `ERROR: no se encontró el proceso`
- el panel responde `HTTP 200`
- `stack_up` y `stack_status` muestran los 7 servicios previstos en `CORRIENDO`

Evidencia final de estado:

- `scheduler`: `CORRIENDO`
- `web`: `CORRIENDO`
- `telegram_radar_supervisor`: `CORRIENDO`
- `overlay_shadow_supervisor`: `CORRIENDO`
- `ci_digest_supervisor`: `CORRIENDO`
- `codegen_nightly_supervisor`: `CORRIENDO`
- `core_sleeve_supervisor`: `CORRIENDO`

Comprobacion JSON posterior:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stack_status.ps1 -Json
```

Resultado:

- `ok=true`
- `foreign_processes=[]`
- 7/7 servicios con `state="CORRIENDO"`
