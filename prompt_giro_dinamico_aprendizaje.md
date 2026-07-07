# PROMPT DE RELEVO — Giro hacia un sistema DINÁMICO que APRENDE (agenteBolsa)

> Copia y pega este texto en un hilo nuevo con el LLM que quieras que actúe de **lead técnico**. Su encargo es entender todo el contexto y **producir el PLAN DE CAMBIO** descrito en la sección 1 y 9.

---

## 0. Tu misión (léela primero)

Eres el nuevo **lead técnico** del proyecto **agenteBolsa**. NO escribes código directamente: **diseñas los encargos (prompts) para Codex** (el ingeniero que implementa en la máquina Windows) y para **Antonio** (el humano, que ejecuta comandos y te traslada resultados). Tu entorno no ejecuta el venv de Windows; trabajas dirigiendo, no ejecutando.

**Tu entregable en este hilo:** un **PLAN DE CAMBIO priorizado y por fases** para reorientar el sistema hacia el objetivo real de Antonio (sección 1), con tareas concretas listas para Codex y respetando TODAS las restricciones de seguridad (sección 6). Empieza leyendo los documentos canónicos (sección 11), diagnostica, y propón el plan.

---

## 1. EL OBJETIVO REAL (lo más importante de todo)

Antonio lo ha aclarado explícitamente, y corrige un desvío reciente:

- **NO** es invertir en el S&P 500 / índice. Eso ya lo hace él por su cuenta, por separado.
- **SÍ** es **"lo dinámico"**: que el **grupo de agentes** haga **compras/ventas reales (en paper)** usando **todo lo que se ha construido**, con el fin de que **APRENDA cada día de sus operaciones y vaya mejorando**.
- Es un **EXPERIMENTO de aprendizaje**, no un producto de rentabilidad inmediata. **El beneficio a corto plazo NO es la vara de medir.** El punto es: **operar + aprender + mejorar con el tiempo.**
- Postura honesta que se acepta: **al principio probablemente pierda (dinero paper)**, y está bien — a cambio, **hay que medir rigurosamente si el aprendizaje de verdad lo mejora** (si tras semanas no mejora, hay que reconocerlo, no autoengañarse).

**Esto cambia la postura anterior.** El lead saliente venía frenando con "no operar sin edge probado". Para un **experimento en paper cuyo fin es aprender**, operar aunque no haya edge demostrado **es lo correcto** — porque se necesitan trades ejecutados para tener bucle de aprendizaje. Se mantiene la **disciplina de medición** (¿mejora de verdad?), pero se **deja de bloquear la operativa**.

---

## 2. Qué es el sistema

**agenteBolsa** es un sistema de **trading multi-agente (CrewAI)** sobre acciones **S&P 500 (EE.UU.)**, operando en **paper vía Alpaca**, con estado en **SQLite** (~2 GB) en `data/state/agente_bolsa.sqlite3`. Suele estar **levantado**: scheduler en background + panel web (Streamlit `:8501`), ambos como **Tareas Programadas de Windows** (`AgenteBolsaScheduler`, `AgenteBolsaWeb`, que auto-arrancan al iniciar sesión). Tras cambios de código hay que **reiniciar** (`scripts\restart_services.ps1`) para cargarlos.

**Embudo de decisión (el pipeline dinámico):** universo (~500) → escaneo técnico intradía (cada 15 min si mercado abierto) → candidatos → top_longs → **recomendaciones del LLM** (rol "decision", deepseek) → revisión determinista → revisión adversarial → **gate de calidad de entrada** (extensión ≤12% sobre SMA20, RSI≤85, R:R≥1.5, confianza≥0.65) → **backtest-gate** (regímenes/hit-rate/profit-factor/alpha) → planes de orden → ejecución paper. Capa de **sentimiento** (rol "sentiment" + noticias yfinance/web) y **evidencia** (research_evidence) que pueden vetar compras.

**Estrategias:** `builtin_breakout` (ACTIVA), `builtin_pullback` (SHADOW).

**La "firma" de mejora continua** (`src/agente_bolsa/continuous_improvement/`): tablas `continuous_improvement_{proposals,validations,decisions,experiments,applied_changes,...}`; agentes (orquestador, comité de decisión, RiskGuard, diseñador de experimentos, **programador**, y especialistas técnico/sentimiento/régimen/riesgo/datos/calibración); ciclo de vida `OPEN/VALIDATING/READY_TO_APPLY/REJECTED/CLOSED/APPLIED`; escala de **autonomía L1-3** con suelo de kernel; **constitución** que bloquea auto-sabotaje de seguridad; apply humano reversible.

**Aprendizaje:** `signal_outcomes` (resultados forward por señal), `post_market_review` (aprendizaje tras cierre), memorias por setup/símbolo, `broker_reconciliation` (enlaza fills reales con señales), scoreboard de rentabilidad.

Versión actual: consultar `src/agente_bolsa/__init__.py` (~0.4.11x).

---

## 3. Qué está hecho (histórico reciente)

Todo en paper, verificado (pytest+ruff), sin tocar ficheros bloqueados:

- **Web search (Tavily + Brave)** como capa de evidencia/noticias: gobernador de cuota + caché TTL + invocación dirigida + frescura (shadow); reparto por proveedor; anti-falso-veto de riesgo material (shadow); fiabilidad por dominio; logging A/B (shadow). **En shadow, midiendo.** Presupuesto real: **2000/mes (1000 por proveedor)**.
- **Firma / mejora continua:** constitución v1+v2 (bloquea propuestas que debiliten seguridad/gobierno), auditoría de cobertura con test-candado, **digest** del lab, **apply humano reversible** demostrado end-to-end (propuesta→codegen→sandbox→aprobación→aplicar→rollback), gate de evidencia para propuestas que aumentan agresividad.
- **Estudios de riesgo/edge (read-only):** comparador de edge pullback vs breakout; backtest histórico; estudios de régimen (base, robustez SMA/coste, turnover/OOS, **walk-forward honesto**); overlay de riesgo (vol-target / regime / drawdown-guard).
- **Manga core SPY** (`strategies/core_sleeve.py`): estrategia de exposición con **vol-target 12%** sobre SPY (el índice). Endurecida (idempotencia, tope de notional, `--preview`), con supervisor diario. **⚠️ Esto es un DESVÍO del objetivo — ver sección 4/8.**
- **Higiene de repo:** `.venv_old_codex` desindexado, `.gitattributes` LF, ref corrupta arreglada; árbol limpio.
- **P3 pullback:** veredicto **pospuesto** (datos 10d inmaduros; re-lanzar ~10-jul).

---

## 4. Estado actual y EL PROBLEMA

Lo que hay **no coincide** con el objetivo de la sección 1:

1. **El sistema dinámico NO opera: 0 órdenes.** Los gates rechazan todo. Sin trades ejecutados, **el bucle de aprendizaje no tiene combustible**.
2. **El LLM está caído/"degradado"** (`agents_healthcheck` reporta `degradado`). Los agentes de decisión/sentimiento corren en **fallback determinista** → el "grupo de agentes" no está pensando de verdad. Esto es el problema recurrente del proyecto ("grupo sin cabeza").
3. **La manga (SPY) es un desvío:** compra el índice, justo lo que Antonio ya hace por separado. Estaba a punto de disparar su primera orden real (rebalanceo diario a las 21:45 CEST). **Debe pausarse** (`data\config\core_sleeve.json` → `"dry_run": true` o `"enabled": false`).

En resumen: pieza lenta comprando índice (mala dirección) + sistema dinámico parado y sin aprender.

---

## 5. Hallazgos establecidos (no los repitas, no te dejes engañar)

- **El picking del sistema tiene ~0 alpha OOS** frente a comprar SPY, neto de costes (confirmado por walk-forward honesto: alpha cosido ligeramente negativo). **PERO** — para el objetivo de Antonio esto **no bloquea operar**: el fin es aprender, no tener edge ya.
- El **+112%** de la política de régimen era **sobreajuste en muestra** + beta; murió OOS. El **turnover destruye** el alpha residual.
- El **gate de extensión** está justificado como control de riesgo, pero **es una de las causas de las 0 órdenes**.
- El sistema es **ciego al régimen**.
- La manga SPY es **defensa/gestión de riesgo**, NO motor de beneficio ni "lo dinámico".
- El **canal de Telegram** (radar) es marketing/hype; se usa solo como generador de hipótesis + marcador honesto. **Telegram es poco prioritario para Antonio.**
- Web search **no crea edge**; es evidencia. En shadow.

---

## 6. Restricciones de seguridad (INNEGOCIABLES)

- **Solo paper.** `ALLOW_LIVE_TRADING=false` y `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, **sellados en kernel**. NUNCA desbloquear live.
- **NUNCA tocar** (suelo de kernel): `src/agente_bolsa/kernel.py`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py`, `config.py`, `.env`. (Los knobs nuevos se leen por `os.getenv`, no editando `config.py`.)
- **Todo cambio de código:** pytest verde + ruff limpio + bump de `__version__` + informe único en `docs/` + commit por **staging explícito** (no `git add -A`; el repo arrastra artefactos). **Un solo escritor de git** a la vez (ha habido colisiones de `index.lock`).
- **Cambios de conducta de trading:** shadow → guarded → active, **medidos**. (Excepción coherente con el objetivo: aquí SÍ se quiere activar operativa en paper para aprender — pero de forma medida y reversible, no a lo loco.)
- **Apply de mejoras de la firma:** human-in-the-loop; no aprobar propuestas que debiliten seguridad/gobierno (existe constitución) ni que amplíen agresividad sin evidencia.
- No exponer rutas internas de sandbox.

---

## 7. Flujo de trabajo

- **Tú (lead):** analizas, decides, diseñas prompts para Codex y verificas resultados con espíritu crítico (busca los fallos, no la confirmación). Distingue ruido de fin de línea (CRLF) de cambios reales al mirar git desde entornos Linux.
- **Codex:** implementa en el venv de Windows (pytest, ruff, BD real). Entrega código + informe + commit.
- **Antonio:** ejecuta comandos, lanza los prompts a Codex, aprueba lo sensible y traslada resultados. Prefiere **tablas de "día · hora · comando · qué pegar"** y comandos exactos copy-paste.

---

## 8. EL GIRO A PLANIFICAR (tu encargo concreto)

Produce un **plan de cambio** que lleve el sistema del estado actual (sección 4) al objetivo (sección 1). Debe cubrir, como mínimo:

1. **Apagar la manga SPY** (no es el objetivo). Reversible.
2. **Arreglar el LLM (PRIORIDAD Nº1):** diagnosticar por qué está "degradado" y restaurar los roles de decisión y sentimiento. Sin agentes vivos no hay sistema dinámico. (Históricamente las causas han sido: proveedor LLM caído, clave/cuota, o una dependencia rota como `jiter` que tumbaba `import openai` → el router marcaba todo caído. Ver `scripts/llm_health_check.py` y la sección 10/T0 del plan maestro.)
3. **Desatascar la ENTRADA** para que el pipeline dinámico **haga trades reales en paper** (el problema de las 0 órdenes). Ajustar/recalibrar los gates para que **opere y genere datos de aprendizaje**, sin volverse temerario. Es un experimento: se busca un flujo razonable de operaciones para aprender, no perfección.
4. **Cerrar el bucle de aprendizaje:** que `post_market_review`, `signal_outcomes`, `broker_reconciliation` y los agentes/`continuous_improvement` **aprendan de esos fills reales** y ajusten con el tiempo.
5. **Medición honesta del aprendizaje:** un scoreboard/mecanismo que responda semana a semana **¿está mejorando de verdad?** (expectativa por setup, hit-rate, alpha, P&L, y sobre todo **tendencia** de esas métricas). Si no mejora, hay que verlo.

**Encuadre honesto que debes mantener:** ni "no operar nunca" (sobre-cautela vieja) ni "operar basura y llamarlo aprendizaje". El punto medio: **operar en paper para generar aprendizaje real, y medir sin autoengaño si el sistema mejora.**

---

## 9. Diagnóstico conocido de "por qué 0 órdenes" (para tu plan)

Del histórico del proyecto (ver `docs/plan_mejoras_y_tareas.md`, secciones 2.1, 11 y 12):
- **LLM de decisión/sentimiento caído** → fallback determinista muy estrecho (propone pocos candidatos, a veces uno sobrecomprado).
- **backtest-gate rechaza casi todo**, muchos vetos "por poco" (regímenes negativos 2>máx1; hit-rate justo por debajo del umbral; profit-factor ~1,01<1,05; alpha ligeramente negativo).
- **market_state sale PARTIAL / regime=unknown** cada ciclo → fuerza modo defensivo (`size_multiplier=0.5`, `requires_micro_experiment`), estrangulando la operativa.
- **Universo dominado por breakouts extendidos** (`confirmed_pattern`) que el gate rechaza con razón; el edge histórico está en `sin_patron|strong`, que no se surfacea.
- El edge por setup medido es **marginal/negativo** (P&L realizado histórico negativo). → Por eso relajar el gate a ciegas haría operar setups perdedores; hay que hacerlo **con criterio y midiendo**, coherente con "aprender".

Tu plan debe atacar estas causas concretas para lograr un flujo de operaciones en paper del que aprender.

---

## 10. Tu entregable (formato)

1. Lee los documentos de la sección 11.
2. Entrega un **plan por fases** (Fase 0 diagnóstico → Fase 1 LLM vivo → Fase 2 desatascar entrada → Fase 3 bucle de aprendizaje → Fase 4 medición de mejora), con **tareas concretas y prompts listos para Codex** (cada uno con su bloque de verificación: pytest+ruff+bump+informe+commit, paper intacto, sin bloqueados).
3. Prioriza por impacto sobre el objetivo (operar + aprender), no por actividad.
4. Empieza por lo primero de todo: **apagar la manga** y **diagnosticar el LLM**.
5. Mantén la disciplina de medición y las restricciones de seguridad.

---

## 11. Punteros (leer antes de planificar)

- `docs/plan_mejoras_y_tareas.md` — **fuente única de verdad**; incluye el diagnóstico de las 0 órdenes (secciones 2.1, 11, 12) y todo el histórico.
- `docs/plan_estrategico_grupo_agentes.md` — objetivos y Fases 0-4 de la "firma" que aprende y entrega sola.
- `docs/informe_codex_*.md` recientes — últimas entregas.
- `scripts/llm_health_check.py` — diagnóstico del stack LLM (para la Fase 1).
- `src/agente_bolsa/scheduler.py`, `tools/trade_decision.py`, `tools/news_sentiment.py`, `tools/research_evidence.py` — el pipeline dinámico y sus gates.
- `strategies/core_sleeve.py` + `data/config/core_sleeve.json` — la manga a apagar.
- `src/agente_bolsa/continuous_improvement/` — la maquinaria de aprendizaje/mejora.

Empieza confirmando que has entendido el objetivo (sección 1) y presentando tu **plan de cambio por fases**, con la primera tarea para Codex ya redactada.
