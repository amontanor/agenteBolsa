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

## §3 — research_guard: 3ª pared oculta (ARREGLADA v0.4.47)

Hallado en premarket: tras §2, las recomendaciones llegaban por primera vez al
`research_guard` (`build_buy_order_plans:4597`). El fichero `latest_research_evidence.json`
existe con `required=True, decision_ready=False` → `research_block_reason` bloqueaba TODA
compra (`research_evidence_not_ready`). Era la 3ª pared, invisible hasta ahora porque
`market_state_guard` bloqueaba antes. **Corregido (v0.4.48):** el research_guard YA tiene un flag de control,
`RESEARCH_EVIDENCE_FAIL_CLOSED_FOR_BUYS` (default True; `research_evidence.py:270` lo usa
para fijar `summary.required`). El enfoque correcto NO es hardcodear paper, sino respetar
el flag: el helper `_effective_research_block_reason` bloquea solo si el flag esta en True
(de inmediato, sin depender del 'required' obsoleto del ultimo reporte). Para operar en
paper sin feed de research, se pone el flag a **False** en `.env` (decision reversible del
operador) + kernel-seal + restart. Test `test_research_guard_paper.py` (flag-based). El
test existente del flag vuelve a verde. Misma filosofia que §2 pero por el knob previsto.

## Wall-check final (premarket 25-jun) — NO quedan más paredes ocultas

Trazado completo de `build_buy_order_plans` tras relajar market_state (§2) y research (§3).
Gates restantes y su naturaleza:
- `operational_kill_switch` (4613): enabled=True pero SIN `operational_block.json` → no bloquea.
- `min_llm_confidence_to_trade=0.65` (4629): por-recomendación, legítimo (no muro).
- `open_order` / `position_add` (allow_position_adds=false) / `duplicate_symbol` (4644-4682):
  por-símbolo (dedup), no muros; irrelevantes con cartera vacía.
- `position_sizing` notional>0 (4713) + evaluación de `risk.py`: por-recomendación, legítimos.

**Veredicto:** las 3 paredes de datos (material_risk, market_state, research) están abajo y
NO hay otro hard-block-all. A las 15:30, una recomendación con confianza ≥0.65, R:R≥1.5 y no
extendida → produce orden paper (micro). Si entran pocas, el lever real será §1 (construcción
de entrada / R:R). Ya no hay "0 trades por muro": ahora es "entran las de buena calidad".
