# Informe Codex Fase 2B-apply - revision y apply humano reversible

Fecha: 2026-06-30

## Objetivo

Anadir un camino manual, explicito y reversible para revisar diffs ya validados y aprobar su aplicacion con suite completa. No se conecta al loop residente y no debilita el bloqueo autonomo.

## Implementacion

Commit de implementacion:

- `3b03dfd8 feat: add human diff approval cli`

Nuevo modulo:

- `src/agente_bolsa/continuous_improvement/human_apply.py`

Nuevos comandos:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal <id> --json
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal <id> --actor <operador> --json
```

`review` es solo lectura: lista artefactos `code_diff_preview` con `status=READY_FOR_HUMAN_REVIEW` y `tests_ok=true`, mostrando diff, targets y validacion sandbox.

`approve` ejecuta esta cadena:

1. Busca la propuesta y su ultimo artefacto `code_diff_preview` valido.
2. Requiere `tests_ok=true`.
3. Requiere `ALLOW_LIVE_TRADING=false`.
4. Requiere `TRADING_MODE=paper`.
5. Requiere working tree limpio.
6. Revalida targets del diff contra suelo de kernel y allowlist humano.
7. Ejecuta backup de DB.
8. Aplica el diff con `git apply --index`.
9. Corre `ruff check src tests`.
10. Corre `pytest tests/ -x -q`.
11. Si todo pasa, crea commit git reversible.
12. Registra artefacto `code_diff_human_approval`.
13. Registra fila `continuous_improvement_applied_changes` con `status=APPLIED`.
14. Actualiza propuesta a `APPLIED`.

Si la aplicacion o la suite fallan, revierte el patch del working tree, restaura targets, marca `REJECTED_BY_TESTS` y no crea `applied_change`.

## Seguridad

El apply humano usa allowlist propia:

- `src/agente_bolsa/continuous_improvement/`
- `src/agente_bolsa/tools/operational_`
- `tests/`
- `docs/`

Suelo de kernel absoluto, tambien con aprobacion humana:

- `.env`
- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`

Estado operativo verificado tras la demo:

- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
- `ALLOW_LIVE_TRADING=false`
- `TRADING_MODE=paper`

La ruta autonoma sigue separada: el runtime residente no invoca `approve`, y los tests de invariante/autonomia siguen verdes.

## Tests

Anadidos en `tests/test_ci_human_apply.py`:

- `review` lista un diff listo sin cambiar estado.
- `approve` aplica un diff dentro del allowlist, crea commit y registra `applied_change`.
- `approve` rechaza `.env` y `src/agente_bolsa/tools/risk.py` aunque exista aprobacion humana.
- `approve` con suite fallida marca `REJECTED_BY_TESTS`, no crea `applied_change` y deja working tree limpio.

Verificacion antes de la demo real:

- `.\.venv\Scripts\python.exe -m ruff check src tests` -> OK.
- `.\.venv\Scripts\python.exe -m pytest tests/ -x -q` -> 815 passed, 1 warning.

## Demo real

Primero se ejecuto revision read-only:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_codegen_demo_de3a43fac9bc --json
```

Resultado:

- `count=1`
- diff artifact: `ci_artifact_d429292a2ce6`
- target: `docs/ci_codegen_demo.md`
- `tests_ok=true`
- `applied_changes=0` antes del apply

Despues se ejecuto aprobacion humana:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_codegen_demo_de3a43fac9bc --actor codex --json
```

Resultado:

- `status=APPLIED`
- applied change: `ci_applied_18703ab1d9a2`
- commit aplicado: `32ae00e3cb5d42588d30b47236f0e654702014e9`
- approval artifact: `ci_artifact_b65f82e6a0f8`
- backup DB: `data\backups\agente_bolsa_db_backup_human_apply_04c33d6ee126.sqlite3`
- backup report: `data\reports\database_backup_db_backup_human_apply_04c33d6ee126.json`
- suite en apply: `ruff` OK + `pytest` OK (`815 passed, 1 warning`)

Diff aplicado:

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

## Reversibilidad

Se probo la reversibilidad sin dejar el revert aplicado:

```powershell
git revert --no-commit 32ae00e3cb5d42588d30b47236f0e654702014e9
```

Resultado:

- exit code: `0`
- `git status --short`: `D  docs/ci_codegen_demo.md`
- `Test-Path docs\ci_codegen_demo.md`: `False`

Despues se limpio la prueba de revert restaurando desde `HEAD`:

```powershell
git restore --staged --worktree -- docs/ci_codegen_demo.md
```

Resultado final:

- `docs/ci_codegen_demo.md` vuelve a existir.
- working tree limpio antes de crear este informe.
- `continuous_improvement_applied_changes`: 1 fila.

## Veredicto

El hito queda completado: hay CLI de revision read-only y CLI de aprobacion humana que aplica un diff validado con backup, suite completa, commit reversible, approval artifact y `applied_change`.

El bloqueo autonomo sigue intacto: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false` no habilita ningun apply desde el runtime residente; la unica ruta nueva exige comando humano explicito.
