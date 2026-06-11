# Informe del proyecto y plan hacia autonomía total

Fecha: 2026-06-10

## 1. Resumen ejecutivo

`agenteBolsa` es un sistema multiagente (CrewAI + Python, ~47.600 líneas, 42 suites de tests) que opera acciones USA en paper trading con Alpaca. Su diseño actual es un **pipeline autónomo controlado**: el código determinista genera candidatos técnicos (S&P 500), los enriquece con sentimiento de noticias, el LLM prioriza y decide dentro de un marco estricto, y capas deterministas de riesgo, sizing y calidad bloquean lo que no cumple. Todo queda registrado en SQLite/JSONL para aprendizaje posterior.

**Estado frente a tu objetivo:** la infraestructura está muy avanzada (~70-80%), pero la autonomía real está limitada por diseño (~25-30%). El sistema aprende de forma conservadora (ajuste de parámetros, contrafactuales) y su capacidad de auto-modificar código está restringida por allowlist a módulos periféricos. No puede crear estrategias nuevas, reescribir su propio núcleo, ni promover cambios sin validación humana. El README lo dice explícitamente: "No es un trader experto plenamente autónomo".

## 2. Partes del proyecto

### 2.1 Núcleo
- `config.py`, `main.py` (CLI con +60 comandos), `scheduler.py` (jobs por minuto / 15 min / diario / mercado cerrado, calendario XNYS), `storage.py` (SQLite), `models.py`, `eventing.py`, `logging_utils.py`, `llm_router.py` (Qwen local vía llama.cpp, fallback Gemini), `market_calendar.py`.

### 2.2 Pipeline técnico y de datos
- `market_data.py` (FMP / yfinance con caché), `market_snapshot.py`, `market_state.py` (régimen, amplitud, volatilidad, postura de riesgo).
- `technical_analysis.py` (SMA/EMA, MACD, RSI, ATR, Bollinger, z-score volumen, velas), `chart_patterns.py` (HCH, doble techo/suelo, triángulos), `technical_state_validator.py`, `technical_study.py` (estudio S&P 500 con mercado cerrado), `breakout_scanner.py`, `universe.py`.

### 2.3 Decisión y ejecución
- `news_sentiment.py` (noticias por símbolo → LLM), `trade_decision.py` (decisión LLM en JSON estricto + entry_quality_gate + backtest_gate), `position_sizing.py` (sizing determinista por riesgo), `risk.py` (límites de exposición, drawdown, pérdida diaria; puede vetar todo), `portfolio_optimizer.py`, `execution.py` + `broker.py` (Alpaca paper, bracket orders).

### 2.4 Aprendizaje
- `signal_learning.py` (outcome de cada señal), `daily_learning.py`, `counterfactual_analysis.py` (retrospectivas, walk-forward), `adaptive_tuning.py` (ajustes conservadores de parámetros), `operational_learning.py`, `operational_health.py` (kill switch), `post_market_review.py`, `trade_history.py`, `pre_earnings.py`.

### 2.5 Laboratorio de mejora continua (`continuous_improvement/`)
- Runtime residente con agentes propios (orquestador, colector, evaluador, validador, risk guard, reporter), memoria compartida, experimentos y `AutoApplyCodeAgent`: aplica cambios de código pequeños y reversibles **solo** en allowlist (`continuous_improvement/`, herramientas operacionales, `tests/`, `docs/`, `.env.example`) y bloquea explícitamente broker, ejecución, claves y todo lo relativo a live trading.

### 2.6 Operación
- Dashboard Streamlit (`web_app.py`), despliegue 24/7 en Fly.io (Docker, volumen persistente, Gemini como LLM), GitHub Actions, runbooks y checklist de promoción en `docs/`.

## 3. Qué hace (flujo end-to-end)

1. Con mercado cerrado: estudio técnico del S&P 500 completo → candidatos largos/cortos con entrada, stop, take, patrones.
2. Sentimiento de noticias sobre los finalistas.
3. Con mercado abierto: ciclo cada 15 min con snapshot real + market_state.
4. LLM decide buy/sell/hold/reduce/exit sobre el espacio ya recortado.
5. Gates deterministas: calidad de entrada, backtest, sizing por riesgo, límites agregados.
6. Ejecución paper en Alpaca solo si riesgo aprueba.
7. Maduración de resultados, contrafactuales, aprendizaje diario, propuestas de ajuste.

## 4. Brecha frente al objetivo de autonomía total

| Capacidad deseada | Estado actual | Brecha |
|---|---|---|
| Comprar/vender de forma autónoma | Paper auto-trade gated; `execute-approved` requiere confirmación | Media |
| Leer noticias y entender el mercado | Sentimiento por símbolo + market_state | No hay comprensión macro continua ni ingesta amplia de noticias |
| Estudiar figuras | Velas + chartismo implementados | Bien cubierto |
| Programar y cambiar lo que necesite | AutoApplyCodeAgent con allowlist periférica | **La mayor brecha**: no puede tocar estrategia, decisión, riesgo ni crear módulos nuevos |
| Aprender y mejorar cada día | Tuning conservador de parámetros, contrafactuales | No crea estrategias nuevas; no edita sus propios prompts/agentes |
| Análisis del pasado para mejorar el futuro | Walk-forward, retrospectivas, postmortems | Existe pero alimenta cambios pequeños, no rediseños |
| Libertad total | Filosofía explícita de "libertad limitada al LLM" | Choque de diseño deliberado |

Limitaciones adicionales: el LLM local corre con `max_iter=1` y planning desactivado (poca capacidad de razonamiento profundo); los agentes están definidos en YAML estático y no pueden auto-modificarse; la promoción de cambios exige aprobación humana.

## 5. Plan hacia el sistema de agentes autónomos

Principio recomendado: **autonomía total sobre todo excepto un kernel inmutable mínimo** (credenciales, kill switch, límite absoluto de pérdida, flag de live trading). Los agentes pueden reescribir cualquier otra cosa — estrategias, prompts, herramientas, sus propios agentes — siempre que cada cambio pase validación automática (no humana) y tenga rollback. Así consigues libertad real sin que un bug autoinfligido vacíe la cuenta.

### Fase 0 — Cimientos (1-2 semanas)
- Subir capacidad de razonamiento: modelo más potente para los agentes de investigación/mejora (mantener el local para tareas rutinarias vía `llm_router`), `max_iter` > 1 y planning activado para el laboratorio.
- Baseline de métricas: Sharpe, drawdown, hit rate, PnL paper actuales como referencia obligatoria de toda mejora futura.
- Sandbox git real: cada cambio de agente en rama propia, CI completo (pytest + ruff + smoke run), merge automático solo si todo pasa; rollback automático si las métricas caen tras N sesiones.

### Fase 1 — Autonomía de código (2-4 semanas)
- Ampliar progresivamente el allowlist de `AutoApplyCodeAgent`: primero `tools/` de análisis (technical_analysis, chart_patterns, scanners), luego `trade_decision.py` y prompts, manteniendo bloqueados broker/execution/kernel.
- Sustituir aprobación humana por **promoción por métricas**: champion/challenger en paper — el cambio corre en shadow N sesiones y se promueve solo si supera al campeón con significancia. El esqueleto ya existe en `experiments.py` (in_sample, walk_forward, out_of_sample, paper_window, risk_review); falta cerrarle el ciclo sin humano.
- Permitir creación de archivos/módulos nuevos en `tools/` y `strategies/` (carpeta nueva con registro de estrategias plugables).

### Fase 2 — Agentes que se mejoran a sí mismos (4-6 semanas)
- Prompts y agentes versionados como datos editables: el laboratorio puede proponer, testear (replay sobre decisiones pasadas) y promover nuevas versiones de prompts y nuevos agentes especialistas. `decision_committee` ya contempla "crear expertos adicionales"; implementarlo.
- Retrospectiva nocturna generativa: cada pérdida y cada oportunidad perdida (`missed_opportunities` ya existe) se convierte automáticamente en hipótesis falsable que entra a la fábrica de backtests.
- Memoria de largo plazo consolidada: destilar los JSONL/SQLite en lecciones estructuradas que se inyectan en los prompts (qué setups fallan en qué regímenes).

### Fase 3 — Comprensión del mercado (en paralelo, 3-4 semanas)
- Ingesta macro continua: calendario económico, Fed, earnings, titulares de mercado — no solo noticias por símbolo. Un agente macro que mantiene una tesis de mercado viva y versionada.
- Fábrica de hipótesis + granja de backtests: el generador de hipótesis produce variantes a diario, el backtester las valida en lote, las supervivientes pasan a shadow/paper automáticamente.

### Fase 4 — Gobierno de la autonomía (continuo)
- Presupuesto de riesgo como único límite duro: los agentes deciden libremente dentro de un presupuesto de drawdown/exposición; el kernel solo corta si se viola.
- Promoción/degradación automática de estrategias por rendimiento rodante.
- Humano solo como circuit breaker: dashboard de cambios aplicados (`ci-lab applied-changes` ya existe) + posibilidad de rollback, pero sin estar en el camino crítico.
- Paso a live: solo cuando el sistema lleve 2-3 meses batiendo benchmark en paper con el ciclo autónomo completo, y empezando con capital pequeño.

### Riesgos a aceptar conscientemente
- Un sistema que se auto-modifica puede degradarse rápido: la protección es el ciclo champion/challenger + rollback automático, no la prudencia del agente.
- Sobreajuste: la fábrica de hipótesis generará estrategias que funcionan en backtest y fallan en real; el filtro out-of-sample + paper window es innegociable.
- Coste de LLM: razonamiento profundo diario sobre S&P 500 + noticias + código tiene coste real; el router por niveles (local barato / API potente) lo mitiga.
- Marco legal: auto-trading con dinero real sin supervisión tiene implicaciones regulatorias; mantener registro auditable completo (ya lo hay).

## 6. Estimación de esfuerzo

| Fase | Duración | Resultado |
|---|---|---|
| 0 | 1-2 sem | Sandbox seguro + métricas baseline + LLM potente |
| 1 | 2-4 sem | Auto-modificación de estrategia/decisión con promoción por métricas |
| 2 | 4-6 sem | Agentes que crean agentes y reescriben sus prompts |
| 3 | 3-4 sem (paralelo) | Comprensión macro + fábrica de hipótesis |
| 4 | continuo | Autonomía gobernada solo por presupuesto de riesgo |

Total estimado hasta autonomía operativa en paper: **2,5-3,5 meses** de trabajo iterativo, aprovechando que el ~70% de la infraestructura (eventos, persistencia, validaciones, kill switch, champion/challenger parcial) ya está construida.
