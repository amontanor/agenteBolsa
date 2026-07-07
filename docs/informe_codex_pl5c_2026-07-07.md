# Informe Codex P-L5C - honesty capacity fill + cohort telemetry - 2026-07-07

## Objetivo

Corregir la etiqueta engañosa de los `deterministic_capacity_fill` y propagar
esa procedencia a `signal_outcomes.features` para futuros analisis de cohortes.

## Diagnostico del ciclo real 20260707-145337

Evidencia inspeccionada:

- `data/reports/learning_mode_shadow_2026-07-07.json`
- `agent_events` del ciclo `20260707-145337`
- `trade_recommendations` del ciclo `20260707-145337`

Hallazgos:

- El ciclo SI tuvo respuesta LLM real.
  - En el shadow report: `TECH` con `source="llm"`.
  - En `agent_events`: existe `paper_auto_trade_recommendation_augmented`.
  - No existe evento `paper_auto_trade_llm_fallback`.
- Los fills `LYV`, `IFF` y `SYY` fueron añadidos despues para completar
  capacidad de compra.
- Por tanto, la etiqueta antigua:
  - `Fallback determinista por fallo del LLM ... Completa capacidad buy no usada por el LLM.`
  - era heredada y deshonesta en ese caso.

Conclusión:

- No fue un fallo parcial real del LLM en ese ciclo.
- Fue un problema de texto/origen heredado en la construcción del
  `deterministic_capacity_fill`.

## Cambios aplicados

- `deterministic_trade_fallback_recommendations(...)` deja de incrustar
  "por fallo del LLM" salvo cuando el caller indica fallo real.
- `augment_recommendations_with_deterministic_fallback(...)` distingue:
  - `capacity_fill_tras_llm_ok`
  - `capacity_fill_por_fallo_llm`
- `TradeRecommendation` gana metadatos:
  - `decision_origin`
  - `capacity_fill_reason_code`
- `update_signal_decisions(...)` persiste en `signal_outcomes.features`:
  - `recommendation_source`
  - `decision_origin`
  - `capacity_fill_reason_code`
  - `llm_response_status`
- `Store.update_signal_decision(...)` ahora fusiona tambien `features_json`.
- Se mantiene compatibilidad con dobles de prueba que aun usan la firma antigua
  de `update_signal_decision`.

## Archivos

- `src/agente_bolsa/models.py`
- `src/agente_bolsa/tools/trade_decision.py`
- `src/agente_bolsa/tools/signal_learning.py`
- `src/agente_bolsa/storage.py`
- `src/agente_bolsa/cycle_runner.py`
- `tests/test_trade_decision.py`
- `tests/test_signal_learning.py`
- `src/agente_bolsa/__init__.py`

## Verificacion real

- `.\.venv\Scripts\python.exe -m pytest tests -x -q`
  - `1004 passed, 1 warning`
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts`
  - `All checks passed!`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`
  - `trading_mode=paper`
  - `allow_live_trading=false`
  - `broker.paper=true`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`
  - `ok=true`

Ejecucion real minima para la nueva telemetria:

- script Python ejecutado contra `data/tmp_pl5c_demo/state.sqlite3`
  - resultado:
    - `decision=approved_buy`
    - `recommendation_source=deterministic_capacity_fill`
    - `decision_origin=deterministic_capacity_fill`
    - `capacity_fill_reason_code=capacity_fill_tras_llm_ok`
    - `llm_response_status=ok`

Evidencia real del bug antiguo:

- shadow report `run_id=20260707-145337`
  - `llm_symbols=["TECH"]`
  - `capacity_fill_symbols=["LYV","IFF","SYY"]`
  - las tres reasons antiguas incluian incorrectamente `por fallo del LLM`

## Version

- `src/agente_bolsa/__init__.py`
- `0.4.123 -> 0.4.124`
