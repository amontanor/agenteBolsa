# Estudio Semanal — agenteBolsa · 19 jun 2026

> **Metodología**: solo lectura. Fuentes: reportes JSON en `data/reports/`, logs `data/logs/system.jsonl` y `data/logs/agents/`. La BD SQLite principal (`agente_bolsa.sqlite3`) devolvió *disk I/O error* en modo lectura (escritura concurrente del scheduler activo). Todos los datos provienen de fuentes secundarias. Los conteos de BD proceden del snapshot embebido en el CI report.

---

## Resumen Ejecutivo

Semana de arranque operativo con **dos incidencias de infraestructura mayores** que dominaron el resultado. El sistema ejecutó un único trade con resultado esta semana (cierre de FRT el martes 17), con pérdida realizada de **–$43.77**. La equity cayó de $70 697 (10-jun) a **$70 653** (18-jun, –0.06%). Sin posiciones abiertas al cierre.

El problema operativo principal fue el **fallo sistemático del crew** (dependencias pip sin resolver 11–15 jun), que dejó el sistema en fallback determinista el 100% de los días hábiles hasta el lunes 16. Cuando el LLM volvió a estar disponible (16-17 jun), las decisiones fueron coherentes: 150 holds justificados por el edge negativo de `confirmed_pattern`, más 3 intentos de buy en APH por catalizador excepcional (upgrade analista). El jueves 18 la cuota de MiMo se agotó (~14:51 UTC), causando 40 fallos de crew y 21 ciclos en fallback. La transición a kimi-k2.6 (opencode-go) comenzó ese mismo día en la capa CI —con éxito parcial— pero no alcanzó la capa de decisión en horario de mercado.

La **capa de sentimiento estuvo caída** (quota 429) prácticamente toda la semana, generando 120+ penalizaciones `sentimiento_no_validado_penalizado` que bloquearon candidatos técnicamente sólidos, incluyendo los 3 intentos de APH.

**Limitaciones de muestra**: BD no accesible; solo 2 trades con resultado (0% hit-rate, estadísticamente no significativo); régimen de mercado "unknown" el 100% de la semana; alpha vs. SPY no calculable (sin fetcher de benchmark).

---

## 1. Rendimiento

### 1.1 Equity y P&L

| Día | Equity cierre | P&L día | Unrealized | Posiciones |
|-----|--------------|---------|------------|------------|
| 10-jun (ref.) | $70 697.19 | — | $0 | 0 |
| 12-jun | $70 691.98 | –$5.21 | –$5.18 | 1 (FRT) |
| 15-jun | $70 676.16 | –$15.82 | –$21.00 | 1 (FRT) |
| 16-jun | $70 657.54 | –$18.62 | –$39.62 | 1 (FRT) |
| **17-jun** | **$70 653.39** | **–$43.77 realizado** | $0 | **0** |
| 18-jun | $70 653.37 | ~$0 | $0 | 0 |

**P&L realizado semana 16–19 jun: –$43.77**
P&L acumulado período 10–19 jun (incluye CRWD): –$122.09

### 1.2 Trades ejecutados (período 16–19 jun)

**FRT (Federal Realty Investment Trust)**

| Operación | Fecha | Lado | Qty | Precio | Notional | P&L real. | % |
|-----------|-------|------|-----|--------|----------|-----------|---|
| Entrada | 12-jun | BUY | 14 (5+9) | $126.16–$126.30 | $1 766.94 | — | — |
| Cierre | 17-jun | SELL | 9+4+1 | $123.08–$123.09 | $1 723.17 | **–$43.77** | **–2.47%** |

La posición se mantuvo 5 días con pérdida creciente (–$5 → –$21 → –$40) antes de cerrarse el martes 17. Stop-loss en $120.96; cierre por encima del stop, calificado como `venta_mejorable` por el evaluador. La compra fue generada por **fallback determinista** (no por LLM).

**CRWD (referencia semana anterior):** –$78.32 (–5.68%) cerrado el 10-jun.

### 1.3 Métricas de rendimiento

| Métrica | Valor | Nota |
|---------|-------|------|
| Hit-rate (semana) | 0/1 = **0%** | Muestra mínima, no significativa |
| Profit factor | N/A (0 ganadoras) | — |
| Sharpe-60 (18-jun) | –13.71 | Distorsionado por exposición ~0 |
| Max drawdown semana | 0.06% | Exposición muy baja |
| Alpha vs SPY | **No calculable** | Sin fetcher de benchmark |
| IQ score | 50.0 | Baseline sin historial |
| Avg exposure | 0–2.5% | Posición única pequeña |

---

## 2. Operativa: propuestas vs. ejecutadas

### 2.1 Ciclos de mercado y estado del crew

| Día | Ciclos | Crew OK | Crew fallido | Causa fallo |
|-----|--------|---------|-------------|-------------|
| 11-jun | 18 | 0 | 18 | Dependencias pip |
| 12-jun | 26 | 0 | 26 | Dependencias pip |
| 15-jun | 28 | 0 | 28 | Dependencias pip |
| 16-jun | 17 | 13 | 4 | Parciales |
| **17-jun** | **28** | **28** | **0** | ✅ Todos OK |
| 18-jun | 45 | 5 | 40 | Quota MiMo (429) + 403 kimi |
| **TOTAL** | **162** | **46** | **116** | |

**Causa raíz fallos 11-15 jun**: 73 eventos con mensaje `Instala dependencias con pip install -r requirements.txt`. El entorno del scheduler perdió las dependencias pip y el crew no pudo arrancar.

### 2.2 Decisiones paper (paper_auto_trade_completed)

| Día | Ciclos paper | Source=LLM | Source=fallback | Compras ejecutadas |
|-----|-------------|-----------|-----------------|-------------------|
| 11-jun | 16 | 0 | 16 | 0 |
| 12-jun | 25 | 0 | 57* | **1 (FRT)** |
| 15-jun | 26 | 0 | 26 | 0 |
| 16-jun | 13 | 40 | 0 | 0 |
| 17-jun | 28 | 93 | 0 | 0 |
| 18-jun | 39 | 20 | 21 | 0 |
| **Total** | **147** | **153** | **99** | **1** |

*El fallback el 12-jun generó la única compra real de la semana (FRT, $1 766 notional).

### 2.3 Propuestas de compra y etapa de veto (LLM activo, 16-18 jun)

| Ciclo | Símbolo | Acción LLM | Confianza | Ejecutado | Motivo veto |
|-------|---------|-----------|-----------|-----------|-------------|
| 17-jun 15:24 | APH | buy | 0.70 | ❌ | `sentimiento_no_validado_penalizado` + R/R bajo |
| 17-jun 18:22 | APH | buy | 0.72 | ❌ | `sentimiento_no_validado_penalizado` + R/R bajo |
| 17-jun 19:54 | APH | buy | 0.67 | ❌ | `sentimiento_no_validado_penalizado` + R/R bajo |

El LLM argumentó override por catalizador excepcional (upgrade analista por AI growth, evidence_ids documentados), pero el gate de entry_quality vetó los tres por ausencia de sentimiento validado. Los otros 150 ciclos LLM decidieron HOLD con razón unánime: edge negativo de `confirmed_pattern` (–5.4%, WR 36%) + régimen desconocido.

### 2.4 Oportunidades perdidas el 18-jun (sistema en fallback)

| Símbolo | Dirección | Retorno sesión | Considerado LLM | Motivo no ejecutado |
|---------|-----------|---------------|-----------------|---------------------|
| SNDK | Long | **+6.91%** | Sí | llm_candidate pero LLM caído |
| LHX | Short | +6.46% | No | not_selected_by_llm |
| NOC | Short | +5.85% | No | not_selected_by_llm |
| GLW | Long | +5.30% | — | Shadow (intraday momentum) |
| GNRC | Long | +4.63% | — | Shadow (intraday momentum) |

El 18-jun el crew falló el 89% de los ciclos. Las mejores oportunidades del día quedaron sin decisión LLM.

---

## 3. Edge por setup, tag y régimen

### 3.1 Setups (horizonte 3d, acumulado desde abr-2026)

| Setup | Señales | Maduras 3d | Win-rate | Avg return 3d | Estado |
|-------|---------|-----------|---------|---------------|--------|
| confirmed_pattern | 17 995 | 13 978 | 33.85% | **–0.56%** | ⚠️ Edge negativo (muestra alta) |
| baseline_trend | 2 403 | 1 944 | 35.80% | –0.11% | ⚠️ Débil |
| event_momentum | 10 | 10 | 10.0% | –0.92% | ❌ Negativo (n=10, insuficiente) |
| orderly_breakout | 11 | 8 | 37.5% | –2.42% | ❌ Negativo (n=8, insuficiente) |
| range_expansion_breakout | 7 | 7 | 0.0% | –2.53% | ❌ Negativo (n=7, insuficiente) |
| trend_volume | 4 | 1 | — | –4.20% | ❌ Sin muestra |

`confirmed_pattern` domina el universo (17 995 señales) y tiene **edge negativo con muestra suficiente** para actuar. La penalización operativa `deprioritize` ya está activa; el LLM la cita en cada HOLD.

### 3.2 Tags — mejores a 3d

| Tag | Señales | Win-rate 3d | Avg return 3d | Nota |
|-----|---------|------------|---------------|------|
| macd:non_positive | 83 722 | 19.8% | **+0.06%** | Único tag con retorno medio positivo a 3d en muestra grande |
| sma20_dist:lt0 | 82 885 | 14.9% | –0.03% | Casi neutro a 3d, positivo a 5-10d (+1.52%) |
| rsi:lt60 | 136 426 | 15.7% | –0.29% | Mejor a 5-10d (+1.14%) |

La expectativa positiva real emerge a horizontes 5-10d para casi todos los tags. El sistema genera señales válidas pero las evalúa principalmente a 1-3d donde el ruido domina.

### 3.3 Tags — peores a 3d (candidatos shadow)

| Tag | Señales | Win-rate | Loss-rate 3d | Avg return 3d | Shadow candidato |
|-----|---------|---------|-------------|---------------|-----------------|
| sma20_dist:gt12pct | 882 | 27.4% | 62.6% | **–2.42%** | ✅ Ya en lista |
| score:gte15 | 2 646 | 29.7% | 49.8% | –1.95% | ✅ Ya en lista |
| sma20_dist:6_12pct | 2 160 | 29.7% | 54.1% | –1.61% | Propuesto |
| volume_z:gt1 | 565 | 26.4% | 49.1% | –1.43% | Muestra límite |
| rsi:75_85 | 997 | 28.0% | 53.0% | –1.32% | Muestra límite |

### 3.4 Falsos negativos del backtest-gate

| Símbolo | Fecha señal | Retorno 3d | Motivo bloqueo |
|---------|-------------|-----------|----------------|
| HSIC | 11-jun | **+2.24%** | blocked_backtest |
| CPT | 05-jun | +1.77% | blocked_backtest |
| TER | 15-jun | +1.50% | blocked_entry_quality (sentimiento no validado) |
| MAA | 04-jun | +1.49% | blocked_backtest |

Tasa falsos negativos a 3d: **13.3%** (4/30 candidatos vetados eran ganadores). Muestra pequeña pero patrón consistente.

### 3.5 Régimen y alpha

Régimen: **"unknown" el 100% de la semana**. Sin régimen calculado, el sistema opera en postura defensiva por defecto. Alpha vs SPY: no calculable (fetcher de benchmark no configurado).

---

## 4. Salud LLM por proveedor, modelo y propósito

### 4.1 Capa CI (mejora continua) — por día y proveedor

| Día | mimo/mimo-v2.5-pro | mimo/mimo-v2.5 | opencode-go/kimi-k2.6 | Fallos | Tasa fallo |
|-----|-------------------|---------------|----------------------|--------|------------|
| 10-jun | 47 ✅ | 0 | 0 | 1 | 2.1% |
| 11-jun | 50 ✅ | 61 ✅ | 0 | 0 | 0% |
| 12-jun | 46 ✅ | 32 ✅ | 0 | 1 | 1.3% |
| 15-jun | 61 ✅ | 3 ✅ | 0 | 3 | 4.5% |
| 16-jun | 30 ✅ | 0 | 0 | 1 | 3.2% |
| 17-jun | 58 ✅ | 0 | 0 | 0 | **0%** |
| 18-jun | 56 ✅ | 0 | 33 ✅ | **75** | **45.7%** |
| **Total** | 348 | 96 | **33** | **81** | |

**18-jun**: MiMo agotó quota a las ~14:51 UTC (43 errores HTTP 429 consecutivos hasta las ~20h). kimi-k2.6 de opencode-go comenzó a rotar en CI con éxito (33 ciclos, 0 fallos). A las ~20h kimi también falló (HTTP 403, error code 1010). Las últimas horas del día, CI quedó sin proveedor disponible.

### 4.2 Capa de decisión de trading

| Período | Source=llm | Source=fallback | Fallback % | 0-fallback cuando LLM disponible |
|---------|-----------|----------------|------------|----------------------------------|
| 11-15 jun | 0 | 88 | **100%** | N/A (crew caído) |
| 16-17 jun | 153 | 0 | **0%** | ✅ Confirmado |
| 18-jun | 20 | 21 | ~51% | ❌ Fallback tras quota agotada |

**Cuando el crew funciona, las decisiones son 100% LLM (0 fallback)**. El fallback solo aparece en ausencia total del crew.

### 4.3 Capa de sentimiento

| Período | Estado | Impacto operativo |
|---------|--------|-------------------|
| 11-15 jun | ❌ Caído (quota 429) | 120+ ciclos con `sentimiento_no_validado_penalizado` |
| 16-17 jun | ✅ Operativo (parcial) | 6 penalizaciones residuales el 17-jun |
| 18-jun | ❌ Caído (quota 429) | 24/24 símbolos con "sentiment failed: quota exhausted" |

El sentimiento fue el **factor de bloqueo más recurrente** de la semana. TER (falso negativo) y las 3 propuestas de APH fueron vetadas principalmente por ausencia de sentimiento validado.

### 4.4 Calidad de decisión LLM cuando disponible (16-17 jun)

Las decisiones LLM mostraron coherencia y trazabilidad:
- **Hold**: citó consistentemente el edge negativo de confirmed_pattern (–5.4%), la penalización `deprioritize` activa, y el régimen desconocido.
- **Buy APH (×3)**: override documentado con evidence_ids de noticias de analistas, reconociendo el edge negativo pero justificando excepción. Decisión coherente aunque bloqueada en entry_quality.
- **Sin alucinaciones detectadas**. Sin fallback determinista.

---

## 5. Mejora continua

### 5.1 Estado del backlog CI

| Categoría | Cantidad |
|-----------|---------|
| Hipótesis activas (OPEN) | 15 |
| Tareas completadas | 494 |
| Iniciativas OPEN | 11 |
| Iniciativas REJECTED | 189 |
| Cambios de código aplicados | **0** |
| Experimentos ejecutados | **0** |
| Backlog sin clasificar | 200 items (estado UNKNOWN) |
| Ciclos CI totales acumulados | 783 |

### 5.2 Hipótesis activas relevantes

| Hipótesis | Confianza | Resumen |
|-----------|-----------|---------|
| decision_governance | **ALTA** | La decisión final debe depender del estado de validación y del impacto medido |
| experiment_design | **ALTA** | Los experimentos deben comparar baseline, shadow y propuesta con la misma ventana |
| risk_capital_alignment | BAJA | Capital y riesgo deben moverse con evidencia de bloqueos y degradación real |
| strategy_stability | BAJA | Estabilidad parcial hasta tener outcomes maduros suficientes |
| data_quality | BAJA | Calidad de datos necesita vigilancia antes de confiar en el edge |

### 5.3 Candidatos shadow activos

| Tag | Señales maduras | Win-rate | Avg return 3d | Estado |
|-----|----------------|---------|---------------|--------|
| `sma20_dist:gt12pct` | 770 | 27.4% | –2.42% | Candidato shadow (en lista) |
| `score:gte15` | 1 934 | 29.7% | –1.95% | Candidato shadow (en lista) |
| `intraday_same_session_momentum` | 2 casos | avg +4.96% sesión | Captura top-3 ~0.5% | Shadow para promoción |

### 5.4 Políticas activas (guarded)

| Política | Estado | Nota |
|---------|--------|------|
| `dedupe_same_symbol_cycle` | guarded_active | Bloquea duplicados mismo símbolo por ciclo/fuente |
| `intraday_same_session_momentum` | guarded_active | Prioriza momentum intraday repetido antes del LLM |

### 5.5 Iniciativas OPEN destacadas

| Iniciativa | Dominio | Expectativa |
|-----------|---------|-------------|
| Revisar motor de riesgo | trading | Mejorar captura de winners sin degradar protección |
| Recalibrar veto pre-earnings | software | Capturar más ganadores pre-earnings |
| Enhance Analyst Estimation Coverage | software | Cobertura de estimaciones de analistas insuficiente |
| P002: trades bloqueados con edge positivo | software | Recuperar ~3 trades |
| Observation Executor | software | Generar outcomes para medir impacto de señales |

---

## 6. Decisiones a proponer (sin aplicar)

### A. ¿Activar shadow formal para `confirmed_pattern`?

**Sí, con condición.** Con 13 978 señales maduras a 3d y avg_return=–0.56%, la muestra es suficiente. El sistema ya tiene `deprioritize` activo. La propuesta es formalizar la **shadow penalty** que impide que `confirmed_pattern` genere recomendaciones de compra en régimen unknown o sin sentimiento validado, manteniendo la excepción para catalizadores excepcionales documentados (como APH con upgrade analista).

### B. ¿Near-miss del backtest-gate con expectativa forward positiva?

Los 4 falsos negativos (HSIC, CPT, TER, MAA) muestran retornos positivos (+1.49% a +2.24%) pero la muestra es pequeña (n=4). **No relajar el gate todavía.** Proponer: registrar durante 2-3 semanas más los casos `selection_rank ≤ 2` + `entry_quality OK` bloqueados por backtest para valorar si el umbral está sobre-ajustado para top candidatos.

### C. ¿La calidad con kimi/glm mejora vs. MiMo?

**Imposible valorar.** kimi-k2.6 solo operó 33 ciclos en CI el 18-jun y ninguno en la capa de decisión. MiMo fue el único proveedor de decisiones durante toda la semana. La comparativa requiere al menos una semana completa con kimi activo en ambas capas.

### D. ¿Activar stale_guard?

**Sí, explorar en shadow.** FRT tardó 5 días en cerrar con pérdida creciente (–$5 → –$21 → –$40 → –$44). El patrón es claro: posición sin movimiento hacia el TP durante >2 días con drawdown creciente. Propuesta: shadow de stale_guard con parámetros iniciales: corte si unrealized < –2% Y han pasado ≥3 días sin acercarse al TP en un 20%. No activar en producción sin al menos 10 casos de referencia histórica.

### E. ¿Subir peso del ranker RS?

**No todavía.** Con régimen "unknown" el 100% de la semana, sentimiento inestable y sin alpha vs SPY calculable, modificar el ranker sin datos de referencia introduce riesgo sin mejora medible. Prioridad: primero configurar el fetcher de benchmark para obtener alpha; después evaluar ajuste del ranker.

---

## 7. Acciones recomendadas para la semana del 23–27 jun

| Prioridad | Acción | Justificación |
|-----------|--------|---------------|
| 🔴 **1** | **Resolver dependencias pip del scheduler** | Causa raíz de 100% fallback durante 4 días hábiles (11-15 jun). Sin esto, el sistema opera ciego la mayor parte de la semana |
| 🔴 **2** | **Asegurar continuidad LLM post-transición kimi-k2.6**: configurar como proveedor activo en capa de decisión Y sentimiento antes de apertura del 23-jun | El 18-jun demostró que MiMo agota quota y kimi aún no está configurado en decisión/sentimiento |
| 🟡 **3** | **Restaurar la capa de sentimiento** | Caída >40h de sentimiento bloqueó las 3 únicas propuestas de compra de la semana (APH) y penalizó ~120 ciclos. Es la segunda causa de inactividad operativa |
| 🟡 **4** | **Activar shadow penalty formal para `confirmed_pattern`** | 13 978 señales maduras con edge –0.56%. El sistema ya lo evita de facto; formalizarlo reduce ruido en el LLM y libera contexto de decisión |
| 🟢 **5** | **Configurar fetcher de precios benchmark (SPY)** | Sin él, alpha=None y Sharpe está distorsionado. Impide evaluar si el sistema añade valor vs. buy-and-hold |

---

## Apéndice: Limitaciones y fuentes

| Fuente | Estado | Nota |
|--------|--------|------|
| `data/state/agente_bolsa.sqlite3` | ❌ Inaccesible | disk I/O error (scheduler activo) |
| `data/reports/latest_post_market_learning.json` | ✅ | 18-jun 22:27 CEST |
| `data/reports/post_market_review_2026-06-1[5-8]_*.json` | ✅ | Datos diarios completos |
| `data/reports/latest_continuous_improvement_report.json` | ✅ | 18-jun 19:56 UTC |
| `data/reports/latest_daily_learning_digest.json` | ✅ | 18-jun 20:27 UTC |
| `data/logs/system.jsonl` (semana) | ✅ | 4 918 eventos |
| `data/logs/agents/execution_agent.jsonl` | ✅ | Principal fuente operativa |
| `data/logs/agents/orchestrator.jsonl` | ✅ | Ciclos y crew status |
| `data/logs/agents/performance_baseline_agent.jsonl` | ✅ | Serie de equity |

*Informe generado automáticamente — viernes 19-jun-2026 — tarea programada `estudio-semanal-agentebolsa`*
