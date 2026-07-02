# Informe Codex P6 - Firma e2e y fix CLI

Fecha: 2026-07-02

## Resumen

- Se sembro una propuesta real CODE_CHANGE para que la firma agregara "Overlay shadow" al digest diario.
- Se intento `continuous-improvement-lab gen-diff` tres veces.
- Los tres intentos fallaron igual; no quedo artefacto `READY_FOR_HUMAN_REVIEW`.
- Siguiendo el prompt, el cambio del digest se aplico como fallback directo de Codex.
- Se registro el comando CLI directo `validate-agent-config --json`.
- Version P6: `0.4.86`.

## Propuesta sembrada

- `proposal_id`: `ci_prop_p6_overlay_shadow_digest`
- Tipo: `CODE_CHANGE`
- Target: `src/agente_bolsa/continuous_improvement/digest.py`
- Objetivo: agregar al digest diario la ultima senal de `data/research/overlay_shadow/overlay_shadow_log.jsonl`.

## Intentos de la firma

Comando ejecutado tres veces:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab gen-diff --proposal ci_prop_p6_overlay_shadow_digest --json
```

Resultados literales:

1. `ci_artifact_0b281b0ed4c5`
   - `primary_error=LLM response without text content | local_fallback_error=Connection error.`
   - `llm_call_id=ci_llm_1973acc2de16`
   - `provider=opencode-go`
   - `model=glm-5.2`

2. `ci_artifact_86bf85da4811`
   - `primary_error=LLM response without text content | local_fallback_error=Connection error.`
   - `llm_call_id=ci_llm_9f73ce32e9f4`
   - `provider=opencode-go`
   - `model=glm-5.2`

3. `ci_artifact_4f417f0df834`
   - `primary_error=LLM response without text content | local_fallback_error=Connection error.`
   - `llm_call_id=ci_llm_87520d4a0482`
   - `provider=opencode-go`
   - `model=glm-5.2`

Revision humana de la propuesta:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_p6_overlay_shadow_digest --json
```

Resultado: `count=0`, sin artefactos listos. Por tanto no hay comando `approve` valido para esta propuesta.

## Fallback aplicado por Codex

Cambios:

- `build_lab_digest(..., data_dir=...)` ahora incluye `overlay_shadow`.
- `format_lab_digest_text` renderiza seccion "Overlay shadow".
- Lee la ultima linea JSON valida de `data/research/overlay_shadow/overlay_shadow_log.jsonl`.
- Muestra `data_date`, volatilidad realizada, VT10, VT12 y SMA200.
- Marca advertencia si la senal tiene mas de 3 sesiones de mercado.
- Tests sintéticos en `tests/test_ci_digest_overlay_shadow.py`.

No se forzo una ejecucion real del digest con esta seccion porque el flujo de la firma no produjo diff aprobable por Antonio.

## Fix CLI directo

Se registro:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
```

Resultado real:

- `ok=true`
- `errors=[]`
- `warnings=[]`
- `agents=23`
- `tasks=6`

Test: `tests/test_cli_validate_agent_config.py`.

## Cola READY_TO_APPLY readonly

Estado leido tras el saneo P4, sin modificar estados:

| Propuesta | Target | Evidencia enlazada | Recomendacion |
|---|---|---:|---|
| `ci_prop_p6_overlay_shadow_digest` | `continuous_improvement/src/agente_bolsa/continuous_improvement/digest.py` | no | Rechazar/cerrar: codegen fallo 3 veces y el fallback ya cubre el cambio. |
| `ci_prop_712ea5e73d18` | `risk_manager/ci_prop_862f4196e8a3` | no | Rechazar: depende de propuesta de gobierno ya rechazada. |
| `ci_prop_4c6c76e3e77f` | `OBSERVATION_SCHEDULER/micro_batch_execution_v2` | no | Mantener/revisar manual: no toca broker, pero requiere especificacion ejecutable. |
| `ci_prop_08f79290fec2` | `continuous_improvement/ci_prop_ext_002` | no | Rechazar si es duplicada/prosa; no hay evidencia accionable. |
| `ci_prop_d952ddf82197` | `continuous_improvement/ci_prop_ext_001` | no | Rechazar si es duplicada/prosa; no hay evidencia accionable. |
| `ci_prop_6d884bc7fe00` | `OBSERVATION_SCHEDULER/micro_batch_execution_v2` | no | Mantener solo si se convierte a patch/test concreto; si no, rechazar. |
| `ci_prop_9688d540359c` | `OBSERVATION_SCHEDULER/` | no | Rechazar: target incompleto. |
| `ci_prop_71120d536576` | `continuous_improvement/Ejecucion Segura de Observaciones en Micro-Lotes` | no | Mantener para revision humana si se transforma en diff acotado; no auto-aplicar. |

## Verificacion P6

- Tests focalizados: `7 passed`.
- Suite completa: `875 passed, 1 warning`.
- Lint: `ruff check src tests scripts` limpio.
- `status`: OK, `trading_mode=paper`, `allow_live_trading=false`.
- `validate-agent-config --json`: OK.
- `run-once --skip-crew`: OK, sin traceback.
- Flags al cierre:
  - `trading_mode=paper`
  - `allow_live_trading=false`
  - `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
  - `core_sleeve.enabled=false`

## Comandos para Antonio

No hay diff de la firma aprobable para `ci_prop_p6_overlay_shadow_digest`. Estos comandos sirven para verificarlo:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab review --proposal ci_prop_p6_overlay_shadow_digest --json
```

No ejecutar `approve` sobre esa propuesta: no existe artefacto `READY_FOR_HUMAN_REVIEW` con `tests_ok=true`.
