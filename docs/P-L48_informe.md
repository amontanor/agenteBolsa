# P-L48B-T — caracterización del contrato canónico de operaciones y freshness

## Estado

- Worktree: `pl48b_telemetry_tests`
- Rama: `codex/pl48b-telemetry-tests`
- Base: `acc6e29a818ba217b99100a3dd35b04d98c2d75f`
- Versión candidata aislada: `0.4.183` (bump exigido por `test_version_policy`; no es un release)
- Schema futuro: `p-l48b.canonical-operation-telemetry.v1`
- Alcance: pruebas y fixtures sanitizadas únicamente
- Producción, scheduler, postmarket, reconciliación y dashboard: no conectados

Este lote no implementa el productor productivo ni modifica tablas, columnas,
políticas, órdenes, decisiones o configuración.

## Grano y denominadores

La unidad canónica es `broker_order_id`. Una operación no se multiplica por:

- fragmentos de `trade_memory`;
- recomendaciones;
- planes;
- reevaluaciones postmarket;
- actualizaciones de execution quality;
- eventos de reconciliación.

El resultado futuro conserva por separado:

```text
broker_order_count
buy_order_count
sell_order_count
fill_fragment_count
signal_count
candidate_count
recommendation_count
plan_count
```

En la fixture de 16–17 de julio:

| Métrica | Resultado |
|---|---:|
| broker orders | 8 |
| BUY canónicas | 7 |
| SELL canónicas | 1 |
| fragmentos | 16 |
| señales | 7 |
| candidatos | 7 |
| recomendaciones | 7 |
| planes | 8 |

Los campos ausentes permanecen `null`/`unavailable`; nunca se convierten en
cero ni se reconstruyen por símbolo o fecha.

## Defectos legacy reproducidos

### Performance

`_count_signals()` lee `signal_outcomes` y solo clasifica decisiones
`buy/long/enter` y `sell/exit/reduce`. Con 576/603 filas `decision="candidate"`
devuelve `signals` distintos de cero, pero `buys=0` y `sells=0`, aunque existan
las ocho órdenes canónicas.

La salida futura separa el dominio de señales del dominio de operaciones:

```text
signal_count       ← señales
canonical_buy_count  ← broker_order_id + side=BUY
canonical_sell_count ← broker_order_id + side=SELL
fill_fragment_count  ← fills agregados
```

No se cambian las filas productivas en este lote.

### Atribución de salidas

La función legacy conserva `stop_loss` como origen conocido, pero el contador
automático solo cuenta valores con prefijo `automatic_`. El contrato futuro
conserva ambos campos:

```text
raw_exit_trigger       = "stop_loss"
normalized_exit_origin = "automatic_stop_loss"
```

La matriz caracterizada es:

| Raw | Normalizado |
|---|---|
| `stop_loss` | `automatic_stop_loss` |
| `take_profit` | `automatic_take_profit` |
| `trailing_stop` | `automatic_trailing_stop` |
| `time_stop_v2` | `automatic_time_stop` |
| `manual` | `manual` |
| desconocido/inválido | `unknown_exit_origin` |

ANET sigue siendo una única operación, aunque tenga dos fragmentos.

### Reconciliación

Se caracterizan explícitamente estos estados:

```text
submitted
pending_local
position_observed_without_exact_order_link
reconciled_filled
reconciled_rejected
reconciliation_unavailable
conflict
```

Una posición sin `broker_order_id` exacto nunca confirma un fill. Un BUY
`PENDING_NEW` junto a una posición del mismo símbolo queda
`position_observed_without_exact_order_link`, no `filled`.

Los relojes se mantienen separados: envío, primera observación de posición,
inicio/fin de reconciliación y primer fill/fill agregado.

### Freshness

El bloque caracterizado contiene timestamps y precios separados para señal,
recomendación, plan, envío y fill. Las duraciones están siempre en segundos.

El caso de 17-jul conserva `signal_to_plan_seconds≈8604.54`, es decir,
aproximadamente 143,4 minutos; no se interpreta como 8,604 segundos. Precios
idénticos no prueban refresco: si no existe cotización nueva con timestamp
verificable, `price_refresh_status="unverified"`.

Timestamps ingenuos, invertidos, ausentes, NaN e Infinity producen warnings y
`null`/`unavailable`. `captured_at` queda fuera del hash de contenido.

### Rechazos

Los rechazos `duplicate_symbol_cycle_guard` conservan:

```text
cycle_id
candidate_id
signal_id
recommendation_id
plan_id
reason_code
observed_at
identity_quality
```

`recommendation_id` y `plan_id` pueden ser `null`. La fixture demuestra que dos
rechazos del mismo símbolo en ciclos distintos no se enlazan entre sí.

## Capacity fill

La telemetría conserva, sin autoridad de decisión:

```text
decision_source=deterministic_capacity_fill
capacity_fill_reason_code=capacity_fill_tras_llm_ok
llm_considered=true
llm_selected=false
micro_experiment=true
size_multiplier=0.5
setup_edge_3d_raw=-0.0007
operational_penalty=0.05
expected_edge_3d=-0.0507
```

Las pruebas verifican que estos datos no bloquean, reordenan, dimensionan ni
modifican órdenes.

## Hash, idempotencia y paridad

- Hash canónico determinista, independiente del orden de claves.
- `captured_at` no participa en el hash.
- Repetición idéntica: no-op.
- Mismo ID con contenido distinto: conflicto auditable; el original se conserva.
- IDs de broker y client duplicados: detección explícita.
- No se incorporan P/L, MFE/MAE, first-hit, prompts ni outcomes maduros.
- La fixture activa permanece sin mutaciones; señales, scores, ranks,
  recomendaciones, gates, sizing, planes, stops, takes, cantidades, órdenes,
  exposición, límites y políticas P-L43/P-L44 conservan paridad.

## Validación

Pruebas nuevas: **28 passed**.

## P-L48B-W - productor shadow implementado (0.4.184)

El worktree `pl48b_telemetry_impl` implementa el contrato
`p-l48b.canonical-operation-telemetry.v1` sin autoridad sobre trading. La
unidad es exclusivamente `broker_order_id`; los fragmentos se conservan en
`fill_fragment_count` y los dominios de señal, candidato, recomendación y plan
se publican por separado. No se hacen uniones por símbolo/fecha ni backfill.

La secuencia postmarket construye y persiste una sola foto local después de
reconciliación/outcomes/revisión y antes de `performance_daily`, digest y
health. La escritura usa `canonical_operation_telemetry:<session_date>`,
`BEGIN IMMEDIATE` únicamente durante la inserción corta, es append-only,
idempotente y publica conflictos sin reemplazar el original. Los consumidores
son read-only y el CLI devuelve `collecting` con denominadores `null` cuando
no existe evento.

`performance_daily` recibe el snapshot ya construido y expone
`signal_count`, `candidate_count`, `canonical_buy_order_count`,
`canonical_sell_order_count` y `fill_fragment_count`, manteniendo los campos
legacy y `legacy_actionable_signal_count` separados. La normalización de
salidas y freshness viven solo en esta telemetría shadow.

No se alteran señales, scores, ranks, recomendaciones, gates, entry quality,
sizing, microexperimentos, planes, stops, takes, cantidades, órdenes,
exposición, límites ni las políticas P-L43/P-L44/P-L45/P-L47. No se crean
tablas ni migraciones. El batching P-L45 permanece en 250.

No se ejecutaron jobs productivos, servicios, broker, red, LLM, scheduler,
postmarket, reconciliación ni run-once. No se accedió a SQLite productiva.
