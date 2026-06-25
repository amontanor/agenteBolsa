# Plan de desbloqueo del embudo (25-jun-2026)

Origen: `cycle-funnel --history 40` (12 ciclos, 27 recomendaciones, **0 órdenes**). Mapa
de blockers agregado, con veredicto honesto de cada uno (bug / legítimo / puerta de datos):

| blocker (etapa: motivo) | nº | veredicto | acción |
|---|---|---|---|
| determinista: material_risk | 26 | **BUG** | **ARREGLADO v0.4.45** (`bool(dict)` siempre True) |
| entry_quality: reward_risk_bajo | ~12 | construcción de entrada | diseño abajo (§1) |
| plan: market_state_partial_missing_macro | 8 | puerta de datos | diseño abajo (§2) |
| entry_quality: extendido sobre SMA20 (13-19%) | 6 | **LEGÍTIMO** | NO tocar (nuestro estudio: lo extendido pierde) |
| entry_quality: RSI flojo + volumen débil | 2 | **LEGÍTIMO** | NO tocar |

Tras el fix de `material_risk` (desplegado), a las 15:30 los blockers dominantes serán
§1 y §2. Ambos están **diseñados pero NO implementados** (cambian conducta → requieren
pytest + medición; se deciden con los datos reales del embudo post-fix).

## §1 — reward_risk_bajo: construcción de entrada con R:R garantizado

**Diagnóstico:** el entry-quality exige `reward_risk >= 1.5` (`_entry_score_v2`,
`config.entry_score_v2_min_reward_risk=1.5`), calculado desde el stop/take de la
recomendación, que pone **el LLM**. El LLM coloca objetivos demasiado cerca / stops
demasiado lejos → R:R < 1.5 → rechazo. **El gate es correcto** (1.5 es estándar); el
problema es la *construcción* de la entrada.

**Diseño propuesto (shadow primero):** placement determinista de stop/take basado en
ATR/estructura que **garantice R:R ≥ 1.5 por construcción**:
- `stop = entrada − k·ATR` (k≈1.0–1.5, o por debajo del swing low reciente).
- `take = entrada + R·(entrada − stop)` con `R ≥ 1.5` (p.ej. 2.0).
- Aplicar SOLO si mejora el R:R respecto al del LLM; nunca empeorarlo.
- **Shadow:** registrar, por candidato, el R:R del LLM vs el determinista y el outcome
  forward, sin cambiar la conducta. Promover a activo solo si el placement determinista
  no degrada el hit-rate/expectativa neta de costes.
- Riesgo: stops por ATR pueden ser muy anchos en nombres volátiles (reduce size) o muy
  estrechos (te saca por ruido). Medir antes de activar.

Ficheros probables: `tools/trade_decision.py` (donde se construye/normaliza la
recomendación) o un helper nuevo `tools/entry_construction.py`. Con test.

## §2 — market_state_partial: bloqueo de plan incoherente con la revisión

**Diagnóstico:** `build_buy_order_plans` (`trade_decision.py:4533`) llama a
`_fallback_market_state_block_reason`, que **bloquea en DURO todo plan de compra** si
market_state es PARTIAL y la degradación menciona macro/news/sentiment/vendor. Como no
hay feed de macro/news (sin FMP), market_state es PARTIAL **por eso** → el bloqueo
**siempre** salta. Es una **puerta de datos, no de calidad de trade**.

**Incoherencia clave:** la revisión determinista (`deterministic_reviewer.py:143-165`)
trata el mismo PARTIAL como **micro-experimento** (aprobado, tamaño reducido) en modo
paper. Pero el plan lo **bloquea en duro**. Una recomendación puede pasar la revisión
como micro y luego morir en el plan. Inconsistente.

**Diseño propuesto (con criterio, medido):** en **modo paper**, que
`build_buy_order_plans` trate el PARTIAL-por-falta-de-macro/news igual que la revisión:
**permitir el plan a tamaño micro/reducido en vez de bloquear en duro**. Mantener el
bloqueo duro para `INSUFFICIENT` y para degradación de *integridad* de datos (vendor
severity BLOCK, datos obsoletos). Justificación: en paper queremos **operar para
generar datos**; la falta de macro/news es un hueco de *contexto*, no un riesgo de
ejecución en paper. Alternativa limpia: conseguir el feed (FMP) → quality GOOD → sin
bloqueo (decisión de coste, aparcada).

Ficheros: `tools/trade_decision.py` (`build_buy_order_plans`), gobernado por
`settings.trading_mode == "paper"`. Con test. NUNCA tocar risk/kernel/execution.

## Orden recomendado a las 15:30
1. Re-leer `cycle-funnel --history` (ya sin material_risk).
2. Si domina §2 (market_state_partial) → es el desbloqueo de mayor impacto y el más
   claro (coherencia con la revisión); implementarlo en paper, con test, medido.
3. §1 (R:R) en shadow en paralelo.
4. Si entran trades paper → el lab y los estudios de edge por fin tendrán datos
   ejecutados (cierra el bucle de mejora continua, ver
   `docs/diagnostico_lab_mejora_continua_2026-06-25.md`).

**Disciplina:** todo cambio de conducta con pytest verde + shadow/medición + bump de
versión; paper-only; jamás risk.py/kernel/broker/execution/ALLOW_LIVE.
