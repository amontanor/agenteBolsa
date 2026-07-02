# Informe P7 - Fix codegen LLM

Fecha: 2026-07-02

## Resumen

Se corrigio el diagnostico del cliente LLM de mejora continua para que las respuestas truncadas o con contenido en `reasoning_content` no se reporten como `LLM response without text content`. Tambien se separo el rol CODEGEN del modelo general de mejora cuando este sea `glm-*`: CODEGEN usa el modelo de orquestador configurado (`deepseek-v4-flash` en este entorno) sin tocar decision ni sentimiento.

La cola `READY_TO_APPLY` quedo vacia tras sanear las propuestas antiguas y degradar P7 despues de agotar los 3 intentos permitidos. No se aplico fallback manual.

## Diagnostico crudo

Configuracion observada antes del fix:

- `IMPROVEMENT_LLM_PROVIDER=opencode-go`
- `IMPROVEMENT_LLM_MODEL=glm-5.2`
- `IMPROVEMENT_LLM_MAX_TOKENS=6000`
- hard cap previo de codegen: `min(..., 4000)`
- prompt estimado para `ci_prop_p6_overlay_shadow_digest`: `prompt_tokens_estimate=5773`, `context_target=12000`, `context_hard=20000`

Llamada cruda via SDK OpenAI-compatible:

```json
{
  "raw_status": 200,
  "model": "frank/GLM-5.2",
  "choice": {
    "finish_reason": "length",
    "message": {
      "content": "",
      "reasoning_content": "The user wants to add an \"Overlay shadow\" section..."
    }
  }
}
```

Conclusion: el proveedor devolvia razonamiento truncado sin `content`; la causa primaria no era ausencia de respuesta, sino limite de salida insuficiente y parsing poco diagnostico.

## Cambios implementados

- `ImprovementLLMClient`:
  - rechaza `finish_reason=length` con `llm_response_truncated: finish_reason=length content_chars=... reasoning_chars=...`;
  - extrae JSON balanceado desde `reasoning_content` cuando `content` viene vacio y la respuesta no esta truncada;
  - parsea JSON balanceado dentro de prosa/fences antes de fallar;
  - normaliza el fallback local apagado como `fallback local no disponible en 127.0.0.1:8080 (esperado si el servidor local no esta arrancado)`.
- `CodegenPatchAgent`:
  - elimina el cap de 4000 tokens;
  - fija minimo CODEGEN en 16000 tokens;
  - selecciona `IMPROVEMENT_LLM_CODEGEN_MODEL` si existe;
  - si el modelo general es `glm-*`, usa el modelo de orquestador solo para CODEGEN.
- `scripts/llm_health_check.py`:
  - anade probe explicito `codegen [continuous improvement]`;
  - valida JSON `{"ok": true}` para CODEGEN;
  - reporta `codegen_ok`;
  - replica la seleccion de modelo CODEGEN.
- Version subida a `0.4.87`.

## Intentos gen-diff P7

Propuesta creada: `ci_prop_p7_core_sleeve_digest`. Se creo en `PENDING`, paso por `ValidationAgent` y obtuvo `objective_status=READY_TO_APPLY`, pero la politica real de codigo la dejo `PENDING` por `safety_flags`/cola humana. Se registro una decision explicita `P7ManualCodegenGate` para permitir solo `diff preview`, con `no_auto_apply=true`.

Intento 1:

```text
artifact=ci_artifact_4772fd1778ff
status=FAILED
model=glm-5.2
error=primary_error=llm_response_truncated: finish_reason=length content_chars=3930 reasoning_chars=27913 | local_fallback_error=Connection error.
```

Intento 2:

```text
artifact=ci_artifact_e5cf0b23c697
status=FAILED
model=glm-5.2
error=primary_error=llm_response_truncated: finish_reason=length content_chars=0 reasoning_chars=57693 | local_fallback_error=fallback local no disponible en 127.0.0.1:8080 (esperado si el servidor local no esta arrancado)
```

Intento 3:

```text
artifact=ci_artifact_f099eb2d1e34
status=REJECTED_BY_TESTS
model=deepseek-v4-flash
error=ValueError: No se encontro bloque old en src/agente_bolsa/continuous_improvement/digest.py
```

Resultado: no hay `READY_FOR_HUMAN_REVIEW`. La propuesta P7 quedo en `VALIDATING` con razon `codegen_failed_after_3_attempts_requires_executable_spec_no_fallback`.

## Saneado de READY_TO_APPLY

Estados finales:

- `ci_prop_p6_overlay_shadow_digest`: `REJECTED`, razon `superseded_by_fallback`.
- `ci_prop_712ea5e73d18`: `REJECTED`, razon `depends_on_rejected_governance_proposal`.
- `ci_prop_9688d540359c`: `REJECTED`, razon `incomplete_target`.
- `ci_prop_08f79290fec2`: `REJECTED`, razon `duplicate_or_prose_no_executable_spec`.
- `ci_prop_d952ddf82197`: `REJECTED`, razon `duplicate_or_prose_no_executable_spec`.
- `ci_prop_4c6c76e3e77f`: `VALIDATING`, razon `requires_executable_spec`.
- `ci_prop_6d884bc7fe00`: `VALIDATING`, razon `requires_executable_spec`.
- `ci_prop_71120d536576`: `VALIDATING`, razon `requires_executable_spec`.
- `ci_prop_p7_core_sleeve_digest`: `VALIDATING`, razon `codegen_failed_after_3_attempts_requires_executable_spec_no_fallback`.

`READY_TO_APPLY`: 0 propuestas.

Payload literal relevante de `ci_prop_08f79290fec2`:

```json
{"proposal_type":"MONITORING_CHANGE","target_component":"continuous_improvement","target_identifier":"ci_prop_ext_002","current_value":"","proposed_value":"El sistema actualmente requiere intervención manual para aplicar mejoras, lo que ralentiza el ciclo. Con trading_mode=paper, permitir auto-aplicación de cambios de bajo riesgo acelera la iteración sin comprometer la seguridad.","rationale":"El sistema actualmente requiere intervención manual para aplicar mejoras, lo que ralentiza el ciclo. Con trading_mode=paper, permitir auto-aplicación de cambios de bajo riesgo acelera la iteración sin comprometer la seguridad.","expected_impact":"Las propuestas validadas se aplican automáticamente, reduciendo el tiempo de desbloqueo de observaciones y recolección de outcomes.","risk_level":"MEDIUM","required_validations":["configuration_review"],"rollback_plan":"Revertir el cambio propuesto si la validacion falla.","promotion_state":"shadow","evaluation_window_frozen":false,"next_review_at":"","initiative_key":"software:ci_prop_ext_002","initiative_score":49,"merged_count":1,"frozen_conflict":false}
```

Payload literal relevante de `ci_prop_d952ddf82197`:

```json
{"proposal_type":"PARAMETER_CHANGE","target_component":"continuous_improvement","target_identifier":"ci_prop_ext_001","current_value":"","proposed_value":"Estas propuestas han pasado todas las validaciones y son de riesgo bajo (LOW/MEDIUM) en paper trading. Su aplicación inmediata permitiría recolectar outcomes y habilitar exit_policy_v2.","rationale":"Estas propuestas han pasado todas las validaciones y son de riesgo bajo (LOW/MEDIUM) en paper trading. Su aplicación inmediata permitiría recolectar outcomes y habilitar exit_policy_v2.","expected_impact":"Ejecución gradual de observaciones pendientes en los próximos ciclos, mejorando la calidad de datos y desbloqueando el pipeline de mejora.","risk_level":"MEDIUM","required_validations":["in_sample","out_of_sample","walk_forward","paper_or_shadow_window","risk_review"],"rollback_plan":"Revertir el cambio propuesto si la validacion falla.","promotion_state":"shadow","evaluation_window_frozen":false,"next_review_at":"","initiative_key":"software:ci_prop_ext_001","initiative_score":78,"merged_count":1,"frozen_conflict":false}
```

## Verificacion

- `python -m pytest tests/test_continuous_improvement.py::test_improvement_llm_client_rejects_truncated_reasoning_only_response tests/test_continuous_improvement.py::test_improvement_llm_client_extracts_json_from_reasoning_when_content_missing tests/test_ci_codegen.py::test_codegen_preview_produces_diff_artifact_and_no_applied_change tests/test_ci_codegen.py::test_codegen_uses_codegen_role_model_when_general_model_is_glm -q`: 4 passed.
- `python -m pytest`: 878 passed, 1 warning.
- `python -m ruff check src tests scripts`: passed.
- `python scripts/llm_health_check.py --json --timeout 20`: `decision_ok=true`, `sentiment_ok=true`, `codegen_ok=true`; local fallback reportado como no disponible en `127.0.0.1:8080` de forma explicita.
- `python -m agente_bolsa.main validate-agent-config --json`: ok, 0 errores, 0 warnings.
- `python -m agente_bolsa.main run-once --skip-crew`: ok, ciclo `20260702-115557`, modo paper, sin ordenes automaticas.
- Flags: `trading_mode=paper`, `allow_live_trading=false`, `allow_auto_apply_improvements=false`.
- `data/config/core_sleeve.json`: `dry_run=true`.

