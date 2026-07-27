# Relevo de direccion tecnica — agenteBolsa

> Actualizado: **20-jul-2026**. Produccion **0.4.185** (`8cfa0db3`, tree
> `4c3636be`). P-L48B desplegado en mercado cerrado; P-L44B sigue en shadow.

> P-L50BR1: el worktree combinado queda en candidato **0.4.188**, con la
> secuencia P-L49B 0.4.186 -> P-L46BR3 0.4.187 -> P-L50B 0.4.188. No es un
> despliegue productivo.

> P-L51BR1 (21-jul-2026): el worktree combinado queda en candidato **0.4.189**.
> P-L51B-W esta integrado como shadow fail-open, pero la captura futura real
> queda bloqueada por falta de provenance BUY->SELL y fill fragments canonicos
> en los objetos persistidos. Dictamen: `needs_redesign`; produccion intacta.

> P-L51C-T (21-jul-2026): el carrier minimo ya esta caracterizado en tests.
> La frontera seleccionada es metadata del `order_plan` transportada al payload
> local de `broker_order`; sobrevive reconciliacion y no cambia el request del
> broker. P-L48 aun lo descarta al proyectar operaciones. Siguiente lote:
> implementar esa proyeccion acotada sin tocar kernel/broker/execution/risk/config.
> Dictamen: `ready_for_p51c_implementation`.

## Objetivo

Mejorar beneficio neto sin aceptar grandes caidas y construir expertos
autonomos que aprendan con evidencia. Live, apply, configuracion sensible y
promociones siguen human-gated.

## Produccion

- Paper activo; live y auto-apply desactivados.
- Kernel sellado sin violaciones. `unsealed` temporal no describe produccion.
- P-L45B1 desplegado: un postmarket efectivo, reconciliacion coordinada, una
  actualizacion de outcomes y terminales duraderos.
- P-L48B desplegado (19-jul): telemetria canonica shadow `p-l48b.canonical-operation-telemetry.v1`
  unidad `broker_order_id`; consumo read-only en digest/health/CLI/performance_daily.
  Sin backfill, sin tablas/migraciones, sin autoridad sobre trading.
- P-L43: legacy gobierna time-stop; XNYS es exclusivamente shadow.
- Cohortes P-L27/P-L29/P-L30/P-L31/P-L32/P-L33 siguen collecting.
- Overrides adaptativos historicos permanecen; la frontera actual impide nuevas
  promociones con auto-apply false.
- P-L49B-W queda en ensayo aislado como `0.4.186`: captura/finalización shadow
  de calidad por candidato, evento append-only y consumidores read-only. No
  concede autoridad sobre entradas, gates ni salidas y requiere identidad de
  observación y temporalidad verificables.

## Secuencia validada

1. **0.4.175 P-L45B2**: observations en chunks de 250; 33.336 filas, 134
   commits, paridad exacta y sin locks normales; desplegado dentro de 0.4.176.
2. **0.4.176 P-L43BR5**: autoridad desde buy order exacta; corrige
   `PositionSide.LONG -> unsupported_side` solo en shadow.
3. **0.4.177 P-L44B**: penalizacion unica solo shadow; esperar evidencia real.
4. **0.4.178 P-L46B UI**: Cartera abierta por ultima compra y fecha/hora.

P-L46B queda desplegado como cambio exclusivamente visual; la fecha procede
de lotes BUY filled locales verificables y las posiciones sin autoridad quedan
al final como `Fecha de compra no disponible`.

No combinar releases sin ensayo conjunto. Despliegue: XNYS cerrado, sin jobs,
suite verde, hash sensible intacto y rollback por revert.

## Evidencia reciente

- P-L43C: 69 portfolio watches, cinco eventos idempotentes, cero ordenes XNYS.
- P-L45A: postmarket p50 ~23 min, maximo ~41 min; P-L45B1 coordina y P-L45B2
  reduce commits.
- 7–13 jul: cuenta -0,0401%, SPY +0,1953%; muestra/exposicion insuficientes.
- Salidas time-stop: muestra pequena/mixta; no cambiar politica aun.

## Agenda

- Cada sesion: ciclos, identidad, shadow, ejecucion y terminal PMR.
- Tras P-L45B2: cinco sesiones antes de juzgar duracion/locks; evidencia aún
  collecting.
- 20-jul: relectura `builtin_pullback`.
- 27/28-jul: primeras madureces tecnicas RR/salidas, aun no muestra suficiente.
- Tras 45 dias agent_run: evaluar roles.
- 1-sep: dictamen de aprendizaje con criterio original.

## Reglas

- No rellenar legacy ni IDs por simbolo/fecha.
- No usar fills/P&L como forward.
- No promover collecting/unavailable.
- No tocar archivos protegidos sin revision humana.
- No desplegar/reiniciar con XNYS abierto salvo emergencia expresa.
- No servicios manuales: tareas y `scripts/stack_*.ps1`.
- No ocultar suite roja con skip/xfail.

## Comandos

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
```

`docs/plan_mejoras_y_tareas.md` es la unica fuente de tareas.

## P-L43C-W - estado del candidato shadow (22-jul-2026)

- Candidato aislado: worktree `pl43c_exit_authority_impl`, rama
  `codex/pl43c-exit-authority-impl`, version `0.4.192`.
- La autoridad activa sigue siendo `legacy_calendar_days`; XNYS es
  `shadow_only`. No se modifica la politica ni la llamada protegida
  `close_position(symbol)`.
- Carrier: captura en memoria antes del submit; decision/link append-only
  despues del intento; identidad exacta de lote y conflicto seguro. Sin
  simbolo/fecha/FIFO.
- QA: 40 pruebas P-L43C-W, 178 focales relacionadas, Ruff/NUL/diff/config
  verdes. Suite completa, smoke aislado y validacion cerrada integrada quedan
  pendientes; no desplegar hasta completarlos con XNYS cerrado.

### P-L43C-R1 - orden durable post-submit (22-jul-2026)

- Worktree aislado `pl43cr1_exit_authority_ordering`, version `0.4.192`.
- La prioridad corregida es `submit -> save_broker_order local -> persistencia
  P-L43C fail-open -> reconciliacion`.
- La reproduccion de la base observo `submit -> P-L43C -> save_broker_order`;
  la prueba R1 confirma el orden corregido, sin duplicar save ni alterar la
  llamada activa.
- 44 pruebas focales y Ruff verdes. Suite completa, smoke, benchmark largo y
  validacion cerrada permanecen pendientes con XNYS cerrado.
## P-L43B — estado del candidato shadow (15-jul-2026)

- P-L43BR4 desplegó en producción la versión `0.4.173` mediante merge no destructivo.
- `legacy_calendar_days` es la única ruta activa de `time_stop_v2`; XNYS es exclusivamente shadow.
- La evidencia histórica usa eventos append-only por `position_identity` y `shadow_observation_id`; `runtime_state` es `latest_view`.
- Los datos prospectivos reales permanecen `collecting`; la activación XNYS requiere autorización humana y otro lote.

## P-L44BR2 — ensayo de integración shadow (15-jul-2026)

- El candidato `0.4.177` integra P-L44B sobre P-L43BR5 desplegado mediante un
  merge no destructivo en un worktree aislado.
- `legacy_double_application` sigue activa; `single_application` es sólo
  shadow y los datos reales permanecen `collecting`.
- Dictamen del ensayo: `ready_for_future_shadow_deployment`; producción no se
  modificó ni reinició.

## P-L47B1 — recuperación de leases desplegada (0.4.180)

El despliegue del 18-jul-2026 (`f60a3d82`) confirmó que Windows ejecuta un
único scheduler lógico mediante wrapper → launcher `.venv` → runtime Python.
El lock v1 quedó asociado al runtime real. El bootstrap recuperó de forma
append-only el lease terminal residual de reconciliación, conservó el terminal
original y no reprocesó postmarket, reconciliación ni outcomes. No cambian
stops, takes, time-stop, ranking, gates, órdenes, exposición ni límites.
P-L43BR6 y P-L44BR3 permanecen fuera y conservan los slots `0.4.181` y
`0.4.182`.

## Secuencia post-P-L47B1 del ensayo

## Estado actual tras el despliegue P-L43BR6 + P-L44BR3 (18-jul-2026)

- Producción: versión `0.4.182`, merge `7cc432aee3f594d946f5a65d1f86f3e49fa82e4`.
- Secuencia: P-L47B1 `0.4.180`, P-L43BR6 `0.4.181`, P-L44BR3 `0.4.182`.
- El stack quedó con un scheduler lógico wrapper → launcher venv → runtime,
  lock v1 propiedad del runtime y heartbeat fresco.
- `legacy_calendar_days` y `legacy_double_application` siguen siendo las
  políticas activas; XNYS y `single_application` continúan exclusivamente
  shadow. La evidencia sigue `collecting`/`partial`, sin backfill.

- 0.4.180: P-L47B1 desplegado.
- 0.4.181: P-L43BR6 integrado primero en este ensayo.
- 0.4.182: P-L44BR3 integrado después; versión final del ensayo.
- Ambos lotes continúan exclusivamente shadow y no modifican trading.
## P-L44BR3 — corrección del contrato lector (candidato 0.4.181, 18-jul-2026)

- Se corrigió la frontera de lectura del shadow: primero se valida
  `signal_capture_id`/`signal_id` y después la disponibilidad de scoring.
- Los candidatos identificados sin inputs quedan `shadow_inputs_unavailable`;
  no se convierten en `identity_unavailable` ni reciben score inventado.
- Digest, health y CLI cuentan un único evento canónico por `cycle_id`, ignoran
  filas genéricas del reporter y dejan los conflictos visibles.
- P-L44 conserva `legacy_double_application` activa y
  `single_application` exclusivamente shadow. La evidencia previa queda
  invalidada para interpretación y no se hace backfill; P-L43BR6 sigue como
  prioridad `0.4.181`; P-L44BR3 deja el ensayo en `0.4.182`.

## P-L44BR3 — despliegue cerrado (17-jul-2026)

- Producción quedó en `0.4.177` mediante el merge `23e4bf4d`, con el tree
  validado del ensayo y sin incluir P-L46B.

## P-L48B-W - telemetria canonica de operaciones (candidato 0.4.184)

- Productor shadow unico `p-l48b.canonical-operation-telemetry.v1` con unidad
  `broker_order_id`, denominadores separados y freshness descriptiva.
- Evento append-only por sesion, hash estable excluyendo `captured_at`,
  idempotencia y conflictos auditables. Consumidores read-only.
- No altera trading ni activa ninguna politica shadow; P-L43/P-L44/P-L45/P-L47
  permanecen con sus invariantes.

## P-L48BR1 - ensayo de integracion superado (0.4.185)

- Worktree `pl48br1_integration_rehearsal`, rama
  `codex/pl48br1-integration-rehearsal`: merge `--no-ff` del candidato exacto
  mas tres commits QA (`b3155389`, `919f58b6`, `77d2e743`).
- QA adversarial completo (65 pruebas nuevas): fuente unica, orden postmarket,
  fail-open, idempotencia, fragmentacion, ANET, performance_daily,
  reconciliacion, freshness, volumen, lectores y paridad
  P-L43/P-L44/P-L45/P-L47. Suite 1689 passed y gates en verde.
- Tres defectos del candidato corregidos en el ensayo (D1 centinela
  `_MISSING`, D2 digest tras conflicto, D3 `candidate_count`); un defecto
  preexistente de `profitability_scoreboard` documentado para el backlog.
- Dictamen: `ready_for_closed_market_deployment`. Siguiente paso: despliegue
  con XNYS cerrado mediante merge `--no-ff` del tree validado del ensayo a
  produccion, conservando los commits QA.
- `legacy_double_application` conserva la autoridad; `single_application` es
  exclusivamente shadow y la captura real permanece `collecting`.
- Suite, kernel, configuración y stack pasan; no se generaron órdenes por P-L44B.

## P-L48BD - despliegue cerrado de P-L48B (0.4.185). DEPLOYED

- Auditoria P-L48BD-P: `single_logical_stack_launcher_runtime_chains`,
  `ready_to_resume_p48bd`. Una sola cadena logica por servicio
  (launcher venv → runtime Python base); el `scheduler.lock` v1 pertenece al
  runtime APScheduler hijo del launcher `.venv`, no al launcher. No se
  "normalizo" la topologia.
- Stack down con `scripts\stack_down.ps1 -IncludeScheduled`; merge `--no-ff`
  de `266950a0` a produccion: commit `8cfa0db3`, tree funcional
  `4c3636be` identico al ensayo, sin conflictos, sin squash/rebase/amend.
- Validacion con stack detenido: baterias P-L48BR1 + P-L48B-T/W (111 passed),
  focales scheduler/storage/postmarket/performance/reconciliation/execution/
  digest/health/CLI y P-L43/P-L44/P-L45/P-L47 (verdes), suite completa ≈1693
  passed/0 fallos, Ruff limpio, `check_no_nulls.py` OK, `git diff --check` OK,
  `validate-agent-config` `ok=true`, `kernel-status` sellado sin violaciones.
- `scripts\stack_up.ps1`: dos comprobaciones con HTTP 200/200, unico listener
  8501, lock v1 PID 49096 token `134289557074352030` coincide con el runtime
  real, `post_market_coordination:active = None`, 0 ordenes desde el reinicio,
  0 `database is locked`, health `warning` con 0 alertas criticas.
- Bootstrap: `terminal:skipped` reason `market_not_ready` unico; sin reprocesar
  17-jul, sin repetir reconciliacion/outcomes, sin crear telemetria/ordenes ni
  lease residual. Estado P-L48B inicial: CLI/digest/health `collecting`,
  denominadores null, 0 eventos canonicos, sin backfill.
- Deuda `profitability_scoreboard` (`pnl_pct=NULL` sin `max_dd`) NO corregida
  (backlog). Sin push. Produccion `8cfa0db3` / tree `4c3636be` limpia.

## P-L49BR1 — relevo de QA

- Worktree de ensayo: `pl49br1_shadow_rehearsal`, merge `2ea57983`, QA
  `b8aee78a`/`db6577b2`, versión `0.4.186`; producción no modificada.
- Hallazgo operativo: `market_snapshot`/`market_state` no transportan hoy la
  observación OHLC exacta por feature. El shadow lo hace visible como
  `unavailable_temporal` y conserva `PARTIAL`; nunca convierte calidad global
  en bloqueo ni usa un informe posterior.
- La corrección de identidad canónica (zona horaria equivalente y `-0.0`) y la
  clasificación temporal están solo en el ensayo. Suite completa y smoke
  requieren ventana con XNYS cerrado; P-L48C permanece prohibido hasta
  postmarket terminal.
## P-L46BR3 - metricas del periodo de cartera (candidato 0.4.187)

- Corrige una contradiccion visual: la grafica mostraba equity descendente,
  pero `P/L desde abril` usaba el P/L del historial de operaciones y podia ser
  positivo. Ahora `Resultado del periodo` usa exactamente los extremos de la
  curva visible y sigue el filtro de rango.
- El bloque queda reducido a `Resultado del periodo` y `P/L abierto`; `P/L
  hoy` se mantiene solo en la cabecera. El abierto procede de las posiciones
  actuales ya obtenidas.
- `Desde inicio` solicita todo el historial disponible. Cabecera y control
  externo quedan alineados con la misma serie de equity.
- Solo UI/lectura; no cambia rutas de trading ni persistencia. P-L49 mantiene
  el slot `0.4.186`; P-L46BR3 usa `0.4.187`.
## P-L50BR1 - ensayo combinado pendiente de validacion cerrada

Secuencia del worktree: P-L49B `0.4.186`, P-L46BR3 `0.4.187`, P-L50B `0.4.188`.
Los shadows conservan identidades y eventos independientes; la UI sigue siendo
solo lectura. QA focal: 675 passed; interacción: 10 passed. XNYS estaba abierto,
por lo que no se ejecutaron suite completa, smoke ni despliegue.

## P-L50BR1 - cierre del relevo QA (20-jul-2026)

- Worktree/rama: `C:\Antonio\Bref\agenteBolsa_worktrees\pl49_pl46_pl50_combined_rehearsal`,
  `codex/pl49-pl46-pl50-combined-rehearsal`; versión final `0.4.188`.
- Orden de merges: `0f5a26a0` P-L49B (`753136fc`), `17b5fbc7` P-L46BR3
  (`a0ab7ce4`), `045288dd` P-L50B (`8ebac5f2`). QA adicional: `c99cd318`.
- Secuencia temporal y separación de identidades verificadas; los shadows son
  fail-open y la UI es read-only. No se modificaron kernel, broker, execution,
  risk, config ni `.env`.
- QA: 90 + 84 + 211 + 290 = **675 passed**; Ruff, nulls, diff y
  `validate-agent-config --json` temporal (`ok=true`) verdes.
- Producción permanece en `24537e81`/0.4.185 con solo su suciedad UI previa;
  candidatos originales permanecen en sus HEAD/tree indicados. No hubo
  despliegue, reinicio, detención de servicios ni push.
- Pendiente con XNYS cerrado: suite completa, smoke, jobs reales y validación
  histórica de 33.336 filas. Dictamen:
  `ready_for_closed_market_full_validation`.

## P-L50B - candidato shadow de linaje (0.4.188)

- Corrige el wiring P-L44 preparando `signal_capture_id`/`signal_id` antes de
  anotación y ranking y proyectando una copia profunda acotada hacia fase A.
- El schema v2 separa identidad, inputs, decisiones (`action` +
  `recommendation_id`), controles, rechazos canónicos y freshness descriptiva;
  el lector mantiene compatibilidad v1 declarada.
- No parsea texto, no inventa IDs, no convierte missing en cero y no enlaza por
  símbolo/fecha. No altera ranking, selección, gates, sizing, planes ni órdenes.
- Fixture 443: 425 identidades verificadas, 8 unavailable, 10 ambiguous, 420
  inputs disponibles y 23 unavailable. Estado `ready_for_integration_rehearsal`.
- P-L49B conserva el slot 0.4.186 y P-L46BR3 el 0.4.187. No hubo despliegue ni
  push; la suite completa queda para mercado cerrado.

## P-L51C-W - relevo del carrier BUY -> SELL (candidato 0.4.189)

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl51c_provenance_carrier_impl`;
  rama `codex/pl51c-provenance-carrier-impl`; base P-L51C-T
  `0c5f1314986d5cf8bfdbe3a691dd7706be096903`.
- La frontera validada es metadata de `order_plan` transportada al payload
  local de `broker_order`, conservada por reconciliacion y proyectada de forma
  explicita por P-L48 para P-L51. No se cambia el request broker ni la ruta
  activa.
- End-to-end temporal: `buy-1 -> sell-1`, fills canonicos 2, allocation 1,
  `attributed_sell_count=1`, `closed_lot_count=1`, gross 100.0 y net 98.5.
  Costes incompletos, historicos sin carrier y provenance ambigua permanecen
  null/unavailable; no se hace FIFO ni backfill.
- Commits: `c86917ee feat: persist exit lot provenance carrier` y
  `5c0077d9 test: verify end-to-end exit lot provenance`. Falta el commit
  documental de este lote.
- No promover ni desplegar con XNYS abierto. Siguiente gate: ejecutar Ruff,
  `check_no_nulls.py` y `validate-agent-config --json` con DATA_DIR temporal;
  posteriormente, con XNYS cerrado y PMR terminal, suite completa, smoke y
  validacion de mercado cerrado. Sin cambios en archivos protegidos, produccion,
  SQLite productiva, servicios, reinicios o push.
## P-L51CV2 - validacion completa nocturna (21-jul-2026)

- Candidato `codex/pl51c-provenance-carrier-impl`, HEAD
  `a889dd976af11435bbcaf2d9a8e8cd59981e546b`, tree
  `7f04dbb5f528388cc01b060839378d141b39cdb6`, version `0.4.189`, limpio.
- PMR terminal y lease vacio; suite `1864 passed, 1 skipped`, focales y
  regresiones `364 passed`, P-L45B2 `1 passed`, Ruff/NUL/diff/configuracion
  verdes. El smoke real queda `smoke_unavailable_by_safety`; el sustituto
  seguro paso 8 pruebas.
- Dictamen: `ready_for_closed_market_deployment`, sin despliegue. La siguiente
  tarea decide/promueve separadamente y conserva el control humano; no tocar
  produccion, SQLite productiva, servicios, archivos protegidos ni hacer push.
## P-L52B-T — snapshot EOD contable y benchmark comparable (21-jul-2026)

- Se caracterizó en worktree aislado el contrato
  `p-l52b.canonical-eod-account-snapshot.v1`, sin cambios en `src` ni en
  producción. La ecuación probada es `delta_equity = flows + net_realized_pl
  + delta_open_pl + residual`.
- El contrato exige ledger exacto de flujos, costes completos para neto,
  posiciones/lot IDs exactos y SPY con misma ventana, timestamps, `price_basis`
  y calidad. P-L52A queda reproducible como pérdida absoluta verificada, cash
  opportunity descriptiva y residual/atribución unavailable.
- Resultado: `21 passed` P-L52B-T, `248 passed` focales, Ruff/NUL/diff/config
  verdes. Dictamen: `ready_for_p52b_implementation`.
- Próximo lote: implementación shadow mínima, fail-open y append-only, sin
  tablas/migraciones ni consumo en trading hasta demostrar paridad.

## P-L52B-W — implementación shadow EOD contable (candidato 0.4.190)

- Worktree/rama: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52b_eod_snapshot_impl`,
  `codex/pl52b-eod-snapshot-impl`, base `609183e1`.
- Secuencia PMR verificada en tests: P-L48 → P-L51 → P-L52 → performance.
  P-L52 reutiliza los objetos ya construidos, publica el contrato
  `p-l52b.canonical-eod-account-snapshot.v1`, conserva missing/unavailable y
  falla abierto. No aparece en la ruta de trading ni toca archivos protegidos.
- Commits: `57ec7b7f` feature, `eb17d582` tests, `4e868109` QA freshness.
  Focales del lote: `32 passed`; Ruff y diff verdes.
- Estado: `ready_for_integration_rehearsal`, no desplegado. Suite completa,
  P-L45B2, smoke y promoción quedan pendientes con XNYS cerrado y PMR terminal.

## P-L52BR1 — cierre del ensayo integrado (22-jul-2026)

- Ensayo: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52br1_integration_rehearsal`,
  rama `codex/pl52br1-integration-rehearsal`, version 0.4.190.
- Merge `36bdd366` (`--no-ff`) de P-L52B-W; correccion QA `932c648a`.
- Secuencia final: reconciliation -> P-L48 -> P-L51 -> P-L52 -> performance ->
  measurement -> thesis -> terminal. Los tres eventos son append-only,
  idempotentes/conflict-safe y fail-open; el mismo objeto P-L52 llega a
  performance.
- Evidencia E2E real temporal: BUY/SELL carrier exacto, reconciliacion,
  `attributed_sell_count=1`, neto 98.5 y contribution exacta por lote. Las
  salidas multi-lote sin importe por allocation quedan con importe null.
- QA: `1899 passed, 1 skipped, 1 warning`; P-L45B2 33.336 filas pasado,
  volumen 100 sesiones/1000 operaciones sin locks, Ruff/NUL/diff/config verdes.
  Smoke CLI real: `smoke_unavailable_by_safety`; sustituto aislado verde.
- Produccion 0.4.185 y candidatos P-L51C/P-L52B-W intactos. Kernel productivo
  sellado; archivos protegidos iguales a base/produccion. No hubo SQLite
  productiva, despliegue, reinicio, servicios ni push.
- Dictamen: `ready_for_closed_market_deployment`. Siguiente paso: preflight
  operativo independiente y autorizacion humana; no promover automaticamente
  desde este ensayo.
## P-L51CR2 - correccion de regresiones temporales de provenance (22-jul-2026)

- El padre P-L52BR1 fue reproducido en un worktree nuevo. Los tres fallos de
  provenance no eran perdida de carrier: las fixtures persistian ordenes con
  `created_at` del 22-jul y consultaban sesion 21-jul.
- `9a7b46d2` anade la caracterizacion de la frontera temporal y `494e6515`
  congela el reloj de las tres pruebas. No cambia `src/`, por lo que la version
  permanece `0.4.190`; no se reserva 0.4.191 para este lote.
- Resultado: tres regresiones verdes, `239` focales relacionadas y suite segura
  `1900 passed, 1 deselected`. La exclusion es unicamente el test legado que
  apunta a `data/state/agente_bolsa.sqlite3`; no se anadieron skips/xfails.
- El carrier sobrevive plan -> orden local -> reconciliacion -> P-L48 -> P-L51
  -> P-L52 con IDs exactos, sin joins por simbolo/fecha y con request broker
  identico. Produccion, P-L52BR1 y P-L53BR1 permanecen intactos.
- Dictamen: `ready_for_reintegration`. Siguiente lote: reintentar P-L53BR1
  sobre este worktree con slot posterior 0.4.192, sin ejecutarlo ahora.

## P-L53B-W - handoff del candidato 0.4.191

- Worktree aislado: `C:\Antonio\Bref\agenteBolsa_worktrees\pl53b_selection_ledger_impl`;
  rama `codex/pl53b-selection-ledger-impl`.
- Commits funcional/QA: `e5ace319` y `eea3794a`; falta únicamente el commit
  documental separado de este lote.
- El ledger shadow captura una vez por ciclo la fase A completa y las etapas
  reales de decisión posteriores, con identidad `signal_capture_id` exacta,
  fallback explícito `signal_id`, estados separados y persistencia
  append-only/conflict-safe.
- No cambia prompts, ranking, selección, LLM, gates, sizing, planes, órdenes,
  broker requests, exposición ni límites. Históricos sin identidad permanecen
  unavailable; outcomes futuros se unen solo por identidad y madurez XNYS.
- Validación focal P-L53B-T/W: 28 passed, Ruff/check_no_nulls/diff/version en
  verde. Suite completa y smoke están pendientes de precondiciones cerradas.

Siguiente lote único: P-L53BR1, ensayo integrado aislado desde el candidato
0.4.191; no desplegar ni hacer push antes de esa validación.

## P-L53BR1 - ensayo integrado sobre P-L52BR1 (22-jul-2026)

## P-L53BR2 - relevo final del reensayo limpio (22-jul-2026)

- Worktree `C:\Antonio\Bref\agenteBolsa_worktrees\pl53br2_integration_rehearsal`,
  rama `codex/pl53br2-integration-rehearsal`, base `2da5ccda`, merge
  `3b2ae0bf`, version `0.4.191`.
- Gate temporal `3 passed`; QA de volumen `2bb92a4b`/`165ad748` y fixture
  concurrente `ff6267a0`, sin cambio productivo.
- Orden de mercado y PMR conservado; P-L53 fase A tras ranking, finalizacion
  despues del envio activo y fuera de PMR. Identidades/paridad exactas.
- BR2: 100x500 y escalas, 109 eventos/conexiones/transacciones, evento p50/max
  `757177`, memoria pico `17066653`, WAL `0`, shadow p50 `511.6280 ms`; riesgo
  `medium`, sin O(n2) descriptivo y sin retraso del envio.
- Suite final `1933 passed, 1 deselected, 1 warning`; el unico deselect es el
  test legado que abre `data/state/agente_bolsa.sqlite3`; no hay skips/xfails.
  P-L45 33.336 esta incluido. Smoke real:
  `smoke_unavailable_by_safety`.
- Dictamen: `ready_for_closed_market_deployment` como candidato no desplegado.
  Siguiente paso unico: preflight cerrado y autorizacion humana; no deploy ni
  push desde este ensayo.

- Se creó el worktree aislado `pl53br1_integration_rehearsal` desde
  `134ec525` y se fusionó P-L53B-W con `--no-ff` en `fc4eb767`; la QA quedó en
  `52668b42`. Versión final: `0.4.191`.
- La ruta de mercado verificada conserva P-L49/P-L50/P-L44, añade P-L53 como
  sombra predecisión/finalización y no altera decisiones ni retrasa el envío.
  El PMR permanece `reconciliation -> P-L48 -> P-L51 -> P-L52 -> performance
  -> measurement -> thesis -> terminal`, con sus etapas previas ya validadas.
- La batería combinada cubrió 500 observaciones, 37 anomalías, 443 candidatos,
  20 finalistas, 5 recomendaciones, 3 planes y 2 órdenes; la persistencia
  concurrente fue `inserted` sin locks, con idempotencia y conflictos separados.
  El volumen 100x500 fue verde, con p50/p95/máximo de construcción
  373,9511/406,0575/434,1302 ms y persistencia 67,8627/82,5894/86,6022 ms.
- Gates: Ruff, NUL, diff, configuración, versión, kernel productivo sellado y
  suite segura `1928 passed, 4 deselected`. Tres tests P-L51/P-L51C fallan
  también en el padre P-L52BR1 y quedan como deuda heredada; el cuarto es el
  test legado que intenta abrir SQLite productiva. No se añadieron skips/xfails.
- Dictamen: `needs_fix`; no desplegar. Siguiente lote mínimo: resolver esos
  tres focales heredados y repetir suite/preflight cerrado. Producción,
  servicios, SQLite productiva, locks y candidatos originales permanecen
  intactos; no hubo reinicio, despliegue ni push.
