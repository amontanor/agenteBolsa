# P-L54B-T — caracterización del embudo shadow de despliegue de capital

## Dictamen

`ready_for_p54b_implementation`.

La frontera real está suficientemente identificada para implementar un
productor shadow separado: el ciclo genera recomendaciones, aplica gates,
sizing y `RiskManager`, crea planes y después persiste órdenes. La
caracterización no inventa una exposición objetivo ni un notional desplegable.
Ambos quedan `null/unavailable` cuando no existe una fuente estructurada
autorizada. El siguiente paso es una implementación shadow aislada; no se
ejecuta en este lote.

P-L54B-T-R1 corrige una deuda del primer informe: sus conteos intermedios no
eran una particion secuencial. El snapshot anterior publicado decia
`gates_passed=135`, `risk_approved=135` y `risk_rejected=80`; por tanto,
`risk_approved + risk_rejected = 215 > gates_passed`. Tambien declaraba
135.000 USD de riesgo aprobado aunque solo 15 identidades llegaban a plan.
Esas aserciones negativas reproducen el fallo contra `b99d6fc4` y ahora quedan
rechazadas por el contrato.

## Alcance y estado

- Fecha de ejecución: 27-jul-2026, Europe/Madrid; XNYS cerrado, próxima
  apertura observada 15:30 CEST.
- Base P-L58R1 exacta: `2e7602bace51cd43806e8ecab0abb23748c63ec9`, tree
  `5430155c405bd916fe932362f767d4696bd70aef`, versión `0.4.193`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54bt_capital_funnel_characterization`.
- Rama: `codex/pl54bt-capital-funnel-characterization`.
- Producción no se abrió para escritura ni se incluyó. P-L58R1 no se modificó.
- El trabajo contiene únicamente el test de caracterización hasta el commit de
  tests y este informe/documentación. La versión permanece `0.4.193` porque
  tests y documentación no reservan un slot funcional nuevo.

## Productor real trazado

La ruta observada es:

`TradeRecommendation` y contexto de ciclo → selección y gates previos →
`build_buy_order_plans` (capacity check, guards y sizing) →
`RiskManager.validate_order` → `OrderPlan` con `decision_lineage` →
`save_order_plan` → envío paper → `save_broker_order`.

Evidencia de código en el árbol base:

- `src/agente_bolsa/tools/trade_decision.py:4660` define
  `build_buy_order_plans`; en su cuerpo se calculan el límite efectivo de
  planes, el cap de learning, el contexto de riesgo y los símbolos con orden o
  posición abierta.
- En la misma función se registran rechazos por estado de mercado,
  investigación, kill switch, confianza, orden/posición existente y guard de
  símbolo duplicado; se aplica el multiplicador de microexperimento, el cap de
  notional de learning, `RiskManager.validate_order`, el cap de exposición de
  learning y el mínimo de ejecución.
- `src/agente_bolsa/cycle_runner.py:1815` construye planes desde las
  recomendaciones ya gated; `:2117` llama `save_order_plan` y `:2204` llama
  `save_broker_order` después del envío.
- El plan real conserva `decision_lineage`, pero no se encontró un campo
  estructurado `target_account_exposure` en esta frontera ni una autoridad
  explícita de notional objetivo. No se deduce de cash, SPY, rendimiento o
  configuración actual.

El productor operativo usa símbolos para guards de duplicado y algunos
contextos de ejecución. Eso no es autoridad de identidad del ledger. La
implementación futura debe usar los IDs exactos del objeto activo y conservar
BUY/EXIT separados; nunca debe reconstruir el embudo uniendo por símbolo,
fecha, texto o `source_run_id+symbol`.

## Contrato caracterizado

Schema propuesto: `p-l54b.capital-deployment-funnel-shadow.v1`.

La unidad pre-plan es:

`cycle_id + action + signal_capture_id`, con fallback exclusivo a `signal_id`,
y `recommendation_id` cuando existe. `candidate_id` es auxiliar. Plan,
`broker_order_id` y fill conservan dominios separados y no se cuentan como
candidatos adicionales.

Cada fila conserva, cuando existe antes de la etapa correspondiente:

- estrategia/setup y `as_of`;
- timestamps UTC de ciclo, decisión, plan, envío y fill;
- elegibilidad técnica, fuente de decisión, LLM considerado/seleccionado;
- etapa de gates y riesgo;
- IDs exactos de recomendación, plan y orden;
- requested/risk-approved/planned/submitted/filled notional en USD;
- sizing base, multiplicador de microexperimento, cap y reason codes;
- `primary_drop_reason` exclusivo y `secondary_reasons` auditables;
- `captured_at` fuera del `content_hash` determinista.

Missing no es cero. `null`, `unavailable`, `not_generated`,
`identity_unavailable`, `temporal_unavailable` y `not_applicable` conservan
significados distintos.

Etapas sin doble conteo:

1. candidates observed;
2. technically eligible;
3. recommendations generated;
4. `llm_selected`, `deterministic_capacity_fill` y otras fuentes separadas;
5. gates evaluated/passed/rejected/unavailable;
6. risk approved/rejected/unavailable;
7. plans generated;
8. orders submitted;
9. orders filled/rejected/cancelled/pending.

El matching posterior de resultados no forma parte del evento predecisión. No
entran P/L, fills futuros, outcomes, MAE/MFE ni benchmark.

## Denominadores de la fixture principal

Fixture sanitizada: 376 recomendaciones BUY, 15 planes BUY y 15 órdenes/fills.
La exposición observada es 0,1085 (10,85%); `target_account_exposure` y
`buying_power` son `null/unavailable`.

| Denominador | Valor | Estado |
|---|---:|---|
| raw candidates | 376 | complete |
| canonical candidates | 376 | complete |
| identity unavailable | 0 | verified |
| technically eligible | 376 | complete |
| recommendations generated | 376 | complete |
| `llm_selected` / `llm_considered` | 15 / 15 | complete |
| decision source LLM / deterministic capacity fill | 126 / 250 | descriptive |
| gates evaluated / passed / rejected / unavailable | 306 / 145 / 100 / 61 | complete |
| risk approved / rejected / unavailable | 15 / 80 / 0 | complete |
| plans generated | 15 | complete |
| orders submitted / filled | 15 / 15 | complete |
| pending / rejected / cancelled orders | 0 / 0 / 0 | verified zero |

### Waterfall de notional

| Etapa | Notional USD | Cobertura |
|---|---:|---|
| candidate requested | 564.000 | 376/376, USD, complete |
| gate eligible | 217.500 | 145/145, USD, complete |
| risk approved | 15.000 | 15/15, USD, complete |
| sizing approved | 95.000 | 95/95, USD, complete |
| planned | 15.000 | 15/15, USD, complete |
| submitted | 15.000 | 15/15, USD, complete |
| filled | 15.000 | 15/15, USD, complete |
| target/min/max exposure estructurados | `null` | unavailable |
| notional objetivo realmente desplegable | `null` | unavailable |

La cobertura parcial suma únicamente valores explícitos de las unidades que
alcanzaron la etapa; no convierte las 361 restantes en notional cero ni en una
estimación de oportunidad perdida.

La fixture de volumen separada contiene 500 candidatos y 20 planes. Su medición
local registró 126,737 ms, pico de memoria de 4.353.074 bytes y objeto
serializado de 530.105 bytes. Es una caracterización, no un umbral de capacidad
ni una garantía de scheduler.

## Razones de caída

Se asigna una sola razón primaria por identidad con prioridad estable:

`identity_unavailable` → `temporal_unavailable` → `selection_unavailable` →
`gate_unavailable` → `gate_rejected` → `risk_unavailable` → `risk_rejected` →
`execution_rejected_cancelled` →
`capacity_exhausted` → `quota_duplicate_guard` → `not_selected` →
`sizing_zero` → `cap_limited` → `not_generated` →
`not_applicable_exit`.

En la fixture 376/15/15: `gate_rejected=100`, `risk_rejected=80`,
`not_selected=70`, `capacity_exhausted=50` y `gate_unavailable=61`. Quince
filas alcanzan plan/orden/fill y no tienen drop reason. Razones secundarias no
se suman a la caída; por ejemplo, `capacity_exhausted` es la primaria cuando
coexiste con el reason genérico `quota`.

BUY y EXIT con la misma señal, recompras y multilote se mantienen como filas
distintas por `action` e identidad exacta. Una recomendación sin plan, un plan
sin orden y una orden pending/rejected/cancelled no se promocionan a la etapa
siguiente.

## Persistencia: solo caracterizada

El helper de tests verifica hash estable con JSON reordenado y `captured_at`
fuera del hash, repetición idéntica `idempotent` y contenido distinto
`conflict` con el original intacto. No crea Store, tablas, migraciones, eventos,
backfill ni wiring productivo. La implementación futura deberá preparar y
serializar fuera de SQLite, usar una transacción corta append-only y exponer
conflictos separados.

## Validación ejecutada y omitida

Ejecutado con Python del proyecto, `PYTHONPATH` del worktree y `DATA_DIR`
temporal:

- pruebas P-L54B-T/R1: **27 passed**;
- focales P-L53/P-L50/P-L51/P-L52: **126 passed**, con una advertencia de
  deprecación de `websockets` preexistente;
- trade-decision/riesgo/gates/lineage/storage/controles: **80 passed**;
- `tests/test_trade_decision.py`: **129 passed**;
- Ruff completo `src tests`: **OK**;
- `scripts/check_no_nulls.py`: **OK (430 archivos)**;
- `git diff --check`: **OK**;
- compilación `src` y `tests`: **OK**;
- volumen 500/20 ejecutado mientras XNYS seguía cerrado.

Omitidos por alcance: suite completa, smoke/run-once, benchmark largo, prueba
histórica P-L45 de 33.336 filas, `validate-agent-config`, red, broker, LLM,
jobs, postmarket y reconciliación. No se añadieron skips ni xfails.

## Seguridad y siguiente paso

No hubo cambios en `src/`, archivos protegidos, producción, SQLite productiva,
servicios, procesos, configuración, locks, leases, P-L58R1 ni otros worktrees.
No hubo despliegue, reinicio ni push. La caracterización no cambia candidatos,
scores, ranks, recomendaciones, gates, sizing, planes, órdenes, exposición ni
límites.

## P-L54B-T-R1 — invariantes de alcance y notional

La tabla corregida es secuencial y sin doble conteo:

| Etapa | Reached | Passed/approved | Rejected | Unavailable | Not generated |
|---|---:|---:|---:|---:|---:|
| selection | 376 | 306 | 70 | 0 | 0 |
| gates | 306 | 145 | 100 | 61 | 70 |
| capacity | 145 | 95 | 50 | 0 | 231 |
| sizing | 95 | 95 | 0 | 0 | 281 |
| risk | 95 | 15 | 80 | 0 | 281 |
| plans | 15 | 15 | 0 | 0 | 361 |
| orders | 15 | 15 | 0 | 0 | 361 |
| fills | 15 | 15 | 0 | 0 | 361 |

El orden caracterizado es selección → gates → `capacity check` dentro de
`build_buy_order_plans` → sizing → `RiskManager` → plan. Una etapa
posterior a una caída primaria es `not_generated`, no `unavailable`.

El waterfall corregido es: requested 564.000 USD (376/376), gate eligible
217.500 USD (145/145), sizing approved 95.000 USD (95/95), risk approved 15.000,
planned 15.000, submitted 15.000 y filled 15.000. Cada importe lleva
`available_count`, `unavailable_count`, `denominator_count`, moneda y estado.
Target/min/max exposure y notional objetivo siguen `null/unavailable`.

La partición terminal BUY es 15 éxitos de plan/orden/fill + 361 caídas = 376.
Los estados `risk_unavailable`, `sizing_unavailable` y
`selection_unavailable` son categorías separadas. Un gate rechazado no aparece
como riesgo rechazado; un riesgo unavailable no genera plan.

Siguiente lote único: implementar el productor shadow en un worktree nuevo desde
este commit, reutilizando los objetos reales del ciclo y dejando explícitos los
campos de target/notional que siguen `unavailable`. No ejecutar esa
implementación en P-L54B-T.

## P-L54B-W - implementacion shadow del embudo de capital (0.4.194)

Dictamen provisional: `ready_for_integration_rehearsal`.

Worktree aislado: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54bw_capital_funnel_shadow`;
rama `codex/pl54bw-capital-funnel-shadow`; base
`20e8be04d5d622dae441320c656d64a0c287e3ff`; tree base
`226a6baea4454bb531792d9c07dbd91379aee77a`; version candidata 0.4.194.

El productor `capital_deployment_funnel_shadow.py` solo proyecta observaciones
estructuradas ya producidas por la ruta activa. La frontera es:

`seleccion -> gates previos -> capacity check -> sizing/caps -> RiskManager ->`
`OrderPlan -> filtros post-plan -> save plan -> envio/save broker_order ->`
`persistencia P-L54B shadow`.

La persistencia ocurre fuera del bucle de candidatos, no llama a gates,
RiskManager, broker, red, LLM ni seleccion, y falla abierta. El evento canónico
es `capital_deployment_funnel_shadow:<cycle_id>`, schema
`p-l54b.capital-deployment-funnel-shadow.v1`. El hash excluye `captured_at`;
repeticion identica es idempotente y contenido distinto crea conflicto separado
sin reemplazar el original.

La identidad es `cycle_id + action + signal_capture_id`, con fallback exclusivo
a `signal_id`; `candidate_id` es auxiliar y recommendation/plan/order se anaden
solo cuando el objeto activo cruza esa frontera. BUY y EXIT permanecen separados.
No hay joins por simbolo, fecha, texto o `source_run_id+symbol`.

La fixture cerrada conserva 376 candidatos, 306 que pasan seleccion, 145 gates,
95 capacity/sizing, 15 risk-approved y 15 planes/ordenes/fills. Las caidas
primarias son 361 y cada identidad tiene una sola razon. El waterfall de
notional mantiene cobertura y moneda por etapa. `target_account_exposure`,
min/max target, buying power y notional objetivo son `null/unavailable` si no
los aporta un objeto estructurado; no se derivan de cash, SPY ni rendimiento.

El evento es acotado: conserva denominadores completos y detalles compactos,
publicando `detail_total`, `detail_persisted`, `detail_omitted` y `truncated`.
La fixture de 500 candidatos exige menos de 350 KB y build/serialise menor de
250 ms; una muestra truncada queda `partial` y no sustituye al universo.

Se anadio lector read-only, CLI `capital-deployment-funnel --json` y resumen del
digest. Sin evento, los denominadores son null y el estado es `collecting`.
Los consumidores no reconstruyen ni alimentan learning/readiness/promotion.

Validacion focal ejecutada: **33 passed** (P-L54B-T/R1 y P-L54B-W), Ruff de los
archivos modificados y compilacion Python. Suite completa, smoke/run-once,
P-L45 de 33.336 filas, `validate-agent-config`, jobs, postmarket,
reconciliacion, broker, red y LLM quedan pendientes para P-L54BR1 y no se
ejecutaron en este lote.

No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
`config.py` ni `.env`; produccion, P-L54B-T-R1, P-L58R1 y SQLite productiva
permanecen intactos. No hubo despliegue, reinicio ni push. Siguiente lote unico:
ensayo integrado P-L54BR1 sobre este candidato.

## P-L54B-R1 - identidad de decision antes del ensayo integrado

Dictamen: `ready_for_integration_rehearsal`.

La reproduccion contra `9c8940a0` confirmo que la clave anterior era solo
`cycle_id + action + signal_capture_id` (con fallback a `signal_id`). Dos
recomendaciones distintas para la misma senal y accion se fusionaban en una
fila y el segundo contenido incompatible se descartaba como duplicado. Tambien
faltaban estados durables para una recomendacion sin `recommendation_id` y para
un ciclo embebido distinto del ciclo externo.

Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54br1_decision_identity`.
Rama: `codex/pl54br1-decision-identity`. Base y referencia exactas:
`9c8940a00d8d57521720bbeade0725bbc33d2f6d`, tree
`9d496ba5568e4a0cd24039fa75ead96eafb70b92`, version `0.4.194`.
Commits: `de08b9fd` caracterizacion inicial, `8d814934` cobertura adicional y
fixture temporal coherente, `3f85071f` correccion funcional. La version no
cambia.

El contrato corregido separa cuatro dominios:

- `signal_identity`: `signal_capture_id` preferido, `signal_id` como fallback;
  `candidate_id` es auxiliar.
- `decision_identity`: `cycle_id + action + signal_identity +
  recommendation_id` cuando existe.
- `plan_identity`: `plan_id`.
- `order_identity`: `broker_order_id`/`client_order_id`.

Una recomendacion sin `recommendation_id` queda `partial` si es unica; dos
filas parciales de la misma senal/accion/ciclo quedan `ambiguous`. Contenido
incompatible con la misma decision exacta conserva ambas filas como conflicto
auditable y excluye ambas de stages y notional evaluables. Una repeticion
identica es no-op. Un plan u orden sin decision exacta no se adhiere por senal,
posicion o lista; queda `attachment_unavailable`/`ambiguous`. BUY y EXIT siguen
separados por `action`; un `candidate_id` distinto no crea una decision nueva.
Un ciclo embebido distinto del ciclo externo es `cycle_mismatch` y no se
reencaja silenciosamente.

Los denominadores nuevos son `signal_identity_verified/unavailable/ambiguous`,
`decision_identity_verified/partial/unavailable/ambiguous`,
`recommendation_id_available/unavailable`, `plan_attachment_*` y
`order_attachment_*`. `canonical_count`, stages, razones primarias y
waterfalls usan solo la poblacion de decision verificada; la poblacion BUY
observada y la poblacion excluida se publican por separado. El cierre de
invariantes exige `success + dropped + excluded_identity = observed`.

La compactacion de detalles conserva el limite de volumen: la fixture de 500
filas sigue por debajo de 350 KB y el tiempo de construccion/serializacion de
la prueba focal queda por debajo de 250 ms en el entorno temporal. El hash
determinista incorpora la identidad con `recommendation_id`; `captured_at`
continua fuera del hash. No se cambio el orden de productor, stages, notional,
persistencia, callbacks, cap/truncation ni la ruta activa.

QA focal: `15 passed` para la regresion de identidad y el contrato P-L54B-W;
`49 passed` al incluir caracterizacion T, R1 y `cycle_funnel`. Ruff completo,
compilacion, `check_no_nulls.py` y `git diff --check` quedan verdes. Suite
completa, smoke y P-L45 de 33.336 observaciones se omiten por alcance; no se
anadieron skips/xfails. No se modificaron archivos protegidos, produccion,
SQLite productiva, servicios ni otros candidatos; no hubo despliegue, reinicio
ni push.

Siguiente lote unico: reintentar P-L54BR1 desde este candidato con validacion
integrada cerrada; no se ejecuta en P-L54B-R1.
