# Informe Codex PL7 - gate preview con ruff - 2026-07-08

## Objetivo

Corregir la asimetria entre `gen-diff` y `approve` para propuestas `CODE_CHANGE`: el preview validaba con `pytest` pero el approve ejecutaba tambien `ruff`, lo que permitia dejar artefactos `READY_FOR_HUMAN_REVIEW` que luego caian en lint.

## Cambios aplicados

- `src/agente_bolsa/continuous_improvement/experiments.py`
  - `CodeDiffPreviewAgent._validation_steps()` ahora fuerza `ruff check src tests` antes de `full_pytest`, igual que el approve.
  - Si la propuesta ya trae un comando `ruff`, no se duplica.
- `tests/test_ci_sandbox.py`
  - Se verifica que el gate de preview inyecta `ruff` como primer paso obligatorio.
  - Nuevo test: un fallo de `ruff` devuelve `code_diff_preview_invalid` con `status=REJECTED_BY_TESTS`.
- `tests/test_ci_codegen.py`
  - Nuevo test del bucle de autocorreccion: un rechazo por `ruff` se reinyecta al modelo y provoca un segundo intento.
- `src/agente_bolsa/__init__.py`
  - Version: `0.4.128 -> 0.4.129`.

## Relanzamiento real de `ci_prop_b3f950033a99`

Estado previo observado:

- `review --proposal ci_prop_b3f950033a99` mostraba `ci_artifact_e88d21a8c5bf` como diff listo, pero era un preview generado sin el gate nuevo.
- La propuesta estaba en `REJECTED_BY_TESTS`, asi que se reabrió a `READY_TO_APPLY` solo para regenerar el preview con la validacion corregida.

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab gen-diff --proposal ci_prop_b3f950033a99 --json
```

Resultado real:

- No queda `READY_FOR_HUMAN_REVIEW`.
- El nuevo artefacto `ci_artifact_28f9fdcdc2ab` queda en `code_diff_preview_invalid`.
- Motivo: el modelo devolvio un diff sobre `src/` sin tocar `tests/`, asi que el gate determinista lo rechaza antes de promocionarlo.

Evidencia literal:

```json
{
  "ok": false,
  "status": "REJECTED_BY_GATE",
  "proposal_id": "ci_prop_b3f950033a99",
  "artifact": {
    "artifact_id": "ci_artifact_28f9fdcdc2ab",
    "artifact_type": "code_diff_preview_invalid",
    "payload": {
      "status": "REJECTED_BY_GATE",
      "tests_ok": false,
      "error": "new_code_requires_tests: el diff modifica src/ pero no toca tests/.",
      "gate_reason": "new_code_requires_tests",
      "target_paths": [
        "src/agente_bolsa/continuous_improvement/digest.py",
        "src/agente_bolsa/__init__.py"
      ]
    }
  }
}
```

Conclusión: con el gate nuevo activo ya no se puede dejar aprobable un preview que despues vaya a fallar por validacion incompleta. En este relanzamiento concreto, la propuesta no esta lista para Antonio porque ni siquiera supera el gate de tests del preview.

## Verificacion

Comandos ejecutados:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -x -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew
```

Resultados:

- `pytest`: `1009 passed, 1 warning`
- `ruff check src tests`: `All checks passed!`
- `status`: OK en paper, sin errores de configuracion operativa.
- `validate-agent-config --json`: `ok=true`, sin errores ni warnings.
- `run-once --skip-crew`: ciclo completado sin traceback.
