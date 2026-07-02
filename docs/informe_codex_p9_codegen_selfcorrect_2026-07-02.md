# Informe P9 - Codegen con autocorreccion acotada

Fecha: 2026-07-02

## Resumen

Se reforzo `CodegenPatchAgent` para que entregue parches aplicables y auditables:

- El contexto del target ya no se recorta silenciosamente: ficheros <=800 lineas se envian completos con metadatos `lines/chars/truncated`.
- Cada payload crudo generado por el LLM se guarda como artefacto `code_diff_attempt`.
- Si sandbox falla por aplicacion de patch o por validacion, el agente puede reenviar error literal + contexto real y pedir una correccion. Maximo: 2 correcciones internas.
- El prompt exige que `old` se copie VERBATIM, sea corto y unico; para ficheros nuevos o existentes <300 lineas se permite `{path, content}`.
- CODEGEN sube a minimo 32000 tokens por el aumento de contexto completo.

Version: `0.4.88`.

## Diagnostico de contexto

Fallo P7 original: `ci_artifact_f099eb2d1e34`, `ValueError: No se encontro bloque old en src/agente_bolsa/continuous_improvement/digest.py`.

Antes de P9, `_context_files()` enviaba `text[:12000]` por fichero. El target real habia crecido por encima de ese limite, asi que el modelo recibia una version truncada sin metadatos.

Contexto medido en P9 antes del reintento:

```text
messages=2
system_chars=765
user_chars=39724
digest.py: lines=713 chars=29765 truncated=false
tests/test_ci_phase3_digest.py: lines=186 chars=6549 truncated=false
```

Conclusion: P9 corrige el problema original de contexto parcial. En el intento real tambien se observo que el contexto completo requirio mas presupuesto de salida: el primer reintento con 16000 tokens volvio a truncar.

## Cambios tecnicos

Archivos modificados:

- `src/agente_bolsa/continuous_improvement/codegen.py`
  - `CODEGEN_SELF_CORRECTION_ROUNDS = 2`
  - `CODEGEN_FULL_CONTEXT_MAX_LINES = 800`
  - `CODEGEN_FULL_CONTENT_MAX_LINES = 300`
  - `CODEGEN_MIN_MAX_TOKENS = 32000`
  - artefactos `code_diff_attempt`
  - correccion con error literal, respuesta previa y contexto real
- `tests/test_ci_codegen.py`
  - autocorreccion: primer patch invalido + correccion valida
  - agotamiento: 2 correcciones fallidas
  - fichero nuevo por contenido completo
  - contexto completo del target sin truncado silencioso
- `src/agente_bolsa/__init__.py`
  - version `0.4.88`

## Reintento e2e real

Propuesta: `ci_prop_p7_core_sleeve_digest`.

Objetivo: seccion `Core sleeve` del digest, leyendo `data/research/core_sleeve/core_sleeve_log.jsonl`, ultima decision, status, exposicion objetivo, orden hipotetica y advertencia si hay mas de 3 sesiones de mercado sin registro.

Se reactivo desde `VALIDATING` a `READY_TO_APPLY` con `P9ManualCodegenGate`, `no_auto_apply=true`.

Intento P9-1:

```text
artifact=ci_artifact_2375c8206877
type=code_diff_codegen_failed
model=deepseek-v4-flash
error=primary_error=llm_response_truncated: finish_reason=length content_chars=3202 reasoning_chars=59017 | local_fallback_error=fallback local no disponible en 127.0.0.1:8080 (esperado si el servidor local no esta arrancado)
```

Accion: subir CODEGEN a 32000 tokens e instruir salida directa/compacta.

Intento P9-2:

```text
attempt=ci_artifact_19f1ca84c3f7
preview=ci_artifact_ad6aa8141faf
status=REJECTED_BY_TESTS
motivo=test_core_sleeve_section_stale_warning fallo porque el test generado escribia JSON invalido con None dentro de una cadena.
```

Accion: ampliar autocorreccion a fallos de validacion del sandbox, no solo a fallos de aplicacion.

Intento P9-3:

```text
attempt=ci_artifact_759e38e59eb1
preview=ci_artifact_259b18101111
status=READY_FOR_HUMAN_REVIEW
tests_ok=true
sandbox_change_id=ci_diff_a20189293667
target_paths=src/agente_bolsa/continuous_improvement/digest.py, tests/test_core_sleeve_digest.py
```

Validacion del sandbox del artefacto final:

```text
tests/test_core_sleeve_digest.py::test_latest_core_sleeve_signal_returns_not_available_when_file_missing PASSED
tests/test_core_sleeve_digest.py::test_latest_core_sleeve_signal_parses_valid_log PASSED
tests/test_core_sleeve_digest.py::test_latest_core_sleeve_signal_detects_stale_data PASSED
tests/test_core_sleeve_digest.py::test_digest_includes_core_sleeve_section_in_markdown PASSED
tests/test_core_sleeve_digest.py::test_digest_shows_warning_when_core_sleeve_stale PASSED
5 passed
```

## Comandos para Antonio

Revisar diff:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_p7_core_sleeve_digest
```

Aprobar y aplicar si el diff es correcto:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_p7_core_sleeve_digest --actor Antonio
```

El comando `approve` aplicara el artefacto `code_diff_preview`, correra la validacion completa del flujo de aprobacion humana y creara el commit reversible correspondiente.

## Verificacion local P9

- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q`: `882 passed, 1 warning`.
- `.\.venv\Scripts\ruff.exe check src tests scripts`: limpio.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: ok, `trading_mode=paper`, `allow_live_trading=false`.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`: ok, 0 errores, 0 warnings.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`: ok, ciclo `20260702-121930`.

Flags confirmados:

```json
{
  "trading_mode": "paper",
  "allow_live_trading": false,
  "allow_auto_apply_improvements": false,
  "core_sleeve_dry_run": true
}
```

## Riesgo residual

El diff generado por la firma esta listo para revision humana, pero todavia no se ha aplicado al arbol real. La decision de aprobarlo queda para Antonio mediante los comandos anteriores.

