# Runbook del stack local

Fecha de referencia: 2026-07-04.

## Ver estado

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stack_status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stack_status.ps1 --json
```

Servicios esperados:

- `scheduler`: tarea programada `AgenteBolsaScheduler`.
- `web`: tarea programada `AgenteBolsaWeb`, HTTP en `127.0.0.1:8501`.
- `telegram_radar_supervisor`.
- `overlay_shadow_supervisor`.
- `ci_digest_supervisor`.
- `codegen_nightly_supervisor`.
- `core_sleeve_supervisor`.

`pids` muestra las raices logicas del servicio. `process_pids` en JSON conserva
los procesos hijos vistos, porque en Windows el venv puede delegar al Python base.

## Levantar sin duplicar

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stack_up.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stack_up.ps1 --json
```

`stack_up` solo arranca servicios en `PARADO`. Si un servicio esta `CORRIENDO` o
`DUPLICADO`, informa `already` y no lanza otra instancia. Scheduler y web se
arrancan mediante sus tareas programadas; los supervisores se arrancan como
procesos PowerShell ocultos.

## Parar supervisores

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stack_down.ps1
```

Por defecto solo detiene supervisores y deja intactos scheduler y web. Para parar
tambien las tareas programadas:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stack_down.ps1 -IncludeScheduled
```

## Locks

Cada supervisor residente toma `data\run\<servicio>.pid`. Si al arrancar el PID
del lock sigue vivo con una linea de comando compatible, el nuevo proceso sale
limpiamente con `ya corriendo (PID X desde HH:mm)`. Si el lock es huerfano, se
sobrescribe. Al salir, el proceso libera su propio lock.

El panel web no usa lock propio: antes de lanzar Streamlit comprueba el puerto
configurado. Si `127.0.0.1:8501` ya responde, sale sin crear otra instancia.

## Duplicados y huerfanos

1. Ejecutar `stack_status.ps1 --json`.
2. Si `state=DUPLICADO`, revisar `pids` y `command_lines`.
3. Matar solo procesos inequívocos del mismo servicio y del mismo repositorio.
4. Si `lock_orphan=true`, ejecutar de nuevo el supervisor o borrar el lock solo
   tras confirmar que el PID no existe o no corresponde a ese servicio.
5. Repetir `stack_status.ps1` y conservar la salida en el informe operativo.
