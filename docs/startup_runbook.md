# Runbook de arranque

Guia operativa para levantar el proyecto completo en local y verificar que queda listo para operar en `paper`.

Estado validado en este entorno el **14 de mayo de 2026**:

- Panel web: `http://127.0.0.1:8501`
- LLM local OpenAI-compatible: `http://127.0.0.1:8080/v1`
- Scheduler: proceso `python` en background

## 1. Prerrequisitos

- Windows + PowerShell
- Python virtualenv en `.\.venv`
- Dependencias instaladas
- `.env` configurado
- Alpaca paper configurado
- Servidor LLM local disponible

Comprobacion rapida:

```powershell
Test-Path .\.venv\Scripts\python.exe
Test-Path .\.env
```

Si falta el entorno:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
copy .env.example .env
```

## 2. Configuracion minima esperada

### Trading

```env
TRADING_MODE=paper
ALLOW_LIVE_TRADING=false
BROKER=alpaca
ALPACA_PAPER=true
```

### LLM local

```env
OPENAI_API_KEY=local-llama
OPENAI_API_BASE=http://127.0.0.1:8080/v1
OPENAI_MODEL_NAME=qwen3.6-27b
```

## 3. Orden recomendado de arranque

### Paso 1. Verificar broker y base local

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main init-db
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status
.\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status
```

Que debe pasar:

- `init-db` sin error
- `broker-status` conectado a Alpaca paper
- `portfolio-status` devuelve cuenta, posiciones y ordenes

### Paso 2. Levantar el LLM local

El proyecto espera un endpoint OpenAI-compatible en `127.0.0.1:8080`.

Con la configuracion usada en esta maquina:

```powershell
C:\llama.cpp\llama-server.exe --host 127.0.0.1 --port 8080 --alias qwen3.6-27b
```

Verificacion minima:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/v1/models
```

Verificacion real de inferencia:

```powershell
$body = @{
  model = "qwen3.6-27b"
  messages = @(@{ role = "user"; content = "Responde solo OK" })
  max_tokens = 8
  temperature = 0
} | ConvertTo-Json -Depth 5

Invoke-WebRequest `
  -UseBasicParsing `
  http://127.0.0.1:8080/v1/chat/completions `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

Que debe pasar:

- `/v1/models` responde `200`
- aparece el modelo `qwen3.6-27b`
- `/v1/chat/completions` responde JSON

### Paso 3. Levantar el panel web

Foreground:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main web --host 127.0.0.1 --port 8501
```

Background:

```powershell
Start-Process `
  -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList @("-m","agente_bolsa.main","web","--host","127.0.0.1","--port","8501") `
  -WorkingDirectory "C:\Antonio\Bref\agenteBolsa" `
  -WindowStyle Hidden
```

Verificacion:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501
```

Que debe pasar:

- respuesta `200`
- panel accesible en `http://127.0.0.1:8501`

### Paso 4. Levantar el scheduler

Foreground:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule
```

Background:

```powershell
Start-Process `
  -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList @("-m","agente_bolsa.main","schedule","--quiet") `
  -WorkingDirectory "C:\Antonio\Bref\agenteBolsa" `
  -WindowStyle Hidden
```

Verificacion:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
```

Ademas, revisar eventos:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main log --lines 30 --all-events
```

Que debe pasar:

- `schedule-status` devuelve mercado, jobs y `job_runtime`
- aparece `scheduler_started` en `data/logs/system.jsonl`
- si mercado esta cerrado, los jobs deben quedar en `skipped` o `completed` de espera
- si mercado esta abierto, deben empezar `portfolio_watch` y `market_cycle`

## 4. Comprobacion de “todo levantado”

Consideramos que el proyecto esta realmente arriba cuando se cumplen estas 4 condiciones:

1. **Broker paper accesible**
   - `broker-status` y `portfolio-status` responden

2. **LLM accesible y generando**
   - `GET /v1/models` responde
   - `POST /v1/chat/completions` responde

3. **Panel web accesible**
   - `http://127.0.0.1:8501` devuelve `200`

4. **Scheduler vivo**
   - proceso `python` activo
   - `schedule-status` con jobs
   - `scheduler_started` en logs

## 5. Verificaciones operativas utiles

### Estado general

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
.\.venv\Scripts\python.exe -m agente_bolsa.main live-readiness
```

### Decision LLM en seco

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main scan-technical --quiet
.\.venv\Scripts\python.exe -m agente_bolsa.main decide-once --top-per-side 5
```

Esto verifica:

- scan tecnico
- lectura de candidatos
- llamada al LLM
- gates de `entry_quality`
- gates de `backtest`
- calculo de planes dry-run

### Ciclo completo puntual

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --quiet
```

### Historial reciente

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main trade-history --from 2026-05-01 --json
```

## 6. Diagnostico rapido de fallos

### El LLM no responde

Comprobar:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/v1/models
Get-Process | Where-Object { $_.ProcessName -match "llama|python" }
```

Revisar:

- `OPENAI_API_BASE`
- alias del modelo
- puerto `8080`

### El panel web no abre

Comprobar puerto:

```powershell
Get-NetTCPConnection -LocalPort 8501 -State Listen
```

Si esta ocupado, usar otro:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main web --host 127.0.0.1 --port 8502
```

### El scheduler no arranca

Comprobar lock:

```powershell
Test-Path .\data\state\scheduler.lock
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
```

Si hay lock huerfano, primero identificar si queda un scheduler vivo. No borrar el lock a ciegas si el proceso sigue activo.

### El ciclo no compra aunque hay señal

Revisar:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main log --lines 80 --all-events
.\.venv\Scripts\python.exe -m agente_bolsa.main missed-opportunities --from 2026-05-01 --json
```

Puntos tipicos:

- `entry_quality_gate`
- `backtest_gate`
- `risk_manager`
- `operational_kill_switch`

## 7. Como parar todo

### Panel web

Buscar PID:

```powershell
Get-Process | Where-Object { $_.Path -like "*agenteBolsa*" } | Select-Object ProcessName,Id,Path
```

Parar:

```powershell
Stop-Process -Id <PID>
```

### Scheduler

Si esta en foreground, `Ctrl+C`.

Si esta en background:

```powershell
Stop-Process -Id <PID>
```

### LLM local

Parar el proceso del servidor:

```powershell
Stop-Process -Name "llama-server"
```

## 8. Secuencia corta recomendada para la proxima vez

```powershell
cd C:\Antonio\Bref\agenteBolsa
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/v1/models
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @("-m","agente_bolsa.main","web","--host","127.0.0.1","--port","8501") -WorkingDirectory "C:\Antonio\Bref\agenteBolsa" -WindowStyle Hidden
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @("-m","agente_bolsa.main","schedule","--quiet") -WorkingDirectory "C:\Antonio\Bref\agenteBolsa" -WindowStyle Hidden
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
```

Si todo eso pasa, el proyecto esta arriba.
