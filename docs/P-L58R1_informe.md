# P-L58R1 — ensayo combinado de seguridad de medicion

## Dictamen

`ready_for_closed_market_full_validation`.

El ensayo aislado integra P-L53BR2, P-L43C-R1 y P-L57A en 0.4.193. Las
pruebas demuestran que las tres sombras permanecen fuera de la autoridad de
trading, que la evidencia de una salida se guarda despues del `broker_order`
local canonico y que una fila contable incompleta no derriba el PMR. No se
despliega este candidato.

## Precondiciones y referencias

- Fecha de validacion: 2026-07-27; XNYS cerrado, proxima apertura 15:30 CEST.
- PMR efectivo 2026-07-24: `pmr_e7569ba3887c`, estado terminal
  `completed/pipeline_completed`; `post_market_coordination:session:2026-07-24`
  quedo terminal y la lease fue liberada.
- Los estados actuales de `market_cycle`, `portfolio_watch`, postmarket y
  reconciliacion son `skipped` por mercado cerrado. El runtime residente
  `continuous_improvement_lab` sigue en dry-run y no se detuvo ni bloqueo el
  ensayo.
- Scheduler lock: propietario vivo, PID/token coherentes. No habia pytest ni
  despliegue operativo antes de la suite.
- Produccion: `24537e813ff0905696cda0b3925a212045ee7b09`, tree
  `4747f27f3d5dc152410203bf089baee500440897`, 0.4.185, suciedad conocida
  preservada.
- Candidato: worktree
  `C:\Antonio\Bref\agenteBolsa_worktrees\pl58r1_measurement_safety_rehearsal`,
  rama `codex/pl58r1-measurement-safety-rehearsal`, version 0.4.193.

La lectura de la SQLite productiva usada para precondiciones se hizo con URI
`mode=ro` y `PRAGMA query_only=ON`; no hubo escrituras. Configuracion
efectiva leida sin exponer secretos: `trading_mode=paper`,
`allow_live_trading=false`, `allow_auto_apply_improvements=false`,
`auto_paper_trading=true`.

## Git, merges y conflictos

Base: produccion comprometida `24537e81`.

1. P-L53BR2 `4f656383715c0a943a82716a08c78bce31a4d9fe` integrado con merge
   `01c2c5644d449b235c594e79032b5260c8a82fe1`, tree
   `02bb1c4dcf170c329de21b4be9310ded788b7221`; sin conflictos.
2. P-L43C-R1 `2e6e6158e7601c790e58251769668058058424ca` integrado con merge
   `b61a3036ee05bfa8a6fd2edef90a34e548e9aa73`, tree
   `b1efca4b88f6d350d227e41d415cc1aa9fb42caa`.
   Hubo conflictos en `__init__.py`, `main.py` y `scheduler.py`; se
   resolvieron campo a campo conservando el carrier P-L51, la CLI y el orden
   seguro P-L43C.
3. P-L57A `92f24e4d93da89f51eaf69acbc6cb8c0ad391a0f` integrado con merge
   `e0e1962534e0877fa96fcfd80c524f000a58dafe`, tree
   `74889f9e818adc1b993e9414f2d3e84f0694cc85`.
   Hubo conflictos documentales y en `__init__.py`; se preservaron los
   estados anteriores y la version 0.4.193.

QA combinada: `b066b65c50d0a43713bbcd899304e5b3202753ec`.
El commit documental contiene este informe y las actualizaciones del
plan/relevo.

## Orden real y reutilizacion

Ruta de mercado verificada en codigo y pruebas:

`market data/observaciones -> market_state -> P-L49 Fase A -> aprendizaje y
ranking -> P-L50/P-L44 Fase A -> P-L53 Fase A sobre el contexto rankeado ->
seleccion/recomendaciones -> gates/limites/cuotas/pausas -> controles/planes ->
P-L49 Fase B -> P-L50/P-L44 Fase B -> persistencia/envio activo -> P-L53
finalizacion/persistencia`.

P-L53 no recalcula ranking, aprendizaje, LLM, gates, RiskManager, controles,
planes u ordenes. Su persistencia sucede despues del envio activo. `ordered` y
`broker_order_id` solo aparecen cuando el objeto reutilizado aporta identidad
exacta; en otro caso permanecen `null/unavailable`.

PMR real en el candidato:

`reconciliation -> postmarket_report -> canonical_operation_telemetry (P-L48)
-> canonical_trade_attribution (P-L51) -> canonical_eod_account_snapshot
(P-L52) -> performance -> measurement_pipeline -> thesis -> terminal`.

P-L48, P-L51 y P-L52 tienen una construccion y persistencia por PMR efectivo y
los consumidores reciben el mismo objeto. No se vuelve a consultar broker,
cartera, SPY, outcomes ni reconciliacion para reconstruirlo. P-L53 queda fuera
del PMR.

Para P-L43C el orden post-submit comprobado es:

`captura inmutable en memoria -> submit activo -> save_broker_order canonico
-> persistencia P-L43C decision/link fail-open -> reconciliacion`.

Si falla `save_broker_order`, no se persiste un link que aparente una orden
local durable. Si falla P-L43C, la orden y su resultado activo permanecen. Si
falla submit, se conserva el error activo sin inventar `broker_order_id`.

## Identidades y null-safety

| Lote | Identidad canonica | Separaciones verificadas |
|---|---|---|
| P-L49 | observacion OHLCV + proveedor + intervalo + timestamp de barra + price basis | no une por simbolo/fecha |
| P-L50/P-L44 | `signal_capture_id -> signal_id` + action + recommendation | BUY y EXIT separadas |
| P-L53 | `cycle_id + action + signal_capture_id`, fallback exclusivo a `signal_id` | `candidate_id` auxiliar; no usa texto |
| P-L51 | `broker_order_id` + lote/carrier + allocations exactas | recompras y multilote separados |
| P-L52 | session/account/currency/ventana + contributions exactas | no convierte fragments en operaciones |
| P-L43C | decision_id + plan/position + broker/client order | `trigger=time_stop_v2` no es autoridad |

P-L57A mantiene `null`, `unavailable`, `partial` y `not_applicable`
distintos. `pnl_pct`, `previous_equity`, alpha, drawdown, costes y flujos
ausentes no se convierten en cero ni se reconstruyen. Scoreboard, promotion
readiness, digest y serie web conservan filas validas y publican cobertura
parcial.

## Perfil P-L53BR2

Medicion temporal sobre SQLite temporal, 100 ciclos de 500 candidatos y 3
escalas adicionales por 250/500/1000. El test informo:

| Segmento | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|
| Fase A, 500 | 202.7304 | 209.7147 | 221.2068 |
| Finalizacion | 16.2282 | 18.2743 | 20.9481 |
| Construccion total | 382.1593 | 399.9323 | 409.5260 |
| Hash/serializacion medida | 131.0679 | 141.2780 | 148.0200 |
| Espera `BEGIN IMMEDIATE` | 0.5477 | 0.6638 | 0.8428 |
| Dentro de transaccion | 4.1269 | 17.2708 | 18.2532 |
| Persistencia total | 68.5087 | 80.4210 | 82.4719 |
| Shadow total | 512.5990 | 529.7794 | 540.2943 |

El evento de 500 candidatos fue 757177 bytes; memoria pico 17067021 bytes;
WAL pico/final 0 bytes. Se observaron 109 eventos, conexiones y transacciones:
100 ciclos de volumen y 9 casos de escala. No hubo `database is locked`.

El tamaño por candidato fue aproximadamente constante: 250 = 375497 bytes,
500 = 751173 y 1000 = 1510506. Proyeccion descriptiva, no capacidad
garantizada: a 26 ciclos de 500 candidatos son aproximadamente 19.7 MB de
payload diario; a 100, 75.7 MB. El riesgo operativo se clasifica `medium`
por tamaño de evento, memoria y latencia de shadow; la persistencia ocurre
despues del envio activo y no bloquea decisiones. No se midio una nueva serie
numerica de interaccion completa P-L43C/P-L57A con el perfil, por lo que esa
interaccion queda `unavailable` como capacidad cuantificada.

## QA y gates

- Focales fusionadas P-L43C/P-L52/P-L53/P-L57 y regresiones relacionadas:
  `19 passed, 1 warning`.
- QA nueva `tests/test_p58r1_combined_safety.py`: `3 passed`; con la gate de
  version policy: `4 passed`.
- Suite completa `python -m pytest tests/ -x -q` con `PYTHONPATH` y
  `DATA_DIR` temporales: `1987 passed, 1 skipped, 1 warning` en 693.46 s.
- El unico skip es preexistente:
  `tests/test_pre_earnings.py::test_score_study_regression_current_sqlite`.
  Intenta abrir literalmente `data/state/agente_bolsa.sqlite3` y se salta si
  no existe (o si no hay 70 eventos resueltos). No se abrio desde la suite ni
  se anadio skip/xfail. Las pruebas temporales de pre-earnings y el resto de
  regresiones pasaron, pero no sustituyen la historia productiva.
- La suite incluyo la prueba sintetica de batching de 33336 filas de P-L45B2;
  no se uso SQLite productiva ni se hizo un reproceso postmarket.
- Ruff completo: OK. `scripts/check_no_nulls.py`: OK, 429 archivos.
  `git diff --check`: OK. `validate-agent-config --json`: OK, 23 agentes,
  6 tareas habilitadas.
- Smoke CLI `run-once --skip-crew`: `smoke_unavailable_by_safety`; no se
  inicio porque el entrypoint no permite garantizar simultaneamente proveedor
  local, Store temporal y ausencia de broker/red/LLM sin monkeypatch dentro del
  proceso. La QA combinada y las pruebas de ciclo/postmarket usaron objetos y
  Store temporales monkeypatched.

## Paridad y proteccion

Los blobs Git de los archivos protegidos son iguales a produccion:

| Archivo | Blob |
|---|---|
| `src/agente_bolsa/kernel.py` | `35788edf80cc02c015fdef24f7c62fe8a490a442` |
| `src/agente_bolsa/tools/broker.py` | `2050468ca4d81f06bb58464a688eaf4d916f80e5` |
| `src/agente_bolsa/tools/execution.py` | `018c52f0754bec4a1f8cf8440f308bc10b01a588` |
| `src/agente_bolsa/tools/risk.py` | `75c1242c2f10c989120243ca1149e22749d342bb` |
| `src/agente_bolsa/config.py` | `912e943b24160b5e4b1fb4b1f60dbdf15f4c9e9f` |

No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
`config.py` ni `.env`. Se verifico `kernel-status` de produccion sellado y
valido; el candidato temporal aparece `unsealed` por falta de manifiesto, lo
que no describe produccion. Las pruebas de paridad cubren candidatos, scores,
ranks, recomendaciones, gates, sizing, microexperimentos, planes, cantidades,
precios, stops/takes/trailing, requests broker, ordenes, exposicion y limites.

Estado externo: operational health no reporto alertas criticas nuevas y
`adaptive_auto_apply_authorized=false`; existe una advertencia preexistente de
gobernanza adaptativa degradada con seis overrides marcados
`preexisting_unauthorized`. No fue creada ni modificada por este lote.

## Limites y siguiente paso

Las sombras no autorizan promocion ni cambios de trading. No se hizo
despliegue, reinicio, merge productivo, broker, red, LLM, job manual, backfill,
SQLite productiva en escritura ni push. Siguiente paso unico: preflight humano
y validacion de despliegue en una ventana cerrada, con comprobacion de la
advertencia de gobernanza y un smoke completamente aislado antes de cualquier
promocion.
