# Plan estratégico — del grupo de agentes que DELIBERA al que ENTREGA

> Objetivo del proyecto (Antonio): no un sistema a medida con buen resultado puntual, sino
> **una firma de agentes expertos que trabaja sola y en continuo** —orquestador, analistas
> técnico/sentimiento/riesgo/régimen, diseñador de experimentos y un **programador experto**—
> y que mejora poco a poco el portfolio Y el código por sí misma, con supervisión humana por excepción.

## 1. Punto de partida (diagnóstico honesto, 2026-06-29)

**Lo que YA existe (y es mucho):** el cast de agentes está construido en `src/agente_bolsa/continuous_improvement/`:
- Especialistas: `TechnicalAnalystAgent`, `SentimentAnalystAgent`, `MarketRegimeAgent`, `RiskCapitalAgent`,
  `DataQualityAgent`, `ParameterCalibrationAgent`, `PreEarningsSpecialistAgent`, `TechnicalEdgeAgent`.
- Gobierno: `ChiefInvestmentOrchestratorAgent`, `DecisionCommitteeAgent`, `RiskGuardAgent`, `ExperimentDesignerAgent`.
- Programador: `ProgrammerAgent` + `SoftwareReliabilityAgent`, con `ProgrammerAgentResponse`.
- Ciclo de vida: estados `OPEN/VALIDATING/READY_TO_APPLY/REJECTED/CLOSED/APPLIED`; `strategy_builder` con
  `applied_change_id` y `REJECTED_BY_TESTS`; escala de autonomía `autonomy.py` (niveles 1-3) con **suelo de kernel
  inviolable** (nunca kernel/broker/execution/risk/config/.env).

**El problema medido:** `continuous_improvement_experiments = 0`, `continuous_improvement_applied_changes = 0`,
frente a 1.624 propuestas y 24.245 "decisiones". **La firma delibera muchísimo pero no entrega.**

**Causas raíz probables (a confirmar en Fase 0):**
1. **Huevo-y-gallina de autonomía:** subir de nivel exige cambios aplicados sin rollback, pero hay 0 aplicados →
   nunca arranca.
2. **Propuestas no ejecutables:** el `ProgrammerAgent` emite *prosa* ("reforzar manejo de errores…"), no un *diff*
   concreto → no hay nada que aplicar.
3. **Experiment runner no cierra:** los diseños del `ExperimentDesignerAgent` no se ejecutan/persisten → `experiments=0`.
4. **Apply en dry-run permanente / committee que rechaza / cooldown.**

→ Conclusión: tenemos un Ferrari que no arranca. El plan **no construye un coche nuevo: arregla el encendido y lo pone a rodar con seguridad.**

## 2. Objetivo y criterios de éxito (medibles)

**La firma, sola y en continuo, debe cerrar este bucle:**
detectar → **proponer (ejecutable)** → validar (backtest/medición) → **experimentar en shadow** → generar un **diff testeable** →
pasar gate (tests+ruff+riesgo+autonomía, con aprobación humana al inicio) → **aplicar reversible** → medir impacto → aprender y ajustar autonomía.

**KPIs (firm scorecard):**
- `experiments/semana > 0`; `applied_changes/semana ≥ 1` (con 0 rollbacks no controlados).
- % de propuestas que llegan a experimento; % de experimentos que llegan a cambio aplicado.
- **Impacto neto medido** de los cambios aplicados (iq_score / edge / tests), no solo actividad.
- WIP bajo control; tiempo propuesta→decisión; ratio de rollback.

**Definición de "firma funcionando" (hito de éxito):** una semana en la que la firma produce **≥3 experimentos** y
**≥1 cambio aplicado, medido y reversible**, todo dentro de guardrails, con **digest diario** al humano y **sin que tú toques código**.

## 3. Principios de seguridad (la espina dorsal — innegociables)

- **Suelo de kernel inviolable** (ya existe): jamás kernel/broker/execution/risk/config/.env, en ningún nivel.
- **Autonomía progresiva** (ya existe L1-3): empezar en L1; subir solo por historial real de fiabilidad.
- **Todo cambio:** branch/sandbox, pytest verde + ruff + bump de versión, **diff revisable**, **reversible (git)**, audit trail.
- **Human-in-the-loop al inicio:** los primeros cambios exigen tu aprobación explícita; relajar a "auto con veto" solo tras historial probado.
- **Paper-only**; los cambios de conducta de trading van **shadow→guarded→active con medición** (lo que ya practicamos).
- **Presupuesto y frenos:** límites de tokens LLM, WIP, rate; kill-switch del lab.

## 4. Plan por fases (épicas) con TODAS las tareas

### Fase 0 — Diagnóstico del bucle atascado (READ-ONLY) · DESBLOQUEA TODO
- **T0.1 Mapa de muerte del pipeline.** Coger 5-10 iniciativas/propuestas recientes y trazar su estado por las tablas
  (`initiatives → proposals → validations → decisions → experiments → applied_changes`). Documentar **dónde y por qué mueren**.
- **T0.2 Auditar la escala de autonomía.** ¿Nivel actual (`code_autonomy_level`)? ¿La promoción está bloqueada por el
  huevo-y-gallina? ¿El apply está habilitado o forzado a dry-run? ¿Qué exige exactamente subir de nivel?
- **T0.3 Auditar el experiment runner.** ¿Quién ejecuta los diseños del `ExperimentDesignerAgent`? ¿Existe y está cableado el
  runner? ¿Por qué `experiments=0`?
- **T0.4 Auditar calidad de propuestas.** Muestrear propuestas reales: ¿son **ejecutables** (parámetro+valor / regla shadow /
  spec de diff) o **prosa**? Cuantificar.
- **Entregable:** informe de diagnóstico con el mapa de muerte + las 1-3 causas raíz reales (como hicimos con el embudo de trading).

### Fase 1 — Cerrar el bucle de EXPERIMENTOS (shadow, sin tocar trading)
- **T1.1 Propuestas ejecutables.** Estandarizar el schema de propuesta para que sea **accionable** (no prosa): tipo,
  componente, valor actual→propuesto, validaciones requeridas, plan de rollback.
- **T1.2 Runner de experimentos.** Que un diseño del `ExperimentDesignerAgent` **se ejecute de verdad**, reutilizando el motor
  de medición que ya construimos (`strategy_edge_backtest.py`, `study_strategy_edge_compare.py`) y **escriba en
  `continuous_improvement_experiments`** con resultado + veredicto.
- **T1.3 Gate de validación por evidencia.** Una propuesta solo pasa a `READY_TO_APPLY` si su experimento shadow muestra
  **mejora robusta neta de costes** (criterios que ya usamos: OOS, varios regímenes, ajustado por riesgo).
- **Entregable:** `experiments/semana > 0`, con propuestas que adjuntan evidencia real.

### Fase 2 — Cerrar el bucle de CÓDIGO (programador experto que ENTREGA, máxima seguridad)
- **T2.1 ProgrammerAgent que produce DIFFS, no prosa.** Dada una propuesta validada, genera un **patch concreto** en branch
  sandbox, corre pytest+ruff+bump y adjunta el diff + resultados.
- **T2.2 Gate de aplicación human-in-the-loop.** El cambio queda `READY_TO_APPLY` con diff + evidencia; tú apruebas/rechazas
  desde un CLI/digest. Solo tras aprobación se aplica y commitea. (Internaliza de forma segura lo que hoy hace Codex.)
- **T2.3 Aplicación reversible + romper el huevo-y-gallina.** Aplicar por `strategy_builder` (`applied_change_id`), registrar
  `APPLIED/ROLLED_BACK`. Las **primeras** aplicaciones van con aprobación humana (no exigen autonomía alta); ese historial es
  el que luego **sube el nivel de autonomía** por el cauce ya diseñado.
- **T2.4 Medición de impacto post-aplicación.** Tras aplicar, medir efecto (iq_score/edge/tests) y **rollback automático** si degrada.
- **Entregable:** `applied_changes/semana ≥ 1`, todos reversibles y medidos, 0 rollbacks no controlados.

### Fase 3 — Orquestación, gobierno y autonomía continua (red de seguridad; en paralelo desde el inicio)
- **T3.1 Orquestador conductor.** `ChiefInvestmentOrchestratorAgent` dirige el ciclo completo en continuo (no solo cooldown),
  con prioridades, WIP limit (ya arreglado hoy) y cooldowns.
- **T3.2 Crítico/PM adversarial efectivo.** Asegurar que `DecisionCommitteeAgent` + `RiskGuardAgent` **muerden** (rechazan
  busywork y riesgo) en vez de aprobar en masa.
- **T3.3 Gobierno + digest diario.** Límites de tokens/coste, rate, kill-switch del lab, y un **digest diario al humano**:
  "qué hizo la firma hoy: propuso X, experimentó Y, aplicó Z, pide tu OK para W".
- **T3.4 Escala de autonomía gobernada.** Empezar L1 + aprobación humana; subir a "auto con veto" solo tras N cambios
  aplicados sin rollback e iq_score estable.
- **Entregable:** la firma corre sola, gobernada, con supervisión humana por excepción.

### Fase 4 — Profundidad de especialistas, memoria y régimen (continuo)
- **T4.1 Calidad por especialista.** Eval por agente: ¿sus hipótesis/análisis aciertan? Medir hit-rate y retirar lo que no aporta.
- **T4.2 Memoria→decisión.** Que `lessons`/`memories` (485) **alimenten** de verdad las decisiones, no solo se almacenen.
- **T4.3 Régimen-awareness.** Conecta con el hallazgo de hoy: que la firma proponga/aplique ajustes de política **según régimen**
  (participar en alcista confirmado, proteger en selloff) — el lever que identificamos contra el "0 trades en rally".
- **T4.4 Feeds que faltan.** Sentimiento/macro reales (el hueco FMP) para que los analistas tengan materia prima.
- **Entregable:** especialistas con señal medible y memoria que mejora decisiones.

## 5. Secuencia y dependencias

1. **Fase 0 primero** — sin saber por qué está a 0, todo lo demás es a ciegas. (Read-only, rápida.)
2. **Fase 1 (experimentos) → Fase 2 (código)** — aplicar cambios sin experimentos validados es peligroso; primero el bucle de evidencia.
3. **Fase 3 desde el principio, en paralelo** — el gobierno/digest es la red de seguridad, no un añadido final.
4. **Fase 4 continua** — profundidad de especialistas a medida que el bucle ya entrega.

## 6. Riesgos y mitigaciones

- **El mayor riesgo es un agente que escribe código solo.** Mitigación: suelo de kernel + autonomía progresiva + human-gate
  inicial + tests obligatorios + reversibilidad git + paper-only + presupuesto + audit trail.
- **Busywork (lo que pasa hoy):** crítico/RiskGuard que muerden + KPIs de *entrega*, no de actividad + WIP limit.
- **Sobre-optimización / overfitting:** validación OOS, varios regímenes, neto de costes, ajustado por riesgo (ya es nuestra práctica).
- **Regresión silenciosa:** medición de impacto post-aplicación + rollback automático.

## 7. Hito de éxito (cuándo decimos que la firma "funciona")

La semana en que, **sin que toques código**, la firma:
- genera **≥3 experimentos** con evidencia,
- aplica **≥1 cambio reversible y medido** dentro de guardrails,
- y te entrega un **digest diario** con lo hecho y lo que pide aprobar.

Ese es el momento en que dejas de tener "agentes que opinan" y pasas a tener **una firma que entrega**.

---

## Progreso 30-jun (mañana) — raíles de la firma construidos (sin apply)

- ✅ **Invariante de apply blindado con test (v0.4.66):** con `ALLOW_AUTO_APPLY_IMPROVEMENTS=false` el applier no se invoca; `REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=true` bloquea `APPLIED`; el suelo de kernel rechaza los 6 ficheros prohibidos en niveles 1/2/3. (commit bea8b3c6)
- ✅ **venv-base:** diagnosticado — `.venv\Scripts\python.exe` es un launcher que delega en el Python311 base; cada servicio = shim+worker, NO runtimes duplicados, código actual. **Cosmético → sin acción, fuera del backlog.** (be7ac375)
- ✅ **Fase 2A — preview de diffs (v0.4.67):** `CodeDiffPreviewAgent` aplica un payload en `GitSandbox`, corre tests y adjunta el diff como `proposal_artifact`. 0 apply, suelo de kernel, no toca árbol real. (b06579b8)
- ✅ **Fase 2B — codegen (v0.4.68):** `CodegenPatchAgent` (LLM) convierte prosa→patch, restringido a allowlist (`continuous_improvement/`, `tools/operational_*`, `tests/`, `docs/`), encadena con el preview → artefacto `READY_FOR_HUMAN_REVIEW`. CLI manual `continuous-improvement-lab gen-diff`. Demo real verificada, `applied_changes=0`. (675d5fbf)

**Cadena actual:** detectar → proponer → experimentar (shadow) → **codegen patch → sandbox+tests → adjuntar diff para revisión humana**. Todo con `applied_changes=0` y auto-apply off+sellado+testeado.

**PENDIENTE — Fase 2B-apply (sesión dedicada, en frío):** el "botón" de **aprobación humana positiva** → aplica una propuesta concreta de forma **reversible** (backup + tests + suelo de kernel + rollback automático si degrada). Es el único punto donde el código ENTRA al repo → máxima cautela. Luego: Fase 3 (orquestación/gobierno/digest) y Fase 4 (memoria, especialistas, régimen).
