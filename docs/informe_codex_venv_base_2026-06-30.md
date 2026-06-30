# Informe Codex - venv/base Python en runtime

Fecha: 2026-06-30  
Repositorio: `C:\Antonio\Bref\agenteBolsa`  
Objetivo: conseguir que todos los procesos runtime del proyecto aparezcan ejecutando el interprete de `.venv`, no el interprete base `Python311`.

## Resultado

La tarea queda bloqueada y sin cambio funcional retenido.

Se intento el fix minimo pedido para spawns internos, pero la verificacion estricta post-restart siguio mostrando procesos:

```text
C:\Users\utopi\AppData\Local\Programs\Python\Python311\python.exe -m agente_bolsa.main web ...
C:\Users\utopi\AppData\Local\Programs\Python\Python311\python.exe -m agente_bolsa.main schedule
C:\Users\utopi\AppData\Local\Programs\Python\Python311\python.exe -m streamlit run ...
```

Segun la regla operativa de la tarea, se hizo rollback inmediato de los cambios de codigo y restart controlado. El working tree queda limpio salvo este informe.

## Paso 0 - Diagnostico

Comando:

```powershell
.\.venv\Scripts\python.exe -c "import sys; print('exe',sys.executable); print('prefix',sys.prefix); print('base',sys.base_prefix)"
```

Resultado:

```text
exe C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe
prefix C:\Antonio\Bref\agenteBolsa\.venv
base C:\Users\utopi\AppData\Local\Programs\Python\Python311
```

Por el criterio inicial, esto no es causa A: `sys.executable` apunta al `.venv`.

La causa observada tampoco es un simple `python` pelado del PATH. El ejecutable del venv es un launcher:

```text
C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe
InternalName: Python Launcher
OriginalFilename: py.exe
```

Ese launcher crea un proceso hijo del interprete base. El proceso que ejecuta realmente el codigo Python y escribe `scheduler.lock` es el hijo base.

## Procesos y spawns localizados

Antes del intento:

```text
.venv\Scripts\python.exe -m agente_bolsa.main web
  -> Python311\python.exe -m agente_bolsa.main web
      -> .venv\Scripts\python.exe -m streamlit run ...
          -> Python311\python.exe -m streamlit run ...

.venv\Scripts\python.exe -m agente_bolsa.main schedule
  -> Python311\python.exe -m agente_bolsa.main schedule
```

Puntos relevantes:

| Punto | Estado |
|---|---|
| `AgenteBolsaScheduler` | Tarea programada lanza `scripts\run_scheduler_supervisor.ps1`. |
| `scripts\run_scheduler_supervisor.ps1` | Ejecuta `& $Python -m agente_bolsa.main schedule`, donde `$Python` es `.venv\Scripts\python.exe`. |
| `AgenteBolsaWeb` | Tarea programada ejecuta `.venv\Scripts\python.exe -m agente_bolsa.main web ...`. |
| `main.command_web` | Construia streamlit con `sys.executable -m streamlit run ...`. |
| `web_app._start_schedule` | Construia scheduler desde panel con `sys.executable -m agente_bolsa.main schedule`. |

Los dos ultimos son spawns corregibles dentro de la app. Los dos primeros pasan por el launcher del venv incluso cuando se invoca explicitamente `.venv\Scripts\python.exe`.

## Intento de fix y rollback

Se probo localmente:

- Nuevo helper `venv_python()` que devuelve `Path(sys.prefix) / "Scripts/python.exe"` en Windows.
- `main.command_web` usando `venv_python()` para lanzar Streamlit.
- `web_app._start_schedule` usando `venv_python()` para lanzar el scheduler.
- Tests unitarios para el helper y ambos spawns.
- Version bump provisional.

Validacion del intento antes de restart:

```text
pytest tests/ -x -q -> 785 passed, 1 warning
ruff check src tests -> All checks passed
```

Restart controlado:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_services.ps1
```

Resultado: el helper reducia el riesgo de spawns internos por PATH, pero no eliminaba los hijos base porque el entrypoint de las tareas programadas y el streamlit child siguen pasando por el launcher del venv. La verificacion estricta seguia fallando.

Accion tomada:

- Rollback de los cambios de codigo.
- Eliminacion de los tests nuevos.
- Restart controlado posterior.
- Sin commit de codigo.

## Estado post-rollback

Despues del rollback y restart:

- Panel HTTP 200.
- `schedule-status` con heartbeat fresco (`portfolio_watch` actualizado a `2026-06-30T08:33:32Z`).
- `status`: `trading_mode=paper`, `allow_live_trading=false`.
- `kernel-status --json`: `ok=true`, `violations=[]`.
- `.env`: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `TRADING_MODE=paper`, `ALLOW_LIVE_TRADING=false`.

El lock sigue evidenciando la causa raiz:

```json
{"pid":60900,"kind":"scheduler","written_at":"2026-06-30T08:31:32.733482+00:00"}
```

Ese PID corresponde al hijo:

```text
C:\Users\utopi\AppData\Local\Programs\Python\Python311\python.exe -m agente_bolsa.main schedule
```

## Causa raiz confirmada

La causa raiz no es un import ni un spawn por PATH dentro del codigo Python. Es el modelo de launcher del venv Windows actual:

```text
.venv\Scripts\python.exe  (Python Launcher)
  -> Python311\python.exe (interprete real)
```

Como el codigo Python corre en el proceso hijo, `scheduler.lock` necesariamente queda con el PID base. Cambiar `sys.executable` por `Path(sys.prefix)/Scripts/python.exe` en la app no puede cambiar el PID real que ejecuta el scheduler.

## Recomendacion

No forzar esto a mitad de dia.

Para cumplir literalmente "ningun `Python311\python.exe ... agente_bolsa.main` en procesos" hace falta una intervencion fuera del codigo de la app, en ventana controlada:

1. Preparar una prueba fuera de runtime con una copia/recreacion del venv que no use launcher redirector, o confirmar si la distribucion Python instalada puede crear un venv con `Scripts\python.exe` como interprete real.
2. Validar en proceso aislado que:
   - `sys.prefix` apunta a `.venv`;
   - `sys.executable` apunta a `.venv\Scripts\python.exe`;
   - `Get-CimInstance Win32_Process` no muestra hijo `Python311\python.exe`;
   - imports del proyecto y dependencias cargan desde `.venv`.
3. Solo despues, recrear o reparar el venv operativo con scheduler y web parados.
4. Reiniciar servicios y exigir que `scheduler.lock` pertenezca a un PID `.venv`.

Hasta entonces, el estado mas seguro es conservar el runtime actual y documentar que las parejas `.venv launcher -> Python311 child` son una propiedad del venv, no evidencia de codigo viejo ni de `site-packages` del PATH.
