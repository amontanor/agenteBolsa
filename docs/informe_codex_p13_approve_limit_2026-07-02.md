# Informe Codex P13 - approve limit-before-filter

Fecha: 2026-07-02

## Cambio

Se corrigio `_latest_ready_diff_artifact()` en
`src/agente_bolsa/continuous_improvement/human_apply.py`.

Antes pedia `_diff_artifacts(limit=1)`. Como `_diff_artifacts()` ordena por
`updated_at DESC` en SQL y filtra despues en Python por:

- `status=READY_FOR_HUMAN_REVIEW`
- `tests_ok=true`

un artefacto rechazado mas reciente podia ocupar la unica fila recuperada y dejar
fuera al artefacto valido anterior.

Ahora `_latest_ready_diff_artifact()` recupera un lote razonable (`limit=20`) y
devuelve el primer artefacto que supera el filtro existente.

## Regresion

Se anadio `test_human_approve_skips_newer_rejected_preview_and_applies_previous_ready`.

Escenario cubierto:

- propuesta con dos artefactos `code_diff_preview`;
- el mas reciente esta `REJECTED_BY_HUMAN_REVIEW`, `tests_ok=false`;
- el anterior esta `READY_FOR_HUMAN_REVIEW`, `tests_ok=true`;
- `approve_and_apply_code_diff()` selecciona el anterior y llega a apply.

Validacion focal:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ci_human_apply.py -q
# 9 passed

.\.venv\Scripts\ruff.exe check src\agente_bolsa\continuous_improvement\human_apply.py tests\test_ci_human_apply.py src\agente_bolsa\__init__.py
# All checks passed
```

## Comprobacion real de BD

Consulta solo lectura tras el fix:

```json
{
  "artifact_id": "ci_artifact_dda66b200e41",
  "status": "READY_FOR_HUMAN_REVIEW",
  "tests_ok": true,
  "target_paths": [
    "src/agente_bolsa/continuous_improvement/digest.py",
    "tests/test_ci_phase3_digest.py"
  ]
}
```

No se ejecuto `approve` real.

## Verificacion final

Version: `0.4.92`.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
# 890 passed, 1 warning

.\.venv\Scripts\ruff.exe check src tests scripts
# All checks passed

.\.venv\Scripts\python.exe -m agente_bolsa.main status
# trading_mode=paper; allow_live_trading=false

.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
# ok=true; errors=[]; warnings=[]

.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew
# cycle_id=20260702-170606; used_crew=false; market_state_quality=PARTIAL
```

Flags confirmados:

```json
{
  "trading_mode": "paper",
  "allow_live_trading": false,
  "allow_auto_apply_improvements": false
}
```

No se tocaron los ficheros protegidos:

- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`
- `.env`
