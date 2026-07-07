# Informe Codex P-L2 - learning mode - 2026-07-07

## Objetivo

Implementar el modo experimento de aprendizaje en paper, human-gated y reversible, sin alterar la conducta normal cuando `enabled=false`.

## Entrega

- Nuevo config gobernado: `data/config/learning_mode.json`.
- Nuevo helper: `src/agente_bolsa/tools/learning_mode.py`.
- `config-audit` y `Safety` del digest muestran siempre el estado de `learning_mode`.
- Recalibracion de gates solo bajo learning mode:
  - `backtest_gate` acepta near-miss documentado como `learning_near_miss`.
  - `market_state PARTIAL` deja de vetar por si solo.
  - ausencia de sentimiento deja de ser veto automatico salvo `material_risk` real.
  - el gate de extension se mantiene duro.
- `builtin_pullback` entra en el estudio como `LEARNING_ACTIVE` solo dentro del experimento.
- Cohorte aislado con `source=learning_experiment` y muralla por defecto en analytics/edge/promotions.
- `shadow_first=true` genera `data/reports/learning_mode_shadow_<fecha>.json`.
- Si el kill switch operativo esta activo, el shadow sigue registrando el experimento pero nunca envia ordenes reales.

## Evidencia operativa

### Safety al entregar

- `trading_mode=paper`
- `allow_live_trading=false`
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
- `config-audit --json` OK con:
  - `learning_mode.enabled=false`
  - `learning_mode.human_gated=true`

### Shadow real de hoy

Artefacto:

- `data/reports/learning_mode_shadow_2026-07-07.json`

Ejecucion real:

- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once`
- `cycle_id=20260707-145337`

Resultado:

- El shadow quedo registrado aunque el kill switch operativo seguia activo por `kernel_integrity_violation: .env`.
- `would_buy` del cohorte:
  - `LYV`
  - notional `924.15 USD`
  - entrada `184.83`
  - stop `174.6679`
  - take profit `200.0732`
  - paso como `micro_experiment=true`
  - `backtest_soft_override=true`
  - motivo: `deterministic_capacity_fill`
- Recomendaciones del cohorte generadas en ese ciclo:
  - `TECH`, `LYV`, `IFF`, `SYY`

Interpretacion:

- El experimento ya puede dejar una traza honesta de "que habria comprado" durante la sesion.
- El kill switch sigue bloqueando cualquier envio real, como debe ser.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests -x -q`
  - `985 passed, 1 warning`
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts`
  - limpio
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`
  - `ok=true`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`
  - paper, live off
- `.\.venv\Scripts\python.exe -m agente_bolsa.main config-audit --json`
  - `ok=true`, `learning_mode` visible y apagado al cierre

## Version

- `src/agente_bolsa/__init__.py`
- `0.4.115 -> 0.4.116`

## Riesgos y notas

- El shadow de hoy no es una autorizacion de operativa real; Antonio debe decidir el flip a `shadow_first=false`.
- El kill switch operativo sigue activo por `.env`; el cambio de hoy no lo rebaja ni lo esquiva para ejecucion real.
