# Agente Bolsa

Sistema multiagente con CrewAI para investigar, generar hipotesis, simular y operar acciones de Estados Unidos con controles de riesgo.

Este proyecto arranca en modo `paper trading`. No garantiza beneficios y no debe operar dinero real hasta que las estrategias hayan pasado validaciones objetivas, pruebas fuera de muestra y aprobacion humana.

## Objetivo

Crear un ciclo continuo:

1. Recoger datos de mercado, cartera y contexto.
2. Generar hipotesis de trading medibles.
3. Estudiarlas con analisis tecnico, fundamental y de regimen.
4. Validarlas con backtests, walk-forward y paper trading.
5. Aprobar, rechazar o degradar estrategias segun metricas.
6. Ejecutar solo si el gestor de riesgo permite la orden.
7. Guardar todo en logs, SQLite, checkpoints e historial por agente.
8. Repetir el proceso y proponer mejoras controladas.

## Estructura

```text
.
|-- .env.example
|-- requirements.txt
|-- README.md
|-- docs/
|   |-- architecture.md
|   `-- operating_model.md
|-- src/
|   `-- agente_bolsa/
|       |-- main.py
|       |-- config.py
|       |-- crew.py
|       |-- logging_utils.py
|       |-- storage.py
|       |-- models.py
|       |-- config/
|       |   |-- agents.yaml
|       |   `-- tasks.yaml
|       |-- listeners/
|       |   |-- __init__.py
|       |   `-- agent_history_listener.py
|       `-- tools/
|           |-- broker.py
|           |-- market_data.py
|           |-- risk.py
|           `-- technical_analysis.py
|-- data/
|   |-- logs/agents/
|   |-- state/
|   |-- checkpoints/
|   |-- hypotheses/
|   |-- backtests/
|   `-- reports/
`-- tests/
```

## Instalacion

Python requerido: `>=3.10,<3.14`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
copy .env.example .env
```

Rellena `.env` con tus claves. Para empezar, deja `TRADING_MODE=paper` y `ALLOW_LIVE_TRADING=false`.

Runbook operativo de arranque y verificaciones:

- [docs/startup_runbook.md](docs/startup_runbook.md)

## Alpaca paper trading

La conexion con Alpaca queda preparada en modo paper. Edita `.env` y rellena:

```env
TRADING_MODE=paper
ALLOW_LIVE_TRADING=false
BROKER=alpaca
ALPACA_API_KEY=tu_api_key
ALPACA_SECRET_KEY=tu_secret_key
ALPACA_PAPER_ENDPOINT=https://paper-api.alpaca.markets
ALPACA_PAPER=true
```

Tambien se acepta `ALPACA_KEY` como alias de `ALPACA_API_KEY`, ademas de los nombres estandar de Alpaca `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` y `APCA_API_BASE_URL`.

Para comprobar la conexion:

```powershell
python -m agente_bolsa.main broker-status
```

Para leer cartera, posiciones y ordenes abiertas en Alpaca paper:

```powershell
python -m agente_bolsa.main portfolio-status
```

Para pedir al LLM una decision operativa estructurada y generar planes en modo dry-run:

```powershell
python -m agente_bolsa.main decide-once --top-per-side 5
```

`decide-once` no envia ordenes. Lee el ultimo estudio tecnico cerrado, el ultimo informe de sentimiento si existe y la cartera real de Alpaca paper. El LLM propone `buy`, `sell`, `hold`, `reduce` o `exit`, y el sistema calcula el tamano de compra de forma determinista con `MAX_RISK_PER_TRADE`, `MAX_POSITION_EXPOSURE`, `MAX_PORTFOLIO_EXPOSURE` y `buying_power`.

Para enviar a Alpaca paper los planes aprobados pendientes:

```powershell
python -m agente_bolsa.main execute-approved --confirm-paper
```

El comando solo funciona en `TRADING_MODE=paper` y `ALPACA_PAPER=true`. Si NYSE esta cerrado, bloquea el envio salvo que anadas `--queue-closed-market` para dejar las ordenes en cola. Las compras se envian como market bracket orders si `USE_BRACKET_ORDERS=true`; las ventas/reducciones de posiciones existentes se envian como market orders simples.

## LLM local

Todos los agentes usan el mismo LLM configurado en `.env`. La configuracion por defecto espera tu servidor local de `llama.cpp`:

```env
OPENAI_API_KEY=local-llama
OPENAI_API_BASE=http://127.0.0.1:8080/v1
OPENAI_MODEL_NAME=qwen3.6-27b
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=1200
LLM_TIMEOUT_SECONDS=120
CREWAI_PLANNING=false
CREW_AGENT_MAX_ITER=1
CREW_AGENT_MAX_EXECUTION_SECONDS=120
```

El alias `qwen3.6-27b` debe coincidir con el parametro `--alias qwen3.6-27b` de `llama-server.exe`.

Para el modelo local, el planning interno de CrewAI queda desactivado por defecto porque anade llamadas largas. El sistema conserva su propio flujo por fases y su memoria en SQLite/JSONL.

## Comandos iniciales

```powershell
python -m agente_bolsa.main init-db
python -m agente_bolsa.main status
python -m agente_bolsa.main agents
python -m agente_bolsa.main run-once
python -m agente_bolsa.main daemon
python -m agente_bolsa.main schedule
```

Para comprobar el flujo, logs y persistencia sin llamar todavia al LLM:

```powershell
python -m agente_bolsa.main run-once --skip-crew
```

Para ver eventos recientes o seguirlos en vivo:

```powershell
python -m agente_bolsa.main log --lines 50
python -m agente_bolsa.main log --follow
python -m agente_bolsa.main log --follow --all-events
python -m agente_bolsa.main log --agent risk_manager --follow
python -m agente_bolsa.main log --raw --follow
```

La consola normal muestra solo hitos importantes: tarea, resultado, bloqueos y errores. Los eventos internos y progreso detallado siguen guardados en SQLite/JSONL y se pueden ver con `--all-events` o `--raw`.

Scheduler recomendado:

```powershell
python -m agente_bolsa.main schedule
python -m agente_bolsa.main schedule-status
python -m agente_bolsa.main job-once portfolio
python -m agente_bolsa.main job-once market --skip-crew
python -m agente_bolsa.main job-once closed-study --skip-crew
python -m agente_bolsa.main job-once daily --skip-crew
```

El scheduler usa calendario `XNYS` para bolsa americana y muestra las horas en `Europe/Madrid`.

Con mercado cerrado, el monitor de cartera no repite mensajes cada minuto. Se queda en espera y lanza un estudio tecnico amplio una sola vez por proxima apertura. Por defecto estudia el `S&P 500` completo, calcula candidatos largos/cortos y guarda el informe en:

```text
data/reports/closed_market_technical_study_<run_id>.json
```

Puedes cambiar el universo en `.env`:

```env
CLOSED_MARKET_STUDY_UNIVERSE=sp500
CLOSED_MARKET_STUDY_MAX_SYMBOLS=500
```

Tambien se aceptan overlays conservadores de cobertura:

```env
CLOSED_MARKET_STUDY_UNIVERSE=sp500_plus_recent_breakouts
CLOSED_MARKET_STUDY_UNIVERSE=sp500_plus_recent_leaders
```

Este estudio puede tardar bastante. Primero carga/rankea el universo y despues valida el estado tecnico de cada simbolo con la herramienta `technical_state_validator`.

El estudio tecnico incluye patrones de velas como apoyo o advertencia: doji, hammer, shooting star y envolventes alcistas/bajistas. Tambien detecta figuras chartistas de varias sesiones: hombro-cabeza-hombro, hombro-cabeza-hombro invertido, doble techo, doble suelo y triangulos ascendente, descendente o simetrico. Estas figuras no validan una compra por si solas; suman o restan al candidato y requieren confirmacion de ruptura cuando la figura todavia esta en formacion.

Si CrewAI/LLM esta activo, los finalistas tecnicos tambien pasan por validacion de noticias. El sistema descarga ultimas noticias por simbolo, las manda al LLM local y guarda un informe de sentimiento en:

```text
data/reports/news_sentiment_<run_id>.json
```

Configuracion:

```env
NEWS_SENTIMENT_ENABLED=true
NEWS_SENTIMENT_TOP_N=10
NEWS_ITEMS_PER_SYMBOL=5
```

Para forzarlo manualmente:

```powershell
python -m agente_bolsa.main job-once closed-study --force
```

## Seguridad operacional

- `paper trading` por defecto.
- La ejecucion real requiere `TRADING_MODE=live` y `ALLOW_LIVE_TRADING=true`.
- El agente ejecutor no decide por si solo: recibe una propuesta ya validada por riesgo.
- Cada orden debe registrar hipotesis, estrategia, razon, tamano, `entry_price`, `stop_loss` y `take_profit`.
- El ratio beneficio/riesgo minimo inicial es 1.5.
- Las validaciones incluyen un modelo inicial de costes: comision y slippage en puntos basicos.
- Cualquier estrategia nueva pasa por backtest, costes, slippage, out-of-sample y paper trading.
- El agente de mejora puede proponer codigo, pero no promoverlo a produccion sin validacion.

## Visibilidad en ejecucion

Cada ciclo imprime en consola eventos con este formato:

```text
20:44:46     | PORT  Cartera            | START  | portfolio_watch_started          | Revisando cartera...
20:44:46     | RISK  Riesgo             | CHECK  | market_closed_risk_check         | Mercado cerrado...
```

El mismo evento se guarda en:

- `data/state/agente_bolsa.sqlite3`
- `data/logs/system.jsonl`
- `data/logs/agents/<agent>.jsonl`

Asi se puede apagar y reiniciar sin perder el historial de cada agente.

## Datos reales antes del LLM

Antes de llamar a CrewAI, el sistema descarga un snapshot diario con `yfinance`, calcula variables tecnicas basicas y lo guarda en:

```text
data/reports/market_snapshot_<cycle_id>.json
```

Los agentes reciben ese snapshot en el prompt para reducir invenciones de precios o fechas.

## Fuentes de diseno consultadas

- CrewAI installation y estructura de proyecto: https://docs.crewai.com/en/installation
- CrewAI crews, memory, event listeners y checkpointing: https://docs.crewai.com/en/concepts/crews
- Alpaca paper trading con `TradingClient(..., paper=True)`: https://alpaca.markets/sdks/python/trading.html
- FINRA sobre riesgos de servicios de auto-trading: https://www.finra.org/investors/insights/auto-trading-unregistered-entities
