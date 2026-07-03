# Informe Codex P24 - Research-mode con mercado cerrado y supervisor nightly

Fecha: 2026-07-03

## Cambios entregados

- `ContinuousImprovementLabRuntime` ahora mantiene el bloqueo por defecto con mercado cerrado, pero si `data/config/ci_research_mode.json` tiene `enabled=true` y `human_gated=true`, ejecuta el ciclo como `mode=research`.
- El research-mode excluye eventos/tareas de trading: candidatos vivos, ordenes, sizing, snapshots realtime y agentes de mercado/estrategia/riesgo de capital.
- En research-mode solo persiste propuestas `CODE_CHANGE` de observabilidad, herramientas, tests, scripts o documentacion, con cap `max_new_proposals_per_cycle=3`.
- La config nueva queda en `data/config/ci_research_mode.json` con `enabled=false` por defecto.
- El gate de gobierno marca `ci_research_mode`, `ci_research_mode_enabled` y `data/config/ci_research_mode.json` como parametros gobernados, para que la firma no pueda activarlo sola.
- El digest diario incluye la seccion `Research-mode cerrado` con ciclos de las ultimas 24h y tokens/coste LLM atribuidos por `llm_call_id`.
- Se anadieron:
  - `scripts/run_codegen_nightly.ps1` one-shot.
  - `scripts/run_codegen_nightly_supervisor.ps1` supervisor sin admin, hora default `03:00`.

## Ejecucion real documentada

- `continuous-improvement-lab run-once --json` con config default OFF y mercado cerrado devolvio `MARKET_BLOCKED`, como se exige para el modo no activado.
- `continuous-improvement-lab digest --days 1 --json` mostro `research_mode.cycles=0`, `total_tokens=0`, `cost_usd=0.0`.

Comando para Antonio si quiere arrancar el supervisor nightly:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_codegen_nightly_supervisor.ps1 -RunAt 03:00
```

No lo he arrancado.

## Seguridad operativa

- `trading_mode=paper`
- `allow_live_trading=false`
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
- `data/config/core_sleeve.json`: `dry_run=true`
- `data/config/ci_research_mode.json`: `enabled=false`
- No se tocaron los 6 ficheros del suelo de kernel.

## Verificacion

- `.venv\Scripts\python.exe -m pytest tests\ -x -q` -> `925 passed, 1 warning`.
- `.venv\Scripts\ruff.exe check src tests scripts` -> limpio.
- `validate-agent-config --json` -> `ok=true`, sin errores ni warnings.
- `status` -> operativo en paper.
