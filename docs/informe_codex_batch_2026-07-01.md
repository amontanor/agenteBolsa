# Informe Codex - Batch 2026-07-01

## Resumen

Batch de tres tareas de bajo riesgo ejecutado sin tocar archivos protegidos:
`risk.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py`, `config.py` ni
`.env`.

Version final: `0.4.72`.

## Tarea 1 - Digest diario del lab

Se anadio el CLI read-only:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days N
```

El digest resume en texto:

- propuestas creadas
- rechazos por motivo: `self_safety`, `self_governance`,
  `recently_rejected`, `otros`
- propuestas `READY_TO_APPLY` indicando si tienen diff adjunto
- `applied_changes` por estado
- experimentos corridos, `PASSED`, `FAILED`
- seccion `Requiere tu atencion` con `READY_TO_APPLY` que tienen diff listo

Implementacion: `src/agente_bolsa/continuous_improvement/digest.py` +
subcomando en `src/agente_bolsa/main.py`.

Test sintetico: `test_lab_digest_counts_synthetic_categories`.

Ejecucion real de control:

- `continuous-improvement-lab digest --days 1`
- resultado en ventana de 1 dia: `READY_TO_APPLY=4`, `Requiere tu atencion`: nada con diff listo,
  `applied_changes`: `ROLLED_BACK=1`

## Tarea 2 - Auditoria constitucional

Se anadio un candado de regresion que enumera settings reales desde
`Settings.model_fields` y falla si un setting de seguridad/gobierno no queda
cubierto por `self_safety` o `self_governance`.

Cobertura auditada:

- auto-apply y aprobacion humana
- live trading, `TRADING_MODE`, controles de live y capital live
- suelo de kernel por paths protegidos
- autonomia (`code_autonomy_level`, promocion/demote)
- cadencia/WIP/lifecycle del lab (`CI_*`, `CONTINUOUS_IMPROVEMENT_*`)
- sandbox y reparacion del lab

Hueco encontrado y cerrado: referencias con prefijo, por ejemplo
`settings.allow_auto_apply_improvements`, no se capturaban como el identificador
base `allow_auto_apply_improvements`. Se corrigio el matcher estructural para
detectar identificadores prohibidos con prefijos/sufijos de contexto.

Distincion documentada y testeada: parametros de trading como
`trade_selection_top_n` y `min_llm_confidence_to_trade` no se prohiben por esta
constitucion. Siguen en cola humana y requieren evidencia de edge.

Tests:

- `test_constitution_covers_all_security_and_governance_settings`
- regresion explicita para `settings.allow_auto_apply_improvements`
- exclusion explicita de `trade_selection_top_n` y `min_llm_confidence_to_trade`

Limpieza adicional de cola por el hueco cerrado:

- `ci_prop_965e680a5b5f` (`continuous_improvement/settings.allow_auto_apply_improvements`)
  paso de `READY_TO_APPLY` a `REJECTED` con
  `self_safety_modification_forbidden`.

Verificacion posterior:

- `active_constitution_matches = 0`
- `trade_selection_top_n_active = 1`
- `ci_prop_4a759922e290` sigue `READY_TO_APPLY`

## Tarea 3 - Rollback del cambio demo

Se revirtio limpiamente el cambio demo:

```powershell
git revert --no-commit 32ae00e3cb5d42588d30b47236f0e654702014e9
```

El revert elimina `docs/ci_codegen_demo.md` y queda incluido en el commit unico
de este batch.

Registro auditado:

- `applied_change_id`: `ci_applied_18703ab1d9a2`
- `target_key`: `docs/ci_codegen_demo.md`
- estado final: `ROLLED_BACK`
- `rollback_actor`: `codex_batch_2026_07_01`
- `rollback_strategy`: `git_revert_no_commit`
- `reverted_commit`: `32ae00e3cb5d42588d30b47236f0e654702014e9`

Verificacion:

- `Test-Path docs\ci_codegen_demo.md` -> `False`
- `APPLIED` -> `0`
- `ROLLED_BACK` -> `1`

## Verificacion global

Comandos ejecutados:

```powershell
.\.venv\Scripts\ruff.exe check src tests
python -m pytest tests/ -x -q
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days 1
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew
```

Resultados:

- ruff: OK
- pytest: `824 passed`
- digest real: OK, solo lectura
- status: `trading_mode=paper`, `allow_live_trading=false`
- run-once sin LLM: OK, ciclo `20260701-105024`
- applied_changes: `APPLIED=0`, `ROLLED_BACK=1`
- cola activa: `active_constitution_matches=0`, `READY_TO_APPLY=6`
