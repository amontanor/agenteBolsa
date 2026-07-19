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

## P-L48BR1 — QA adversarial y ensayo de integración (0.4.185)

### Ensayo

- Worktree: `pl48br1_integration_rehearsal`; rama: `codex/pl48br1-integration-rehearsal`.
- Base: `acc6e29a818ba217b99100a3dd35b04d98c2d75f` (producción 0.4.182).
- Merge `--no-ff` del candidato exacto `40c05a2d13c696af5c39c1cd0bc7f6bb9f987d31`
  (tree `0a2cc19bc7c80fc9ae2ed3ab9818b80eb99144a9`) → merge `341a50cf`.
- Sin squash, rebase, cherry-pick ni amend sobre los commits funcionales
  (`6c0c30db`, `abcb331a`, `40c05a2d`), conservados tal cual.
- Conflictos de merge: ninguno (estrategia ort limpia).
- Commits QA separados: `b3155389` (fix D1/D2/D3 + batería), `919f58b6`
  (limpieza Ruff), `77d2e743` (tests de consumidores).
- Punto exacto de integración: `post_market_review_job`, stage
  `canonical_operation_telemetry` entre `postmarket_report` (completed) y
  `performance`; persistencia inmediata en el mismo stage.
- Versión del ensayo: `0.4.185` (slot posterior a 0.4.183/0.4.184).

### Resultados por objetivo

**QA-1 Fuente única de verdad.** Contadores de llamadas sobre el PMR real
(broker/red mockeados): `build_canonical_operation_telemetry=1`,
`persist=1` por PMR efectivo. El mismo objeto (identidad `is`) alimenta
`report["canonical_operation_telemetry"]` y `_persist_daily_performance`;
digest/health/CLI leen el evento persistido con **0** reconstrucciones y el
mismo `content_hash`. No existe segunda reconstrucción de órdenes, fragmentos,
atribución, reconciliación, freshness ni denominadores.

**QA-2 Orden postmarket.** Secuencia exacta de stages P-L47 verificada:
`coordination(started/completed) → reconciliation → postmarket_report(started)
→ outcome_update → daily_learning → postmarket_report(completed) →
canonical_operation_telemetry(started/completed) → performance →
measurement_pipeline → thesis → terminal(completed)`. Cero segunda
reconciliación (`reconcile=1`, con `update_learning=False`), cero segunda
actualización de outcomes, una única captura de cartera, cero accesos de red
adicionales; P-L45 mantiene `DEFAULT_LEARNING_OBSERVATION_BATCH_SIZE=250`.
Atribución ANET previa al snapshot: `post_market_review._exit_attribution`
usa su tabla legacy caracterizada (`stop_loss→stop_loss`, contador automático
por prefijo `automatic_`); la normalización nueva
(`stop_loss→automatic_stop_loss`) vive únicamente en
`canonical_operation_telemetry.normalize_exit_origin`. Divergencia
preexistente, caracterizada por P-L48B-T y conservada a propósito: la
prioridad de autoridad P-L48B es determinista — `raw_exit_trigger` >
`exit_trigger` > `trigger`; nivel externo antes que anidado; payload de la
orden > recomendación > plan. No se cambió la ejecución de ninguna salida.

**QA-3 Fail-open.** Fallo de construcción → snapshot `unavailable` con
`producer_failed:*`, sin excepción. Fallo de persistencia en el job →
`terminal(completed)`, warning `persistence_failed:*` visible en el snapshot y
log; performance sigue degradando solo lo telemétrico. Fallo de serialización
(referencia circular) → `ValueError` capturable; la base queda intacta y el
retry inserta. SQLite bloqueada (`BEGIN IMMEDIATE` externo) →
`OperationalError` capturable; retry posterior `inserted`+`idempotent`.
Lectura para digest rota → health degrada a `degraded_observability` sin
tocar trading. Payload inválido, `content_hash` incorrecto o
`schema_version` distinta → `legacy_without_canonical_telemetry`. Un fallo
operativo real (reconciliación) produce `terminal(failed)` y **cero**
telemetría construida: los errores operativos no se ocultan como telemetría.

**QA-4 Idempotencia.** `captured_at` fuera del hash; reordenación de claves
JSON no cambia el hash; dos procesos con el mismo contenido →
`inserted`+`idempotent`; concurrencia con contenido distinto (barrera
determinista) → `inserted`+`conflict` con el original conservado y conflicto
auditable; concurrencia idéntica → `inserted`+`idempotent`; retry tras fallo
de persistencia inserta una vez; reejecución tras `terminal(completed)` →
`session_already_completed` sin reconstruir ni repersistir; el payload
persistido permanece byte a byte idéntico tras repeticiones (sin
`INSERT OR REPLACE`; el conflicto usa `INSERT OR IGNORE` sobre un evento
`*_conflict` separado).

**QA-5 Unidad canónica.** Fixture 16–17 jul sembrada en SQLite temporal leída
por el productor real: `broker_order_count=8, buy=7, sell=1,
fill_fragment_count=16, signal_count=7, candidate_count=7,
recommendation_count=8, plan_count=8`. Adversarial: fragmentos repetidos →
`duplicate_fill_fragments`; suma superior/inferior jamás reescribe
`filled_qty` (autoridad `broker_order_reconciled`); fragmentos sin
`broker_order_id` → `null`, cero unión por símbolo/fecha; dos
`broker_order_id` y recompra del mismo símbolo → operaciones separadas;
`broker_order_id`/`client_order_id` duplicados → warnings sin operaciones
extra; venta parcial → `filled_qty=4`; cancelada con fragmento espurio →
`reconciled_rejected` + `cancelled_count=1`, nunca `filled`.

**QA-6 ANET y atribución.** ANET: `broker_order_count` incluye 1 sola
operación `bo-anet-17`, `sell_order_count=1`, `fill_fragment_count=2`,
`raw_exit_trigger=stop_loss`, `normalized_exit_origin=automatic_stop_loss`,
`automatic_exit_count=1`, `manual_exit_count=0`,
`unknown_exit_origin_count=0`. Matriz completa: `stop_loss`, `take_profit`,
`trailing_stop`, `time_stop_v2`, `manual`, `manual_exit`, `unknown`,
inválido, vacío, `None`, con espacios/mayúsculas; trigger ausente →
`unknown_exit_origin` (nunca inventado); anidado en `risk_decision.checks`
localizado por clave exacta; conflicto plan/evento → gana la orden.

**QA-7 Performance daily y consumidores.** `performance_daily` publica por
separado `signal_count`, `candidate_count`, `canonical_buy_order_count`,
`canonical_sell_order_count`, `fill_fragment_count` y
`legacy_actionable_signal_count`. Contrato documentado: con snapshot
canónico, los nombres legacy `signals/buys/sells` reflejan operaciones
canónicas; `signal_count` nunca sustituye compras ni `fill_fragment_count`
ventas. Base legacy sin P-L48B → conteos legacy intactos; telemetría
`unavailable` → todos los campos P-L48B `null` (nunca cero supuesto);
`partial` conserva los dominios disponibles. Digest, watchdog y health no
rompen con filas antiguas ni degradadas; el scoreboard tolera filas legacy
completas.

**QA-8 Reconciliación.** Timeline `PENDING_NEW` → `position_observed` sin
enlace exacto → `position_observed_without_exact_order_link` →
`reconciled_filled` con `filled_qty` de la autoridad de reconciliación. El
mismo símbolo no confirma identidad; una posición no inventa `first_fill_at`;
`rejected/cancelled` nunca se convierten en `filled`;
`reconciliation_unavailable` cuenta aparte, nunca como cero; un evento
posterior de otra reconciliación no altera el contenido (hash estable).
`reconciliation_terminal_at` no forma parte del contrato v1 persistido: la
caracterización lo reserva; el snapshot publica `reconciliation_status` y los
relojes de freshness separados.

**QA-9 Freshness.** Unidad explícita en segundos (`*_seconds`). 590 s →
`fresh_signal`; 8604,539781 s → `aged_signal` y descriptivamente unos
143,4 minutos (`signal_to_plan_seconds/60 ≈ 143,409`). Timezone-aware
(normalización a UTC), ingenuos (`naive_timestamp` + null), invertidos
(`inverted:*` + null), futuros (`future_timestamp:*` + null), DST
(`-04:00`/`-05:00`), cierre exacto (0,0 s), señal de sesión anterior
(>86 000 s, aged). Igualdad de precios no implica refresh
(`price_refresh_status=unverified`); cotización nueva con timestamp
verificable → `verified`; sin timestamp válido → `unverified`. NaN/Infinity →
`invalid:*` + null. Fill sin `first_fill_at` → `missing:*` + null.
`aged_signal` es solo observación: no existe en `src` fuera del productor;
sin gate, bloqueo, reducción ni cambio de ranking; no incorpora precios
futuros ni outcomes.

**QA-10 Volumen.** 1.000 señales, 100 operaciones canónicas, 500 fragmentos,
2 sesiones: construcción ≈0,13 s/sesión; persistencia ≈6–7 ms/sesión; evento
154 868 bytes (medio=máximo; fixture simétrica); memoria pico tracemalloc
≈1,7 MB; 1 transacción corta por inserción; exactamente 2 eventos
persistidos. `operations` contiene las 100 operaciones canónicas, no los
1.000 candidatos; el evento no crece con eventos raw ajenos al contrato.

**QA-11 Eventos y lectores.** Digest/health/CLI aceptan solo
`schema_version` v1 y validan `content_hash`; los conflictos no cuentan como
snapshots válidos (`canonical_events`) ni deciden el latest; se publican como
`conflict_events` auditables; sin snapshots válidos y con conflictos →
`conflict`. Deduplicación por `event_id` (PK; duplicado genérico →
`IntegrityError`). `runtime_state` nunca se usa como historia. Estados
distinguidos: `collecting` (sin eventos, denominadores null), `available`,
`partial`, `unavailable`, `conflict`,
`legacy_without_canonical_telemetry` y `degraded_observability` (health).
CLI `canonical-operation-telemetry --json`: `available` con evento,
`collecting` con denominadores null sin evento, fail-open ante error de
lectura.

**QA-12 Paridad combinada.** La fixture activa permanece sin mutaciones;
cero referencias P-L48B en `kernel.py`, `tools/broker.py`,
`tools/execution.py`, `tools/risk.py`, `config.py` ni en ninguna decisión,
plan o payload enviado al broker (grep completo de `src`). P-L43 mantiene
`legacy_calendar_days` activa y XNYS shadow; P-L44 mantiene
`legacy_double_application` activa y `single_application` shadow; P-L45
mantiene coordinación, actualización única de outcomes y batching 250; P-L47
mantiene lock/lease v1 y recuperación durable (stages y terminal reales en el
ensayo). Focales P-L43/P-L44/P-L45/P-L47: **142 passed**.

### Defectos encontrados y resolución

- **D1 (corregido, `b3155389`)**: el centinela `_MISSING` es truthy y rompía
  los fallbacks `or` entre `_find_value`; `_text(_MISSING)` publicaba el repr
  del centinela en campos de identidad ausentes, corrompía
  `lineage_quality`/`operations_with_signal`, inflaba `candidate_count` y
  bloqueaba el fallback de `fragment_id` a `memory_id`. Corrección:
  `_or_missing` y `_text`/`_first_present` inmunes al centinela. Regresión
  fijada en la batería (identidad null honesta, fallbacks alcanzables,
  fragmentos con `memory_id`, candidatos no inflados).
- **D2 (corregido, `b3155389`)**: el digest global contaba eventos
  `*_conflict` como canónicos y, tras un conflicto, devolvía `collecting`
  ocultando el snapshot válido. Corrección: conflictos excluidos del conteo y
  del latest; `conflict_events` auditable; estado `conflict` cuando solo
  quedan conflictos.
- **D3 (corregido, `b3155389`)**: `candidate_count` exigía id en todas las
  filas (quedaría `unavailable` en producción real, p. ej. una venta
  automática sin candidato). Ahora cuenta los candidatos observados; solo un
  dominio totalmente ausente permanece `null`.
- **Preexistente (documentado, no tocado)**: `profitability_scoreboard`
  rompe con filas `performance_daily` con `pnl_pct` NULL y sin `max_dd`
  explícito (`_max_drawdown_from_returns`). Reproducido contra la base
  `acc6e29a` sin P-L48B; queda para el backlog, fuera de este lote.
- **Observación (sin impacto)**: la rama `0 if all(fill_fragment_count==0)`
  del denominador global de fragmentos es inalcanzable (por operación es
  `null` sin evidencia, nunca 0). Comportamiento resultante coherente con el
  contrato (ausente → `null`).

### Validación del ensayo

- Batería P-L48BR1: **65 passed**. Baterías P-L48B-T/W: **46 passed**.
- Focales scheduler/storage/postmarket/performance/reconciliation/execution
  quality, digest/health/CLI y combinadas: incluidas en la suite.
- Suite completa: **1689 passed, 1 skipped**.
- Ruff `src tests`: limpio. `check_no_nulls.py`: OK (398 archivos).
  `git diff --check`: limpio.
- `validate-agent-config --json` con `DATA_DIR` temporal: `ok=true`.
- Smoke/entrypoint omitido por mandato del lote: no está garantizado sin
  red/broker/LLM. No se usó SQLite productiva; no se ejecutaron servicios,
  scheduler, postmarket real, reconciliación real, broker, red ni LLM.
- Producción intacta en `acc6e29a` (0.4.182), árbol limpio; sin despliegue
  ni push.

### Dictamen

`ready_for_closed_market_deployment`. Las métricas de operaciones declaran
broker_order_id como unidad canónica; las señales y los fragmentos son
denominadores distintos.

## P-L48BD — despliegue cerrado y controlado (0.4.185)

### Precondiciones verificadas (19-jul, XNYS cerrado, próxima sesión 20-jul)
- Producción `acc6e29a818ba217b99100a3dd35b04d98c2d75f` (0.4.182) limpia;
  ensayo `266950a0fc363e87a8bda706d30fbe0239ee95b4` / tree
  `4c3636be2b6a6c4921e57de3f81ef490cbebbbbf` (0.4.185) limpio.
- Último postmarket 17-jul terminal `completed` (pipeline_completed);
  18/19-jul `skipped/market_not_ready` en historial terminal (no lease).
  `post_market_coordination:active = None`.
- Paper activo; live y auto-apply desactivados; kernel sellado (0 violaciones);
  `validate-agent-config --json` `ok=true`; `adaptive_config.json` SHA-256
  `60833B60F83EDB1B5ECBE0785BDACD68F58AF6D5DFB307649749A8DBF6C7F4D0` exacto.
- HTTP raíz y `/health` 200 en `127.0.0.1:8501`; listener único; `continuous_improvement`
  esperado a terminal en 15 s (no se terminó manualmente).

### Topología (P-L48BD-P: single_logical_stack_launcher_runtime_chains)
Antes y después del despliegue el stack mantuvo una sola cadena lógica por
servicio, patrón launcher venv → runtime Python base (físico del intérprete
base, `sys.prefix=.venv`, paquetes del venv vía `__editable__.agente_bolsa`):

- Scheduler (antes): `powershell 43128 → launcher venv 41544 → runtime 8120`
  (lock token `134288628647465550` coincidía con 8120).
- Scheduler (tras arranque): `powershell 27896 → launcher venv 29536 → runtime 49096`
  (lock token `134289557074352030` coincide con 49096, esquema `p-l47b1.scheduler-lock.v1`).
- Web/Streamlit (tras arranque): `svchost 3576 → launcher venv 45412 → runtime 41544
  → launcher streamlit venv 3060 → runtime streamlit 33104` (único listener 8501).

El propietario correcto del `scheduler.lock` es el runtime hijo (APScheduler),
no el launcher `.venv`. No se "normalizó" la topología: es el comportamiento
esperado del launcher del `.venv` en Windows.

### Despliegue
- `scripts\stack_down.ps1 -IncludeScheduled`: detuvo cadenas gestionadas
  scheduler {43128, 41544, 8120} y web {9440, 43528, 20332, 45704}; sin
  listener 8501, sin procesos del stack ni pytest activos.
- Merge `--no-ff 266950a0fc363e87a8bda706d30fbe0239ee95b4` en producción:
  commit `8cfa0db30ffeae7ae1da8a5dc818d29785b80d08`, **tree funcional
  `4c3636be2b6a6c4921e57de3f81ef490cbebbbbf` idéntico al ensayo**, sin
  conflictos, sin squash/rebase/cherry-pick/amend. Commits del ensayo
  conservados (`6c0c30db`, `abcb331a`, `40c05a2d`, `341a50cf`, `b3155389`,
  `919f58b6`, `77d2e743`, `266950a0`).
- Versión funcional productiva: `0.4.185`. `git diff --check` limpio.

### Validación con stack detenido (sin tocar SQLite productiva)
- Batería P-L48BR1 + P-L48B-T/W: **111 passed** (incluye garantías: unidad
  `broker_order_id`, build=1/persist=1 por PMR, captured_at fuera del hash,
  repetición no-op, conflictos auditables sin sobrescritura, missing no
  convertido en cero, ANET una operación/dos fragmentos/automatic_stop_loss,
  aged_signal descriptivo, cero refs P-L48B en decisiones/gates/planes/órdenes,
  correcciones D1/D2/D3 de `b3155389`).
- Focales scheduler/storage/postmarket/performance_daily/reconciliation/
  execution quality/digest/health/CLI y P-L43/P-L44/P-L45/P-L47: **verdes**
  (138 + 47 + 71 + 73 + 82 + 129 + 81 + 30 + 112 + 369 + 276 + 222 + 21 ≈ 1693
  passed; el caso `test_current_sequential_baseline_records_one_connection_and_commit_per_row[33336]`
  de P-L45 supera el timeout de invocación del entorno; ya pasó en la suite
  completa del ensayo sobre el mismo tree y es un test de caracterización
  P-L45 sin dependencia con P-L48B).
- Ruff `src tests`: limpio. `check_no_nulls.py`: OK (398). `git diff --check` OK.
- `validate-agent-config --json`: `ok=true` (producción). `kernel-status --json`:
  `ok=true`, sellado, 0 violaciones.

### Arranque y dos comprobaciones (intervalo operativo)
- `scripts\stack_up.ps1`: una sola cadena lógica por servicio.
- Comprobación 1 (≈45 s): HTTP 200/200; listener 8501 único (33104); lock v1
  PID 49096 token `134289557074352030` coincide; `post_market_coordination:active
  = None`; heartbeat fresco; 0 órdenes desde el reinicio; 0 `database is locked`;
  kernel sellado; adaptive hash exacto.
- Comprobación 2 (+90 s): HTTP 200/200; listener único; cadenas únicas; lock
  estable; health `overall_status=warning`, **0 alertas críticas**, 5 warnings.
- Bootstrap postmarket: `coordination:started → terminal:skipped` reason
  `market_not_ready`, owner 49096, **una sola vez** — no reprocesa 17-jul, no
  repite reconciliación ni outcomes, no crea telemetría para sesión no
  procesada, no crea órdenes, no deja lease residual.

### Estado P-L48B tras despliegue (sin backfill)
Sin postmarket real desde el despliegue, CLI/digest/health muestran:
- `canonical-operation-telemetry --json`: status `collecting`, denominadores
  `null`, `ok=true`.
- health: `canonical_operation_telemetry.status=collecting`, denominadores null.
- 0 eventos `canonical_operation_telemetry*` en SQLite productiva.
- Cero reconstrucciones históricas heurísticas; cero eventos canónicos inventados.

### Estado de políticas hermanas
- P-L43: `legacy_calendar_days` activa y XNYS shadow.
- P-L44: `legacy_double_application` activa y `single_application` shadow.
- P-L45: batching `DEFAULT_LEARNING_OBSERVATION_BATCH_SIZE=250`, actualización
  única de outcomes, `update_learning=False` en la reconciliación del PMR.
- P-L47: lock/lease v1 (`p-l47b1.scheduler-lock.v1`) con token coherente del
  runtime real; recuperación durable intacta.

### Deuda conservada
`profitability_scoreboard` falla con `pnl_pct=NULL` sin `max_dd` explícito
(defecto preexistente, reproducido contra `acc6e29a` sin P-L48B). **No corregido**
en este despliegue; permanece en backlog en lote separado.

### Cierre
- Tree final producción: `4c3636be2b6a6c4921e57de3f81ef490cbebbbbf` (HEAD
  `8cfa0db3`, merge commit), árbol limpio.
- `adaptive_config.json` intacto; sin push; `profitability_scoreboard` no
  corregido; cero órdenes creadas desde el reinicio; cero `database is locked`.

### Dictamen
`deployed`.
