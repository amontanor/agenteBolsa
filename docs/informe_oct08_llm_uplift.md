# Informe único — LLM uplift P134, 8-oct-2026

## Dictamen

`ready_for_integration_rehearsal` para el contrato de fixture y medición
aislada. La causa de los tres fallos reproducidos era una fixture obsoleta,
no una pérdida de la bandera causal ni un defecto en la agrupación del módulo
`llm_uplift`. La rama reserva `0.4.346`; no hay integración, build, corte ni
despliegue.

## Alcance y preflight

Lote N2 acotado a `tests/test_p134_llm_uplift.py`, el pin de versión relacionado
de `tests/test_p59c_llm_selected_authority.py` y la reserva de versión en
`src/agente_bolsa/__init__.py`. No se modificaron política activa, trading,
riesgo, ejecución, esquema, históricos, configuración protegida, broker, red,
LLM operativo ni producción.

El preflight comunicado para este encargo fue 8-oct-2026 14:41 Europe/Madrid:
XNYS cerrado, próxima apertura 15:30, `paper=true`, `live=false`,
`auto-apply=false` y sin jobs o leases activos observados. Ese gate operativo
no se hereda automáticamente a integración o corte posterior.

## Reproducción y causa

La reproducción previa a clasificar se ejecutó sobre la base exacta
`1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2` (tree
`4d118b504b305e45f45a06d9aaffa063079abaf7`), con el Python
`C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`, `PYTHONPATH` del
worktree, `DATA_DIR` temporal y sin proveedores externos:

```text
FF.F 3 failed, 1 passed
```

Fallaban `test_sufficient_sample_measures_uplift_from_causal_flag` y
`test_embedded_snapshot_needs_no_join` con `insufficient_sample`, y
`test_source_text_is_never_used_as_proxy` con `unattached == 0` en vez de 35.

La reconstrucción `784e6cd7` hizo explícito el contrato de madurez
direction-corrected: `_mature_signed_return_with_reason` exige retorno maduro,
retorno disponible y dirección válida; si falta dirección devuelve
`direction_unavailable`. Las fixtures de P134 conservaban `return_5d` y
`matured_horizons`, pero no `features.direction`. Por tanto
`_mature_return` devolvía `None`, `mature_executed` quedaba en cero y el
contador `unattached` no se alcanzaba. Restaurar el comportamiento anterior
inferiría dirección y rompería el contrato de datos, por lo que no se restauró.

## Contrato productor/consumidor

El productor canónico `signal_learning._signal_features` porta
`direction=candidate.direction`. `daily_learning._observation_payload` copia
esas features a la observación materializada. La fixture corregida conserva
ese carrier explícito (`long`) tanto en `signal_outcomes` como en la
observación.

La agrupación de `tools/llm_uplift.py` sigue usando exclusivamente
`decision_context_snapshot.llm_selected`, normalizado por
`normalize_llm_selected`. La snapshot embebida se consume primero; si falta,
el join usa únicamente `best_signal_id` exacto contra `signal_outcomes`.
`source` y `recommendation_source` no participan en la clasificación causal.
La prueba de texto libre porta dirección válida, mantiene snapshot ausente,
devuelve `llm.n == 0` y ahora cuenta `unattached == 35`.

Se añadió `test_missing_direction_stays_unverified`: 35 observaciones maduras
sin dirección quedan fuera del denominador (`mature_executed == 0`,
`unattached == 0`, brazo LLM vacío). Así se verifica que el consumidor no
inventa dirección para obtener muestra.

## Cambios y paridad

- `f8cb1956 test(p134): align uplift fixtures with direction contract`: corrige
  fixtures obsoletas y añade el negativo de dirección ausente.
- `d3e449e0 chore(p134): reserve 0.4.346 uplift candidate`: reserva `.346`,
  actualiza el pin de version policy a `.346` y no altera comportamiento de
  producción.

No hubo diff en `llm_uplift.py` ni en rutas activas. Se preservan causalidad,
identidad exacta, dirección, outcome, coste fijo, umbrales
`30/10/0.70`, estados `insufficient_sample`/`sufficient_sample`, y el veto a
usar texto libre como proxy. No se inventan IDs, vínculos, outcomes ni
direcciones en datos sin carrier.

## QA

Con el candidato final y el harness
`C:\Users\utopi\.codex\worktrees\ef99\agenteBolsa\validate_oct08_isolated.py`
(DATA_DIR temporal, `_env_file=None`, paper y flags live/auto-apply falsos,
red local-only):

```text
tests/test_p134_llm_uplift.py
tests/test_p59c_llm_selected_authority.py
tests/test_learning_scoreboard.py
56 passed in 4.05s
```

También pasan Ruff completo (`src tests`), `scripts/check_no_nulls.py`
(`544 archivos`) y `git diff --check`. La ejecución anterior que excluía el
pin de versión fue `55 passed, 1 deselected`; el pin quedó resuelto al reservar
`.346`.

Se omitieron por alcance y autorización: suite completa, smoke, benchmark,
`validate-agent-config`, `kernel-status`, broker, red, LLM, reinicios,
despliegue, merge y push. La producción no fue leída ni mutada en este lote.

## Identidad final y límites

- Worktree: `C:\Users\utopi\.codex\worktrees\oct08-llm-uplift\agenteBolsa`
- Rama: `codex/oct08-llm-uplift`
- Base: `ab28bd86193ef48a18d1f058e2f79492721c1412`, tree
  `daa3f125e2da5b0504924dce5a6858764a9aa1f9`, versión `0.4.343`
- HEAD: `d3e449e0da1c45086dacf2dbfd06dde3859b6212`, tree
  `e3bea62a7d1c946f94f7916722b5c94eda77e696`, versión `0.4.346`
- Estado Git final: limpio.

La evidencia es sintética y de contrato; no demuestra tamaño de muestra real,
uplift económico, causalidad operativa ni readiness de promoción. El siguiente
paso requiere revisión del candidato, ensayo de integración con `.344` y
`.345` coordinados, suite/gates sobre el árbol definitivo y preflight nuevo
sin jobs o leases antes de cualquier corte.
