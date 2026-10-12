# Dictamen SCORE shadow — 12 de octubre de 2026

## Dictamen

`ready_for_integration_rehearsal`. El candidato implementa un marcador
observacional puro y versionado para calidad de oportunidades. Calcula un score
challenger 0–100 únicamente cuando sus cuatro componentes están disponibles y
son numéricos normalizados. No cambia selección, tamaño, gates activos, órdenes,
broker, red ni llamadas LLM.

El score usa pesos fijos: técnica 55 %, noticias 20 %, fiabilidad empírica LLM
15 % y setup 10 %. No redistribuye peso cuando falta evidencia. Horizonte
soportado: 3, 5 y 10 sesiones; 5 es primario.

## Contrato y límites

La entrada pública es:

```python
build_opportunity_quality_carrier(
    payload,
    decision_at=aware_utc_datetime,
    policy=None,
)
```

El adaptador debe entregar identidad explícita bajo `identity` o en campos
raíz: `candidate_id`, `signal_capture_id`, `signal_id`, `recommendation_id`,
`cycle_id` y `symbol`. El marcador conserva esos valores; nunca reconstruye una
identidad desde símbolo, fecha o posición. También conserva `model_id`,
`model_version`, `prompt_version`, `news_ids` y horizonte cuando se entregan.

Los componentes `technical`, `news`, `empirical_llm_reliability` y `setup`
aceptan valores explícitos en `[0, 1]`. `NaN`, infinito, valores fuera de rango
y ausencias quedan `unavailable`, con `score=null` si falta cualquiera de los
cuatro.

Las noticias deben incluir ID exacto, símbolo, fuente, `published_at`,
`available_at` y `canonical_hash`. Ambas marcas temporales deben ser UTC y no
posteriores a `decision_at`. El mismo `canonical_hash` cuenta una sola vez,
aunque llegue sindicado con IDs distintos. Materialidad, novedad y relevancia
económica se conservan como dimensiones separadas; sentimiento y `priced_in`
son opcionales y no sustituyen esas tres dimensiones. Evidencia inválida o
futura queda unavailable y no produce un positivo espurio.

La fiabilidad LLM procede de un recibo `llm_calibration` emitido por
`calibrate_empirical_llm_reliability`. El recibo exige al menos 30 outcomes
maduros, IDs de outcome deduplicados, identidad exacta de recomendación y
captura, modelo, versión, prompt, horizonte y `decision_at < outcome_matured_at
<= as_of`. El carrier comprueba recibo disponible, `as_of <= decision_at`,
provenance exacta, binding completo y IDs sin duplicar; nunca usa un número raw
ni la confianza autorreportada. Excluye filas shadow/fallback y no mezcla
aprendizaje real con esta sombra.

`high_tier.eligible` es una señal separada. Requiere identidad canónica
completa, horizonte válido, score `>=85` (una policy no puede bajar el umbral),
componentes completos, expectativa neta positiva validada para el mismo
horizonte con `evidence_id`, timestamp no futuro, costes incluidos y policy
binding, token de aprobación explícito ligado a
candidato/captura/recomendación, y las cinco claves `hard_gates` (`identity`,
`data`, `risk`, `costs`, `policy`) en `true`. Un score alto por sí solo no
habilita el tier.

El carrier siempre devuelve `authority.shadow_only=true`,
`can_authorize_size=false`, `size_authorized=false` y
`can_change_orders=false`. No existe autorización de tamaño ni de orden en este
contrato.

La sombra conserva una segunda salida independiente, `champion_calibration`,
para el score actual. `current_selection_score` y
`current_selection_components` permanecen raw y separados del score combinado.
`calibrate_current_selection_score` solo acepta un recibo previo con bins
explícitamente congelados y `policy_hash` exacto. Requiere al menos 30 outcomes
de horizonte fijo de 5 sesiones, moneda uniforme, costes incluidos, IDs
exactos, y `decision_at < outcome_matured_at <= calibration_as_of`. La salida
separa `empirical_net_return_after_costs`,
`empirical_positive_net_return_probability` y `calibrated_score_0_100`; un
retorno como `0.057` nunca se relabela como probabilidad normalizada.

## Adaptador previsto

La ruta activa debe construir un snapshot de decisión ya existente y añadir los
carriers numéricos capturados en predecisión. Debe llamar al builder una vez por
recomendación, pasar el `decision_at` de la misma decisión y transportar el
carrier como telemetría o evidencia shadow. La integración debe conservar
linaje exacto entre recomendación, captura, candidato, ciclo, modelo, prompt y
noticias. Este lote no cablea la ruta activa ni crea persistencia nueva.

## Evidencia

Base de candidato: `63cb6f9883f22c0d11dba20dd59c315ceae5dc0e`.

Árbol base: `a7167bca1b9387c40eb37d32d3497505dd573bf7`.

Archivos propios del lote:

- `src/agente_bolsa/tools/opportunity_quality_shadow.py`
- `tests/test_opportunity_quality_shadow.py`
- `docs/informe_oct12_score_shadow.md`

Validación focal ejecutada con `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`,
`PYTHONPATH` apuntando a `src`, `DATA_DIR` temporal y
`PYTHON_DOTENV_DISABLED=1`:

```text
22 passed in 0.15s
ruff check src/agente_bolsa/tools/opportunity_quality_shadow.py tests/test_opportunity_quality_shadow.py
All checks passed!
```

Las pruebas cubren deduplicación de noticias sindicadas, evidencia futura,
componentes ausentes, `NaN`, confianza propia del LLM, fallback LLM, ausencia
de autoridad de tamaño/orden, predicate estricto de tier alto, calibración de
outcomes maduros y exactos, identidad de noticia incompleta y rechazo de
evidencia inválida aunque exista un número declarado. No se ejecutó suite
completa, smoke, broker, red, yfinance, servicio ni LLM.

## Límites y siguiente paso

No hay evidencia económica de superioridad: el score es challenger
observacional. Señales históricas ausentes permanecen `collecting`/
`unavailable` hasta reunir outcomes maduros con identidad y horizonte exactos.
Siguiente paso seguro: revisión del adaptador e integración en worktree del
coordinador, seguida de ensayo focal de paridad de carrier antes de cualquier
consideración de promoción.
