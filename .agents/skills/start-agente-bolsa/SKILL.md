---
name: start-agente-bolsa
description: >
  Arrancar, reiniciar y validar agenteBolsa en Windows mediante sus tareas y
  helpers gestionados. Usar para recuperacion, despliegue y comprobacion diaria.
---

# Arrancar y validar agenteBolsa

Trabajar desde la raiz productiva con `.\.venv\Scripts\python.exe`. Leer
`docs/tutorial_arranque_diario.md` y `docs/startup_runbook.md`.

## 1. Preflight

Obtener hora/zona y ejecutar:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status
.\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health --json
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
```

Exigir paper, live false, kernel `ok` sin violaciones, broker paper accesible,
SQLite accesible y cero alertas criticas. Nunca cambiar flags/credenciales para
forzar un gate.

El calendario de la aplicacion es la autoridad. Para despliegue/reinicio no
urgente exigir XNYS cerrado, ausencia de jobs/pytest activos y margen suficiente.

## 2. Kernel y entorno

El manifest productivo vigila `kernel.py`, `broker.py`, `execution.py` y `.env`.
No ejecutar `kernel-seal` sin confirmacion humana de un cambio intencional.

Un worktree o DATA_DIR temporal puede devolver `unsealed` al no tener manifest.
Repetir desde la raiz y DATA_DIR productivos; no copiar ni crear un manifest para
hacer pasar la prueba.

## 3. Instancias y locks

- Solo las tareas `AgenteBolsaScheduler` y `AgenteBolsaWeb` lanzan servicios.
- No ejecutar `schedule`/`web` manualmente como procesos persistentes.
- Un scheduler valido requiere proceso `.venv`, PID/lock vivo y heartbeat fresco.
- No borrar locks sin demostrar que el propietario no existe.
- No matar Python generico; actuar solo sobre procesos confirmados del proyecto.

## 4. Helpers canonicos

Diagnostico:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
```

Parada de despliegue:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stack_down.ps1 -IncludeScheduled
```

Arranque de piezas ausentes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stack_up.ps1
```

`scripts/restart_services.ps1` queda como helper compatible de reinicio limpio,
pero no amplia la autorizacion para reiniciar con XNYS abierto.

## 5. Despliegue

1. Verificar commits/tree, Git limpio, version y hash sensible.
2. Parar stack gestionado.
3. Merge `--no-ff`; abortar ante conflicto no pre-revisado.
4. Suite, Ruff, NUL, diff, configuracion, kernel y smoke aislado.
5. Ante fallo: revert auditable, validar tree anterior y restaurar stack.
6. Arrancar con `stack_up.ps1`; nunca con `Start-Process` manual.

No ejecutar postmarket/ciclo/reconciliacion manual para validar un deploy.

## 6. Validacion postarranque

Comprobar inmediatamente y otra vez tras al menos 75 segundos:

- HTTP raiz y `/health` 200.
- Un scheduler logico, PID/lock coherente y heartbeat fresco.
- `portfolio_watch`/`market_cycle` coherente con estado de mercado.
- `production-health`, `operational-health`, `market-data-quality`.
- Paper activo, live false, kill switch no activo.
- Hash de configuracion sensible intacto.

Tras P-L45B1, un bootstrap de sesion postmarket ya completada debe terminar
`skipped` sin repetir outcomes/reconciliacion. `database is locked`, run sin
terminal o retroceso de `last_session` bloquea la aceptacion.

## 7. Mercado abierto

- No ejecutar `run-once`, `decide-once`, `job-once`, postmarket o reconciliacion
  contra produccion salvo peticion operativa expresa.
- Si un bootstrap inicia ciclo real, esperar su terminal; fallback LLM solo es
  tolerable si completa sin violar gates.
- Una emergencia no autoriza cambios de trading/configuracion no solicitados.

## 8. Informe final

Reportar hora/mercado, version/commit, kernel, broker/mode, scheduler PID/lock,
heartbeats, HTTP, salud, degradaciones, Git y rollback. No afirmar `arrancado`
hasta verificar actividad fresca.
