# Informe Codex P12 - gate de tests para codigo nuevo

Fecha: 2026-07-02

## Resumen

P12 queda cerrado con dos cambios:

1. `CodeDiffPreviewAgent` rechaza de forma determinista un diff que modifica `src/`
   cuando la propuesta declara `test_requirement` o el diff introduce funciones
   nuevas y no toca tambien un fichero en `tests/` ejecutado por `test_commands`.
   El estado del artefacto pasa a `REJECTED_BY_GATE` con razon estable
   `new_code_requires_tests`.
2. El artefacto P11 `ci_artifact_9a6378dc448e` se marco como rechazado por revision
   humana (`new_code_without_tests`, actor `Responsable`) y se restauro el artefacto
   P10 `ci_artifact_dda66b200e41` como unico `READY_FOR_HUMAN_REVIEW`.

No se ejecuto `approve`.

## Gate determinista

La compuerta nueva se ejecuta despues de generar el diff en sandbox y antes de
marcarlo como listo para revision humana.

Regla aplicada:

- Si el diff toca `src/` y existe `test_requirement`, el diff debe tocar `tests/`.
- Si el diff toca `src/` e introduce una funcion nueva (`def` o `async def`), el
  diff debe tocar `tests/`.
- Al menos uno de los ficheros de test tocados debe aparecer explicitamente en
  `test_commands`.

Si falla, el artefacto queda:

```text
artifact_type=code_diff_preview_invalid
status=REJECTED_BY_GATE
tests_ok=false
gate_reason=new_code_requires_tests
```

Tests añadidos:

- `test_code_diff_preview_rejects_src_change_with_test_requirement_without_test_file`
- `test_code_diff_preview_accepts_src_change_when_touched_test_file_is_executed`

Validacion focal:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ci_sandbox.py -q
# 17 passed

.\.venv\Scripts\ruff.exe check src\agente_bolsa\continuous_improvement\experiments.py tests\test_ci_sandbox.py
# All checks passed
```

## Restauracion del artefacto P10

Se reparo el diff de `ci_artifact_dda66b200e41` con el normalizador de mojibake de
P11. El patch reparado cambia:

- `src/agente_bolsa/continuous_improvement/digest.py`
- `tests/test_ci_phase3_digest.py`

El test restaurado cubre `latest_core_sleeve_signal` con lineas reales del log,
incluyendo la linea:

```text
2026-07-02T11:12:06.753314+00:00
```

Apply check contra el arbol real:

```powershell
git apply --check -v --index --3way --whitespace=nowarn data\tmp\ci_artifact_dda66b200e41.repaired.patch
```

Resultado:

```text
Checking patch src/agente_bolsa/continuous_improvement/digest.py...
Applied patch to 'src/agente_bolsa/continuous_improvement/digest.py' cleanly.
Checking patch tests/test_ci_phase3_digest.py...
Applied patch to 'tests/test_ci_phase3_digest.py' cleanly.
```

Revalidacion sandbox:

La aplicacion simple del patch en el worktree sandbox fallo por diferencia de EOL
derivada de `core.autocrlf=true`. La revalidacion uso el fallback robusto:

```powershell
git apply --index --ignore-whitespace --whitespace=nowarn
```

Tests ejecutados en sandbox:

```powershell
python -m pytest tests/test_ci_phase3_digest.py -q
# 5 passed

python -m pytest tests/test_ci_phase3_digest.py tests/test_ci_digest_p4.py tests/test_ci_codegen.py -q
# 15 passed
```

La decision auditable registrada fue `restored_after_apply_fix`.

## Estado de review

Salida resumida tras la restauracion:

```json
{
  "ok": true,
  "count": 1,
  "artifacts": [
    {
      "artifact_id": "ci_artifact_dda66b200e41",
      "status": "READY_FOR_HUMAN_REVIEW",
      "tests_ok": true,
      "target_paths": [
        "src/agente_bolsa/continuous_improvement/digest.py",
        "tests/test_ci_phase3_digest.py"
      ],
      "has_latest_core_sleeve_signal_test": true,
      "has_real_log_line": true
    }
  ]
}
```

Comandos para Antonio:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_p7_core_sleeve_digest
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_p7_core_sleeve_digest --actor Antonio
```

## Seguridad operacional

Flags confirmados:

```json
{
  "trading_mode": "paper",
  "allow_live_trading": false,
  "allow_auto_apply_improvements": false,
  "core_sleeve_path": "data\\config\\core_sleeve.json",
  "core_sleeve_dry_run": true
}
```

No se tocaron los ficheros protegidos del suelo de kernel:

- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`
- `.env`

## Verificacion final

Version: `0.4.91`.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
# 889 passed, 1 warning

.\.venv\Scripts\ruff.exe check src tests scripts
# All checks passed

.\.venv\Scripts\python.exe -m agente_bolsa.main status
# trading_mode=paper; allow_live_trading=false

.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
# ok=true; errors=[]; warnings=[]

.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew
# cycle_id=20260702-132024; used_crew=false; market_state_quality=PARTIAL
```

El check final del artefacto restaurado contra el arbol real tambien paso:

```powershell
git apply --check -v --index --3way --whitespace=nowarn data\tmp\ci_artifact_dda66b200e41.repaired.patch
# digest.py y tests/test_ci_phase3_digest.py aplican limpio
```
