# Estudio semanal de resultados — agenteBolsa

Metodología fija y repetible para revisar lo que ha hecho el grupo de agentes
durante la semana. Pensado para ejecutarse **el viernes tras el cierre de mercado**
(NYSE cierra 20:00 UTC / 22:00 Europe/Madrid) y **después de los jobs post-mercado**
(`post_market_review`, `broker_reconciliation`, `daily_study` ~21:00 UTC), que son
los que consolidan el aprendizaje del día.

Es un estudio de **solo lectura**: no cambia configuración, no toca trading.

## 1. Objetivo

Responder con datos a: ¿el grupo está ganando/perdiendo y por qué?, ¿las decisiones
del LLM son de calidad?, ¿qué setups/regímenes tienen edge?, y ¿qué conviene
promover o retirar de cara a la semana siguiente?

## 2. Fuentes de datos (con plan B si la BD está bloqueada)

La BD vive en `data/state/agente_bolsa.sqlite3`. Con el scheduler escribiendo,
una lectura directa puede dar `disk I/O error`. Orden de preferencia:

1. **BD en solo-lectura** (`?mode=ro`, con reintentos). Si falla por escritura
   concurrente, pedir una pausa breve del scheduler (1-2 min) o seguir con (2).
2. **Reportes JSON** en `data/reports/` (siempre legibles): `performance_*`,
   `latest_*` (technical_study, breakout_scan, news_sentiment, opportunities,
   agents_healthcheck, daily_learning_digest, post_market_learning).
3. **Logs** `data/logs/system.jsonl` y `data/logs/agents/*.jsonl` para conteos de
   ciclos, decisiones, fallos LLM y trazas de agentes.

## 3. Métricas a calcular

- **Rendimiento**: equity y P&L de la semana (de `performance_daily`); P&L
  realizado FIFO desde `broker_orders` reconciliadas (precio/qty en
  `broker_order_reconciled`); nº ganadoras/perdedoras, profit factor, hit-rate.
- **Operativa**: nº compras propuestas vs ejecutadas; en qué etapa se vetan
  (entry_quality / backtest_gate / risk / regime), desde `paper_auto_trade_completed`.
- **Edge por setup/régimen**: expectativa y alpha vs SPY a 1/3/5/10 días por
  `setup_quality`, tag y `market_regime` (reusar `tools/edge_analysis.py` /
  `scripts/edge_shadow_analysis.py`).
- **Salud LLM**: nº llamadas OK/fallidas por proveedor/modelo y propósito
  (decisión, sentimiento, mejora continua); confirmar 0 caídas a fallback en las
  decisiones; anotar incidencias (429/403/quota) y el cambio de proveedor a media
  semana (MiMo -> opencode-go/kimi-k2.6/glm-5.2).
- **Mejora continua**: propuestas/validaciones, promociones/demociones del
  evaluador (`promotion_readiness`), backlog pendiente.

## 4. Decisiones a proponer (sin auto-aplicar)

- Qué setups/pockets retirar a shadow por edge negativo con muestra suficiente.
- Qué near-miss del backtest-gate ya tienen expectativa forward positiva para
  considerar relajar (solo con evidencia).
- Si la calidad de decisión con kimi/glm mejora o no frente a la etapa anterior.
- Si conviene activar el corte de perdedores (`stale_guard`) o subir el peso del
  ranker RS más allá del fallback.

## 5. Salida

Un informe escrito (resumen ejecutivo + tablas) y, si procede, persistirlo en
`data/reports/weekly_study_<fecha>.md`. Nada se aplica automáticamente: las
acciones se deciden con el informe delante.

## 6. Cadencia

Viernes tras cierre. Esta primera edición: viernes 19-jun-2026. Si una semana el
sistema estuvo en modo degradado (sin LLM) parte del tiempo, anotarlo como
limitación de la muestra.
