# P-L51B-T — contrato canónico de atribución BUY→SELL

## Dictamen

`ready_for_p51b_implementation`.

La caracterización aislada convierte el bloqueo de P-L51A en un contrato de
tests reproducible. Todavía no implementa Store, tablas, eventos, wiring ni
ningún cambio de trading. El P/L de P-L51A continúa sin atribución neta
canónica: los 18 SELL con `realized_pl` sólo pueden publicarse como
`exit_ledger_descriptive`; `closed_lot_count=0` y `net_attributable_pl=null`
cuando falta el mapping exacto BUY→SELL.

## Alcance y precondiciones

- Fecha de ejecución: 21-jul-2026; XNYS abierto; `schedule-status` confirmó la
  sesión abierta y el lock del scheduler vivo/coherente.
- Base exacta: `24537e813ff0905696cda0b3925a212045ee7b09`.
- Producción observada: versión `0.4.185`, HEAD y tree esperados por el lote;
  la suciedad productiva conocida se preservó.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl51b_measurement_contract_tests`.
- Rama: `codex/pl51b-measurement-contract-tests`.
- Sin acceso SQL desde las pruebas, sin datos productivos en fixtures y sin
  modificaciones de `src/`. La comprobación productiva realizada fue sólo el
  `schedule-status` read-only requerido.

## Contrato `p-l51b.canonical-trade-attribution.v1`

La unidad de operación es `broker_order_id`. Las unidades siguientes permanecen
separadas: `fill_fragment_id`, `lot_id`/`position_identity`,
`plan_id`/`source_plan_id`, `recommendation_id`, `candidate_id`,
`signal_capture_id`/`signal_id` y `cycle_id`.

Una salida sólo es `attributed` si el mapping declara de forma explícita, para
cada asignación, `sell_broker_order_id`, `buy_broker_order_id`, `lot_id`,
`fill_fragment_id`, `source_plan_id` y `qty`, y todas las cantidades coinciden
con los fills canónicos. No existe fallback por símbolo, fecha, última compra,
FIFO, texto ni señal aproximada.

El contrato admite fills parciales, múltiples fragments, múltiples salidas de
un lote, recompras como lotes distintos y una salida que consume varios lotes
únicamente mediante allocations explícitas. Un duplicado idéntico de un
fragmento se deduplica; un contenido distinto con el mismo ID es conflicto.
Una cantidad vendida superior a la abierta es conflicto.

Estados no terminales, identidad ausente, source plan ausente, mapping
desconocido o timestamps inválidos permanecen `unavailable`/`ambiguous`; no se
convierten en cero. Una posición sin `broker_order_id` no confirma fill.

El resultado serializable incluye:

```text
received, valid, attributed, unavailable, ambiguous, conflict
broker_order_count, operation_count, buy_order_count, sell_order_count
fill_fragment_count, closed_lot_count, partially_closed_lot_count, open_lot_count
gross_pl_coverage, net_pl_coverage, cost_coverage
gross_attributed_pl, net_attributable_pl, denominators, warnings, reason_codes
```

Los costes están separados en `commissions`, `regulatory_fees`, `spread_cost`,
`slippage_cost` y `other_costs`. `net_realized_pl` sólo se calcula cuando el
gross y todos los costes explícitos están presentes; un coste ausente no se
trata como cero.

El slippage requiere benchmark, lado, precio de benchmark, precio de fill y
timestamps ordenados y timezone-aware. No se deriva del P/L. `initial_risk`,
`realized_r_multiple`, `holding_seconds`, `holding_sessions`, MAE y MFE sólo se
calculan con sus inputs exactos. Fills, P/L y retornos futuros se rechazan como
features predecisión.

El hash estable ordena las claves JSON y excluye `captured_at`. La repetición
idéntica es `idempotent`; el mismo `event_id` con contenido distinto es
`conflict`, sin reemplazar el original.

## Fixtures y cobertura

| Caracterización | Denominador/resultado verificado |
|---|---|
| BUY completa → SELL completa | 2 órdenes, 2 fills, 1 lote cerrado, gross/net disponibles |
| Tres fragments con duplicado idéntico | 2 fragments canónicos, 1 operación, sin doble qty |
| Entrada y salida parciales | 1 lote parcialmente cerrado, cantidad abierta preservada |
| Varias salidas de un lote | 2 SELL atribuidos, 1 lote cerrado una sola vez |
| Recompras del mismo símbolo | 2 lotes independientes; una salida multi-lote explícita |
| Salida sin mapping | `ambiguous`, sin FIFO y sin lote cerrado |
| Source plan válido/ausente/duplicado/incorrecto | respectivamente válido, `unavailable` o `conflict` auditable |
| Mapping SELL duplicado | `conflict`, no doble atribución |
| SELL mayor que qty abierta | `sell_exceeds_open_qty`, no atribuido |
| Pending/rejected/cancelled | `unavailable`, nunca fill |
| Costes completos/parciales/ausentes | net disponible sólo en el primer caso |
| Slippage y timestamps | BUY/SELL adverse bps; missing/naive/invertido unavailable |
| Riesgo y holding | métricas con inputs exactos; missing permanece null |
| Identidad y content conflict | IDs duplicados/conflictivos visibles |
| Hash/captura append-only | inserted, idempotent y conflict; `captured_at` fuera del hash |
| Fixture P-L51A | 18 SELL descriptivas; 0 lotes cerrados; net atribuible null |
| Dominios separados | fragments, trade_memory, señales y outcomes no crean operaciones |
| No mutación | objetos activos idénticos antes/después |

La fixture P-L51A reproduce el total descriptivo `+75,62`, pero no permite
atribuirlo a una entrada ni a una estrategia, fuente, candidate, freshness o
coste. `trade_memory` y `signal_outcomes` sólo generan warnings y reason codes;
no sustituyen la identidad de lote.

## Qué pasa a ser calculable

| Métrica | Inputs mínimos exactos | Estado sin ellos |
|---|---|---|
| Lote cerrado/abierto/parcial | BUY fills, SELL fills, lot IDs y mapping completo | `unavailable`/`ambiguous` |
| Gross por lote | mapping exacto + `gross_realized_pl` explícito | cobertura parcial o null |
| Net por lote | gross + los cinco costes explícitos | `net_attributable_pl=null` |
| Slippage | benchmark, lado, precios y timestamps timezone-aware | `unavailable` |
| Initial risk / R | entry, stop, qty y net exactos | `unavailable` |
| Holding seconds/sessions | entry/exit UTC y sesiones terminales XNYS | `unavailable` |
| MAE/MFE | observaciones exactas del lote | `unavailable` |

## Validación

- `27 passed` en `tests/test_p51b_canonical_trade_attribution.py`.
- Ruff focal del nuevo test: limpio.
- `check_no_nulls.py` sobre el nuevo test: OK.
- `git diff --check`: limpio.
- No se ejecutaron suite completa, smoke, benchmark largo ni P-L45 de 33.336
  filas.
- `validate-agent-config --json` queda omitido: este commit sólo añade tests;
  se revisará en el gate aislado del lote de implementación si la política lo
  exige.

## Paridad y seguridad

El helper no importa ni llama rutas de broker, ejecución, riesgo o kernel y no
modifica candidatos, scores, ranks, recomendaciones, gates, sizing,
microexperimentos, planes, cantidades, precios, stops, takes, órdenes,
exposición o límites. No hay referencias del contrato en `broker.py`,
`execution.py`, `risk.py`, `kernel.py` ni `config.py`. P-L43/P-L44/P-L45/P-L47/
P-L48/P-L49/P-L50 permanecen sin cambios.

## Git y siguiente paso

Primer commit del lote:

```text
6803ba44 test: characterize canonical trade attribution
```

El siguiente commit de este lote es exclusivamente documental. El siguiente
lote funcional mínimo podrá implementar el contrato en la frontera autorizada,
manteniendo el contrato de tests como requisito previo y sin cambiar thresholds,
tamaños, strategy policy, stops o time-stop.

## P-L51B-W — implementación shadow (21-jul-2026)

### Dictamen

`ready_for_integration_rehearsal`.

La implementación está limitada a una sombra fail-open. Consume el snapshot
P-L48 ya construido, exige provenance estructurada y cantidades de fills
exactas, y publica `unavailable`, `ambiguous` o `conflict` cuando no puede
demostrar una atribución. No reconstruye lotes, no hace backfill y no usa
`trade_memory`, señales, outcomes ni posiciones observadas como sustitutos de
un `broker_order_id`.

### Frontera lograda y límite actual

Se añadió `src/agente_bolsa/tools/canonical_trade_attribution.py` con el
schema `p-l51b.canonical-trade-attribution.v1`. La unidad de salida es
`sell_broker_order_id`; cada allocation debe declarar BUY, lote, fill fragment,
source plan y qty. Los fills canónicos explícitos pueden viajar como metadata
local en el snapshot P-L48; la metadata no forma parte del payload enviado al
broker.

La frontera aún no crea automáticamente provenance histórica: las salidas que
no contienen `trade_attribution` y `canonical_fill_fragments` explícitos quedan
`ambiguous`/`unavailable`. La fixture del defecto P-L51A conserva los 18 SELL
descriptivos, pero devuelve `attributed_sell_count=0`,
`closed_lot_count=0` y `net_realized_pl=null`.

### Wiring y persistencia

El PMR ejecuta una única construcción y persistencia de P-L51B después de
`canonical_operation_telemetry` y antes de `performance`. Usa el mismo objeto
construido y no vuelve a consultar broker, reconciliación, cartera, outcomes ni
SQLite para reconstruirlo. El orden verificado queda:

```text
coordination → reconciliation → outcome_update → daily_learning
→ postmarket_report → canonical_operation_telemetry
→ canonical_trade_attribution → performance → measurement_pipeline
→ thesis → terminal
```

La persistencia reutiliza `agent_events`, sin tablas ni migraciones nuevas,
`BEGIN IMMEDIATE` sólo durante la inserción corta y sin `INSERT OR REPLACE`.
`captured_at` queda fuera del hash estable; mismo contenido es idempotente y
contenido distinto crea conflicto auditable conservando el original. Un fallo
del productor o de persistencia no bloquea el PMR ni altera performance.

Los denominadores publicados por el snapshot son:

```text
buy_order_count, sell_order_count, fill_fragment_count,
attributed_sell_count, unavailable_sell_count, ambiguous_sell_count,
conflict_count, closed_lot_count, partially_closed_lot_count, open_lot_count
```

Gross, costes, net, riesgo, R, holding y MAE/MFE conservan cobertura explícita;
un coste ausente no se convierte en cero y `net_realized_pl` permanece null.
Los lectores de health, digest y CLI leen el evento persistido y no
reconstruyen la atribución.

### Validación realizada

- `17 passed` en `tests/test_p51b_trade_attribution_shadow.py`.
- `82 passed` en la batería combinada focal `tests/test_p48br1_adversarial_qa.py` y
  `tests/test_p51b_trade_attribution_shadow.py`.
- `109 passed` en la validación conjunta que añade los 27 tests heredados de
  `tests/test_p51b_canonical_trade_attribution.py`.
- Las pruebas cubren las 27 caracterizaciones heredadas de P-L51B-T, API
  productiva, lotes parciales y multi-lote explícitos, estados pendientes,
  costes parciales, concurrencia inserted/idempotent, conflicto separado,
  readers sin rebuild, build/persist fail-open, orden de stages y paridad
  byte-a-byte del payload del broker.
- Ruff focal limpio y `git diff --check` limpio al cerrar las commits.
- No se ejecutaron suite completa, smoke, benchmark largo, prueba histórica de
  33.336 filas, servicios, jobs reales, broker, red, yfinance, LLM,
  reconciliación productiva ni postmarket productivo.
- Los gates de mercado cerrado (`validate-agent-config` aislado, suite
  completa y smoke) quedan pendientes para la validación de integración con
  XNYS cerrado.

### Paridad, protección y Git

Versión candidata `0.4.189`. No se modificaron `kernel.py`, `broker.py`,
`execution.py`, `risk.py`, `config.py` ni `.env`. La sombra no modifica
candidatos, scores, ranks, recomendaciones, gates, sizing, microexperimentos,
planes, cantidades, precios, stops, takes, órdenes, exposición, límites ni
frecuencia de jobs.

Worktree:
`C:\Antonio\Bref\agenteBolsa_worktrees\pl51b_trade_attribution_impl`.
Rama: `codex/pl51b-trade-attribution-impl`. Base P-L51B-T exacta:
`e4b62a1beafc59d342396cd1cb808cce15c47fed`.

Commits separados:

```text
17ac189d feat: add canonical trade attribution shadow
07925b8c test: verify canonical trade attribution wiring
```

La commit documental de esta sección es el tercer commit del lote. Producción,
el ensayo combinado 0.4.188 y P-L51B-T no se modifican; no hubo merge,
despliegue, reinicio ni push.
