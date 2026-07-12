# P-L30 - snapshot prospectivo de contexto de decision y regimen

## Alcance

P-L30B implementa exclusivamente un snapshot pre-decision dentro de los JSON
existentes. No crea tablas, no rellena historicos y no modifica ranking, gates,
estrategias, ordenes, stops, takes, exposicion ni limites. Los 17 archivos
`idealista_terrenos_*` son untracked ajenos, permanecen intactos y no entran en
staging.

## Contrato

El bloque usa `p-l30b.decision-context.v1` y se guarda como
`decision_context_snapshot`. Incluye `snapshot_id`, `content_hash`, `cycle_id`,
`source_run_id`, `agent_run_id` nullable, `signal_id` y estado de enlace,
estrategia/version si existe, referencia al estado de mercado del mismo ciclo,
fuente raw/normalizada, estado LLM, motivo de fallback, ranking, `captured_at` y
`pre_decision_only=true`.

`content_hash` excluye `captured_at` y el propio hash. El snapshot es idempotente
por identidad de ciclo/señal/recomendación; una discrepancia de hash se conserva
como conflicto y no se sobrescribe silenciosamente. La referencia de mercado
exige ciclo coincidente y `as_of <= captured_at`; si falta el objeto exacto se
publica `status=unavailable`, nunca se consulta el informe más reciente.

## Temporalidad y seguridad

La captura ocurre después de decisión/ranking y antes de planes, fills y
outcomes. Se rechazan recursivamente retornos forward, madurez, MFE/MAE,
`first_hit`, veredictos, fills, P&L, execution snapshot y slippage. El valor raw
de la fuente se conserva separado de su normalización: `llm`, `fallback`,
`capacity_fill`, `hold_override`, `deterministic` o `unknown`. Capacity fill no
se confunde con fallback y el motivo de fallback usa códigos estables.

## Propagación

El ciclo central adjunta el mismo bloque a la recomendación y al objeto
`OrderPlan`; la observación lo conserva al materializar las features desde la
señal y el outcome solo se actualiza mediante `signal_id` exacto. Símbolo/fecha,
`UNKNOWN`/`BUILTIN` o ciclos distintos nunca verifican identidad. Las rutas
`decide-once` y pre-earnings también generan snapshot, con market state
`unavailable` cuando no reciben el objeto exacto en memoria.

El digest añade `decision_context_quality`: recomendaciones nuevas, cobertura,
enlaces verified/broken/unavailable, planes/observaciones/outcomes con snapshot,
vínculo agent_run, mismo ciclo de mercado, cobertura de fuentes y fallback,
contaminación, conflictos, legacy y estado `collecting/evaluable`.

## Verificación

La prueba focal nueva usa `Store` temporal y cubre mercado exacto/distinto,
orden temporal, hash/idempotencia/conflicto, las seis fuentes de decisión,
links estrictos, agent_run nullable, rechazo recursivo de campos posteriores,
propagación a observación/plan, históricos intactos, digest con denominadores y
ausencia de red. No se ejecuta LLM ni se modifican datos productivos durante
tests.

No se afirma ninguna mejora de profits. El snapshot queda destinado a análisis
prospectivo posterior, no a selección de operaciones ni a cambios de estrategia.
