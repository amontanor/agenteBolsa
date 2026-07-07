# Prompts del GIRO — sistema dinámico que opera en paper para APRENDER

Objetivo (Antonio, literal): que el grupo de agentes haga compras/ventas en paper
usando todo lo construido, para que APRENDA cada día y mejore. Experimento de
aprendizaje, no producto de rentabilidad inmediata. Se acepta perder al principio;
se mide con rigor si el aprendizaje mejora el sistema. La manga SPY queda apagada
(desvío reconocido). Ni sobre-cautela ("no operar sin edge") ni temeridad: flujo
de operaciones acotado + medición honesta.

**Bloque de verificación estándar (cada tarea):** `pytest tests\ -x -q` verde;
`ruff check src tests scripts` limpio; bump de `__version__`; ejecución real
documentada; commit por staging explícito; confirmar `trading_mode=paper`,
`allow_live_trading=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`; NO tocar los 6
ficheros del suelo de kernel (knobs nuevos por `os.getenv` o JSON en
`data/config/`); ficheros grandes SOLO con escritura atómica verificada.

---

## P-L1 — LLM vivo otra vez (PRIORIDAD 1; sin esto no hay grupo de agentes)

`agents_healthcheck` reporta `degradado`: decisión y sentimiento corren en
fallback determinista. Historial de causas en este repo: dependencia rota
(`jiter` tumbaba `import openai`), modelo que quema tokens en razonamiento y
devuelve vacío (C1.3, P7), proveedor/cuota caídos, y — hipótesis nueva a
verificar — **presupuesto diario agotado** (`llm_daily_budget_usd=5` con ~500k
tokens/día de decisión; si el gate interno de presupuesto corta, el router puede
reportar "caído" siendo en realidad "sin presupuesto").

1. **Diagnóstico con evidencia ANTES de arreglar** (patrón P7): por cada rol
   (decision, sentiment, deep, codegen, improvement): llamada real con captura
   cruda (status HTTP, finish_reason, content/reasoning chars, error literal),
   `pip check`, estado del gate de presupuesto interno (gasto de hoy vs límite),
   y cuota del proveedor si es visible. Tabla en el informe: rol → causa.
2. **Fix mínimo según causa** (no arregles a ciegas): dependencia → pin+test;
   truncado → límites/extracción como P7; presupuesto → propuesta de reparto
   (p. ej. presupuesto por rol ya existe; si decisión se lo come todo, eso lo
   atacará el modo aprendizaje con su dieta — documenta y recomienda, el knob es
   human-gated); proveedor → conmutar rol al modelo vivo del stack.
3. **Blindaje anti-recurrencia** (tercera vez que pasa): el digest matinal debe
   incluir SIEMPRE una línea `LLM: decision=OK/CAÍDO sentiment=... (horas sin
   respuesta real)` desde `llm_usage`/watchdog — la degradación nunca más
   silenciosa. Con test.
4. Cierre: `llm_health_check --json` todo OK + una ejecución real del rol de
   decisión registrada en `llm_usage` con respuesta válida (si mercado cerrado,
   vía smoke/job-once). Informe: `docs/informe_codex_pl1_llm_vivo_<fecha>.md`.

## P-L2 — Modo experimento de aprendizaje (desatascar la entrada, con criterio)

Diseño del responsable — implementarlo tal cual, todo reversible y human-gated:

1. **Config** `data/config/learning_mode.json` (default `enabled=false`,
   `human_gated=true`): `daily_order_budget: 3`, `per_trade_notional_usd: 1000`,
   `max_portfolio_exposure_pct: 15`, `allowed_strategies: ["builtin_breakout",
   "builtin_pullback"]`, `shadow_first: true`. Añade sus claves al gate de
   autogobierno (la firma no puede encendérselo ni engordarlo) y al
   `config-audit`/línea Safety del digest (learning_mode visible siempre).
2. **Recalibración de gates SOLO bajo learning_mode** (si `enabled=false`, cero
   cambio de conducta — con test que lo pruebe):
   a. `backtest_gate`: los near-miss documentados pasan como `learning_near_miss`
      con el notional del budget: hit-rate ≥ umbral−3pp, PF ≥ 0.95, regímenes
      negativos ≤ 2, alpha ≥ −0.5%. Los rechazos claros (PF<0.9, trades<8, alpha
      muy negativo) SIGUEN vetando: aprender ≠ operar basura.
   b. `market_state PARTIAL/unknown`: deja de estrangular (el budget ya limita
      el riesgo); se registra el estado en la señal para el análisis posterior.
   c. Sentimiento sin datos (LLM caído o sin noticias): no veta por sí solo bajo
      learning_mode (activa el anti-falso-veto que está en shadow); un
      `material_risk` REAL sigue vetando.
   d. Gate de extensión: SE MANTIENE duro (evidencia de momentum-crash). El
      flujo no-extendido viene del punto 3.
3. **`builtin_pullback` pasa a ACTIVE dentro del learning_mode** (sus candidatos
   no están extendidos por construcción; el veredicto OOS sigue pendiente y ese
   estudio continúa aparte — aquí se activa como fuente de aprendizaje con
   notional pequeño, que es coherente con el objetivo).
4. **Cohorte medible**: toda señal/orden del modo lleva
   `source=learning_experiment` en `signal_outcomes`/metadata de orden, con
   muralla equivalente a la del lab_book: los estudios de edge/promociones NO la
   mezclan salvo petición explícita (reutiliza el patrón `include_*` de P22).
5. **Rollout**: primera sesión con `shadow_first=true` → loguea exactamente qué
   HABRÍA comprado (símbolo, gate que lo dejó pasar, tamaño) en
   `data/reports/learning_mode_shadow_<fecha>.json`; Antonio revisa y pone
   `shadow_first=false` para operar de verdad. Kill-switch: `enabled=false`.
6. Tests: budget diario respetado; notional cap; exposición máxima; near-miss
   pasa/rechazo claro veta; enabled=false ⇒ conducta idéntica a hoy (test de
   regresión de oro); etiquetado del cohorte; muralla.
Informe: `docs/informe_codex_pl2_learning_mode_<fecha>.md`.

## P-L3 — Bucle de aprendizaje cerrado (tras los primeros fills)

1. Verificación end-to-end con fills REALES del cohorte: fill → reconciliation →
   `signal_outcomes` (maduración) → `post_market_review` → memorias/lecciones →
   ajuste (adaptive_config o propuesta de la firma). Documenta CADA eslabón con
   el primer trade real como evidencia; arregla el que no fluya.
2. Digest matinal, sección "Aprendizaje de ayer": trades del cohorte, P&L,
   outcomes que maduraron, lecciones destiladas, y qué ajustó o propuso el
   sistema a raíz de ellos. Si no hubo ajuste, decirlo ("operó pero no aprendió
   nada nuevo") — la honestidad es el producto.
3. La firma recibe el material: el puente findings→proposals genera propuestas
   desde los datos del cohorte (p. ej. "el near-miss X pierde consistentemente →
   proponer endurecerlo"), por el cauce normal con evidencia citada.
Informe: `docs/informe_codex_pl3_bucle_<fecha>.md`.

## P-L4 — Medición honesta del aprendizaje (criterios PRE-REGISTRADOS hoy)

1. `learning-scoreboard` semanal del cohorte: expectancy neta (10/20 bps),
   hit-rate, PF, alpha vs SPY del mismo periodo, max DD, n — por semana de vida
   del experimento. Con TENDENCIA explícita.
2. **Criterio pre-registrado del responsable** (evalúalo, no lo reinterpretes):
   "el sistema aprende" si la expectancy neta media de las semanas 5-8 supera a
   la de las semanas 1-4 Y la pendiente semanal es positiva Y el resultado no lo
   explica solo el mercado (control: cohorte contrafactual de candidatos
   rechazados y/o selección aleatoria del universo con las herramientas
   counterfactual existentes — el aprendizaje debe batir a SU contrafactual, no
   solo al azar de un mes verde).
3. Si a las 8 semanas no cumple → el scoreboard lo dice en rojo y se decide con
   Antonio (ajustar el bucle o reconocer que no aprende). Sin autoengaño.
Informe: `docs/informe_codex_pl4_scoreboard_<fecha>.md`.
