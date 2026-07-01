# Informe Codex - Constitucion v2 - 2026-07-01

## Objetivo

Se extendio la constitucion del laboratorio para cubrir dos riesgos:

1. Autogobierno: el lab no puede modificar parametros que aceleren, relajen o
   reduzcan la supervision del propio lab.
2. Busywork: el lab no puede re-promover inmediatamente una idea ya rechazada.

## A - Self-governance denylist

Nuevo motivo canonico: `self_governance_modification_forbidden`.

La regla inspecciona referencias estructurales en `target_component`,
`target_identifier` y payloads de targets/settings/parametros/thresholds/paths.
No depende del LLM ni del texto persuasivo de la propuesta.

Targets cubiertos:

- `ci_recurring_cooldown_hours`
- `micro_experiment_size_multiplier`
- limites WIP del CI, como `ci_max_open_initiatives`
- `code_autonomy_level`
- cadencia del runtime CI: `continuous_improvement_runtime_interval_seconds`,
  `continuous_improvement_group_cooldown_seconds`,
  `continuous_improvement_event_cooldown_seconds`,
  `continuous_improvement_runtime_loop_sleep_seconds`
- supervision/autonomia del lab: `improvement_dry_run`,
  `allow_auto_apply_improvements`,
  `require_human_approval_for_code_changes`,
  sandbox CI y parametros equivalentes con prefijo `ci_`,
  `continuous_improvement_` o `improvement_` cuando controlan cooldown,
  intervalos, WIP, retries, schedule, sandbox, autonomia o supervision.

Distincion documentada: parametros de trading como `trade_selection_top_n` o
`min_llm_confidence_to_trade` no quedan prohibidos por esta regla. Siguen siendo
propuestas de trading que deben permanecer en cola humana y requerir evidencia de
edge, pero no son autogobierno del laboratorio.

## B - Dedup temporal anti-busywork

Nuevo motivo canonico: `recently_rejected_duplicate`.

Antes de insertar o reactivar una propuesta, el runtime consulta propuestas
`REJECTED` de los ultimos 7 dias. Si encuentra el mismo fingerprint o la misma
combinacion `initiative_key + target_component + target_identifier`, fuerza
`REJECTED`, desactiva cualquier auto-apply y deja una decision auditada con el
rechazo previo que causo el bloqueo.

## Integracion

- `RiskGuardAgent.assess` ahora devuelve `REJECTED` con
  `self_governance_modification_forbidden` para targets de autogobierno.
- `ValidationAgent.validate` repite la comprobacion al inicio, antes de cualquier
  seleccion de estado, para bloquear propuestas que ya estuvieran en cola o
  entren por caminos antiguos.
- `ContinuousImprovementLabRuntime._persist_proposals` aplica el dedup temporal
  antes de persistir/promover propuestas y audita el rechazo con
  `recently_rejected_duplicate`.

## Tests

Cobertura anadida o ajustada:

- `test_risk_guard_rejects_self_governance_cadence_target`: propuesta hacia
  `ci_recurring_cooldown_hours` queda `REJECTED`.
- `test_runtime_rejects_recently_rejected_duplicate`: re-propuesta con
  fingerprint rechazado recientemente queda `REJECTED` con
  `recently_rejected_duplicate`.
- `test_validation_does_not_block_low_risk_docs_observability`: docs normales no
  quedan afectados.
- `test_validation_does_not_block_trading_selection_parameter`:
  `trade_selection_top_n` no es rechazado por constitucion.

Verificacion ejecutada:

- `.\.venv\Scripts\ruff.exe check src tests` -> OK
- `python -m pytest tests/ -x -q` -> 822 passed

## Limpieza de cola

Tras quedar verdes ruff y pytest, se marcaron `REJECTED` las propuestas activas
de autogobierno existentes. Actor: `CodexSelfGovernanceMigration`. Razon:
`self_governance_modification_forbidden`.

| proposal_id | estado anterior | target_component | target_identifier | match |
|---|---:|---|---|---|
| `ci_prop_b592aabcf7f9` | READY_TO_APPLY | `settings` | `micro_experiment_size_multiplier` | `micro_experiment_size_multiplier` |
| `ci_prop_480ceed054c8` | READY_TO_APPLY | `settings` | `ci_recurring_cooldown_hours` | `ci_recurring_cooldown_hours` |
| `ci_prop_fbedb46fb046` | READY_TO_APPLY | `settings` | `allow_auto_apply_improvements` | `allow_auto_apply_improvements` |
| `ci_prop_22594059438f` | READY_TO_APPLY | `settings` | `allow_auto_apply_improvements` | `allow_auto_apply_improvements` |
| `ci_prop_6cf3b3baa20b` | READY_TO_APPLY | `settings` | `allow_auto_apply_improvements` | `allow_auto_apply_improvements` |
| `ci_prop_424d2c5a24da` | READY_TO_APPLY | `settings` | `allow_auto_apply_improvements` | `allow_auto_apply_improvements` |

Verificacion posterior:

- `active_self_governance_matches = 0`
- `trade_selection_top_n_active = 1`
- `ci_prop_4a759922e290` sigue en `READY_TO_APPLY` como decision humana/trading,
  no como autogobierno del lab.

## Version

Version subida a `0.4.71` en `src/agente_bolsa/__init__.py`.

Restart operativo diferido: auto-apply esta contenido por configuracion y gate
humano; los procesos vivos recogeran esta logica tras el siguiente reinicio.
