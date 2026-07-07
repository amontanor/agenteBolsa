# Informe Codex P31 - bump determinista y contexto de modulo bajo test

Fecha: 2026-07-07

## Cambios entregados

- El pipeline de preview/codegen ya no delega el bump de version al modelo:
  - filtra cualquier hunk/edit de `src/agente_bolsa/__init__.py` generado por el LLM;
  - aplica el cambio real en sandbox;
  - hace bump determinista `patch + 1` en `__version__`;
  - incorpora ese bump al diff final y lo deja trazado en `payload.version_bump`.
- El prompt de codegen ahora instruye explicitamente al modelo a no tocar `__init__.py`.
- El `approve` humano aplica el diff sin el hunk de version del artefacto y re-bumpea contra el arbol real:
  - si entre preview y approve la rama ya estaba en `X`, el apply deja la rama en `X+1`;
  - queda cubierto por test.
- Las propuestas test-only ya reciben contexto del modulo bajo prueba:
  - parseo de imports `agente_bolsa.*` del test existente;
  - soporte adicional para `payload.modules_under_test`;
  - contexto read-only tambien para `scripts/` cuando se declara explicitamente.
- El filtro de `codegen-nightly` ahora distingue rechazos definitivos de fallos reintentables:
  - bloquea rechazos humanos/constitucionales;
  - permite reintentar `FAILED`/`BLOCKED`/`REJECTED_BY_TESTS` nacidos del propio codegen/sandbox tras arreglos mecanicos.

## Propuestas P25 actualizadas

Se actualizaron en la base real del laboratorio estas propuestas con `modules_under_test`:

- `ci_prop_b3f950033a99` -> `["src/agente_bolsa/continuous_improvement/digest.py"]`
- `ci_prop_0327e166f163` -> `["src/agente_bolsa/continuous_improvement/digest.py"]`
- `ci_prop_82a01dd92356` -> `["scripts/core_sleeve_parity_check.py"]`

## Ejecucion real

Validacion del repo:

- `.venv\Scripts\python.exe -m pytest tests -x -q` -> `995 passed, 1 warning`
- `.venv\Scripts\python.exe -m ruff check src tests scripts` -> limpio
- `.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json` -> `ok=true`
- `.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`

Nightly manual:

- `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab codegen-nightly --json`
- Run real: `ci_codegen_nightly_1fc0e0873511`
- Resultado inicial:
  - `ci_prop_82a01dd92356` -> `READY_FOR_HUMAN_REVIEW` (`ci_artifact_aa50bbd64b02`)
  - `ci_prop_0327e166f163` -> primero quedo `REJECTED_BY_GATE` porque el prompt seguia empujando cambios en `src/` para propuestas test-only
- Tras corregir el prompt test-only:
  - `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab gen-diff --proposal ci_prop_b3f950033a99 --json`
    - `READY_FOR_HUMAN_REVIEW` (`ci_artifact_0f5f1ea3c39f`)
  - `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab gen-diff --proposal ci_prop_0327e166f163 --json`
    - primer reintento: `FAILED` por truncado LLM (`code_diff_codegen_failed` reintentable)
    - segundo reintento: `READY_FOR_HUMAN_REVIEW` (`ci_artifact_6fbd8a753e50`)

Estado final real de las 3 propuestas:

- `ci_prop_b3f950033a99` -> `READY_FOR_HUMAN_REVIEW`, `tests_ok=true`, bump `0.4.118 -> 0.4.119`
- `ci_prop_0327e166f163` -> `READY_FOR_HUMAN_REVIEW`, `tests_ok=true`, bump `0.4.118 -> 0.4.119`
- `ci_prop_82a01dd92356` -> `READY_FOR_HUMAN_REVIEW`, `tests_ok=true`, bump `0.4.118 -> 0.4.119`

No he ejecutado `approve`.

## Seguridad operativa

- `trading_mode=paper`
- `allow_live_trading=false`
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
- `data/config/core_sleeve.json`: `dry_run=true`
- No se tocaron los 6 ficheros del suelo de kernel.

## Review y approve para Antonio

Revisar cada diff:

- `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_b3f950033a99`
- `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_0327e166f163`
- `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_82a01dd92356`

Aplicar manualmente si Antonio los acepta:

- `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_b3f950033a99 --actor Antonio`
- `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_0327e166f163 --actor Antonio`
- `.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_82a01dd92356 --actor Antonio`
