# Informe P11 - Apply humano robusto ante EOL/encoding

Fecha: 2026-07-02

## Resumen

El fallo del `approve` sobre `ci_artifact_dda66b200e41` se reprodujo. La causa principal no fue CRLF en los ficheros reales: ambos estaban en LF y UTF-8 limpio. El problema observable fue que el diff guardado en el artefacto contenia mojibake en una linea de contexto (`PIDE APROBACIÃ“N`) mientras el fichero real contenia UTF-8 correcto (`PIDE APROBACIÓN`).

Se corrigio el camino de apply humano y la generacion de diffs para Windows:

- `approve_and_apply_code_diff` prueba `git apply --index --3way`.
- Si falla, prueba `git apply --index --ignore-whitespace`.
- Si sigue fallando, repara mojibake UTF-8 decodificado como cp1252 y reintenta.
- El sandbox y el apply humano ahora invocan Git con `encoding="utf-8"` y `errors="replace"` para no depender de la locale de Windows.
- El artefacto P10 anterior se marco como `SUPERSEDED_BY_P11`; `review` lista solo el nuevo artefacto.

Version: `0.4.90`.

## Diagnostico previo

Comando:

```powershell
git apply --check -v --index --whitespace=nowarn data\tmp\ci_artifact_dda66b200e41.patch
```

Error reproducido:

```text
Checking patch src/agente_bolsa/continuous_improvement/digest.py...
Checking patch tests/test_ci_phase3_digest.py...
error: while searching for:

    assert text.splitlines()[-2] == "PIDE APROBACIÃ“N"
    assert text.splitlines()[-1] == "- No hay propuestas READY_FOR_HUMAN_REVIEW con tests_ok=true."

error: patch failed: tests/test_ci_phase3_digest.py:184
error: tests/test_ci_phase3_digest.py: patch does not apply
```

Evidencia:

```text
git config core.autocrlf = true
src/agente_bolsa/continuous_improvement/digest.py: i/lf w/lf
tests/test_ci_phase3_digest.py: i/lf w/lf
```

Bytes reales en `tests/test_ci_phase3_digest.py`:

```text
PIDE APROBACIÓN -> 50 49 44 45 ... 49 c3 93 4e
```

Bytes del patch rechazado:

```text
PIDE APROBACIÃ“N -> 50 49 44 45 ... 49 c3 83 e2 80 9c 4e
```

Conclusion: el fichero real no estaba doble-encodificado; el artefacto si tenia la linea de contexto mojibake. `--3way` e `--ignore-whitespace` no arreglaban ese artefacto sin reparar encoding.

## Por que el sandbox paso

El preview aplica primero el payload estructurado del LLM (`file_edits`) sobre un worktree y despues serializa el resultado con `git diff`. El apply humano no aplica ese payload estructurado: aplica el diff serializado del artefacto.

La asimetria estaba en la serializacion/lectura de salida Git en Windows: `subprocess.run(..., text=True)` sin `encoding` depende de la locale. Eso puede convertir bytes UTF-8 del diff en mojibake antes de guardarlos como `content_text`.

Solucion elegida: corregir ambos lados.

- Preview/sandbox: Git se decodifica explicitamente como UTF-8.
- Apply humano: Git se decodifica explicitamente como UTF-8 y, si recibe un artefacto historico mojibake, lo repara antes de rechazar.

## Tests nuevos

- Repo sintetico con fichero CRLF + diff LF: el apply humano aplica.
- Diff con contexto `PIDE APROBACIÃ“N` contra fichero UTF-8 limpio `PIDE APROBACIÓN`: el apply humano aplica con fallback.
- Unit test del reparador cp1252/UTF-8.

## Limpieza de mojibake

No se hizo commit aparte de limpieza porque no habia mojibake real en disco. Se verifico:

```text
src/agente_bolsa/continuous_improvement/digest.py: PIDE APROBACIÓN
tests/test_ci_phase3_digest.py: PIDE APROBACIÓN
```

## Reintento e2e

Se reactivo `ci_prop_p7_core_sleeve_digest` con `P11ManualCodegenGate` y se regenero el diff.

Nuevo artefacto:

```text
artifact_id=ci_artifact_9a6378dc448e
status=READY_FOR_HUMAN_REVIEW
tests_ok=true
target_paths=src/agente_bolsa/continuous_improvement/digest.py
```

El nuevo diff mantiene la semantica aprobada: lee `exposure` y muestra `decision.reason`, `decision.order.side`, `decision.order.notional`. Difiere materialmente del P10 en que no añade un test nuevo y conserva `decision` como dict interno en el digest en vez de aplanar `decision_reason`/`decision_order_*`; el texto renderizado sigue mostrando los campos solicitados.

Prueba obligatoria contra el arbol real:

```powershell
git apply --check -v --index --3way --whitespace=nowarn data\tmp\ci_artifact_9a6378dc448e.patch
```

Resultado:

```text
Checking patch src/agente_bolsa/continuous_improvement/digest.py...
Applied patch to 'src/agente_bolsa/continuous_improvement/digest.py' cleanly.
```

## Salida de review

```text
count=1
artifact_id=ci_artifact_9a6378dc448e
status=READY_FOR_HUMAN_REVIEW
tests_ok=true
target_paths=src/agente_bolsa/continuous_improvement/digest.py
```

Comandos para Antonio:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_p7_core_sleeve_digest
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_p7_core_sleeve_digest --actor Antonio
```

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q`: `887 passed, 1 warning`.
- `.\.venv\Scripts\ruff.exe check src tests scripts`: limpio.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: ok.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`: ok, 0 errores, 0 warnings.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`: ok, ciclo `20260702-125915`.

Flags confirmados:

```json
{
  "trading_mode": "paper",
  "allow_live_trading": false,
  "allow_auto_apply_improvements": false,
  "core_sleeve_dry_run": true
}
```

