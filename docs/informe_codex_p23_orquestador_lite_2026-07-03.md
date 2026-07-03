# Informe P23 - Orquestador-lite codegen nightly

Fecha: 2026-07-03

## Resultado

Implementado `continuous-improvement-lab codegen-nightly` como job aislado,
sin supervisor arrancado y sin apply automatico.

Comando documentado para Antonio:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab codegen-nightly --json
```

El job:

- selecciona solo propuestas `CODE_CHANGE` en `READY_TO_APPLY`;
- exige validacion/evidencia positiva;
- exige targets 100% dentro del allowlist de codegen;
- bloquea violaciones de self-safety/self-governance y agresividad sin edge;
- omite propuestas con fallos/rechazos previos de codegen o decisiones previas `REJECTED`/`REJECTED_BY_TESTS`/`BLOCKED`;
- ejecuta como maximo 2 `gen-diff` por dia;
- aplica presupuesto de tokens desde `data/config/codegen_nightly.json`;
- deja diffs validados como `READY_FOR_HUMAN_REVIEW`;
- registra intentos, exitos, fallos, omitidas y cola en el digest diario.

## Salvaguardas

- `ALLOW_AUTO_APPLY_IMPROVEMENTS != false` bloquea el nightly antes de generar diffs.
- `human_gated=false` en el fichero de cupos tambien bloquea el nightly.
- `data/config/codegen_nightly.json` queda fuera del allowlist de codegen, por lo que la firma no puede subirse su propio cupo.
- El codigo no llama a `approve_and_apply_code_diff`, `AutoApplyCodeAgent.apply` ni rutas equivalentes; el resultado incluye `approved_or_applied=false`.
- El digest no lista artefactos antiguos si la propuesta ya esta en estado terminal (`REJECTED`, `APPLIED`, `ROLLED_BACK`, etc.).

## Limpieza real

Ejecucion real usada para limpieza, sin LLM y sin generar diffs:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab codegen-nightly --config $env:TEMP\codegen_nightly_disabled.json --json
```

Resultado:

- `run_id`: `ci_codegen_nightly_13e1224f9983`
- `status`: `DISABLED`
- `attempts`: 0
- `successes`: 0
- `failures`: 0
- `approved_or_applied`: false
- demo `ci_prop_codegen_demo_51f112150ca0`: `REJECTED`, razon `demo_cleanup`
- P15 `ci_prop_p15_core_sleeve_null_order_digest`: coherente, `APPLIED` con referencia a commit `fa126d40`

Estados inconsistentes encontrados:

| Propuesta | Estado | Hallazgo | Recomendacion |
|---|---|---|---|
| `ci_prop_codegen_demo_51f112150ca0` | `REJECTED` | conserva un artefacto historico `code_diff_preview` `READY_FOR_HUMAN_REVIEW` | No aprobar; queda filtrado del digest por estado terminal. Mantener como evidencia historica o archivar artefacto en limpieza futura. |

No encontre otras propuestas codegen con cruces de estado accionables en la consulta auditada.

## Digest matinal

`continuous-improvement-lab digest --days 1 --json` muestra:

- `codegen_nightly.available=true`
- `codegen_nightly.status=DISABLED` para la ejecucion de limpieza
- `approval_requests=[]` despues de filtrar terminales
- bloque `Codegen nightly` en el markdown con intentos, exitos, fallos y tokens estimados

## Verificacion

Focal:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_codegen_nightly.py tests\test_ci_phase3_digest.py -q
```

Resultado: `17 passed`.

Lint focal:

```powershell
.\.venv\Scripts\python.exe -m ruff check src\agente_bolsa\continuous_improvement\codegen_nightly.py src\agente_bolsa\continuous_improvement\digest.py src\agente_bolsa\main.py tests\test_codegen_nightly.py
```

Resultado: `All checks passed!`.

Flags operativos comprobados:

- `trading_mode=paper`
- `allow_live_trading=false`
- `allow_auto_apply_improvements=false`
- `data/config/core_sleeve.json`: `dry_run=true`
- `data/config/lab_book.json`: `enabled=false`

Verificacion estandar completa:

- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q`: `921 passed, 1 warning`
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts`: `All checks passed!`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: OK, `trading_mode=paper`, `allow_live_trading=false`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`: `ok=true`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`: OK, ciclo `20260703-062811`

Version: `0.4.104`.

No se tocaron `src/agente_bolsa/kernel.py`, `src/agente_bolsa/tools/broker.py`,
`src/agente_bolsa/tools/execution.py`, `src/agente_bolsa/tools/risk.py`,
`src/agente_bolsa/config.py` ni `.env`.
