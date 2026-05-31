# Estudio Completo del Proyecto `agenteBolsa`

## 1. Resumen Ejecutivo

`agenteBolsa` es un sistema de decision para renta variable USA con foco en:

- generar candidatos tecnicos de forma determinista,
- enriquecerlos con sentimiento y contexto de cartera,
- dejar al LLM la capa de priorizacion y decision final dentro de un marco estricto,
- bloquear automaticamente entradas de baja calidad o con validacion historica insuficiente,
- registrar cada senal, decision y resultado para aprender despues con evidencia.

No es un sistema "LLM-only". El LLM no crea la estrategia base. La estrategia base la crea el codigo determinista:

1. construye indicadores,
2. clasifica setups,
3. calcula score tecnico,
4. define entry/stop/take,
5. aplica filtros de calidad,
6. verifica limites de riesgo,
7. registra outcomes,
8. revisa contrafactuales,
9. propone ajustes conservadores.

El LLM actua sobre un espacio ya recortado y muy estructurado.

## 2. Objetivo Real del Algoritmo

El sistema busca comprar pocas entradas `long` de alta calidad en acciones USA, con:

- tendencia favorable,
- momentum util,
- confirmacion tecnica suficiente,
- plan de riesgo predefinido,
- riesgo agregado de cartera acotado,
- trazabilidad completa para aprendizaje posterior.

Por defecto:

- trabaja en `paper`,
- no permite `live` salvo habilitacion explicita,
- no abre cortos en produccion por defecto,
- no aumenta posiciones existentes por defecto,
- limita el numero de compras por ciclo y por sesion.

## 3. Arquitectura del Proyecto

### 3.1 Modulos nucleares

- Configuracion: [config.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/config.py)
- CLI principal: [main.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/main.py)
- Scheduler: [scheduler.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/scheduler.py)
- Persistencia SQLite: [storage.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/storage.py)
- Modelos de datos: [models.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/models.py)

### 3.2 Pipeline tecnico y decision

- Features tecnicas: [technical_analysis.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/technical_analysis.py)
- Validador de estado tecnico: [technical_state_validator.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/technical_state_validator.py)
- Estudio tecnico cerrado: [technical_study.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/technical_study.py)
- Sentimiento y noticias: [news_sentiment.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/news_sentiment.py)
- Decision LLM y filtros: [trade_decision.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/trade_decision.py)
- Rebalanceo de cartera: [portfolio_optimizer.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/portfolio_optimizer.py)
- Sizing: [position_sizing.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/position_sizing.py)
- Riesgo: [risk.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/risk.py)
- Ejecucion paper: [execution.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/execution.py)

### 3.3 Aprendizaje y validacion

- Registro y outcome de senales: [signal_learning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/signal_learning.py)
- Digest diario de aprendizaje: [daily_learning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/daily_learning.py)
- Analisis contrafactual y walk-forward: [counterfactual_analysis.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/counterfactual_analysis.py)
- Ajustes adaptativos conservadores: [adaptive_tuning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/adaptive_tuning.py)
- Aprendizaje operacional: [operational_learning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/operational_learning.py)
- Salud operacional y kill switch: [operational_health.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/operational_health.py)

### 3.4 Subsistemas adicionales

- Backtest tecnico: [backtest.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/backtest.py)
- Breakout scan: [breakout_scanner.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/breakout_scanner.py)
- Pre-earnings: [pre_earnings.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/pre_earnings.py)
- Post-market review: [post_market_review.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/post_market_review.py)
- Historial de trades: [trade_history.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/trade_history.py)

## 4. Flujo End-to-End

### 4.1 Flujo principal

1. Descargar precios diarios.
2. Generar indicadores tecnicos por simbolo.
3. Evaluar estado tecnico y score direccional.
4. Producir `all_candidates`, `top_longs`, `top_shorts`.
5. Anotar contexto de aprendizaje reciente.
6. Seleccionar `selected_candidates` con ranking determinista previo al LLM.
7. Enriquecer candidatos con sentimiento de noticias.
8. Construir contexto de cartera y rebalanceo.
9. Pedir al LLM un JSON estricto de recomendaciones.
10. Aplicar `entry_quality_gate`.
11. Aplicar `backtest_gate`.
12. Dimensionar posiciones de forma determinista.
13. Validar limites de riesgo agregados.
14. Guardar recomendaciones, planes y decisiones.
15. Ejecutar solo si se permite paper auto-trading y no hay bloqueos.
16. Madurar resultados forward y revisar aprendizaje.

### 4.2 Filosofia de control

La filosofia general es:

- libertad limitada al LLM,
- determinismo fuerte en riesgo,
- aprendizaje post-hoc con evidencia,
- promocion muy conservadora de cambios.

## 5. Datos de Entrada y Features Tecnicas

### 5.1 Datos de mercado

El sistema descarga OHLCV diarios y usa un benchmark, normalmente `SPY`.

Campos base usados:

- `Open`
- `High`
- `Low`
- `Close`
- `Volume`

### 5.2 Indicadores calculados

En [technical_analysis.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/technical_analysis.py) se calculan, entre otros:

- `sma_20`, `sma_50`, `sma_200`
- `ema_12`, `ema_26`, `macd`, `macd_signal`
- `return_5d`, `return_20d`, `return_60d`
- `high_20`, `low_20`, `high_55`, `low_55`
- `prev_high_55`, `prev_low_55`
- `high_252`, `low_252`
- `volume_zscore_20`
- `atr_14`
- `realized_vol_20`
- `rsi_14`
- Bollinger bands y `bollinger_pct_b_20`
- `gap_pct`
- `trend_positive`
- `above_long_trend`
- metricas de vela: cuerpo, sombras, posicion de cierre en rango
- patrones de vela: `doji`, `hammer`, `shooting_star`, `bullish_engulfing`, `bearish_engulfing`

### 5.3 Interpretacion tecnica base

La tesis tecnica base favorece:

- precio por encima de SMA200,
- SMA20 por encima de SMA50,
- retorno 20d y 60d positivos,
- MACD sobre senal,
- RSI constructivo, no extremo,
- volumen relativo confirmando,
- cierre cerca de maximos del rango diario,
- ruptura o continuidad con confirmacion.

## 6. Logica de Estado Tecnico

El modulo [technical_state_validator.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/technical_state_validator.py) transforma features en un `candidate` con:

- `direction`
- `score`
- `setup_quality`
- `reasons`
- `technical_state`
- `risk_plan`
- `analysis_plan`
- `tool_requests`

### 6.1 Setups principales

Setups `long` detectados:

- `event_momentum_long`
  - gap fuerte,
  - volumen anormal,
  - cierre firme,
  - ruptura amplia.

- `range_expansion_breakout_long`
  - gap moderado,
  - ruptura 55d,
  - volumen,
  - cierre muy fuerte,
  - RSI controlado.

- `orderly_breakout_long`
  - ruptura 55d sin gap extremo,
  - cierre muy fuerte,
  - volumen positivo,
  - extension mas ordenada.

- `breakout_continuation_long`
  - continuidad de ruptura ya iniciada.

- `momentum_shakeout_hold_long`
  - pullback/gap bajista tactico dentro de una estructura alcista aun fuerte.

- `confirmed_pattern`
  - patron chartista confirmado con sesgo alcista.

- `trend_volume`
  - tendencia positiva con volumen y momentum aceptables.

- `baseline_trend`
  - sesgo alcista general, sin setup mas especifico.

### 6.2 Logica de score

El `score` no es un modelo estadistico; es una suma heuristica de puntos.

Puntos a favor del lado largo:

- precio sobre SMA200,
- SMA20 > SMA50,
- retorno 20d positivo,
- retorno 60d favorable,
- MACD sobre senal,
- RSI constructivo,
- volumen confirma,
- cierre cerca de banda superior,
- setup de ruptura o momentum,
- velas alcistas,
- patrones chartistas confirmados.

Puntos a favor del lado corto:

- precio bajo SMA200,
- SMA20 < SMA50,
- retorno 20d/60d negativo,
- MACD bajo senal,
- RSI sobreextendido,
- volumen confirma caida,
- fallo de ruptura,
- velas bajistas,
- patrones bajistas.

El sistema escoge `direction` segun el lado con mejor score.

### 6.3 Setup quality

`setup_quality` resume la calidad del estado tecnico. La capa de seleccion y filtrado posterior da prioridad practica a `strong`.

## 7. Estudio Tecnico Cerrado

El estudio principal de mercado cerrado en [technical_study.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/technical_study.py):

- escanea un universo configurable,
- calcula `relative_return_20d` contra benchmark,
- produce `all_candidates`,
- ordena `top_longs` y `top_shorts` por `score`,
- almacena warnings, counts y solicitudes de analisis.

Salida principal:

- `all_candidates`: todos los candidatos evaluados.
- `top_longs`: top por score bruto.
- `top_shorts`: top por score bruto.
- `analysis_plan_counts`: conteo de chequeos activados.
- `setup_counts`: conteo de familias de setup.

Importante: `top_longs` no es toda la verdad del sistema; desde la mejora reciente, la decision ya no depende solo de ese ranking bruto.

## 8. Seleccion Determinista Antes del LLM

La capa mas importante para entender la version actual vive en [trade_decision.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/trade_decision.py).

### 8.1 Problema que corrige

Antes, el LLM veia principalmente `top_longs[:N]` ordenado por `score`. Eso podia dejar fuera candidatos con menor score bruto pero mejor expectativa historica.

### 8.2 Cambio actual

Ahora se construyen:

- `selected_candidates`
- `selection_metadata`

desde `all_candidates`, no solo desde `top_longs`.

### 8.3 Regla de elegibilidad para seleccion

Un candidato debe cumplir, como minimo:

- `direction == long`
- `setup_quality == strong`
- `return_20d > 0`
- `risk_plan` valido con `stop < entry < take`

### 8.4 Selection score

El ranking previo al LLM usa un `selection_score` que mezcla:

- edge historico reciente (`expected_edge_3d`),
- edge de setup,
- shrinkage por muestra pequena,
- score tecnico,
- fuerza relativa,
- volumen,
- confirmacion de patron,
- penalizaciones operacionales,
- penalizacion explicita a setups degradados.

### 8.5 Shrinkage

La logica evita que una muestra pequena domine:

- `combo_n >= 30`: el perfil especifico pesa mucho.
- `8 <= combo_n < 30`: mezcla perfil y setup con penalizacion por incertidumbre.
- `combo_n < 8`: se cae a setup/base y se desinfla el edge.

### 8.6 Shadow-only setup

`range_expansion_breakout` queda visible para estudio, pero bloqueado para compra automatica:

- puede aparecer en contexto,
- puede registrarse como candidato,
- no debe terminar en `buy` aprobada.

Razon: evidencia historica reciente desfavorable y necesidad de mas muestra antes de reactivar.

## 9. Sentimiento y Noticias

El modulo [news_sentiment.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/news_sentiment.py) hace dos cosas:

1. descarga noticias por simbolo,
2. usa LLM para clasificar si el flujo informativo apoya o no el setup tecnico.

Campos de salida tipicos:

- `sentiment`
- `sentiment_score`
- `supports_technical_setup`
- `confidence`
- `summary`
- `risk_flags`

Ademas existe un filtro determinista de `material news risk` basado en terminos negativos como:

- `downgrade`
- `guidance cut`
- `lawsuit`
- `investigation`
- `fraud`
- `bankruptcy`
- `data breach`

Interpretacion:

- el sentimiento no crea una compra por si solo,
- pero puede bloquear una compra si el tono es claramente negativo o si falla la validacion de noticias.

## 10. Papel del LLM

### 10.1 Lo que si hace

El LLM:

- compara candidatos seleccionados contra posiciones actuales,
- decide `buy|sell|hold|reduce|exit`,
- evalua edge relativo entre mantener vs abrir,
- incorpora sentimiento, contexto de cartera y aprendizaje reciente,
- devuelve un JSON estricto.

### 10.2 Lo que no hace

El LLM no deberia:

- inventar precios,
- inventar posiciones,
- inventar riesgo,
- comprar candidatos `blocked_auto_buy`,
- rotar solo porque otro ticker tenga mas score,
- forzar operaciones por tener cash disponible.

### 10.3 Contexto entregado al LLM

El prompt incluye:

- snapshot de cartera,
- `technical_candidates.selected_candidates`,
- `technical_candidates.top_longs` como secundario,
- noticias por candidato,
- contexto de rebalanceo,
- digest de aprendizaje diario,
- respuestas operacionales activas,
- guidance post-market,
- limites de riesgo.

### 10.4 Contrato de salida

El LLM debe devolver como maximo 3 recomendaciones con:

- `symbol`
- `action`
- `confidence`
- `reason`
- `entry_price`
- `stop_loss`
- `take_profit`
- `target_exposure_pct`
- `time_horizon`
- `invalidation`

## 11. Filtro de Calidad de Entrada

La funcion `validate_entry_quality` en [trade_decision.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/trade_decision.py) es uno de los guardarrailes mas duros del sistema.

### 11.1 Bloqueos tipicos

Una compra puede ser rechazada por:

- direccion no long,
- `setup_quality != strong`,
- `range_expansion_breakout_shadow_only`,
- score por debajo del minimo,
- retorno 20d no positivo,
- fuerza relativa 20d negativa vs benchmark,
- MACD no confirmando,
- sentimiento negativo o fallo de noticias,
- RSI flojo con volumen flojo,
- prior reciente negativo con muestra suficiente,
- prior historicamente mal calibrado,
- precio demasiado extendido sobre SMA20,
- RSI extremo sin score y patron excepcionales,
- entrada extendida sin volumen, sin fuerza relativa o sin patron confirmado.

### 11.2 Excepciones permitidas

Hay excepciones controladas para:

- `event_momentum`
- `orderly_breakout`
- `momentum_shakeout_hold`
- `momentum_confirmation`

Estas excepciones no son libertad total. Exigen combinaciones duras de:

- score alto,
- RSI bajo control,
- volumen suficiente,
- cierre fuerte en rango,
- a veces patron confirmado,
- a veces momentum 20d muy alto.

### 11.3 Idea de fondo

El filtro de entrada intenta evitar:

- perseguir extension excesiva,
- comprar sin confirmacion,
- comprar edge historicamente degradado,
- operar setups sin evidencia reciente.

## 12. Backtest Gate

El `backtest_gate` valida si el setup del simbolo pasa una prueba mecanica reciente.

### 12.1 Estrategia de backtest

En [backtest.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/backtest.py) se backtestea una regla simple:

- entrada cuando el estado tecnico pasado era `long` y `strong`,
- entrada en la apertura siguiente,
- salida por `stop_loss`, `take_profit` o `time_stop`,
- posicion con exposicion fija,
- costes de transaccion incluidos.

### 12.2 Metricas calculadas

- `trades`
- `wins`
- `losses`
- `hit_rate`
- `total_net_pl`
- `total_return`
- `avg_trade_return`
- `profit_factor`
- `max_drawdown`
- `sharpe`
- `avg_holding_days`
- `exit_reasons`
- resumen por regimen

### 12.3 Benchmark

Se compara contra benchmark via:

- `alpha_vs_benchmark`
- `trade_window_alpha`
- `beat_rate`

### 12.4 Gate de aprobacion

Por defecto, el gate pide al menos:

- `min_trades = 10`
- `min_hit_rate = 0.45`
- `min_profit_factor = 1.05`
- `max_drawdown = 0.10`
- `min_trade_window_alpha >= 0`
- `max_negative_regimes = 1` con muestra minima por regimen

Interpretacion:

- una compra no pasa solo por gustar al LLM,
- tambien necesita una minima coherencia mecanica reciente.

## 13. Sizing y Margenes de Riesgo

### 13.1 Sizing

En [position_sizing.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/position_sizing.py) el notional recomendado es el minimo entre:

- notional permitido por `MAX_RISK_PER_TRADE`,
- notional objetivo por exposicion,
- espacio restante por activo,
- buying power disponible.

Formula clave:

- `risk_per_dollar = abs(entry - stop) / entry`
- `max_risk_notional = (portfolio_value * max_risk_per_trade) / risk_per_dollar`

### 13.2 Limites principales por defecto

- `MAX_PORTFOLIO_EXPOSURE = 0.50`
- `MAX_POSITION_EXPOSURE = 0.05`
- `MAX_RISK_PER_TRADE = 0.01`
- `MAX_TOTAL_OPEN_RISK = 0.03`
- `MAX_ORDERS_PER_CYCLE = 3`
- `MAX_DAILY_BUY_ORDERS = 3`
- `MIN_ORDER_NOTIONAL = 100`

Interpretacion economica:

- como maximo, la cartera pretende estar al 50% expuesta,
- cada posicion nueva tiende a caparse en 5% de cartera,
- el riesgo teorico por trade se limita al 1% de equity,
- el riesgo agregado abierto se limita al 3%,
- se prefieren pocas entradas.

### 13.3 Riesgo por orden

En [risk.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/risk.py):

- se exige `stop < entry < take` para compras,
- `reward_risk >= 1.5`,
- la exposicion por activo no puede exceder el limite,
- la exposicion agregada proyectada tampoco,
- el riesgo abierto agregado proyectado no puede superar `MAX_TOTAL_OPEN_RISK`.

## 14. Contexto de Rebalanceo

El modulo [portfolio_optimizer.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/portfolio_optimizer.py) no ejecuta rebalanceos automaticamente, pero prepara contexto para que el LLM piense bien:

- posiciones actuales con P/L y drawdown,
- mejores candidatos nuevos,
- candidatos `short` como aviso de riesgo,
- coste estimado de rotacion,
- `rotation_candidates`,
- guidance de politica.

Principio importante:

- una posicion abierta no se cierra solo porque aparezca otra mejor,
- el default es mantener hasta `stop_loss` o `take_profit`,
- la rotacion requiere motivo material.

## 15. Ejecucion

El modulo [execution.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/execution.py) envia ordenes solo en `paper` bajo condiciones estrictas.

### 15.1 Condiciones para auto-ejecutar

- `TRADING_MODE = paper`
- `ALPACA_PAPER = true`
- `AUTO_PAPER_TRADING = true`
- `REQUIRE_HUMAN_APPROVAL = false`
- sin bloqueos operacionales

### 15.2 Bracket orders

Si procede, usa:

- `take_profit`
- `stop_loss`

como `bracket order` en Alpaca, salvo casos como fraccionales donde ajusta el tipo de orden.

### 15.3 Kill switch operacional

Si el health report activo marca alertas criticas, puede bloquear nuevas compras y tambien la ejecucion de compras.

## 16. Como Aprende el Sistema

El aprendizaje esta distribuido en varias capas. No existe un solo "modelo entrenado". Hay varios mecanismos de memoria y revision.

### 16.1 Registro de senales

Cada `candidate` se guarda en `signal_outcomes` con:

- features tecnicas,
- score,
- setup,
- ranks,
- gates,
- outcome futuro,
- decision posterior.

Esto ocurre en [signal_learning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/signal_learning.py).

### 16.2 Decisiones registradas

Cuando el LLM decide, el sistema actualiza la senal como:

- `candidate`
- `approved_buy`
- `blocked_entry_quality`
- `blocked_backtest`
- `hold`
- `executed_buy`

Esto permite estudiar no solo lo que se compro, sino tambien lo que se dejo pasar.

### 16.3 Maduracion de outcomes

Horizontes forward:

- `1d`
- `3d`
- `5d`
- `10d`

Para cada senal se calculan:

- `return_1d`, `return_3d`, `return_5d`, `return_10d`
- `mfe_10d`
- `mae_10d`
- primer toque de `stop_loss` o `take_profit`

### 16.4 Observaciones canonicas

`daily_learning.py` agrupa senales repetidas intradia o por familia de fuente en una observacion canonica.

Objetivo:

- evitar contar multiples veces la misma oportunidad,
- distinguir entre candidata, bloqueada, aprobada y ejecutada,
- construir un ledger limpio para aprendizaje.

### 16.5 Digest diario

El digest diario calcula, entre otras cosas:

- `setup_stats_3d`
- buckets por feature/tag
- calibracion del filtro de entrada
- accuracy del prior
- guidance textual de aprendizaje

### 16.6 Priors de aprendizaje

Para cada candidato se puede construir un `learning_prior` usando:

- un `profile_key` derivado de setup y buckets de indicadores,
- estadistica reciente del perfil,
- fallback a estadistica agregada del setup.

Campos tipicos:

- `expected_edge_1d`
- `expected_edge_3d`
- `sample_size_3d`
- `setup_sample_size_3d`
- `win_rate_recent_3d`
- `confidence_weight_3d`
- `operational_penalty`

Interpretacion:

- no es un predictor supervisado avanzado,
- es una memoria estadistica estructurada de como se comportaron perfiles parecidos.

### 16.7 Counterfactuals

En [counterfactual_analysis.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/counterfactual_analysis.py) el sistema compara politicas tipo:

- lo que se hizo,
- lo que se podria haber hecho,
- lo bloqueado por gates,
- oportunidades perdidas,
- cambios de ranking,
- validacion walk-forward.

Esta capa sirve para responder preguntas como:

- que setups estan degradando resultado,
- si el filtro esta evitando perdedores o bloqueando ganadores,
- si un cambio mejora de forma estable en varias ventanas cronologicas.

### 16.8 Aprendizaje operacional

En [operational_learning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/operational_learning.py) el sistema analiza:

- historial real de trades,
- errores recurrentes,
- familias de features asociadas a perdidas,
- posibles `shadow rules`,
- reglas activas o en observacion.

Estas reglas pueden:

- despriorizar setups antes del LLM,
- bloquear ejecucion bajo ciertas condiciones,
- quedarse en `shadow` hasta tener evidencia suficiente.

### 16.9 Adaptive tuning

En [adaptive_tuning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/adaptive_tuning.py) se proponen overrides conservadores para pocos parametros:

- `ENTRY_QUALITY_MIN_SCORE`
- `ENTRY_QUALITY_MAX_RSI`
- `ENTRY_QUALITY_MAX_SMA20_DISTANCE`
- `MAX_DAILY_BUY_ORDERS`
- `MAX_ORDERS_PER_CYCLE`
- parametros de salidas LLM excepcionales
- parametros de extension

Importante:

- los cambios nacen como `shadow`,
- no se autoaplican de forma agresiva,
- se guardan en `adaptive_config.json`,
- `get_settings()` puede cargar solo los overrides `active`.

Esto reduce el riesgo de sobreajuste impulsivo.

## 17. Salud Operacional

El modulo [operational_health.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/operational_health.py) vigila:

- estado de jobs del scheduler,
- duraciones anormalmente lentas,
- ausencia de reportes clave,
- caidas de cobertura de market data,
- setups degradandose en el digest diario,
- salud del pipeline post-market.

Si detecta alertas criticas, puede activar:

- `block_new_buys`
- `block_buy_execution`

Esto es importante: el sistema no solo gestiona riesgo de mercado; tambien riesgo operacional.

## 18. Scheduler y Ritmo del Sistema

El sistema esta pensado para correr continuamente con [scheduler.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/scheduler.py).

Ritmos tipicos:

- cada minuto: vigilancia de cartera,
- cada 15 minutos: ciclo de mercado,
- cada 15 minutos en mercado cerrado: estudio tecnico cerrado,
- diario: digest de aprendizaje y revisiones,
- opcionalmente: pre-earnings y post-market review.

Tiene proteccion de `scheduler.lock` para evitar instancias duplicadas.

## 19. Persistencia y Memoria

Base principal: `data/state/agente_bolsa.sqlite3`

Tablas importantes:

- `agent_events`
- `hypotheses`
- `backtest_runs`
- `decisions`
- `trade_recommendations`
- `order_plans`
- `broker_orders`
- `signal_outcomes`
- `trade_memory`
- `strategy_rules`
- `rule_evaluations`
- `learning_observations`
- `learning_daily_summaries`
- `learning_policy_candidates`
- `learning_policy_evaluations`
- `pre_earnings_predictions`
- `pre_earnings_analyst_snapshots`

Interpretacion:

- `signal_outcomes` guarda la memoria de oportunidades.
- `trade_memory` guarda memoria de ejecuciones reales.
- `learning_observations` consolida senales repetidas.
- `learning_daily_summaries` guarda digests.
- `strategy_rules` y `policy_candidates` soportan el bucle de mejora.

## 20. Parametros Clave y Como Interpretarlos

### 20.1 LLM

- `OPENAI_API_BASE`: endpoint del modelo.
- `OPENAI_MODEL_NAME`: modelo.
- `LLM_TEMPERATURE = 0.2`: decision poco creativa.
- `LLM_MAX_TOKENS = 1200`: respuesta contenida.
- `LLM_TIMEOUT_SECONDS = 120`

Interpretacion: el LLM esta configurado para disciplina, no para exploracion.

### 20.2 Modo de trading

- `TRADING_MODE = paper`
- `ALLOW_LIVE_TRADING = false`
- `ALPACA_PAPER = true`

Interpretacion: seguridad por defecto.

### 20.3 Riesgo estructural

- `MAX_PORTFOLIO_EXPOSURE = 50%`
- `MAX_POSITION_EXPOSURE = 5%`
- `MAX_DAILY_LOSS = 2%`
- `MAX_DRAWDOWN = 10%`
- `MAX_RISK_PER_TRADE = 1%`
- `MAX_TOTAL_OPEN_RISK = 3%`

Interpretacion:

- cartera media-baja en apalancamiento direccional,
- conviccion repartida,
- tolerancia limitada a clustering de errores.

### 20.4 Entry quality

- `ENTRY_QUALITY_MIN_SCORE = 12`
- `ENTRY_QUALITY_MAX_RSI = 85`
- `ENTRY_QUALITY_MAX_SMA20_DISTANCE = 12%`
- `ENTRY_QUALITY_EXTENDED_SMA20_DISTANCE = 8%`
- `ENTRY_QUALITY_EXTENDED_MIN_RELATIVE_RETURN = 2%`

Interpretacion:

- el sistema permite momentum, pero intenta no comprar euforia descontrolada sin confirmaciones adicionales.

### 20.5 Breakout/momentum exceptions

- `ORDERLY_BREAKOUT_MIN_SCORE = 14`
- `ORDERLY_BREAKOUT_MIN_VOLUME_Z = 0.25`
- `MOMENTUM_CONFIRMATION_MIN_SCORE = 15`
- `MOMENTUM_CONFIRMATION_MIN_VOLUME_Z = 0.75`
- `MOMENTUM_CONFIRMATION_MIN_RETURN_20D = 18%`

Interpretacion:

- algunas entradas extendidas son aceptables,
- pero solo si ya son muy fuertes en varios ejes a la vez.

### 20.6 Ejecucion

- `MAX_ORDERS_PER_CYCLE = 3`
- `MAX_DAILY_BUY_ORDERS = 3`
- `MIN_ORDER_NOTIONAL = 100`
- `ALLOW_POSITION_ADDS = false`
- `USE_BRACKET_ORDERS = true`

Interpretacion: pocas decisiones, pequenas, trazables y con stop/take definidos.

### 20.7 Sentimiento

- `NEWS_SENTIMENT_ENABLED = true`
- `NEWS_SENTIMENT_TOP_N = 10`
- `NEWS_ITEMS_PER_SYMBOL = 5`
- `NEWS_SENTIMENT_FAIL_CLOSED_FOR_BUYS = true`

Interpretacion: si no se puede validar noticias correctamente, la compra puede cerrarse por seguridad.

### 20.8 Scheduler / estudios

- `MARKET_CYCLE_INTERVAL_MINUTES = 15`
- `CLOSED_MARKET_STUDY_UNIVERSE = sp500`
- `CLOSED_MARKET_STUDY_MAX_SYMBOLS = 500`
- `INTRADAY_TECHNICAL_SCAN_ENABLED = true`

Interpretacion: el sistema esta pensado para amplitud de universo pero con entradas finales muy filtradas.

## 21. Como Interpretar Resultados del Sistema

### 21.1 Si un simbolo sale como candidato

Significa:

- que tecnicamente cumple una estructura reconocible,
- no necesariamente que deba comprarse.

### 21.2 Si sale en `selected_candidates`

Significa:

- que ademas de la tecnica, el ranking previo al LLM ve edge relativo mejor ajustado por evidencia.

### 21.3 Si el LLM recomienda `hold`

No implica ausencia de oportunidades. Puede significar:

- edge insuficiente,
- riesgo agregado alto,
- sentimiento dudoso,
- coste de rotacion no compensa,
- falta de evidencia reciente.

### 21.4 Si una compra es bloqueada por `entry_quality`

Interpretacion comun:

- el setup existe,
- pero la entrada concreta esta demasiado floja, extendida o mal calibrada.

### 21.5 Si una compra es bloqueada por `backtest_gate`

Interpretacion:

- la idea puede sonar bien hoy,
- pero la regla mecanica equivalente no ha rendido suficiente en el lookback exigido.

### 21.6 Si un setup aparece como degradado

No significa "el setup murio para siempre". Significa:

- evidencia reciente negativa,
- necesidad de bajar prioridad o ponerlo en shadow,
- reactivacion solo tras validacion nueva.

## 22. Limitaciones y Riesgos del Proyecto

### 22.1 Dependencia de heuristicas

La capa tecnica usa reglas y umbrales hechos a mano. Eso da control, pero tambien puede:

- perder no linealidades,
- depender de thresholds rigidos.

### 22.2 Riesgo de muestra pequena

El aprendizaje por perfiles puede sobreinterpretar pocos casos. Por eso el shrinkage es clave.

### 22.3 Riesgo de data snooping

El sistema tiene mecanismos de mejora, pero sigue necesitando:

- validacion cronologica real,
- walk-forward,
- no tocar parametros por un par de sesiones.

### 22.4 Riesgo operacional

- market data faltante,
- jobs fallidos,
- news sentiment sin respuesta valida,
- sobrecarga del LLM,
- discrepancias broker/local.

### 22.5 Riesgo de interpretacion del LLM

El prompt es estricto, pero el LLM sigue pudiendo:

- sobreponderar narrativa,
- rotar de mas si el contexto no esta bien acotado,
- dar demasiada importancia a score sin considerar coste de cambio.

## 23. Como Explicarselo a Otro LLM

Si quieres darle este proyecto a otro LLM, la descripcion mas fiel seria:

> Sistema de trading long-only mayoritariamente deterministic-first para acciones USA. El pipeline genera candidatos tecnicos diarios con indicadores clasicos, clasifica setups de ruptura/momentum/tendencia, asigna score heuristico, define stop y take por ATR/estructura, filtra entradas por calidad y validacion historica, y solo entonces consulta a un LLM para priorizar entre pocos candidatos y posiciones existentes. Cada senal, bloqueo, compra aprobada y resultado forward se guarda en SQLite. El aprendizaje no es un modelo entrenado unico, sino una combinacion de priors estadisticos por perfil/setup, digest diario, revision contrafactual, walk-forward y reglas operacionales shadow/active. El objetivo es mejorar sin sobreajuste, con overrides conservadores y fuerte control de riesgo.

### 23.1 Preguntas que un LLM deberia poder responder con este contexto

- Que hace exactamente el score tecnico.
- Que diferencia hay entre `top_longs` y `selected_candidates`.
- Como se bloquea una compra.
- Como se calcula el sizing.
- Que aprende el sistema y donde lo guarda.
- Que resultados se usan para promover cambios.
- Que parametros son estructurales y cuales tacticos.

### 23.2 Contexto minimo recomendado para otro LLM

Dale, como minimo:

- este documento,
- [config.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/config.py),
- [trade_decision.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/trade_decision.py),
- [technical_state_validator.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/technical_state_validator.py),
- [signal_learning.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/tools/signal_learning.py),
- un `latest_closed_market_technical_study.json`,
- un `latest_daily_learning_digest.json`,
- un `latest_operational_health.json`.

## 24. Comandos Operativos Mas Importantes

- `python -m agente_bolsa.main schedule`
- `python -m agente_bolsa.main run-once`
- `python -m agente_bolsa.main decide-once`
- `python -m agente_bolsa.main scan-technical`
- `python -m agente_bolsa.main backtest --symbol XYZ`
- `python -m agente_bolsa.main missed-opportunities`
- `python -m agente_bolsa.main decision-compare`
- `python -m agente_bolsa.main walk-forward-validate`
- `python -m agente_bolsa.main adaptive-status`
- `python -m agente_bolsa.main adaptive-tune`
- `python -m agente_bolsa.main live-readiness`

## 25. Diagnostico Rapido del Diseno

### 25.1 Fortalezas

- Muy trazable.
- Riesgo deterministicamente controlado.
- LLM acotado por contexto y JSON estricto.
- Aprendizaje basado en evidencia y no en intuicion.
- Buen soporte para analizar oportunidades perdidas y bloqueos.

### 25.2 Debilidades

- Complejidad creciente por acumulacion de reglas.
- Dependencia de thresholds manuales.
- El aprendizaje sigue siendo mas estadistico-heuristico que verdaderamente predictivo.
- Si la calidad del contexto baja, el LLM puede degradar decisiones.

### 25.3 Donde esta hoy el mayor edge de mejora

Por diseno actual, las mejoras con mejor relacion retorno/riesgo estan en:

- mejor ranking previo al LLM,
- mejor calibracion de setups por evidencia,
- mejor control de muestras pequenas,
- mejor seguimiento de coste de oportunidad del `entry_quality_gate`,
- mayor disciplina en walk-forward antes de activar overrides.

## 26. Conclusiones

Este proyecto no es simplemente "un bot que compra por prompt". Es una arquitectura hibrida:

- reglas tecnicas duras,
- ranking determinista,
- decision contextual del LLM,
- riesgo mecanico,
- memoria completa de senales,
- analisis contrafactual,
- adaptacion conservadora.

La mejor forma de entenderlo al 100% es pensar en cinco capas:

1. `detectar`: generar setups y score.
2. `filtrar`: quitar entradas malas o sin evidencia.
3. `decidir`: usar LLM solo sobre un subconjunto de alta calidad.
4. `ejecutar`: size y riesgo completamente acotados.
5. `aprender`: medir todas las decisiones y promover cambios solo con evidencia.

Si se rompe una de esas capas, el sistema sigue teniendo guardarrailes en las otras. Esa es la logica central del proyecto.
