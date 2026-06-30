# Informe Codex Fase 2A - diffs adjuntos sin aplicar

Fecha: 2026-06-30

## Objetivo

Implementar una capacidad de lab para que una propuesta `CODE_CHANGE` validada en `READY_TO_APPLY` genere un diff ejecutable en sandbox git, ejecute tests alli y adjunte el diff mas el resultado como artefacto para revision humana, sin aplicar nada al arbol real ni crear `applied_change`.

## Cambios realizados

- Se anadio `CodeDiffPreviewAgent` en `src/agente_bolsa/continuous_improvement/experiments.py`.
- Reutiliza el sandbox existente `GitSandbox` de `continuous_improvement/sandbox.py`; no se creo un sandbox nuevo.
- El flujo aplica `file_edits` o `patch` solo dentro del worktree sandbox mediante `apply_payload_to_worktree`.
- Genera el parche revisable con `git diff --binary HEAD` en el sandbox.
- Ejecuta tests con `GitSandbox.validate`. Si la propuesta trae `payload.test_commands`, esos comandos se usan como pasos de validacion y `python` se resuelve al interprete actual del venv.
- Adjunta el resultado en `continuous_improvement_proposal_artifacts`:
  - `code_diff_preview`: diff valido, tests OK, `status=READY_FOR_HUMAN_REVIEW`.
  - `code_diff_preview_invalid`: diff generado pero tests fallan, `status=REJECTED_BY_TESTS`.
  - `code_diff_preview_blocked`: propuesta rechazada antes de abrir sandbox por guardas.
  - `code_diff_preview_failed`: fallo operativo del preview, sin aplicar cambios.
- Se cableo el runtime residente para invocar el preview cuando una propuesta `CODE_CHANGE` queda en `READY_TO_APPLY` y no esta habilitada la ruta de auto-apply.
- El estado `READY_TO_APPLY` se conserva como cola humana cuando el diff queda listo o cuando el preview falla por causa operativa. Si el contenido queda bloqueado o los tests fallan, queda documentado con artefacto y motivo.

## Salvaguardas

- `ALLOW_AUTO_APPLY_IMPROVEMENTS` permanece en `false` en la configuracion actual.
- El preview no consulta el gate de auto-apply para generar evidencia, pero siempre guarda `applied=false` y nunca llama a `AutoApplyCodeAgent.try_apply`.
- No se escribe en el arbol real: el cambio se aplica solo en el worktree temporal del sandbox y este se destruye al terminar.
- No se crea ninguna fila en `continuous_improvement_applied_changes`.
- Se reutilizan las guardas de `AutoApplyCodeAgent`:
  - validacion por nivel de autonomia activo;
  - `path_violation` contra el suelo de kernel;
  - bloqueo de `.env`;
  - bloqueo de `src/agente_bolsa/kernel.py`;
  - bloqueo de `src/agente_bolsa/tools/broker.py`;
  - bloqueo de `src/agente_bolsa/tools/execution.py`;
  - bloqueo de `src/agente_bolsa/tools/risk.py`;
  - bloqueo de `src/agente_bolsa/config.py`;
  - guardia AST de imports prohibidos.
- Si el diff toca suelo de kernel, no se abre sandbox y se adjunta `code_diff_preview_blocked`.
- Si los tests del sandbox fallan, se adjunta `code_diff_preview_invalid` y no se promueve como diff valido.

## Tests anadidos

Archivo: `tests/test_ci_sandbox.py`

- `test_code_diff_preview_generates_artifact_without_applied_change`
  - Crea una propuesta `CODE_CHANGE` con `file_edits`.
  - Genera un artefacto `code_diff_preview`.
  - Verifica que el diff contiene el cambio esperado.
  - Verifica `tests_ok=true`.
  - Verifica que `continuous_improvement_applied_changes` sigue vacia.
  - Verifica que el archivo real del repo no cambia.

- `test_code_diff_preview_attaches_failed_tests_without_promotion`
  - Simula tests fallidos en sandbox.
  - Verifica artefacto `code_diff_preview_invalid`.
  - Verifica `status=REJECTED_BY_TESTS`.
  - Verifica que no se crea `applied_change` y el repo real queda intacto.

- `test_code_diff_preview_blocks_kernel_floor_without_worktree`
  - Parametrizado para `.env` y `src/agente_bolsa/tools/risk.py`.
  - Verifica artefacto `code_diff_preview_blocked`.
  - Verifica que no se crea worktree sandbox.
  - Verifica que no se crea `applied_change`.

Ademas, la suite existente `test_runtime_keeps_ready_code_change_in_queue_during_dry_run` confirma que una propuesta READY no se saca de la cola humana por un fallo operativo del preview.

## Verificacion

- `.\.venv\Scripts\python.exe -m ruff check src tests` -> OK.
- `.\.venv\Scripts\python.exe -m pytest tests/test_ci_sandbox.py -q` -> 14 passed.
- `.\.venv\Scripts\python.exe -m pytest tests/test_continuous_improvement.py::test_runtime_keeps_ready_code_change_in_queue_during_dry_run -q` -> 1 passed.
- `.\.venv\Scripts\python.exe -m pytest tests/ -x -q` -> 806 passed, 1 warning.
- `git diff --check` -> OK.
- Version bump: `src/agente_bolsa/__init__.py` de `0.4.66` a `0.4.67`.

No se hizo restart: la fase solo anade capacidad de lab y tests, sin cambio requerido de runtime de trading.

## Estado de BD real

Consulta en modo lectura sobre `data/state/agente_bolsa.sqlite3`:

- `continuous_improvement_proposals`: 1660 filas.
- `continuous_improvement_validations`: 1666 filas.
- `continuous_improvement_proposal_artifacts`: 167 filas.
- `continuous_improvement_applied_changes`: 0 filas.
- `CODE_CHANGE` por estado:
  - `REJECTED`: 109.
  - `PENDING`: 8.
  - `READY_TO_APPLY`: 0.
- Artefactos `code_diff_preview%`: 0.

No se genero un artefacto sobre la BD real porque no habia ninguna propuesta `CODE_CHANGE` real en `READY_TO_APPLY` durante la verificacion. Forzar una propuesta real habria contaminado la cola del lab; por eso el ejemplo verificado queda en test aislado con Store temporal.

## Ejemplo de diff generado

Ejemplo real generado por `test_code_diff_preview_generates_artifact_without_applied_change` en un repo git temporal:

```diff
diff --git a/docs/base.md b/docs/base.md
--- a/docs/base.md
+++ b/docs/base.md
@@
 base
+preview
```

Resultado adjunto:

```json
{
  "artifact_type": "code_diff_preview",
  "payload": {
    "status": "READY_FOR_HUMAN_REVIEW",
    "tests_ok": true,
    "applied": false
  }
}
```

## Veredicto

La Fase 2A queda implementada para propuestas `CODE_CHANGE` ejecutables que ya lleguen a `READY_TO_APPLY`: se genera diff en sandbox, se ejecutan tests, se adjunta evidencia para revision humana y no se aplica nada al arbol real.

El siguiente bloqueo real no esta en el generador de diff, sino en la cola: ahora mismo no hay propuestas `CODE_CHANGE` reales en `READY_TO_APPLY`. La siguiente fase operativa debe alimentar esa cola con propuestas ejecutables y validadas, o promover una candidata concreta de forma humana para probar el preview sobre datos reales del lab.
