# Informe Codex PL6B - approve observabilidad - 2026-07-08

Diagnostico real de `ci_prop_b3f950033a99`:
- el `failed_test=` vacio no vino de un parser roto sobre `pytest`.
- ese rechazo de anoche no llego a `pytest`; fallo antes en `ruff`.
- artefacto inspeccionado: `ci_artifact_36f80d385101` (`code_diff_human_approval_rejected`).

Evidencia literal:
```text
UP015 [*] Unnecessary mode argument
   --> src\agente_bolsa\continuous_improvement\digest.py:968:34

E712 Avoid equality comparisons to `True`; use `lb.get("enabled"):` for truth checks
   --> tests\test_ci_phase3_digest.py:361:12

Found 2 errors.
```

Cambios:
- `src/agente_bolsa/continuous_improvement/human_apply.py`
  - mantiene `failed_test` para `pytest -x`
  - añade `failed_step` y `failure_subject`
  - si no hay test culpable pero si hay paso/lugar culpable, lo anade al error
- `src/agente_bolsa/main.py`
  - el CLI `approve` imprime `failed_test`, `failed_step` y `failure_subject`

Tests:
- parser cubierto para salida realista de `pytest -x`
- rechazo no-pytest cubierto con culpable de `ruff`
- `python -m pytest tests/test_ci_human_apply.py -q`
