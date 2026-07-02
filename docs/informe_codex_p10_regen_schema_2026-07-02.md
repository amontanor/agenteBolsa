# Informe P10 - Regeneracion con esquema real core sleeve

Fecha: 2026-07-02

## Resumen

Se rechazo el artefacto anterior `ci_artifact_259b18101111` porque leia campos inventados (`target_exposure`, `hypothetical_order`) que no existen en el productor real `strategies/core_sleeve.py`. La propuesta `ci_prop_p7_core_sleeve_digest` se actualizo con el contrato real del log y se regenero el diff con la maquinaria de autocorreccion de P9.

Resultado final: nuevo artefacto `ci_artifact_dda66b200e41` en `READY_FOR_HUMAN_REVIEW`, `tests_ok=true`.

Version: `0.4.89`.

## Acciones realizadas

1. Artefacto rechazado:
   - `ci_artifact_259b18101111`
   - nuevo payload: `status=REJECTED_BY_HUMAN_REVIEW`, `tests_ok=false`
   - decision registrada: `rejected_by_human_review`
   - razon: `schema_mismatch_with_real_producer`
   - actor: `Responsable`
   - `review --proposal ci_prop_p7_core_sleeve_digest` ya no lo lista.

2. Spec corregida:
   - contrato real incluido en payload como `schema_contract_real_line`
   - campos exigidos:
     - `data_date`
     - `status`
     - `exposure`
     - `decision.reason`
     - `decision.order.side`
     - `decision.order.notional`
   - si `decision` es null, mostrar solo `status`
   - advertencia si el registro tiene mas de 3 sesiones de mercado.

3. Mejora sistemica:
   - `CodegenPatchAgent` ahora detecta rutas `data/...` en la propuesta y adjunta `data_samples` con primeras/ultimas lineas reales del fichero si existe.
   - El contexto es de solo lectura y no amplia el allowlist de edicion.
   - Se anadio test para confirmar que `data/research/core_sleeve/core_sleeve_log.jsonl` entra como muestra real y no inventa `target_exposure`.
   - `CodegenPatchResponse` acepta `patch: null` normalizandolo a cadena vacia.
   - El prompt exige modificar `target_identifier`; generar solo tests no satisface la propuesta.

## Reintentos gen-diff

Intento 1:

```text
artifact=ci_artifact_f5019ffaeb9f
status=FAILED
error=patch null no validaba como string en CodegenPatchResponse
```

Fix aplicado: normalizar `patch=None` a `""`.

Intento 2:

```text
artifact=ci_artifact_250a1ceb4658
status=REJECTED_BY_TESTS
error=el modelo genero solo tests; faltaba latest_core_sleeve_signal en digest.py
```

Fix aplicado: prompt y payload obligan a modificar `src/agente_bolsa/continuous_improvement/digest.py`.

Intento 3:

```text
artifact=ci_artifact_dda66b200e41
status=READY_FOR_HUMAN_REVIEW
tests_ok=true
sandbox_change_id=ci_diff_88a6fabb7680
target_paths=src/agente_bolsa/continuous_improvement/digest.py, tests/test_ci_phase3_digest.py
```

## Salida de review

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_p7_core_sleeve_digest --json
```

Resultado:

```text
count=1
artifact_id=ci_artifact_dda66b200e41
status=READY_FOR_HUMAN_REVIEW
tests_ok=true
target_paths=src/agente_bolsa/continuous_improvement/digest.py, tests/test_ci_phase3_digest.py
```

Resumen del diff nuevo:

```diff
+        "core_sleeve": latest_core_sleeve_signal(data_dir, now=now),
+def latest_core_sleeve_signal(data_dir: Path, *, now: datetime | None = None) -> dict[str, Any]:
+        "status": latest.get("status"),
+        "exposure": latest.get("exposure"),
+        "decision_reason": (decision.get("reason") if decision else None),
+        "decision_order_side": (decision.get("order", {}).get("side") if decision else None),
+        "decision_order_notional": (decision.get("order", {}).get("notional") if decision else None),
+                f"- exposure: {_none_text(core_sleeve.get('exposure'))}",
+            lines.append(f"- decision.reason: {decision_reason}")
+            lines.append(f"- decision.order.side: {_none_text(decision_order_side)}")
+            lines.append(f"- decision.order.notional: {_none_text(decision_order_notional)}")
```

El test generado en el artefacto usa lineas reales de `data/research/core_sleeve/core_sleeve_log.jsonl`, incluyendo `exposure`, `decision.reason`, `decision.order.side` y `decision.order.notional`.

## Comandos para revision humana

Revisar:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_p7_core_sleeve_digest
```

Aprobar si el diff es correcto:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab approve --proposal ci_prop_p7_core_sleeve_digest --actor Antonio
```

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q`: `884 passed, 1 warning`.
- `.\.venv\Scripts\ruff.exe check src tests scripts`: limpio.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: ok, `trading_mode=paper`, `allow_live_trading=false`.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`: ok, 0 errores, 0 warnings.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`: ok, ciclo `20260702-124257`.

Flags confirmados:

```json
{
  "trading_mode": "paper",
  "allow_live_trading": false,
  "allow_auto_apply_improvements": false,
  "core_sleeve_dry_run": true
}
```

