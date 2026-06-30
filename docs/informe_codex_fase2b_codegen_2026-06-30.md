# Informe Codex Fase 2B - codegen LLM a diff revisable

Fecha: 2026-06-30

## Objetivo

Anadir un entrypoint manual para convertir una propuesta `CODE_CHANGE` en un patch concreto generado por LLM, validarlo en `GitSandbox` y adjuntar el diff mas el resultado de tests como artefacto para revision humana.

No se cableo al loop residente. No se aplica nada al arbol real.

## Implementacion

- Nuevo modulo: `src/agente_bolsa/continuous_improvement/codegen.py`.
- Nuevo agente: `CodegenPatchAgent`.
- Nuevo CLI manual:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab gen-diff --proposal <id> --json
```

- Opcion de demo controlada:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab gen-diff --demo --json
```

Flujo:

1. Carga una propuesta `CODE_CHANGE` en `READY_TO_APPLY`.
2. Pide al LLM un JSON tipado con `file_edits` o `patch` y `test_commands`.
3. Valida el scope antes de abrir sandbox.
4. Sanitiza comandos de test: solo permite `python`, `pytest` o `ruff`; si el LLM propone otro comando, lo sustituye por un check Python sobre los archivos objetivo.
5. Encadena con `CodeDiffPreviewAgent`.
6. `CodeDiffPreviewAgent` aplica el payload solo en `GitSandbox`, genera `git diff --binary HEAD`, ejecuta tests y adjunta el artefacto en `continuous_improvement_proposal_artifacts`.

## Allowlist y bloqueos

El codegen usa un allowlist mas estrecho que la autonomia nivel 1 general:

- `src/agente_bolsa/continuous_improvement/`
- `src/agente_bolsa/tools/operational_`
- `tests/`
- `docs/`

Se rechaza antes de sandbox cualquier ruta fuera de ese scope. Ademas, el preview conserva las guardas existentes de suelo de kernel:

- `.env`
- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`

## Cambios de soporte

- `ImprovementLLMClient.generate_json(..., normalize_response=False)` permite usar schemas JSON especializados sin normalizarlos al formato de ciclo de mejora.
- El cliente LLM ya devuelve error controlado si el SDK/fallback lanza excepciones de red.
- `CodeDiffPreviewAgent` ahora muestra archivos nuevos en el diff con `git add -N .` dentro del worktree sandbox.
- `run_validation_steps` convierte comandos inexistentes en un paso de test fallido, preservando el diff como artefacto invalido.
- `apply_payload_to_worktree` soporta crear archivo nuevo con `{"old": "", "new": "..."}`.

## Demo real

No habia propuestas `CODE_CHANGE` reales en `READY_TO_APPLY`, asi que se creo una propuesta demo de bajo riesgo como permite la tarea:

- `proposal_id`: `ci_prop_codegen_demo_de3a43fac9bc`
- objetivo: `docs/ci_codegen_demo.md`
- modelo: `opencode-go / glm-5.2`
- `llm_call_id`: `ci_llm_b0e70acfa7c4`
- artefacto: `ci_artifact_d429292a2ce6`
- `artifact_type`: `code_diff_preview`
- estado: `READY_FOR_HUMAN_REVIEW`
- `tests_ok`: `true`
- `applied`: `false`

Diff generado y adjuntado:

```diff
diff --git a/docs/ci_codegen_demo.md b/docs/ci_codegen_demo.md
new file mode 100644
index 00000000..fa11af1a
--- /dev/null
+++ b/docs/ci_codegen_demo.md
@@ -0,0 +1,10 @@
+# CI Codegen Demo
+
+Este documento es un artefacto de demostracion de la cadena de generacion de diffs (LLM -> sandbox -> artefacto).
+
+- **proposal_id**: ci_prop_codegen_demo_de3a43fac9bc
+- **risk_level**: LOW
+- **reversible**: Si. Eliminar este archivo para revertir el cambio.
+- **impacto**: Ninguno sobre el runtime de trading.
+
+> Nota: Este archivo no afecta configuracion, ejecucion ni riesgo del sistema.
```

Verificaciones sobre la demo:

- `continuous_improvement_applied_changes`: 0.
- `docs/ci_codegen_demo.md` no existe en el working tree real.
- El cambio solo vivio en el worktree temporal de `GitSandbox`.
- El artefacto quedo persistido para revision humana.

## Tests

Anadidos:

- `tests/test_ci_codegen.py`
  - codegen -> preview produce `code_diff_preview` con diff y tests OK.
  - objetivo fuera del allowlist (`src/agente_bolsa/tools/risk.py`) se rechaza como `code_diff_codegen_blocked`.
  - `applied_changes` sigue vacio.
- `tests/test_ci_sandbox.py`
  - un comando de validacion inexistente queda como step fallido, no como excepcion que pierda el diff.
- `tests/test_continuous_improvement.py`
  - el cliente LLM puede parsear JSON especializado sin normalizarlo.

Verificacion final:

- `.\.venv\Scripts\python.exe -m ruff check src tests` -> OK.
- `.\.venv\Scripts\python.exe -m pytest tests/ -x -q` -> 810 passed, 1 warning.
- Sin restart.
- Version bump: `0.4.67` -> `0.4.68`.

## Veredicto

Si. La firma puede producir ahora un patch revisable desde una propuesta `CODE_CHANGE` de forma segura: entrypoint manual, LLM acotado por allowlist, aplicacion solo en `GitSandbox`, tests en sandbox, artefacto persistido para revision humana y `0` cambios aplicados.

Queda deliberadamente fuera de esta fase el cableado al loop residente y cualquier apply real.
