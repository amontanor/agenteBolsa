# Informe Codex PL6A - catch-up supervisores - 2026-07-08

Cambios:
- `scripts/stack_common.ps1`: helper comun `Get-StackRunSchedule` + `Test-StackDailyCatchUpNeeded`.
- Supervisores diarios actualizados: `run_ci_digest_supervisor.ps1`, `run_overlay_shadow_supervisor.ps1`, `run_codegen_nightly_supervisor.ps1`, `run_core_sleeve_supervisor.ps1`, `run_telegram_radar_supervisor.ps1`.
- Al arrancar, si la hora `RunAt` de hoy ya paso y falta el artefacto natural del dia, el supervisor ejecuta un one-shot inmediato antes de programar `NEXT_RUN`.

Marcadores usados:
- digest: `data/reports/ci_digest_<fecha>.md`
- overlay: `data/research/overlay_shadow/overlay_shadow_<fecha>.json`
- codegen nightly: entrada del dia en `data/research/codegen_nightly/runs.jsonl`
- core sleeve: `data/research/core_sleeve/parity_<fecha>.md`
- telegram radar: `data/research/telegram/reports/radar_<fecha>.md`

Verificacion:
- `python -m pytest tests/test_stack_common_supervisor.py tests/test_ci_phase3_digest.py tests/test_config_audit.py -q`
- `ruff check src tests scripts`

Ejecucion real:
- generado `data/reports/ci_digest_2026-07-08.md`
- linea Safety verificada:
  `Safety: OK | learning_mode=ON, shadow_first=False, authorized_by=Antonio 2026-07-07`
- encabezado verificado en UTF-8 limpio:
  `PIDE APROBACIÓN`
