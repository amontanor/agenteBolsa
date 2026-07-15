# P-L43BR2 — historial auditable de evidencia shadow XNYS

Estado: candidato aislado, pendiente de integración y de autorización humana.

Base: `821496670b5654f4dc90ca104d21f011d72f423b` · versión `0.4.172`.

El candidato aislado se valida como `0.4.173` porque el gate del proyecto exige
patch bump ante cambios funcionales. Producción continúa en `0.4.172` hasta una
integración autorizada.

## Política y paridad

La regla legacy de `time_stop_v2` basada en días naturales continúa siendo la
única ruta activa que puede crear una orden. La semántica XNYS es exclusivamente
shadow: calcula evidencia de cinco sesiones XNYS cerradas estrictamente después
del primer fill, pero nunca autoriza, bloquea, retrasa ni modifica una orden.
Stop-loss, take-profit, trailing, cantidades, precios, gates, ranking y límites
permanecen intactos. Un fallo de observabilidad es fail-open para la operación.

## Identidad de posición y contrato de observación

La identidad se deriva de un conjunto ordenado de lotes verificables, priorizando
`broker_order_id`, cantidad abierta, autoridad del fill y `policy_version`.
Una recompra del mismo símbolo produce otra identidad; varios lotes conservan
sus órdenes y cantidades sin fusionar relojes. Si falta el fill o la identidad
es ambigua, `position_identity` queda `null`, se conserva el motivo y no se
inventa una unión por símbolo/fecha.

Cada observación histórica contiene:

- `position_identity`;
- `shadow_observation_id` determinista;
- `observation_session` XNYS;
- `observation_reason`;
- `content_hash` estable, independiente de `evaluation_at`/`generated_at`;
- estado temporal acotado conocido en el momento de evaluación.

No se guardan retornos posteriores, P&L futuro, MFE/MAE, `first_hit`, outcomes
maduros, prompts ni respuestas LLM.

## Historia append-only frente a vista operativa

La historia se almacena como eventos `time_stop_shadow_observation` en la tabla
existente `agent_events`; no se crean tablas ni migraciones. La inserción es
corta y segura:

- mismo `shadow_observation_id` y contenido: `idempotent`;
- mismo ID con contenido distinto: se conserva la primera entrada y se añade
  un evento `time_stop_shadow_observation_conflict` auditable;
- nuevo estado, sesión, progreso de sesiones, cambio de disponibilidad,
  elegibilidad lógica XNYS, activación legacy o cierre verificable: nueva
  observación;
- sesenta ticks idénticos y reinicios no generan flood.

`runtime_state[time_stop_v2_evidence:<symbol>]` queda documentado únicamente
como `latest_view`: incluye `position_identity`, sirve para freshness operativa
y nunca es autoridad de estadísticas históricas. La desaparición o recompra
del símbolo no elimina los eventos terminales ni la evidencia de lotes
anteriores.

## Digest y health

`time_stop_shadow` lee exclusivamente el ledger append-only y publica, cuando
hay muestra:

- `unique_positions`, `unique_observations`, `current_positions`;
- `both_eligible`, `legacy_only`, `xnys_only`, `both_ineligible`, `unavailable`,
  `ambiguity`;
- `comparison_transitions`, `legacy_exits_observed`,
  `xnys_logical_eligibility_events`;
- sesiones cubiertas, cobertura de fill y freshness.

Sin historia el estado es `collecting` y los denominadores son `null`; no se
presenta la ausencia como cero. La vista actual puede contribuir únicamente a
`current_positions`/freshness.

## Casos históricos descriptivos

Las fixtures AIZ, CRWD, STT, SBUX, EXPE, ALL y EBAY continúan clasificadas
`legacy_only` en sus fechas históricas. DDOG y ANET alcanzan la quinta sesión
lógica al cierre del 21-jul; la oportunidad operativa garantizada sería la
apertura del 22-jul si no existe evaluación al cierre. Estos casos no activan
XNYS ni constituyen evidencia productiva.

## Validación y alcance

P-L43BR2 se valida con pruebas focales de política, scheduler, storage, eventos,
digest y health, además de regresiones existentes. No se ejecutan broker real,
postmarket real, reconciliación real, red, LLM, servicios ni despliegue durante
este lote. La activación XNYS continúa requiriendo otro lote, fecha efectiva y
autorización humana explícita.

## P-L43BR3 — ensayo de integración (15-jul-2026)

La rama candidata `0.4.173` se integró sobre producción `0.4.172` en un
worktree separado mediante `merge --no-ff`, conservando los commits P-L43B,
P-L43BR1 y P-L43BR2. La política `legacy_calendar_days` sigue activa; XNYS
continúa `shadow_only=true`.

La historia append-only usa `agent_events`; `runtime_state` es sólo `latest_view`.
La evidencia prospectiva real sigue `collecting`, sin backfill ni interpretación
de rentabilidad. La activación XNYS queda diferida a autorización humana y otro
lote con guardia explícita.
