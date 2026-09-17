# P-L120 — proveedor determinista de contrato de evidencia

## Dictamen

`ready_for_integration_rehearsal` (L1 de 4). No cambia trading, riesgo,
ejecucion, configuracion, datos historicos ni auto-apply.

## Causa y contrato

`contract_required_all=true` con proponentes LLM sin contrato: 100%
`proposal_contract_violation`. El proveedor reusa contratos ya medidos y
validados del puente `findings_to_proposals` y los adjunta por coincidencia
exacta de `target_identifier` solo a `CODE_CHANGE` en allowlist de bajo
riesgo. Lo no medible sigue rechazable; `null` nunca se convierte en cero.

## Cambios (v0.4.227)

- Nuevo `continuous_improvement/contract_builder.py`: `bridge_contracts_by_target`,
  `attach_bridge_contract`, `enrich_raws`. Sin red, sin LLM, sin escritura.
- `schemas.py`: `ExperimentContract` conserva `origin` e `improvement_direction`
  (antes se perdian en `model_validate` y todo contrato completo volvia a fallar).
- `runtime.py::_prepare_proposals`: adjunta contratos y publica
  `contract_attached`/`contract_unbuildable` en stats. No filtra ni reordena;
  el orden y limites existentes se conservan.

## QA

- Caracterizacion roja reproducida y verde tras el arreglo.
- Focales L1 + regresiones: `test_continuous_improvement` 82 passed,
  cast/proposal/findings/codegen verdes, version policy verde.
- Ruff completo verde, `check_no_nulls.py` verde, `git diff --check` verde.
- `validate-agent-config --json`: `ok=true`.
- `kernel-status --json` temporal: `unsealed` esperado, `violations=[]`.
- Smoke `run-once --skip-crew --quiet`: verde, `market_state_quality=PARTIAL`.
- Paridad: `kernel.py`, `broker.py`, `execution.py`, `risk.py`, `config.py`,
  `.env` identicos objeto-a-objeto a la base `e805217a`.

## Limites y siguiente

Solo `CODE_CHANGE` no-trading. Trading difiere a L3. Gobernanza intacta:
`contract_required_all` sigue `true`, `cast_governance.json` sin tocar,
cupos sin ampliar. Siguiente: L2 medicion Sistema vs SP500.
