---
name: start-agente-bolsa
description: Arrancar, reiniciar y validar de extremo a extremo el proyecto agenteBolsa en Windows/PowerShell. Usar cuando el usuario pida levantar el proyecto, recuperarlo tras reiniciar el equipo, comprobar el arranque diario, reiniciar scheduler o dashboard, o verificar que broker paper, LLM, panel web, scheduler, datos y salud operativa funcionan correctamente.
---

# Arrancar agenteBolsa

Ejecutar todo desde la raiz del repositorio. Tratar `docs/tutorial_arranque_diario.md` como regla diaria y `docs/startup_runbook.md` como referencia de diagnostico. Usar siempre `\.\.venv\Scripts\python.exe` para no depender de la activacion del entorno.

## 1. Determinar si toca arrancar

1. Obtener fecha, hora y zona local con `Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"`.
2. Leer `docs/tutorial_arranque_diario.md` porque festivos y reglas pueden cambiar.
3. Ejecutar:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
```

4. Usar el calendario devuelto por la aplicacion como fuente de verdad:
   - Dia con sesion: arrancar o verificar normalmente.
   - Fin de semana o festivo: no hace falta arrancar para operar. Si el usuario pide expresamente el servicio completo o funcionamiento 24/7, levantarlo en espera y explicar que no operara.
   - No asumir horarios fijos fuera de la informacion devuelta por `schedule-status`.

## 2. Ejecutar gates previos obligatorios

Ejecutar en este orden:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status
.\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health --json
```

Exigir:

- `kernel-status`: `ok: true` y `violations: []`.
- Broker Alpaca accesible, cuenta activa y `paper: true`.
- `TRADING_MODE=paper` y `ALLOW_LIVE_TRADING=false` en `status`.
- Base de datos accesible.
- Sin alertas criticas en `operational-health`.

No arrancar si falla un gate critico. Si hay violaciones de kernel, informar los archivos exactos. Ejecutar `kernel-seal` solo despues de que Antonio confirme explicitamente que los cambios son intencionados y revisados; repetir despues `kernel-status --json`.

Nunca cambiar `TRADING_MODE`, `ALLOW_LIVE_TRADING` ni credenciales para conseguir que el arranque pase.

## 3. Resolver el LLM

Leer solo las claves no secretas necesarias:

```powershell
Select-String -Path .env -Pattern '^OPENAI_API_BASE=|^OPENAI_MODEL_NAME='
```

- Si `OPENAI_API_BASE` es externo, no arrancar `llama-server`.
- Si apunta a `127.0.0.1:8080`, comprobar `GET /v1/models` y una inferencia corta segun `docs/startup_runbook.md`. Arrancar el servidor local con el modelo y alias configurados si no responde.
- No mostrar API keys ni el contenido completo de `.env`.

## 4. Detectar instancias existentes

Intentar localizar exclusivamente procesos de este proyecto:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'agente_bolsa\.main (schedule|web)' } |
  Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine
```

Si Windows deniega la consulta, usar senales internas:

- `data/state/scheduler.lock` y su PID.
- Eventos recientes del scheduler.
- Puerto HTTP del panel.

No inferir que el scheduler esta vivo solo porque `schedule-status` enumera jobs: `job_runtime` puede contener datos antiguos. Exigir timestamps frescos.

Si el usuario pide arrancar y ya esta vivo, no duplicar. Si pide reiniciar, detener solo los PIDs confirmados de `schedule` y `web`; no matar procesos Python genericos. Con mercado abierto y riesgo operativo, respetar la pausa de emergencia descrita en el tutorial.

No borrar `scheduler.lock` a ciegas. Considerarlo huerfano solo tras verificar que su PID no existe.

## 5. Levantar servicios

Usar procesos ocultos persistentes y arrays de argumentos de PowerShell:

```powershell
Start-Process `
  -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList @("-m","agente_bolsa.main","web","--host","127.0.0.1","--port","8501") `
  -WorkingDirectory (Get-Location).Path `
  -WindowStyle Hidden

Start-Process `
  -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList @("-m","agente_bolsa.main","schedule","--quiet") `
  -WorkingDirectory (Get-Location).Path `
  -WindowStyle Hidden
```

Si `8501` esta ocupado por una instancia valida del panel, conservarla. Usar `8502` solo si se necesita una segunda instancia de diagnostico y comunicar la URL.

El lock interno debe impedir schedulers duplicados, pero no usarlo como sustituto de la verificacion posterior.

## 6. Validar que esta realmente operativo

### Panel

Esperar hasta 60 segundos y comprobar:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501
```

Exigir HTTP 200. Streamlit puede tardar mas de 15 segundos en inicializar; no declarar fallo demasiado pronto.

### Scheduler

Revisar inmediatamente y otra vez tras al menos 75 segundos:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main log --lines 120 --all-events
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
```

Exigir:

- Evento `scheduler_started` posterior al arranque, o evidencia fresca de una instancia que ya estaba viva.
- `portfolio_watch` actualizado despues del arranque y despues de un intervalo de 60 segundos.
- Con mercado abierto, `market_cycle` reciente o programado y sin fallo critico.
- Con mercado cerrado, estados `skipped`/espera coherentes son validos.

Si se inicia un ciclo bootstrap con mercado abierto, esperar a `Ciclo finalizado` antes de cerrar la tarea. Una degradacion de CrewAI solo es tolerable si el fallback completa el ciclo; reportarla claramente.

### Salud integral

Ejecutar:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main production-health --json
.\.venv\Scripts\python.exe -m agente_bolsa.main market-data-quality --json
.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health --json
```

Durante mercado abierto, tratar `data_pipeline_down`, datos obsoletos, ausencia de cobertura o jobs criticos fallidos como fallo de validacion. Confirmar que el kill switch no esta activo.

No ejecutar `run-once` ni `decide-once` como smoke test durante una sesion salvo peticion explicita: pueden alcanzar rutas de decision/orden en paper.

## 7. Diagnosticar sin ocultar fallos

- Panel sin HTTP 200: comprobar `Get-NetTCPConnection -LocalPort 8501 -State Listen`, esperar inicializacion y revisar salida/logs de Streamlit.
- Scheduler sin eventos frescos: comprobar lock/PID, ejecutar `schedule --quiet` en foreground con timeout corto solo para capturar errores y luego dejar una instancia persistente.
- Broker fallido: no operar; informar endpoint, modo y mensaje sin exponer secretos.
- LLM fallido: comprobar endpoint/modelo. Distinguir fallo de CrewAI con fallback funcional de indisponibilidad total del LLM.
- Kernel o kill switch: detener el arranque operativo y escalar.

## 8. Informar el resultado

Cerrar con un resumen factual:

- Fecha/hora y estado de mercado.
- Kernel, broker y modo de trading.
- Scheduler: hora de arranque y ultimo `portfolio_watch`/`market_cycle`.
- Dashboard: URL y HTTP.
- Salud de datos y alertas.
- Posiciones/ordenes abiertas si existen.
- Degradaciones o pasos no completados.

No afirmar "arrancado" si solo se lanzaron procesos. Afirmarlo unicamente despues de comprobar HTTP 200 y actividad fresca del scheduler.
