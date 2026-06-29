# Informe Codex — runbook de promoción SHADOW→ACTIVE para pullback (2026-06-29)

## Alcance y guardrails

Trabajo 100% read-only sobre código y BD. No se ha promovido ninguna estrategia ni se han tocado `risk.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py`, `config.py` ni `.env`.

Comandos de inspección usados:

- `rg -n "promotion|start_shadow|evaluate_windows|strategy-registry|guarded_active|min_llm_confidence_to_trade|entry_score_v2_min_reward_risk|entry_quality_max_sma20_distance" src tests docs`
- consultas numeradas a `registry.py`, `technical_study.py`, `builtin_pullback.py`, `trade_decision.py`, `promotion.py`, `runtime.py`, `scheduler.py`, `main.py`, `storage.py`, `config.py`, `tests/test_strategy_registry.py`, `tests/test_promotion.py`
- consulta SQLite read-only a `data/state/agente_bolsa.sqlite3`

Estado actual de BD:

- `strategy_versions` está vacío en la BD live (`data/state/agente_bolsa.sqlite3`), así que hoy manda el default de los builtins en código; no hay override persistido para `builtin_pullback`.

## 1. Cómo pasa una estrategia de SHADOW a ACTIVE

Respuesta corta: en el pipeline actual, para que una estrategia llegue a decisión basta con que su `status` efectivo sea `ACTIVE`. Ese estado puede venir del default del builtin o de un override en `strategy_versions`. No he encontrado flags adicionales en el pipeline de decisión.

Evidencia:

- El contrato de estrategia solo contempla `ACTIVE | SHADOW | RETIRED` (`src/agente_bolsa/strategies/base.py:35-43`).
- El registro escribe `status` en `strategy_versions` vía `register(..., status=...)` (`src/agente_bolsa/strategies/registry.py:80-108`).
- `discover(store)` carga builtins y overrides, excluye `RETIRED`, e incluye solo `ACTIVE` o `SHADOW`; `discover_active(store)` filtra estrictamente por `status == "ACTIVE"` (`src/agente_bolsa/strategies/registry.py:133-174`).
- En el estudio técnico, las estrategias en `SHADOW` mandan sus candidatos a `shadow_candidates` y “NUNCA llegan a decision/ejecucion”; las demás van a `candidates/all_candidates` (`src/agente_bolsa/tools/technical_study.py:66-91`).
- La decisión consume `report["all_candidates"]`; no usa `shadow_candidates` para selección real (`src/agente_bolsa/tools/trade_decision.py:680-713`, `src/agente_bolsa/tools/trade_decision.py:2499-2510`).
- La CLI manual del registro cambia exactamente ese `status`: `strategy-registry --activate/--shadow/--retire <name>` (`src/agente_bolsa/main.py:1772-1804`, `src/agente_bolsa/main.py:3578-3588`).

Conclusión operativa:

- Promoción manual: `builtin_pullback` entra en decisión si su estado efectivo pasa a `ACTIVE`.
- Promoción “oficial” automática: el sistema champion/challenger usa `PromotionManager` y ventanas en `promotion_windows`; cuando decide promover, también materializa el cambio como `set_strategy_status(..., "ACTIVE")` (`src/agente_bolsa/continuous_improvement/promotion.py:201-292`).

## 2. ¿Existe un estado intermedio guarded para estrategias?

No, no en la implementación actual de estrategias.

Evidencia:

- El enum implícito del modelo de estrategia es `ACTIVE | SHADOW | RETIRED` (`src/agente_bolsa/strategies/base.py:42`).
- El registro solo descubre estrategias con estado `ACTIVE` o `SHADOW`, y excluye cualquier otro (`src/agente_bolsa/strategies/registry.py:165-169`).
- La CLI del registro solo permite `--activate`, `--shadow` y `--retire` (`src/agente_bolsa/main.py:3583-3586`).

Sí existe `guarded_active`, pero para otras piezas del sistema, no para estrategias:

- `trade_decision` trata `guarded_active` como estado válido de respuestas operativas/reglas de aprendizaje (`src/agente_bolsa/tools/trade_decision.py:2586` según `rg`).
- La checklist de promoción usa `shadow / guarded_active / active / rejected` como vocabulario general de propuestas (`docs/promotion_checklist.md:32-38`), pero ese estado no está cableado al registro de estrategias.

Conclusión:

- Hoy no hay “guarded strategy” real. El salto implementado es `SHADOW → ACTIVE` o `SHADOW → RETIRED`.
- Si se quisiera un escalón intermedio para estrategias, habría que implementarlo de forma explícita en `registry/discover`, `technical_study` y posiblemente en sizing/gates. Ahora mismo no existe.

## 3. Qué hace builtin_pullback hoy y qué pasaría si pasara a ACTIVE

`builtin_pullback` nace en `SHADOW` por default (`src/agente_bolsa/strategies/builtin_pullback.py:120-125`). Su filtro exige:

- `close > sma_200` y `close > sma_50`
- `distance_sma20` entre `-0.05` y `0.08`
- `RSI 40–60`
- `return_5d <= 0.02`
- `return_20d >= -0.08`
- `return_60d > 0`
- excluye flags de breakout/momentum extendido

Evidencia: `src/agente_bolsa/strategies/builtin_pullback.py:17-23`, `:48-85`, `:108-116`.

Si pasa a `ACTIVE`, sus candidatos entrarían en `all_candidates` y sí llegarían a decisión, porque el único desvío SHADOW→`shadow_candidates` está en `technical_study.py` (`src/agente_bolsa/tools/technical_study.py:81-91`).

## 4. ¿Pasarían los gates vigentes?

### Gate de extensión

Sí, en principio el pullback no debería morir por extensión si conserva su propia definición.

Evidencia:

- `builtin_pullback` exige `distance_sma20 <= 0.08` (`src/agente_bolsa/strategies/builtin_pullback.py:18`, `:65`).
- El gate duro de entrada rechaza por extensión cuando `sma20_distance > entry_quality_max_sma20_distance` salvo excepciones (`src/agente_bolsa/tools/trade_decision.py:3235-3259`).
- El umbral actual es `entry_quality_max_sma20_distance = 0.12` (`src/agente_bolsa/config.py:158-165`).

Conclusión:

- Un candidato pullback sano (`<= 8%` sobre SMA20) queda por debajo del muro duro actual (`12%`), así que no debería ser bloqueado por “precio demasiado extendido sobre SMA20”.

### Gate de R:R

No hay bypass por estrategia. Todo candidato que llegue a recomendación debe superar `entry_score_v2`.

Evidencia:

- `entry_score_v2` mete hard block si `reward_risk < entry_score_v2_min_reward_risk` (`src/agente_bolsa/tools/trade_decision.py:1170-1199`).
- El umbral actual es `entry_score_v2_min_reward_risk = 1.5` (`src/agente_bolsa/config.py:568-571`).
- Sigue existiendo el ajuste paper `§1` que sube `take_profit` para construir el mínimo R:R si el setup es bueno (`src/agente_bolsa/tools/trade_decision.py:1205-1218` y continuación de la función).

Conclusión:

- Promover `builtin_pullback` no lo exime del filtro de R:R. Si el risk plan sale corto, dependerá del mismo mecanismo paper `§1` que ya usa el resto del sistema.

### Gate de confidence

Tampoco hay bypass por estrategia.

Evidencia:

- Las recomendaciones por fallback se crean ya con `confidence = min_llm_confidence_to_trade` (`src/agente_bolsa/tools/trade_decision.py:4338-4349`).
- Cualquier recomendación por debajo de ese umbral se rechaza (`src/agente_bolsa/tools/trade_decision.py:4652-4666`; también para salidas en `:5016-5017`).
- El umbral actual es `min_llm_confidence_to_trade = 0.65` (`src/agente_bolsa/config.py:759`).

Conclusión:

- Un `builtin_pullback` ACTIVE seguiría pasando por el mismo gate de confianza que `builtin_breakout`.

## 5. Vía manual vs vía oficial de promoción

### Vía manual mínima

Operativamente, la vía mínima es cambiar el estado en el registro:

- `python -m agente_bolsa.main strategy-registry --activate builtin_pullback`

Base técnica:

- ese comando persiste `ACTIVE` en `strategy_versions`, o registra la estrategia si aún no existe (`src/agente_bolsa/main.py:1772-1804`);
- `technical_study` la descubrirá como ACTIVE y sus candidatos dejarán de ir a `shadow_candidates` (`src/agente_bolsa/strategies/registry.py:133-174`, `src/agente_bolsa/tools/technical_study.py:81-91`).

### Vía oficial/autónoma champion-challenger

La vía más alineada con el diseño del sistema es:

1. abrir o mantener ventana shadow con `PromotionManager.start_shadow(...)`, que fuerza `SHADOW` y crea fila en `promotion_windows` (`src/agente_bolsa/continuous_improvement/promotion.py:113-138`);
2. acumular outcomes madurados shadow;
3. evaluar la ventana con `PromotionManager.evaluate_windows()` (`src/agente_bolsa/continuous_improvement/promotion.py:201-292`);
4. si la estrategia gana, el manager hace `set_strategy_status(strategy, "ACTIVE")` y degrada el champion previo a `SHADOW` (`src/agente_bolsa/continuous_improvement/promotion.py:270-278`).

Umbrales y reglas de la promoción automática:

- mínimos por defecto: sesiones, señales, drawdown relativo, p-valor binomial y presupuesto de promociones (`src/agente_bolsa/continuous_improvement/promotion.py:103-110`);
- decisión: expectancy shadow positiva y superior al champion, hit-rate dentro del margen, drawdown contenido y significancia estadística (`src/agente_bolsa/continuous_improvement/promotion.py:158-181`);
- con evidencia insuficiente, la ventana se extiende o se rechaza por vencimiento (`src/agente_bolsa/continuous_improvement/promotion.py:217-246`);
- la evaluación corre al cierre de `post_market_review_job` (`src/agente_bolsa/scheduler.py:2030-2043`), y la arquitectura lo documenta explícitamente (`docs/architecture.md:195`).

Hay además enganche automático cuando una propuesta de estrategia queda `APPLIED` en el runtime de mejora continua: se abre ventana SHADOW (`src/agente_bolsa/continuous_improvement/runtime.py:713-736`, `docs/architecture.md:195`).

## 6. ¿Es reversible de forma limpia?

Sí, a nivel operativo la reversión es limpia porque el mecanismo real vive en el registro/BD, no en tocar el código de la estrategia.

Opciones de reversión:

- reversión inmediata a SHADOW: `strategy-registry --shadow builtin_pullback` (`src/agente_bolsa/main.py:1772-1804`, `:3584-3586`);
- retirada completa: `strategy-registry --retire builtin_pullback` (`src/agente_bolsa/main.py:1772-1804`, `:3585-3586`);
- en promoción automática, el champion reemplazado ya queda en SHADOW de forma reversible (`src/agente_bolsa/continuous_improvement/promotion.py:272-275`, `docs/architecture.md:195`).

Matiz importante:

- cambiar el default hardcodeado del builtin en código (`status = "SHADOW"` en `builtin_pullback.py`) también sería reversible por git revert, pero no es la palanca operativa correcta mientras exista `strategy_versions`. La forma segura es el override de registro, no editar el builtin.

## 7. Tests que cubren la promoción de estrategias

Cobertura encontrada:

- registro y descubrimiento:
  - default actual: `builtin_breakout=ACTIVE`, `builtin_pullback=SHADOW`, y `discover_active` excluye pullback (`tests/test_strategy_registry.py:68-75`);
  - transición manual de estados y retiro (`tests/test_strategy_registry.py:78-101`).
- promoción automática champion/challenger:
  - challenger claramente mejor → `PROMOTED`, challenger `ACTIVE`, champion previo `SHADOW` (`tests/test_promotion.py:65-81`);
  - challenger peor → `REJECTED_SHADOW` y `RETIRED` (`tests/test_promotion.py:84-99`);
  - evidencia insuficiente → `EXTEND` (`tests/test_promotion.py:102-112`);
  - presupuesto de ventanas concurrentes → `QUEUED` (`tests/test_promotion.py:120-129`);
  - `start_shadow` crea ventana y fuerza `SHADOW` (`tests/test_promotion.py:132-139`).

Hueco de test:

- no he visto un test end-to-end específico “`builtin_pullback` pasa a ACTIVE y sus candidatos recorren technical_study → trade_decision sin romper gates”. La cobertura actual prueba piezas, no ese camino concreto.

## 8. Riesgos y huecos antes de promover pullback

1. No existe estado intermedio `guarded` para estrategias.
   - El sistema obliga a pasar de medición pura (`SHADOW`) a participación plena en decisión (`ACTIVE`).

2. La promoción por registro no reduce tamaño ni cuota por estrategia.
   - Una vez ACTIVE, la estrategia entra por el mismo embudo que las demás; no hay sizing limitado “por estrategia”.

3. La evidencia automática de promoción está orientada a champion/challenger por outcomes, pero no he visto un test específico que valide la promoción manual de un builtin shadow en producción paper con rollback inmediato.

4. El diseño de promoción automática asume outcomes shadow maduros y comparables frente al champion.
   - Si el edge del pullback se valida el 6-jul, conviene revisar no solo expectancy media sino cobertura madura, número de sesiones y diversidad de régimen antes de activar.

5. La BD live no tiene hoy overrides en `strategy_versions`.
   - Eso simplifica el estado actual, pero también implica que una activación manual sería un cambio operativo nuevo y visible inmediatamente para el scanner.

## 9. Runbook propuesto para promover pullback de forma segura y reversible

### Opción A — la que existe hoy y es segura: promoción a ACTIVE con rollback rápido

1. Verificar evidencia previa a promoción:
   - outcomes shadow maduros de `builtin_pullback` frente a `builtin_breakout`;
   - muestra mínima suficiente y no concentrada en un único régimen;
   - comprobar que sigue generando candidatos sanos (distance_sma20, RSI, R:R).

2. Tomar snapshot del estado antes del cambio:
   - `strategy-registry --list-registry --json`
   - `promotions --json`
   - guardar el último `closed_market_technical_study`.

3. Activar por registro, no tocando código:
   - `python -m agente_bolsa.main strategy-registry --activate builtin_pullback`

4. Verificar inmediatamente:
   - `strategy-registry --list-registry --json` debe mostrar `builtin_pullback=ACTIVE`;
   - el siguiente `closed_market_technical_study` debe mover sus candidatos desde `shadow_candidates` a `all_candidates`;
   - revisar rechazos en decisión para confirmar si pasan gates o dónde caen.

5. Medir en paper durante una ventana corta y explícita:
   - cobertura de candidates seleccionados;
   - rechazo por extensión, R:R y confidence;
   - expectancy forward neta de costes frente a breakout;
   - impacto en concentración de setups.

6. Rollback si degrada o si la evidencia no aguanta:
   - `python -m agente_bolsa.main strategy-registry --shadow builtin_pullback`
   - o `--retire builtin_pullback` si se decide sacarla del scanner.

### Opción B — vía oficial del sistema: mantener SHADOW hasta que PromotionManager la suba

1. Confirmar que `builtin_pullback` sigue en `SHADOW`.
2. Asegurar que existe/permanece ventana en `promotion_windows`.
3. Esperar outcomes shadow maduros suficientes.
4. Evaluar con `python -m agente_bolsa.main promotions --evaluate`.
5. Solo aceptar la promoción si sale `PROMOTED`; el propio manager pondrá `ACTIVE` al challenger y `SHADOW` al champion anterior.

Esta opción es más coherente con el diseño de champion/challenger, pero tiene una limitación práctica: no ofrece un estado intermedio guarded; el salto final sigue siendo a `ACTIVE`.

## 10. Recomendación práctica para el 6-jul

Si el pullback demuestra edge, el camino más seguro y reversible que existe hoy es:

1. no tocar el código del builtin;
2. activar solo por `strategy-registry`;
3. monitorizar 1-2 sesiones en paper con foco en:
   - si los candidatos entran en `all_candidates`,
   - si sobreviven a extensión/R:R/confidence,
   - y si empiezan a competir razonablemente con breakout;
4. revertir a `SHADOW` al primer signo de degradación.

Lo que falta para una promoción “medida y limitada” de verdad no es un runbook, sino una capacidad nueva: un estado intermedio de estrategia tipo `guarded_active` con cupo o sizing reducido. Esa capacidad hoy no existe en el código inspeccionado.
