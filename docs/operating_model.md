# Modelo operativo

## Rutina continua

El comando recomendado para funcionamiento continuo es `schedule`. Lanza tres ritmos:

```powershell
python -m agente_bolsa.main schedule
```

Ritmos:

- Cada minuto: `portfolio_watch_job`.
- Cada 15 minutos: `market_cycle_job`.
- Cada dia: `daily_study_job`.

Cada job consulta el calendario `XNYS` de bolsa americana en zona `America/New_York` y registra las horas en `Europe/Madrid`. Asi el sistema no depende de la hora espanola para decidir si puede operar.

Comprobacion del calendario:

```powershell
python -m agente_bolsa.main schedule-status
```

Pruebas manuales:

```powershell
python -m agente_bolsa.main job-once portfolio
python -m agente_bolsa.main job-once market --skip-crew
python -m agente_bolsa.main job-once daily --skip-crew
```

## Comportamiento por ritmo

### Cada minuto

Agentes implicados:

- `portfolio_manager`
- `risk_manager`
- `compliance_guardian`

Objetivo:

- Saber si NYSE esta abierto.
- Revisar estado de cartera, PnL, ordenes abiertas y limites si NYSE esta abierto.
- Si el mercado esta cerrado, avisar una sola vez y quedar en espera.
- Si el mercado esta abierto, preparar control intradia.

No tiene sentido repetir el mismo aviso cada minuto con mercado cerrado. Por eso el sistema guarda una marca de estado y no vuelve a imprimir hasta que cambie la proxima apertura.

### Cada 15 minutos

Agentes implicados:

- `orchestrator`
- `market_data_researcher`
- `technical_analyst`
- `hypothesis_generator`
- `quant_backtester`
- `risk_manager`
- `portfolio_manager`
- `execution_agent`

Objetivo:

- Solo corre si NYSE esta abierto.
- Descargar snapshot real.
- Recalcular variables tecnicas.
- Generar o revisar hipotesis.
- Bloquear cualquier decision sin backtest, stop loss, take profit y riesgo definido.

### Mercado cerrado: estudio tecnico amplio

Ademas del ciclo intradia, hay un job `closed_market_technical_study`.

Objetivo:

- Solo corre si NYSE esta cerrado.
- Se ejecuta una sola vez por proxima apertura.
- Escanea el universo configurado (`sp500_top250` por defecto: 250 mayores companias del S&P 500 por capitalizacion).
- Genera candidatos largos y cortos.
- Calcula entrada teorica, stop loss, take profit, ATR, momentum, volumen, tendencia y patrones de velas.
- Para los finalistas tecnicos, descarga noticias recientes y valida sentimiento con el LLM local.
- Guarda el informe en `data/reports/closed_market_technical_study_<run_id>.json`.
- Guarda el sentimiento en `data/reports/news_sentiment_<run_id>.json`.
- Si CrewAI esta activo, pasa los mejores candidatos al grupo de agentes para una revision mas profunda.

La validacion por simbolo usa la herramienta `technical_state_validator`. Esta herramienta decide que analisis tecnicos aplicar segun el estado del simbolo:

- `trend_stack`
- `momentum_profile`
- `volatility_atr`
- `volume_confirmation`
- `candlestick_patterns`
- `chart_patterns`
- `breakout_continuation`
- `breakdown_or_reversal`
- `overextension_check`
- `mean_reversion_check`
- `high_volatility_risk`
- `volume_event`
- `candle_confirmation`
- `candle_indecision`
- `risk_plan`

Si durante el analisis detecta que falta una herramienta, genera una solicitud asignada a `self_improvement_engineer`, por ejemplo:

- `premarket_volume_validator`
- `sector_relative_strength_validator`

### Cada dia

Agentes implicados:

- `post_trade_analyst`
- `self_improvement_engineer`
- `quant_backtester`
- `risk_manager`

Objetivo:

- Solo corre si fue dia de mercado y la sesion ya cerro.
- Revisar resultados del dia.
- Comparar hipotesis contra mercado real.
- Actualizar backlog de mejoras.
- Proponer nuevos experimentos, no activar live trading.

## Fases del ciclo base

Fases por ciclo:

1. `preflight`: valida configuracion, modo paper/live, claves y carpetas.
2. `data_update`: actualiza precios y contexto.
3. `research`: los agentes generan observaciones.
4. `hypothesis`: se crean hipotesis nuevas o se revisan antiguas.
5. `validation`: backtest, walk-forward y pruebas de robustez.
6. `risk_review`: bloqueo o aprobacion de propuestas.
7. `execution`: paper/live segun configuracion.
8. `post_mortem`: aprendizaje y resumen del ciclo.

## Decision operativa LLM

La primera version operativa queda en modo dry-run:

1. `portfolio-status` lee cuenta, posiciones y ordenes abiertas desde Alpaca paper.
2. `decide-once` carga los mejores candidatos del ultimo estudio tecnico cerrado y el ultimo sentimiento disponible.
3. El LLM devuelve JSON estricto con `buy`, `sell`, `hold`, `reduce` o `exit`.
4. El codigo normaliza la respuesta y calcula el tamano de compras con reglas deterministas.
5. `risk_manager` valida entrada, stop, take profit, exposicion maxima y ratio beneficio/riesgo.
6. Se guardan recomendaciones y planes en SQLite, pero no se envia ninguna orden.
7. `execute-approved` envia planes aprobados a Alpaca paper solo con confirmacion explicita o `AUTO_PAPER_TRADING=true`.
8. Si NYSE esta cerrado, `execute-approved` bloquea el envio salvo `--queue-closed-market`.

El LLM decide intencion y tesis. El codigo decide limites, tamano maximo y aprobacion de riesgo.

En la consola se imprime cada fase con agente, ciclo y accion. Para validar la maquinaria sin consumir LLM se puede ejecutar:

```powershell
python -m agente_bolsa.main run-once --skip-crew
```

Para seguir el sistema mientras trabaja:

```powershell
python -m agente_bolsa.main log --follow
```

## Auto-mejora

El sistema se auto-mejora por evidencia acumulada, no por intuicion del LLM.

1. Memoria operativa: todos los agentes guardan eventos en SQLite y JSONL.
2. Medicion: cada hipotesis debe tener entrada, salida, invalidacion, stop, take profit y costes.
3. Validacion: el backtester debe calcular rendimiento neto, drawdown, Sharpe, numero de operaciones, slippage y robustez fuera de muestra.
4. Post-mortem: el sistema clasifica fallos como mala tesis, mala ejecucion, mala calidad de datos o mala suerte.
5. Backlog: `self_improvement_engineer` propone cambios concretos.
6. Promocion: una mejora solo pasa a uso si supera tests, backtest y paper trading.

La auto-mejora puede proponer codigo, indicadores o prompts, pero no puede saltarse al `risk_manager`, cambiar a live trading ni ejecutar una estrategia no validada.

## Estudios tecnicos

Los estudios tecnicos iniciales se hacen como variables medibles:

- Tendencia: SMA 20, 50 y 200; pendiente; precio sobre o bajo media larga.
- Momentum: retorno 20 dias, maximos/minimos de N dias, rupturas y aceleracion.
- Volatilidad: ATR 14, rango, gaps, expansion/contraccion de volatilidad.
- Volumen: media 20 dias, desviacion, z-score de volumen y confirmacion de ruptura.
- Velas: doji, hammer, shooting star, envolvente alcista y envolvente bajista como confirmacion o advertencia.
- Figuras chartistas: hombro-cabeza-hombro, hombro-cabeza-hombro invertido, doble techo, doble suelo y triangulos mediante pivotes locales, neckline/soporte/resistencia, estado confirmado o en formacion y confianza.
- Sentimiento: noticias recientes de los finalistas tecnicos, validadas por LLM como apoyo, contradiccion o contexto neutro.
- Fuerza relativa: comparacion contra `SPY` y, mas adelante, contra sector.
- Regimen: mercado abierto/cerrado, sesion, tendencia del benchmark, volatilidad del indice.
- Riesgo tecnico: stop basado en ATR, take profit, ratio beneficio/riesgo y time stop.

Ninguna lectura tecnica vale por si sola. Debe convertirse en regla testeable y pasar costes, slippage y fuera de muestra.

## Criterios de promocion iniciales

Una estrategia candidata solo pasa de investigacion a paper si cumple:

- Al menos `MIN_BACKTEST_TRADES` operaciones.
- Sin look-ahead bias conocido.
- Costes y slippage incluidos.
- Sharpe fuera de muestra superior a `MIN_OUT_OF_SAMPLE_SHARPE`.
- Drawdown inferior a `MAX_STRATEGY_DRAWDOWN`.
- Resultado no dependiente de un unico simbolo o periodo corto.

Para pasar de paper a live:

- Minimo 30 dias naturales en paper.
- Max drawdown en paper dentro del limite.
- Diferencia razonable entre backtest y paper.
- Revision humana del reporte.
- `ALLOW_LIVE_TRADING=true`.

## Historial por agente

Cada agente escribe eventos JSONL:

```json
{
  "timestamp": "2026-04-26T12:00:00Z",
  "agent": "technical_analyst",
  "event_type": "observation",
  "cycle_id": "20260426-120000",
  "payload": {
    "symbol": "AAPL",
    "signal": "trend_positive",
    "confidence": 0.62
  }
}
```

Esto permite apagar y reiniciar sin perder contexto. La base SQLite guarda una version consultable y los JSONL mantienen una auditoria sencilla.

## Modo de mejora

El agente `self_improvement_engineer` puede:

- Proponer nuevos indicadores.
- Crear nuevas hipotesis.
- Sugerir cambios de prompts.
- Generar modulos de estrategia en sandbox.
- Crear tests y backtests asociados.

No puede:

- Activar live trading.
- Saltarse al gestor de riesgo.
- Modificar claves, limites o ejecutor de ordenes sin revision.
- Promover una estrategia solo por una explicacion convincente.

## Fallos y recuperacion

- Si un ciclo falla, se registra en `data/logs/system.jsonl`.
- Los agentes conservan historial individual.
- CrewAI puede usar checkpoints en `data/checkpoints`.
- SQLite conserva hipotesis y resultados.
- Al reiniciar, `status` muestra estado basico y la proxima ejecucion continua el ciclo.
