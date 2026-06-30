# Informe Codex - Constitucion anti-auto-sabotaje - 2026-06-30

## Objetivo

Se anadio una regla determinista, no LLM, para rechazar cualquier propuesta del
laboratorio de mejora continua que intente modificar sus propios controles de
seguridad antes de llegar a `READY_TO_APPLY`.

Motivo canonico de rechazo: `self_safety_modification_forbidden`.

## Denylist estructural

La regla inspecciona `target_component`, `target_identifier` y referencias
estructurales del `payload` como targets, settings, parametros, thresholds,
paths, `file_edits` y cabeceras de patch. No decide por narrativa libre del LLM.

Targets rechazados:

- `allow_auto_apply_improvements`
- `require_human_approval_for_code_changes`
- `ALLOW_LIVE_TRADING`
- `TRADING_MODE`
- suelo de kernel: `risk.py`, `kernel.py`, `tools/broker.py`,
  `tools/execution.py`, `config.py`, `.env`
- escala de autonomia: `autonomy.py`, `code_autonomy_level`
- `DETERMINISTIC_GATE`
- umbrales de gates de riesgo: `entry-quality`, `entry_quality`,
  `backtest_gate`, `backtest gate`, `risk_gate`

## Integracion antes de READY_TO_APPLY

La integracion tiene dos capas:

1. `RiskGuardAgent.assess` aplica `self_safety_modification_violation` al
   persistir nuevas propuestas. Si hay match, devuelve `status=REJECTED`,
   `approved_for_auto_apply=false` y anade el motivo
   `self_safety_modification_forbidden`.
2. `ValidationAgent.validate` repite la misma comprobacion al inicio de la
   validacion. Esto bloquea propuestas creadas por caminos antiguos, pruebas
   manuales o registros que ya estuvieran en cola antes del cambio.

El runtime pasa el payload bruto al `RiskGuard` para que tambien se inspeccionen
referencias de archivo que pydantic no conserva en el esquema canonico.

## Tests

Cobertura anadida o ajustada en `tests/test_continuous_improvement.py`:

- `test_risk_guard_rejects_self_safety_target_before_queue`: una propuesta hacia
  `allow_auto_apply_improvements` queda `REJECTED`.
- `test_validation_rejects_self_safety_payload_file_target`: un `file_edit` hacia
  `.env` queda `REJECTED`.
- `test_validation_rejects_protected_file_basename_target`: un target directo
  `risk.py` queda `REJECTED` aunque no venga con ruta completa.
- `test_validation_does_not_block_low_risk_docs_observability`: una propuesta
  normal de `docs/observabilidad` llega a `READY_TO_APPLY`.
- Pruebas antiguas de `entry_quality_filter` / `entry_quality_gate` actualizadas
  para esperar rechazo constitucional.

Verificacion ejecutada:

- `.\.venv\Scripts\ruff.exe check src tests` -> OK
- `python -m pytest tests/ -x -q` -> 819 passed

## Cola existente rechazada

Tras quedar verdes tests y ruff, se marco `REJECTED` toda propuesta activa que
apuntaba a la nueva denylist. Se uso actor `CodexSelfSafetyMigration` y razon
`self_safety_modification_forbidden`.

| proposal_id | estado anterior | target_component | target_identifier | match |
|---|---:|---|---|---|
| `ci_prop_3299bbd50843` | READY_TO_APPLY | `DETERMINISTIC_GATE` | `blocked_by_error_threshold` | `deterministic_gate` |
| `ci_prop_081090359395` | READY_TO_APPLY | `DETERMINISTIC_GATE` | `error_tolerance_threshold` | `deterministic_gate` |
| `ci_prop_a073c555f5b3` | READY_TO_APPLY | `settings` | `allow_auto_apply_improvements` | `allow_auto_apply_improvements` |
| `ci_prop_fd19d2cc10fa` | READY_TO_APPLY | `DETERMINISTIC_GATE` | `error_tolerance_threshold` | `deterministic_gate` |
| `ci_prop_8ec6df9615bd` | READY_TO_APPLY | `entry_quality_filter` | `shadow_entry_quality_threshold_review` | `entry_quality_filter` |
| `ci_prop_795a84a435bd` | PENDING | `DETERMINISTIC_GATE` | `gate_failure_logging` | `deterministic_gate` |
| `ci_prop_4d0607e6e32e` | PENDING | `DETERMINISTIC_GATE` |  | `deterministic_gate` |
| `ci_prop_5067133ee710` | PENDING | `DETERMINISTIC_GATE` | `observation_execution_bypass` | `deterministic_gate` |
| `ci_prop_f83a45e6ce9a` | PENDING | `DETERMINISTIC_GATE` | `proposal_validation_details` | `deterministic_gate` |

Verificacion posterior de cola activa: `active_self_safety_matches = 0`.

## Version

Version subida a `0.4.70` en `src/agente_bolsa/__init__.py`.

Restart operativo diferido: el suelo del kernel, el gate humano y esta regla del
lab ya bloquean nuevas promociones peligrosas; los procesos vivos recogeran el
cambio tras el proximo reinicio.
