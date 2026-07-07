# Informe Codex P-L5A - safety learning_mode autorizado - 2026-07-07

## Objetivo

Eliminar el falso rojo permanente de `learning_mode.enabled` en `config-audit` y
en el digest ahora que el modo de aprendizaje esta autorizado por Antonio, sin
rebajar los checks reales de seguridad.

## Cambios aplicados

- `learning_mode.enabled` deja de ser violacion por si mismo.
- Violaciones reales nuevas:
  - `learning_mode.config_parseable`
  - `learning_mode.sin_autorizacion`
- La linea Safety muestra siempre el estado:
  - `learning_mode=ON|OFF`
  - `shadow_first=True|False`
- `learning_mode.json` real incorpora:
  - `"authorized_by": "Antonio 2026-07-07"`
- Se aislaron varios tests que dependian del `DATA_DIR` real, porque ahora el
  repo vive con `learning_mode=ON` autorizado.

## Archivos

- `src/agente_bolsa/tools/learning_mode.py`
- `src/agente_bolsa/tools/config_audit.py`
- `tests/test_config_audit.py`
- `tests/test_cycle_runner_summary.py`
- `tests/test_market_state_partial_paper.py`
- `tests/test_trade_decision.py`
- `data/config/learning_mode.json`
- `src/agente_bolsa/__init__.py`

## Verificacion real

- `.\.venv\Scripts\python.exe -m pytest tests -x -q`
  - `1002 passed, 1 warning`
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts`
  - `All checks passed!`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`
  - `ok=true`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`
  - `trading_mode=paper`
  - `allow_live_trading=false`
  - `broker.paper=true`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main config-audit --json`
  - `ok=true`
  - `learning_mode.enabled=true`
  - `learning_mode.human_gated=true`
  - `learning_mode.shadow_first=false`
  - `learning_mode.authorized_by="Antonio 2026-07-07"`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`
  - ciclo real completado sin traceback
  - `cycle_id=20260707-212611`
  - `used_crew=false`
  - `market_state_quality=PARTIAL`

## Resultado operativo

El safety queda honesto:

- `learning_mode=ON` ya no dispara alerta por existir.
- Si falta autorizacion humana o el fichero no parsea, si hay alerta.
- Paper/live/auto-apply permanecen intactos.

## Version

- `src/agente_bolsa/__init__.py`
- `0.4.121 -> 0.4.122`
