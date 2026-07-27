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

`TradeRecommendation` y contexto de ciclo →
`build_buy_order_plans` → guards/gates y sizing →
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
| gates evaluated / passed / rejected / unavailable | 376 / 135 / 180 / 61 | complete |
| risk approved / rejected / unavailable | 135 / 80 / 161 | complete |
| plans generated | 15 | complete |
| orders submitted / filled | 15 / 15 | complete |
| pending / rejected / cancelled orders | 0 / 0 / 0 | verified zero |

### Waterfall de notional

| Etapa | Notional USD | Cobertura |
|---|---:|---|
| candidate requested | 564.000 | 376/376, complete |
| risk approved | 135.000 | 135/376, partial |
| planned | 15.000 | 15/376, partial |
| submitted | 15.000 | 15/376, partial |
| filled | 15.000 | 15/376, partial |
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

`identity_unavailable` → `temporal_unavailable` → `gate_unavailable` →
`gate_rejected` → `risk_rejected` → `execution_rejected_cancelled` →
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

- nuevas pruebas P-L54B-T: **13 passed**;
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

Siguiente lote único: implementar el productor shadow en un worktree nuevo desde
este commit, reutilizando los objetos reales del ciclo y dejando explícitos los
campos de target/notional que siguen `unavailable`. No ejecutar esa
implementación en P-L54B-T.
