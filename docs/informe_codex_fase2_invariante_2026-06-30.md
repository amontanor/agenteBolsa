# Informe Codex Fase 2 - Invariante de seguridad de auto-apply

Fecha: 2026-06-30  
Repositorio: `C:\Antonio\Bref\agenteBolsa`  
Objetivo: fijar con tests la cadena de guards que impide aplicar cambios antes de construir Fase 2.

## Veredicto

El apply queda bloqueado por defecto en el runtime residente:

- Si `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, una propuesta `CODE_CHANGE` en `READY_TO_APPLY` permanece en cola humana y no se invoca `AutoApplyCodeAgent`.
- Si `IMPROVEMENT_DRY_RUN=true`, tampoco se invoca `AutoApplyCodeAgent`.
- Si alguien llama directamente a `AutoApplyCodeAgent.try_apply(...)`, el propio agente vuelve a bloquear por `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `IMPROVEMENT_DRY_RUN=true`, `ALLOW_LIVE_TRADING=true` o `REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=true`.
- El suelo de kernel bloquea siempre los paths protegidos en todos los niveles de autonomia.

No encontre una ruta que pueda acabar en `APPLIED` con `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.

Matiz importante para Fase 2: no existe todavia un artefacto positivo de aprobacion humana explicita que habilite apply. Lo que existe hoy es un bloqueo negativo: `REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=true` impide `APPLIED`; si se desactiva ese requisito y se activan los demas flags, `AutoApplyCodeAgent` puede aplicar. Para Fase 2 conviene introducir una aprobacion humana persistida y verificable antes de permitir esa transicion.

## Cadena exacta de apply

### Ruta runtime residente

Archivo: `src/agente_bolsa/continuous_improvement/runtime.py`

1. `_persist_validations(...)` ejecuta validacion y actualiza la propuesta.
2. Solo considera auto-apply si:
   - `proposal_type == "CODE_CHANGE"`
   - `validation["status"] == "READY_TO_APPLY"`
   - `not settings.improvement_dry_run`
   - `settings.allow_auto_apply_improvements`
3. Solo entonces llama:
   - `self.code_applier.try_apply(...)`
4. Si el resultado es `APPLIED`, `ROLLED_BACK`, `FAILED`, `BLOCKED` o `REJECTED_BY_TESTS`, actualiza propuesta/iniciativa y registra evento.

Invariante fijado: con `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, el runtime no llama al applier y no escribe filas en `continuous_improvement_applied_changes`.

### Ruta AutoApplyCodeAgent

Archivo: `src/agente_bolsa/continuous_improvement/experiments.py`

`AutoApplyCodeAgent.try_apply(...)` elige sandbox git o legacy:

- Sandbox si `ci_sandbox_enabled` y hay repo git.
- Legacy si no hay sandbox soportado.

Ambas rutas llaman primero a `_blocked_reason(...)`.

Orden de guards en `_blocked_reason(...)`:

1. `system_freeze_mode`
2. `not settings.allow_auto_apply_improvements`
3. `settings.improvement_dry_run`
4. `settings.allow_live_trading`
5. `settings.require_human_approval_for_code_changes`
6. `proposal_type != "CODE_CHANGE"`
7. `risk_level == "HIGH"`
8. `validation["status"] != "READY_TO_APPLY"`
9. falta `rollback_plan`
10. falta `patch` o `file_edits`

Despues de pasar esos guards:

1. Calcula `level = active_autonomy_level(store, settings)`.
2. Extrae targets desde `file_edits` o patch.
3. Valida rutas con `_validate_paths(...)`.
4. `_validate_paths(...)` llama a `path_violation(rel, level)`.
5. `path_violation(...)` aplica el suelo absoluto:
   - `ALWAYS_BLOCKED_EXACT={".env"}`
   - `ALWAYS_BLOCKED_PREFIXES` incluye `.git/`, `.venv/`, `data/`, `logs/`, `.github/`, `sandboxes/`, `src/agente_bolsa/kernel.py`, `src/agente_bolsa/tools/broker.py`, `src/agente_bolsa/tools/execution.py`, `src/agente_bolsa/tools/risk.py`, `src/agente_bolsa/config.py`.
6. Solo si rutas y AST pasan, aplica en sandbox/legacy y ejecuta tests.
7. Solo si la validacion pasa persiste `status="APPLIED"`.

### Ruta strategy_builder

Archivo: `src/agente_bolsa/continuous_improvement/strategy_builder.py`

1. `build_strategy_from_spec(...)` exige `CI_BUILD_STRATEGY_ENABLED=true`.
2. `StrategyBuilder.build(...)` pide al LLM `file_edits` y un test obligatorio bajo `tests/`.
3. Construye una propuesta `CODE_CHANGE` en `READY_TO_APPLY`.
4. Llama directamente a `AutoApplyCodeAgent.try_apply(...)`.

Esta ruta no pasa por el guard previo del runtime, pero si pasa por todos los guards internos de `AutoApplyCodeAgent`. Por tanto, con `ALLOW_AUTO_APPLY_IMPROVEMENTS=false` no puede acabar en `APPLIED`.

### Rutas API / CLI

- `continuous_improvement/api.py` usa `AutoApplyCodeAgent.rollback(...)` para rollback, no para aplicar.
- `main.py` expone rollback y estado; no encontre otra llamada a `try_apply(...)` fuera de runtime y `strategy_builder`.

## Tests anadidos

Archivo: `tests/test_continuous_improvement.py`

1. `test_runtime_keeps_ready_code_change_in_queue_when_autoapply_disabled`
   - Fuerza una validacion `READY_TO_APPLY`.
   - La propuesta tiene `guard.reason="autonomous_apply_enabled"`.
   - Configura `IMPROVEMENT_DRY_RUN=false` y `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
   - Sustituye el applier por uno que falla si se invoca.
   - Verifica:
     - propuesta sigue `READY_TO_APPLY`;
     - no se llama al applier;
     - `continuous_improvement_applied_changes` queda vacia.

2. `test_auto_apply_code_agent_blocks_when_human_review_required`
   - Configura `ALLOW_AUTO_APPLY_IMPROVEMENTS=true`, `IMPROVEMENT_DRY_RUN=false`, pero `REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=true`.
   - Verifica:
     - resultado `BLOCKED`;
     - error exacto `REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES=true`;
     - no hay `APPLIED`;
     - el archivo objetivo no cambia.

Archivo: `tests/test_autonomy_tiers.py`

3. `test_auto_apply_blocks_kernel_floor_paths_at_every_autonomy_level`
   - Parametriza niveles `1`, `2`, `3`.
   - Parametriza paths:
     - `src/agente_bolsa/kernel.py`
     - `src/agente_bolsa/tools/broker.py`
     - `src/agente_bolsa/tools/execution.py`
     - `src/agente_bolsa/tools/risk.py`
     - `src/agente_bolsa/config.py`
     - `.env`
   - Verifica que `AutoApplyCodeAgent.try_apply(...)` devuelve `BLOCKED` en todos los casos y que no escribe el archivo.

## Validacion

Comandos ejecutados:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_continuous_improvement.py::test_runtime_keeps_ready_code_change_in_queue_when_autoapply_disabled tests/test_continuous_improvement.py::test_auto_apply_code_agent_blocks_when_human_review_required tests/test_autonomy_tiers.py::test_auto_apply_blocks_kernel_floor_paths_at_every_autonomy_level -q
.\.venv\Scripts\python.exe -m pytest tests/ -x -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

Resultados:

- Tests focalizados: `20 passed`
- Suite completa: `802 passed, 1 warning`
- Ruff: `All checks passed`

## Cambios

- `tests/test_continuous_improvement.py`: tests del gate runtime y del bloqueo por revision humana requerida.
- `tests/test_autonomy_tiers.py`: test parametrizado del suelo de kernel en todos los niveles.
- `src/agente_bolsa/__init__.py`: `0.4.65` -> `0.4.66` para cumplir la politica de versionado del repo ante cambios en `tests/`.

No hubo restart porque no se cambio conducta runtime; solo se anadieron tests, informe y bump requerido por policy.
