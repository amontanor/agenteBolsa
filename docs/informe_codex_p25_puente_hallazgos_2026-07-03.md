# Informe Codex P25 - Puente hallazgos a propuestas ejecutables

Fecha: 2026-07-03

## Cambios entregados

- Nuevo modulo `findings_to_proposals`:
  - lee hallazgos medidos de agenda/config, codegen nightly, tests existentes y calidad reciente de propuestas;
  - genera propuestas `CODE_CHANGE` con `target_files`, `test_requirement`, `test_commands`, evidencia citada y rollback;
  - limita a 3 propuestas por ejecucion;
  - dedupea por fingerprint contra propuestas existentes.
- Nuevo CLI:
  - `continuous-improvement-lab findings-to-proposals --json` para dry-run;
  - `continuous-improvement-lab findings-to-proposals --apply --settle-observations --json` para persistir y zanjar observaciones.
- Dedupe/settlement de la familia `observation_execution_*`, `micro_batch_execution_*` y variantes `micro-lotes`.

## Ejecucion real

Dry-run previo:

- Hallazgos medidos: `lab_book_config_present=1`, `overlay_shadow_tests_present=1`, `parity_script_present=1`, `ready_not_code_change=15`, `recent_prose_pct=88.5`.
- Auditoria de observaciones: 160 filas recientes, todas `source_family=closed_market_study`, `executed_buy=0`, `approved_buy=0`, `pending_or_immature_outcomes=160`, fechas `2026-07-02`.

Apply real:

- Creadas 3 propuestas `CODE_CHANGE` listas para nightly:
  - `ci_prop_b3f950033a99` -> `src/agente_bolsa/continuous_improvement/digest.py`
  - `ci_prop_0327e166f163` -> `tests/test_ci_digest_overlay_shadow.py`
  - `ci_prop_82a01dd92356` -> `tests/test_core_sleeve_parity_check.py`
- Verificacion de elegibilidad: `eligible_count=3`; targets coinciden con los 3 anteriores.

## Decision sobre observaciones

No he convertido las 160 observaciones en ejecucion por micro-lotes. Evidencia:

- No son ordenes pendientes ni observaciones ejecutables; son candidatos de `closed_market_study`.
- Las 160 tienen `executed_buy=0` y `approved_buy=0`.
- El outcome esta inmaduro por falta de barras posteriores (`pending_or_immature_outcomes=160`).
- Ejecutarlas artificialmente mezclaria semantica de investigacion con ejecucion y no aportaria senal valida.

Accion tomada: rechazar la familia activa completa con razon `observation_execution_family_rejected_not_actionable`.

IDs cerrados:

- `ci_prop_45cbdcaa97ef`
- `ci_prop_a4bdafd557e3`
- `ci_prop_8a82b446a551`
- `ci_prop_17f72bdc066b`
- `ci_prop_6d884bc7fe00`
- `ci_prop_4c6c76e3e77f`
- `ci_prop_71120d536576`

Los tres micro-batch pedidos (`ci_prop_4c6c76e3e77f`, `ci_prop_6d884bc7fe00`, `ci_prop_71120d536576`) quedaron `REJECTED`.

## Seguridad operativa

- `trading_mode=paper`
- `allow_live_trading=false`
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
- `data/config/core_sleeve.json`: `dry_run=true`
- No se tocaron los 6 ficheros del suelo de kernel.

## Verificacion

- `.venv\Scripts\python.exe -m pytest tests\ -x -q` -> `928 passed, 1 warning`.
- `.venv\Scripts\ruff.exe check src tests scripts` -> limpio.
- `validate-agent-config --json` -> `ok=true`, sin errores ni warnings.
- `status` -> operativo en paper.
