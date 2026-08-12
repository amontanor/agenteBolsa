# Relevo de direccion tecnica — agenteBolsa

### P-L70 — resumen diario Telegram UX (candidato 0.4.203)

- Base `87d29018`/árbol `fd690a93`; worktree aislado
  `pl70_telegram_summary_ux`; rama `codex/pl70-telegram-summary-ux`.
- El resumen usa `p-l70.telegram-daily-summary.v2`, conserva idempotencia por
  `session_date`, no toca fills y no envía mensajes durante pruebas.
- El saldo es absoluto; la variación monetaria exige el par equity de
  `performance_benchmark`; SP500 conserva valor provisional sin declarar
  ganador si P-L68 no confirma comparabilidad; posiciones llevan cobertura y
  grupos deterministas.
- Implementación `f78de077` y QA `0a18924c`, `b3c4d1c2`, `7e96191a`,
  `12de9be5`, `1b64dc5a`. La regresión de fecha dinámica P-L63 quedó congelada
  en el test, sin tocar comportamiento. El recibo v2 conserva texto exacto,
  `text_sha256` y unidades UTF-16; `content_hash` sigue siendo el hash del
  payload canónico. La suite aislada final obtuvo `2261 passed, 1 skipped, 1
  warning`; el skip es el test condicional preexistente
  `test_score_study_regression_current_sqlite` por historia local insuficiente
  o no disponible. Ruff/NUL/diff/compile/config verdes. No se ejecutó smoke real
  ni se enviaron mensajes.

> Actualizado: **28-jul-2026**. Producción estable **0.4.201**
> (`915481ab325d46c81a92986bfd603f13c5134dd9`, árbol funcional
> `f3a2eda76f3c317d68d8679ce00a7ea43a6aa023`). P-L67R1 desplegado y
> validado con dos comprobaciones; candidato final `b25c9603` conservado.

### P-L71 — autoridad EOD y coherencia temporal Sistema vs benchmark

- Candidato aislado `pl71_eod_authority`, versión `0.4.205`. La base de
  producción `0.4.202` conserva el SPY 28-jul incorrecto en storage; no se
  reescribió ni se hizo backfill.
- El bug era la elección por nombre/hash de caches mutables same-day. Ahora se
  exige metadata diaria, rango, fuente, basis explícita, par de cierres y
  autoridad temporal; la vista puede usar solo un cache posterior validado.
- La cabecera live muestra su propia captura/as_of y el panel diario/Telegram
  rotulan `SPY (ETF S&P 500)` y `Provisional`/`n/d` cuando corresponde. No hay
  cambios de trading ni despliegue. Siguiente: ensayo cerrado P-L71 con suite
  completa verde (2260 passed, 1 skip preexistente) y smoke temporal pendiente
  de un ensayo posterior sin servicios reales.

### P-L67R1 — despliegue productivo 0.4.201

- Se preservaron los cambios productivos previos en `b2d7c5c6`; el merge
  `--no-ff` `915481ab` resolvió versión, plan y UI campo a campo.
- El árbol funcional coincide exactamente con el candidato final. La suite
  productiva pasó `2243` pruebas; Ruff, NUL, diff, configuración y kernel
  quedaron verdes.
- Stack gestionado arriba: HTTP raíz y `/health` 200, scheduler
  launcher→runtime único, lock v1 PID 18888/token coherente, lease PMR vacío.
- Tras la parada apareció una alerta transitoria de datos >30 min; el ciclo
  natural `mkt_2fe0c3db689e` terminó en 598,277 s y la salud regenerada quedó
  `warning` con `0 critical`. Cero órdenes fueron creadas desde el reinicio.
- Telegram diario está programado a las 22:05 Europe/Madrid y los avisos de
  fills están activos. No hubo push.

### P-L65A — caracterización diaria Sistema vs SP500 (28-jul-2026)

- Dictamen: `ready_for_p65b_implementation`; worktree aislado y versión
  `0.4.198` preservada. XNYS abierto.
- Equity diaria (`equity_t - equity_prev_close`) es la autoridad primaria;
  invertido queda como métrica secundaria. El consumidor baseline actual usa
  `pnl_pct`/`spy_pct` legacy sin exigir comparabilidad del payload canónico.
- El selector existente de `Valor de cartera` es calendario: con huecos puede
  mostrar menos de 7 sesiones. El baseline Sistema/SP500 no tiene selector ni
  contadores en este árbol; la observación `13/17/0/9 de 39` queda
  `unavailable`, no se atribuye por nombre.
- 12 tests P-L65A pasan. Suite completa, smoke, benchmark largo y validación
  cerrada pendientes por XNYS abierto. Siguiente único lote: P-L65B, rowset
  canónico read-only por sesiones con estados pending/unavailable y cierre
  aritmético de contadores.
### P-L71-R1 - wiring EOD comun para Telegram

- La reproduccion contra `7beeb135` demostro que Telegram ignoraba el overlay
  EOD y usaba `row['spy_pct']` stale: `-0,30%` en lugar de `+0,25%`.
- `publish_daily_summary` es ahora la frontera comun de proyeccion para el job
  22:05 y el fallback PMR. `build_daily_summary` solo acepta benchmark
  proyectado/comparable con autoridad EOD completa; sin cache posterior queda
  `n/d`, incluso si existe un scalar legacy.
- P-L70BR1 permanece paralelo y no se mezcla. Siguiente lote: ensayo cerrado
  P-L71; no backfill, no reenvio automatico de sesiones ya recibidas.

> P-L48B sigue desplegado y P-L44B sigue en shadow.

### P-L70BR1 — ensayo integrado cerrado

- Merge `--no-ff` `0083f414` desde producción documental exacta; tree funcional
  resultante igual al candidato P-L70R1. QA adicional `a64c493a` conserva la
  separación del evento de resumen frente a notificaciones de fills.
- Suite integrada `2261 passed, 1 skipped, 1 warning`; focales `86 passed` y
  QA integrada `1 passed`. El skip es únicamente el test condicional
  `test_score_study_regression_current_sqlite` por historia local insuficiente
  o no disponible. No se añadió skip/xfail.
- `telegram_daily_summary.py` es la única lógica funcional modificada; el
  recibo v2 guarda texto exacto, `text_sha256`, `content_hash` independiente y
  unidades UTF-16. Fills, scheduler, Store, PMR y trading permanecen iguales.
- Dictamen `ready_for_closed_market_deployment`, sin despliegue, reinicio,
  push ni mensaje real. El siguiente lote mínimo es el preflight/normalización
  productiva autorizado para despliegue; no iniciar P-L69 en paralelo.

P-L65A version policy required candidate `0.4.199`; no production logic
changed. The next lot is P-L65B after closed-market validation gates.

> P-L65A-R1 (28-jul-2026): se corrigió el alcance de la caracterización. El
> checkout productivo dirty sí contiene `_render_daily_vs_spy_table` P-L61 y
> P-L62, pero P-L63R1/P-L65A no lo contienen. Hashes dirty:
> `web_app.py` `FC6ABAD9D799077D402866194A93D939657CC16CAC6943BC40B139A608D8205A`,
> `test_web_app.py`
> `9580147B3E0C8F0E264A1721AA95D13C5EFF3E14F75634517E25C1C551EA1E1B`.
> El panel dirty explica `13/17/0/9 de 39`: cuenta antes del filtro, prioriza
> `pnl_invested_pct`, recorta tabla y gráfico sobre rowsets distintos y deja
> interpolados/parciales en la comparación. 22 pruebas aisladas pasan; no hubo
> cambios en src ni producción. Dictamen `ready_for_p65b_implementation`
> condicionado a componer el diff exacto, manteniendo `0.4.200` reservado
> para P-L65B.

> P-L54B-T (27-jul-2026): caracterizacion aislada completada en
> `C:\Antonio\Bref\agenteBolsa_worktrees\pl54bt_capital_funnel_characterization`,
> rama `codex/pl54bt-capital-funnel-characterization`, desde P-L58R1 exacto.
> Dictamen `ready_for_p54b_implementation`: el productor real queda trazado
> hasta `save_order_plan`/`save_broker_order`, pero target exposure y notional
> objetivo no tienen autoridad estructurada y deben permanecer
> `unavailable`. La fixture 376 -> 15 -> 15 y la bateria focal pasan; no hubo
> cambios en src, produccion ni politica. Siguiente paso: implementar el
> shadow en worktree separado, sin desplegar.

> P-L54B-T-R1 (27-jul-2026): se corrigieron las invariantes del contrato sin
> tocar src. El snapshot anterior permitia risk-approved=135 y risk-rejected=80
> con gates-passed=135, y 135.000 USD de notional no alcanzable. La tabla
> cerrada es 376 -> 306 -> 256 -> 95 -> 15, con 361 caidas y 15 planes.
> Dictamen: `ready_for_p54b_implementation`. El siguiente lote unico es
> implementar el productor shadow en worktree separado.

> P-L58R1-Retry (27-jul-2026): worktree
> `C:\Antonio\Bref\agenteBolsa_worktrees\pl58r1_measurement_safety_rehearsal`,
> rama `codex/pl58r1-measurement-safety-rehearsal`, HEAD final posterior al
> commit documental. Merges `01c2c564` -> `b61a3036` -> `e0e19625` en orden.
> Dictamen `ready_for_closed_market_full_validation`: 1987 passed, 1 skip
> preexistente, Ruff/NUL/diff/config/version policy verdes. No despliegue.
> El siguiente gate es preflight humano y smoke completamente aislado; no
> promover sombras ni cambiar politica.

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
## P-L66 — candidato Telegram

El candidato 0.4.201 añade un consumidor externo para el resumen
diario. Debe integrarse después de P-L65 para preservar la secuencia de
versiones. Hace el primer intento a las 22:05 Europe/Madrid y conserva el hook
postmarket como fallback idempotente. Está desactivado por defecto y requiere
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_DAILY_SUMMARY_CHAT_ID` y
`TELEGRAM_DAILY_SUMMARY_ENABLED=true` únicamente en el entorno productivo.
No desplegar con XNYS abierto.

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
- P-L57A corrige en candidato aislado la continuidad null-safe de
  `postmarket_report`, `performance_daily`, `profitability_scoreboard`,
  `promotion_readiness`, digest semanal y serie web read-only. La causa
  reproducida es `pnl_pct=NULL` entrando en la reducción de drawdown; los
  valores faltantes siguen `null/unavailable`, con cobertura parcial explícita.
  No se ha desplegado ni se ha hecho backfill del PMR fallido del 23-jul.
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

## P-L57A — continuidad null-safe del cierre postmarket (candidato 0.4.193)

- Base exacta: `24537e813ff0905696cda0b3925a212045ee7b09`, producción intacta
  con su suciedad conocida. Worktree:
  `C:\Antonio\Bref\agenteBolsa_worktrees\pl57a_pmr_null_safety`, rama
  `codex/pl57a-pmr-null-safety`.
- PMR `pmr_dbfa382016b8` del 23-jul: reconciliación completada, pero
  `postmarket_report` falló con `stage_postmarket_report_failed` y el
  `TypeError` de comparación/agregación causado por `pnl_pct=NULL` y ausencia
  de drawdown numérico. El 24-jul conservó `pnl_pct`, `previous_equity` y
  `alpha` como null cuando faltaba una sesión XNYS comparable; no se copió el
  `result_metrics.pnl_pct` al ledger SQL.
- Estado de commits: `5d05092c` test/reproducción, `12684790` fix,
  `6ddf93da` expectativa null-safe de primera sesión y `ee9afee6` documentación.
  La suite cerrada terminó `1698 passed, 1 skipped`; el skip preexistente es
  `test_score_study_regression_current_sqlite` por ausencia de SQLite local.
  Ruff, NUL, diff, configuración, kernel productivo sellado y version policy
  pasan. No cambiar la secuencia PMR: solo se hace observacionalmente tolerante
  a filas incompletas; no se reconstruyen datos ni se reejecutan sesiones.
- Dictamen P-L57A: `ready_for_integration_rehearsal`. Próximo paso: ensayo de
  integración aislado; la promoción a producción requiere otra precondición
  cerrada, comparación de objetos protegidos y autorización explícita.

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

## P-L54B-W - relevo del candidato 0.4.194

- Worktree aislado: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54bw_capital_funnel_shadow`;
  rama `codex/pl54bw-capital-funnel-shadow`; base `20e8be04`; version 0.4.194.
- El productor shadow captura transiciones ya decididas y persiste un unico
  evento por `cycle_id` despues de la ruta activa. No tiene autoridad sobre
  seleccion, gates, sizing, RiskManager, planes, ordenes o exposicion.
- Persistencia append-only, hash sin `captured_at`, idempotencia y conflictos
  separados. Lector/CLI devuelven `collecting` con denominadores null cuando
  no existe evento. Target exposure permanece unavailable sin autoridad.
- QA focal P-L54B-T/R1/W: 33 passed; quedan pendientes suite completa, smoke,
  prueba P-L45 larga y ensayo integrado cerrado P-L54BR1. No desplegar ni hacer
  push desde este lote.

## P-L54B-R1 - relevo de identidad de decision

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54br1_decision_identity`;
  rama `codex/pl54br1-decision-identity`; base `9c8940a0`; version `0.4.194`.
- La decision canonica es `cycle_id + signal_identity + action +
  recommendation_id` cuando existe. Repeticion exacta es idempotente; contenido
  incompatible es conflicto auditable; faltante es partial/ambiguous segun
  colision. No se adjuntan planes u ordenes por simbolo, fecha o candidato.
- Stages y notional solo cuentan decision identity verificada y exponen la
  poblacion excluida. La paridad de la ruta activa no cambia.
- Commits `de08b9fd`, `8d814934`, `3f85071f`; focales `49 passed` incluyendo
  P-L54B T/R1/W y cycle funnel. Siguiente paso unico: reintentar P-L54BR1;
  suite completa y smoke siguen pendientes. Produccion intacta; sin deploy ni
  push.

### P-L65B — implementación aislada (28-jul-2026)

- Worktree `pl65b_daily_vs_spy_consistency`, rama
  `codex/pl65b-daily-vs-spy-consistency`, base P-L65A-R1
  `53b49f71e3acedd9b5ed73f80ff8cb793221df8`, candidato `0.4.200`.
- La UI usa `performance_daily(readonly=True)` y un rowset canónico común para
  selector, contadores, tabla y gráfico. Equity contra SPY es la comparación
  primaria; exposición-normalizada es descriptiva; missing/partial/stale/
  interpolated/future quedan pending.
- Feature `8d4deca6`, tests `0cb872a9`, QA `02aee0c9`; focales
  P-L65/P-L63/P-L46/UI: 129 passed.
  Ruff, NUL, diff, py_compile, validate-agent-config y version policy aislados
  deben cerrarse antes del ensayo integrado; suite completa y smoke se omiten
  con XNYS abierto.
- Producción dirty, P-L66 y archivos protegidos intactos. No despliegue.
  Siguiente paso único: ensayo combinado aislado P-L63/P-L65B, revalidando
  XNYS cerrado y precondiciones; P-L66 no se integra aquí.

## P-L54BR1-Retry - relevo (27-jul-2026)

- Worktree `pl54br1_integration_rehearsal`, rama
  `codex/pl54br1-integration-rehearsal`, merge `8574a227`, version `0.4.194`,
  tree `ff42c750`.
- XNYS estaba abierto al comenzar; PMR 24-jul terminal completed y leases
  activos vacios se verificaron mediante fuentes persistidas/directas.
- QA focal integrada: `330 passed`; Ruff, NUL, diff y validate-agent-config
  verdes. No se ejecutaron suite completa, P-L45 33336, smoke ni benchmark
  combinado.
- P-L54 mantiene `376 -> 306 -> 145 -> 95 -> 15`, 361 razones primarias y
  notional target unavailable. No cambia trading, riesgo, ejecucion ni PMR.
- Dictamen: `ready_for_closed_market_full_validation`. Siguiente paso unico:
  repetir los gates cerrados, incluida suite/smoke/benchmark, sin desplegar
  automaticamente. El incidente previo queda documentado como
  `unconfirmed_sqlite_mutation`, sin limpieza.

## P-L46BR4 - filtro calendario de cartera (candidato 0.4.195)

P-L46BR4 corrige la interpretacion del selector del grafico: `days` ya no es
un numero de filas sino una ventana calendario anclada al ultimo snapshot
visible. Se conservan 7/15/30/90/`Desde inicio`, el orden y la deduplicacion
de fechas, y la serie visible alimenta tanto grafica como Resultado del
periodo. El cambio no toca trading ni broker. El worktree tiene 75 pruebas UI
verdes; con XNYS abierto quedan pendientes suite completa, smoke y validacion
cerrada.

## P-L60R1 - ensayo integrado UI sobre P-L54BR1 (27-jul-2026)

- Worktree/rama: `pl60r1_ui_measurement_integration`,
  `codex/pl60r1-ui-measurement-integration`; merge `489b229f`, version
  `0.4.195`, tree `5f3afdc7`.
- P-L46BR3 ya estaba presente. El selector unico y estable ofrece
  7/15/30/90/`Desde inicio`; la ventana se aplica por fechas calendario al
  ultimo snapshot visible, con orden/deduplicacion deterministas y sin mutar
  la fuente. Grafica y Resultado del periodo comparten la misma serie; P/L
  abierto reutiliza posiciones ya cargadas.
- QA focal: `83 passed`; relacionados: `159 passed, 1 warning`; Ruff, NUL,
  diff, py_compile y config temporal verdes. Con XNYS abierto quedan
  pendientes suite completa, smoke y validacion cerrada. No hubo broker, red,
  SQLite productiva, despliegue ni push. La incertidumbre historica
  `unconfirmed_sqlite_mutation` y P-L54 se conservan sin declararlas resueltas.

## P-L59B-T-R5 (final) - caracterizacion cerrada (27-jul-2026)

- Dictamen: **`needs_fix`**. XNYS abierto. Hora real: 19:43 CEST. HEAD: `a48113fe`.
- 27 P-L59 + 5 integracion (32 total). Ruff/NUL/diff verdes.
- Stage order: rama 2399/2412. plan_id nace en plan_records; identidades por
  symbol+side+lineage reales del modelo. Sin object.__setattr__.
- Informe unico sin secciones duplicadas. Caracterizacion cerrada.
- Siguiente: P-L59C.

## P-L59C-R6 - autoridad prospectiva estructurada de llm_selected (27-jul-2026)

- Dictamen: **`ready_for_integration_rehearsal`** (R6 corregido). XNYS abierto, 20:30 CEST.
- R6: list branch inside_dcs=False. Docs con hashes R5 reales. 15 integration.
  Ruff/NUL/diff verdes. Brecha P-L53 abierta.
- Siguiente: P-L59D rehearsal de integracion.

## P-L59D - rehearsal de integracion (27-jul-2026)

- Dictamen: **`ready_for_closed_market_full_validation`**. XNYS abierto, ~21:32 CEST.
- Merge `--no-ff` de P-L59C-R6D (`30b6b76b`, v0.4.196) sobre P-L60R1 (`70de3401`, v0.4.195).
  Sin conflictos. HEAD final `4524cbe3` (tree `661216b3`); merge `9009c7f2` (tree `ad69264e`, identico a P-L59C-R6D).
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59d_llm_selected_rehearsal`,
  rama `codex/pl59d-llm-selected-rehearsal`.
- 5 protegidos versionados identicos contra base y produccion; .env no modificado (hash unavailable). Ruta activa P-L60R1 intacta.
- QA: 300 passed (10 archivos, 65.53s). Ruff/NUL/diff/py_compile/validate-config verdes.
- Brecha P-L53 recommendation_id sigue abierta.
- Gates omitidos: suite, smoke, benchmark, P-L45 33.336, kernel (XNYS abierto).
- Siguiente: P-L59E validacion cerrada completa.

## P-L59F-T-R3 — caracterizacion final, contrato cerrado (27-jul-2026)

- Dictamen: **`ready_for_implementation`**. XNYS cerrado (~22:15 CEST),
  postmarket no terminal, P-L59E bloqueado.
- HEAD tests R3: `e14caa1e`. Solo tests/docs, sin src.
- R3: lineage literal, adjuntos P-L53/P-L54 coherentes, stage explicito,
  `_denominators` real en expansion.
- 17 tests pasan (0.90s). Ruff/NUL/diff verdes.
- Contrato de implementacion completo en informe.
- Siguiente: P-L59F-I (requiere precondiciones XNYS verificadas).

## P-L59F-T-R4 — cierre de diseño (27-jul-2026)

- Dictamen: `ready_for_implementation`. HEAD `224b4958`, tree `135df124`, v0.4.196.
- 17 tests verdes. Contrato decision_rows completo. P-L59E bloqueado.

## P-L59F-I-R1 — implementacion decision_rows v2 corregida (27-jul-2026)

- El candidato inicial `305b56ee` fue `needs_fix`; la correccion del worker se
  interrumpio y direccion clasifico el diff antes de completarlo.
- Dictamen final: **`ready_for_integration_rehearsal`**.
- Worktree/rama: `pl59fi_decision_rows`, `codex/pl59fi-decision-rows`.
- Base `224b4958`, tree `135df124`, version `0.4.196`.
- Candidato v0.4.197. Commit correctivo `1ce3c155`, tree funcional
  `ed1e6879`.
- SCHEMA_VERSION v2. decision_rows por identidad exacta de recomendacion.
  candidate_rows summary 8 estados. Bounded 600. Denominadores v2.
  Reader backward-compatible v1. Sin cambios en cycle_runner/storage/protegidos.
- 169 passed en la bateria focal disjunta; Ruff completo, NUL y diff verdes.
- Recomendaciones fuera de Fase A/ciclo quedan unavailable; adjuntos exigen
  IDs y linaje exactos; idempotencias y conflictos tienen denominadores
  separados; el test fail-open fuerza un fallo real.
- Brecha P-L53 recommendation_id: CERRADA.
- Gates omitidos: suite, smoke, benchmark, P-L45, kernel (precondiciones
  no terminales: postmarket no terminal, continuous_improvement running).
- Siguiente: P-L59F-D rehearsal de integracion. P-L59E sigue bloqueado.

## P-L59F-D — ensayo integrado cerrado (27-jul-2026)

- Dictamen: `ready_for_closed_market_deployment`, sin autorizacion para
  desplegar.
- Worktree/rama: `pl59fd_decision_rows_rehearsal`,
  `codex/pl59fd-decision-rows-rehearsal`.
- Merge `f535923f`; QA `e0290762`, `2f156eb8`; tree `f8193f6d`; version
  `0.4.197`.
- Suite completa: 2184 passed, 1 skip y 1 warning preexistentes. Ruff, NUL,
  diff/config/kernel/protegidos verdes.
- QA corrigio una asercion v1 exacta para validar v1+v2 y movio la
  instrumentacion de `_attach_phase_b` a `_build_decision_rows`.
- Benchmark 500 candidatos: total p95 649.32 ms, 840,943 bytes/evento,
  memoria pico 17.2 MB. Riesgo operativo medio por volumen.
- Smoke real no ejecutado por seguridad; sin proveedor CLI sintetico que
  garantice cero red/broker/LLM.
- Produccion y servicios intactos; sin SQLite productiva, despliegue ni push.

## P-L63 - contrato de equity desde el 1 de abril (28-jul-2026)

- Worktree/rama: `pl63_portfolio_april_baseline`,
  `codex/pl63-portfolio-april-baseline`; base `8c66f966`/tree `fb96f589`/
  v0.4.197. Fix `cad229af`, candidato v0.4.198.
- La causa fue la constante divergente `PORTFOLIO_CHART_START_DATE=2026-04-28`.
  Se alinea con `DEFAULT_START_DATE=2026-04-01`; la historia se solicita una
  sola vez con `period="all"`. La cabecera ya no usa `current_statistics.total_pl`
  como baseline y captura el resumen real de equity.
- Cuenta, grafica y Resultado comparten fuente/ventana/primer y ultimo equity;
  fechas, source y coverage se muestran. Sin punto de abril: partial/unavailable,
  sin reconstruccion desde trades. P/L hoy y P/L abierto permanecen separados.
- `101 passed` focales UI/portfolio/version; Ruff, NUL, diff, py_compile y
  configuracion temporal verdes. Con XNYS cerrado se requieren suite completa,
  smoke aislado y validacion cerrada; no se ejecutaron ni hubo despliegue.

### P-L63 — corrección semántica UX de equity (28-jul-2026)

- La reproducción adicional mostró que `equity 71.550 -> 70.700` con
  `trade_history.total_pl=+106,83` podía producir una tarjeta verde. El
  resultado correcto es `-850,00` (aprox. `-1,19%`), calculado solo como
  último menos primer equity visible; `total_pl` queda fuera de la cabecera y
  del baseline.
- El copy es `Resultado del periodo`/`Variación de equity`, con fechas exactas
  y tone derivado del signo. P/L hoy y P/L abierto son snapshots separados.
  Se añade ventana explícita `Desde 01/06/2026`; la misma serie filtrada
  alimenta gráfica, importe, porcentaje y fechas.
- Commits: `50976dfe` (tests/reproducción) y `22609ba3` (fix). Versión
  `0.4.198` sin cambio. QA focal `103 passed`; estáticos y configuración
  temporal verdes. Suite completa, smoke y validación cerrada quedan
  pendientes con XNYS abierto/premarket. No producción, broker, red, SQLite
  productiva, despliegue ni push.

### P-L63R1 — semántica diaria y tooltip del baseline (28-jul-2026)

- 2,10% sobre exposición no es el retorno diario de la cuenta. La cabecera
  usa ahora today_equity_change / previous_equity, con copy Variación de
  equity hoy y desde el cierre anterior; cambios de exposición no alteran
  el porcentaje. Sin cierre previo: n/d, nunca sustitución por exposición.
- No se publica desde apertura ni se interpreta la curva diaria como
  intradía. P/L abierto, variación diaria y resultado histórico son métricas
  separadas.
- Sistema/SP500: línea y puntos comparten tooltip explícito Fecha, %
  ganancias, Serie, el campo retorno_acumulado y formato +.2%. La fuente,
  el eje y los valores no cambian; desaparece el tooltip automático con
  decimal crudo.
- QA focal 106 passed; Ruff, NUL, diff, py_compile y config temporal
  verdes. Suite completa, smoke y benchmark largo pendientes por XNYS abierto.
  Versión 0.4.198; commits 12a6cb11, bef256d6, 031597c7, 89adde7f
  y fb2c47a7. Sin producción, broker, red, SQLite productiva, despliegue ni
  push.
## P-L68 — corrección Sistema vs SP500 (28-jul-2026)

- Worktree `pl68_benchmark_comparability_fix`, rama
  `codex/pl68-benchmark-comparability-fix`, base productiva `f015428f`.
- Versión candidata `0.4.202`.
- Se corrige la base de precio yfinance, la dirección de la latencia
  benchmark/captura y la visualización de históricos `pending`.
- Línea continua = comparable; discontinua = provisional. Solo la primera
  participa en ganadores. No hay backfill ni neutralización de flujos.
- El baseline acumulado usa composición geométrica.
- Suite completa 2249 passed, 1 skip y 1 warning preexistentes. Ruff, NUL,
  diff, configuración y kernel productivo verdes.
- Dictamen `ready_for_integration_rehearsal`; producción sigue en 0.4.201.

Siguiente secuencia:

1. ensayo `--no-ff` de P-L68 sobre producción exacta y QA visual aislada;
2. despliegue solo con autorización humana y precondiciones cerradas;
3. P-L69 separado para que Telegram detecte fills durante mercado abierto:
   persistencia local primero, envío idempotente después, nunca al submit.

## P-L68 — desplegado (28-jul-2026)

- Producción quedó en versión `0.4.202`, merge `18add12488cfb4179391d685540d65aac9f8870d`
  y árbol funcional `68a7b4c5d04d78a54df425ab15d9c13431d7bc13`.
- Suite productiva: 2250 passed; estáticos, configuración y kernel verdes.
- Stack arriba mediante helpers gestionados; HTTP 200/200, listener único,
  scheduler lógico único y lock/token coherentes en dos comprobaciones.
- PMR 2026-07-28 permaneció terminal `completed`; bootstrap posterior
  `session_already_completed`, lease vacío y cero órdenes nuevas.
- Los históricos con base desconocida se dibujan como provisionales y no
  cuentan como victorias. Las nuevas capturas pueden adquirir comparabilidad
  canónica sin backfill.
- P-L69 continúa como lote independiente para detectar y notificar fills
  durante mercado abierto; no mezclarlo con cambios de política.

## P-L66 - siguiente paso

El candidato 0.4.201 incluye resumen Telegram a las 22:05 y avisos de fills.
Antes de desplegar requiere ensayo `--no-ff`, suite completa y smoke aislado
con XNYS cerrado. No desplegar automaticamente.

## P-L67R1 — ensayo combinado final (28-jul-2026)

- Worktree `pl67_p65_p62_p66_deployment_rehearsal`, HEAD `62de5525`, tree
  `77ec5a4f`, versión 0.4.201. Merge P-L66 `--no-ff` conservado.
- P-L62 freshness quedó subsumido sin copiar el panel P-L61 dirty; P-L65B
  conserva la comparación canónica sin yfinance. P-L66 queda desactivado por
  defecto y fail-open.
- QA final: 2242 passed, 1 skip preexistente (`test_pre_earnings.py:1041`),
  Ruff/NUL/diff/compile/config verdes. XNYS estaba abierto; no hubo despliegue.
- Smoke CLI real queda pendiente por seguridad; el sustituto monkeypatched de
  `run_observable_cycle(use_crew=False)` pasó en DATA_DIR temporal. Antes de
  desplegar hay que repetir preflight cerrado y normalizar el checkout dirty
  sin descartar cambios del operador.

## P-L72 — siguiente integración (29-jul-2026)

- Worktree `pl72_open_to_open_performance`, rama
  `codex/pl72-open-to-open-performance`, versión `0.4.206`.
- Integra P-L70 y P-L71 y corrige la frontera diaria con aperturas exactas
  Alpaca 15 minutos y Open ajustado de SPY.
- Semántica única: T open → next T open; para la sesión vigente, open → now.
  No utilizar `performance_daily`, timestamps midnight de 1D ni exposición
  actual como denominador.
- La UI muestra las últimas sesiones completas, tabla descendente y cero
  `pending`. Telegram comparte el intervalo cuando existe evidencia exacta.
- Suite completa `2283 passed, 1 skipped`; gates estáticos/configuración
  verdes. Siguiente paso: preflight cerrado, merge `--no-ff`, validación
  productiva con stack detenido, arranque gestionado y doble salud.

## P-L72 — desplegado (29-jul-2026)

- Producción `0.4.206`, merge funcional
  `50d959d76de113da40067dfbb3a03973d5635d2f`, árbol
  `b7eb971fc7fa8733706a6eef826ba5750e1aa267`.
- Suite sobre producción detenida: `2284 passed`; Ruff, NUL, diff,
  configuración, kernel y smoke aislado verdes.
- Doble comprobación: HTTP 200/200, scheduler único lógico, lock del runtime
  con token exacto, kernel sellado, lease PMR vacío y cero órdenes nuevas.
- UI productiva comprobada: siete filas completas y descendentes; seis
  intervalos finales y uno `En curso`, sin `Pendiente`.
- La próxima apertura XNYS es 29-jul a las 15:30 Europe/Madrid. Desde ese
  instante el intervalo vigente cambia automáticamente a apertura 29-jul →
  ahora.

## P-L74 - siguiente lote

- Candidato 0.4.208 con productor dedicado de apertura SPY y lector
  conflict-safe. La cache `market_data` no es autoridad por recencia: se
  requiere provenance explicita para resolver aperturas distintas.
- La captura corre al final del ciclo natural, no en `portfolio_watch`; no
  hay limite artificial de tres intentos. `inserted/available/idempotent/
  recovered` detienen el guard; metadata sin `.pkl` recuperable no lo detiene.
- Siguiente paso: ensayo `--no-ff` cerrado y suite completa aislada; mantener
  produccion 0.4.206 intacta hasta superar precondiciones y paridad.
- No hubo push ni cambio de política activa.

## P-L73 — cartera abierta con P/L total y diario

- Worktree `pl73_position_daily_pl`, rama
  `codex/pl73-position-daily-pl`, base productiva `36077a06`.
- Versión candidata `0.4.207`.
- `trade_history` conserva los campos total e intradía del mismo
  `PositionSnapshot` ya cargado por la UI.
- Dashboard y página Cartera muestran USD y porcentaje para `P/L total` y
  `P/L día`; missing se publica `n/d`.
- No se añade una llamada al broker y no se unen posiciones con otra fuente por
  símbolo. P-L72 conserva por separado la métrica de apertura a apertura.
- Focales `129 passed`; suite completa `2289 passed, 1 skipped`; Ruff, NUL,
  diff y configuración temporal verdes. Smoke sustituto aislado verde; CLI
  real omitido por seguridad de proveedores.

## P-L69-W - watcher intradia de fills confirmados

- Candidato aislado 0.4.209 en `pl69_fill_watch_impl`, rama
  `codex/pl69-fill-watch-impl`, base P-L75 `08e8f8fa`.
- El contrato consulta un `OrderStatusProvider` por `broker_order_id`; el
  adaptador del proveedor esta confinado en `tools/fill_provider.py`. La
  secuencia segura es snapshot remoto, commit local filled, claim, Telegram
  fail-open y recibo `telegram_trade_fill:<broker_order_id>`.
- Job separado, `max_instances=1`, cap 25, cadence 30 s por defecto y backoff
  acotado 30->300 s. Esta desactivado por defecto. Fills parciales/pending no
  avisan; SELL requiere `source_plan_id` exacto y compra unica filled.
- Commits: caracterizacion `581f6bfc`, implementacion `6bffedf2`, QA
  `9a689153`, fixes QA `fc9f7206`/`8e8da2c1`; documentacion `5c87cdd2`.
- XNYS abierto: no se ejecutaron suite completa, smoke, broker, red, Telegram
  real, SQLite productiva ni despliegue. Dictamen provisional
  `ready_for_closed_market_full_validation`; siguiente paso unico: ensayo
  cerrado con las precondiciones operativas completas.

## P-L75 - siguiente paso

- Ensayo combinado P-L73 + P-L74 integrado con `--no-ff` en version 0.4.208.
- P-L73 conserva el carrier de posicion; P-L74 conserva autoridad SPY,
  recovery de `.pkl` y retry por ciclo natural de mercado.
- Focales combinadas verdes; con XNYS abierto quedan pendientes suite completa
  y smoke. Repetir validacion cerrada antes de cualquier despliegue.
- Dictamen `ready_for_integration_rehearsal`. Sin despliegue, reinicio, push o
  cambios de política.

## P-L69-R1 - finalización downstream tras fill intradía

- En `pl69_fill_watch_impl`, `31560cfb` reprodujo que una orden terminalizada
  por el watcher desaparecía de `_pending_orders` y no alcanzaba la
  finalización postmarket. El recibo Telegram estaba presente, pero signal,
  learning y execution quality quedaban sin el paso posterior.
- `584575c1` añade el marcador durable `reconciliation_finalization` al payload
  de `broker_orders` y hace que PMR procese esos terminales con el snapshot
  local exacto. Claim transaccional `pending -> processing -> applied`, sin
  reabrir orden ni consultar otra transición remota; efectos y attach se
  confirman en la misma transacción. `0c121836`/`86b653ce`/`0909ea4b` cubren
  restart, idempotencia, carrera, SELL/rejected/cancelled y fallback SDK.
- Estado: `ready_for_closed_market_full_validation`, versión 0.4.209. Focales
  `133 passed` y R1 `18 passed`; suite completa/smoke y proveedor real siguen
  pendientes por XNYS abierto. Siguiente lote único: validación cerrada del
  candidato, sin despliegue automático.

## P-L69-R2 - endpoint provider y rollback de finalización

- `dac98d0b` reprodujo con el `TradingClient` real que `_base_url` enum se
  serializaba como `BaseURL.TRADING_PAPER`, generando URL inválida.
- `de8b250e` usa `.value` cuando existe, valida HTTP(S) y conserva el endpoint
  paper/live de la instancia; mantiene timeout, headers, redirects y fallback
  exacto por client ID. Endpoint inválido queda fail-open y no altera la orden.
- `f6c82f85`/`b819c540` cubren rollback transaccional del marcador R1, GET,
  fallback, live y ausencia de Telegram/transición en error. Batería final:
  `138 passed`; Ruff/NUL/compile/diff/config verdes.
- Dictamen: `ready_for_closed_market_full_validation`, versión 0.4.209.
  XNYS abierto; pendiente solo la validación cerrada antes de reintegrar o
  desplegar.

## P-L76-CLOSE - despliegue validado

- Producción desplegada en merge `49d33e17`, árbol funcional `3f2b859b`,
  versión `0.4.210`; tracked limpio y untracked del operador preservados.
- Suite merged `2340 passed`, focales `107 passed`, gates estáticos/config,
  kernel y smoke aislado verdes.
- PMR 2026-07-31 completed; XNYS cerrado. El watcher está activo en config
  `True/30/25/5/30/300`, pero el estado natural es `skipped` por mercado
  cerrado; no se provocaron fills ni Telegram real.
- Health 10:20:02 y 10:22:45 CEST, HTTP raíz/health 200/200, cero críticos,
  cero órdenes nuevas/duplicados/locks post-arranque. El `lock_orphan` es el
  falso positivo launcher/runtime documentado y el árbol PID es coherente.
- Dictamen final: `deployed`; sin push y sin abrir mejoras nuevas.

## P-L76R1 - gate funcional cerrado

- El candidato `pl76_p69_predeployment_rehearsal` queda en versión `0.4.210`
  tras `00015af6`; `1f4b4a79` y `2b2a21d0` son QA de expectativas obsoletas.
- Causa corregida: `capital_deployment_funnel_shadow_conflicts()` no debe
  importar ni filtrar por estados de `broker_orders`; su consulta solo contiene
  `agent_events`. La frontera `pending_broker_orders()` conserva su propio
  filtro terminal.
- Suite cerrada final: `2339 passed`, un skip preexistente y una advertencia
  externa; focales `107 passed`; gates estáticos/config y smoke de entrypoint
  temporal aislado verdes.
- No se ha tocado producción. Reanudar únicamente con el preflight cerrado
  exigido, merge exacto, delta `.env` autorizado y doble health posterior.

## P-L76-PRECLOSE - relevo para validación cerrada

- Ensayo aislado: `pl76_p69_predeployment_rehearsal`, rama
  `codex/pl76-p69-predeployment-rehearsal`.
- Merge `faccc5de42064211276b449d3cc78ebb6c022212`, tree
  `f2b5a7728b04e73916c95fec02c5ea1bb0c0bc18`, versión `0.4.209`.
- Producción base `36077a06`/tree `b15ac3a2`, P-L69-R2
  `4c3ed11d`/tree `f2b5a772`; referencias/tracked limpios y untracked del
  operador fuera del ensayo.
- QA focal `145 passed` + `2 passed`; Ruff/NUL/py_compile/diff/config verdes.
  XNYS abierto impidió suite completa, smoke y operación real.
- Contrato: snapshot provider-neutral por `broker_order_id` → commit local
  terminal → Telegram fail-open → recibo; PMR aplica
  `reconciliation_finalization` pendiente una sola vez. Watcher disabled por
  defecto y separado del ciclo activo.
- Antes de promover: XNYS cerrado, PMR terminal/lease vacío, sin jobs/test/
  deploy activos, paper/live/auto-apply seguros, suite `tests/ -x -q`, smoke
  temporal o `smoke_unavailable_by_safety`, doble salud >=75 s tras
  `stack_up`, cero órdenes inesperadas y cero locks. No desplegar desde este
  relevo sin esos gates.

## P-L77B1 - autoridad fail-closed de overrides adaptativos

- Candidato `pl77b1_adaptive_override_authority`, versión `0.4.211`, sobre
  `ba9d60d4`/árbol `7ea8ea9a`. La reproducción confirmó que la lectura legacy
  podía materializar `MAX_ORDERS_PER_CYCLE=2` con global false; la base es 4.
- `active_adaptive_overrides` ahora exige autorización global literal,
  `requested_auto_apply` y `authorized_auto_apply` individuales, y caducidad
  evaluable por sesiones XNYS. Sin sesión fiable, devuelve vacío; no usa mtime.
  El inventario health continúa mostrando `preexisting_unauthorized`.
- `config.py`, los protegidos, `.env`, SQLite y producción no se modificaron.
  Focales `49 passed`; suite `2361 passed`, un skip preexistente y una warning;
  Ruff/NUL/py_compile/diff/config/kernel aislado y smoke temporal verdes.
  Estado previo del candidato: `ready_for_closed_market_deployment`.
- Cierre P-L77B1 completado en producción mediante merge `7682901a` desde el
  candidato exacto `9701e2f1`; versión `0.4.211`, árbol funcional
  `ea93a512`. Suite `2361 passed`, `1 skipped` preexistente y `1 warning`,
  focales post-merge `73 passed`; dos checks post-arranque separados por más
  de 75 s confirmaron HTTP `200/200`, kernel `sealed/ok`, paper/live-off,
  scheduler/token coherentes, `MAX_ORDERS_PER_CYCLE=4`, cero órdenes abiertas
  y cero críticos. El inventario legacy sigue `preexisting_unauthorized` y
  warning observacional; no tiene autoridad efectiva. No abrir P-L78 en este
  turno.

## P-L79H - cierre intentado, gate rojo y rollback

- El preflight del 02-ago-2026 fue verde: XNYS cerrado, PMR 2026-07-31
  terminal `completed/pipeline_completed`, lease vacio, kernel `ok` y
  referencias limpias. Se preservaron los untracked del operador.
- El merge `--no-ff` `d05ce134` integro `222d2371` sobre `ba7d488d` y produjo
  temporalmente el arbol `205964d4`, version `0.4.214`.
- La suite completa se detuvo por un fallo real despues de `1678 passed` y
  `751.99 s`:
  `tests/test_p69_fill_watch_implementation.py::test_configuration_is_disabled_and_provider_timeout_is_neutral`
  afirma `False`, pero el `.env` productivo autorizado activa el watcher por
  P-L76. Hubo una warning externa y ningun cambio de test/config para ocultarlo.
- Revert auditable `6c36c062` dejo el arbol funcional `6938d157`, version
  `0.4.211`; `stack_up` y dos comprobaciones a las `01:31:22` y `01:33:06`
  CEST confirmaron HTTP raiz/health `200/200`, un scheduler, listener unico,
  kernel `ok` y ausencia de blockers.
- Estado: `needs_fix`. Proximo unico lote: aislar esa expectativa de test del
  `.env` productivo o actualizar su contrato de forma autorizada, sin cambiar
  la activacion del watcher; despues repetir suite y cierre. No desplegar
  `0.4.214` hasta obtener suite completamente verde.
## P-L78B - default global DeepSeek V4 Flash

- Candidato aislado `pl78b_deepseek_default`, versión `0.4.212`, sobre la base
  productiva `ba7d488d`/tree `6938d157`.
- `opencode-go/deepseek-v4-flash` es el default global. Los fallbacks técnicos
  siguen siendo Qwen y luego deterministas; GLM/Kimi/MiMo solo quedan como
  overrides explícitos, compatibilidad o historia.
- La telemetría de uso, snapshots de decisión y eventos CrewAI llevan
  `requested/effective/provider/fallback` del endpoint real. No se cambia la
  autoridad económica de gates, riesgo, sizing, planes u órdenes.
- QA: focales `317 passed`; suite completa aislada `2370 passed`, 1 skip
  preexistente y 1 warning externo en `812.37 s`; Ruff, NUL, compilación,
  diff, config, kernel temporal y smoke `run-once --skip-crew` temporal verdes.
- El worktree está listo para ensayo de integración cerrado. No tocar
  producción ni `.env` desde este relevo; el siguiente turno debe integrar el
  HEAD final con `merge --no-ff`, repetir gates y verificar dos health checks.

## P-L78C - `schedule-status` read-only (0.4.213)

- El candidato `pl78c_schedule_status_readonly` parte de P-L78B exacto y
  elimina la ruta `ensure_schema` del lector de estado del scheduler.
- `Store.read_runtime_values` usa SQLite URI `mode=ro` + `query_only`, cierra
  la conexión y falla cerrado ante DB ausente, schema legacy/incompatible,
  error de acceso, payload inválido o WAL/sidecars cuya lectura podría tocar
  `-shm`. En esos casos `runtime_state.available=false` y los jobs tienen
  `null`; calendario/cadencias permanecen informativos.
- El contrato CLI acepta `schedule-status --json`. No representa runtime
  unavailable como cero o como actividad confirmada; mantiene código `0` por
  compatibilidad y exige consumir `runtime_state.reason`.
- Suite final: `2380 passed, 1 skipped` preexistente
  (`test_score_study_regression_current_sqlite`, sin SQLite histórica local) y
  `1 warning` externo; focal P-L78C `10 passed`; Ruff, NUL, compilación, diff,
  config y smoke fake aislado verdes. Kernel temporal `unsealed` esperado sin
  violaciones.
  `schedule-status --json` real con DB ausente no crea `DATA_DIR` ni logs.
  La deriva productiva de `.env`/kernel continúa bloqueando P-L78B y no fue
  tocada por este lote.
- No integrar ni desplegar desde este relevo. Siguiente paso único: cerrar
  gates del candidato y resolver la procedencia autorizada de `.env` antes del
  ensayo combinado P-L78B+P-L78C.

## P-L78D - ensayo combinado P-L78B + P-L78C

- Merge de ensayo `304a61ab` con padres exactos producción `ba7d488d` y
  candidato `1bab847a`; árbol funcional `308baa64`, versión 0.4.213.
- Focales `174 passed`; suite `2380 passed`, un skip preexistente y una warning
  externa; Ruff, NUL, compilación, diff, config y smoke fake aislado verdes.
- Kernel temporal `unsealed` esperado sin violaciones. Kernel/broker/execution/
  risk son idénticos a producción; `config.py` solo contiene los cuatro
  defaults DeepSeek autorizados por P-L78B.
- Producción, `.env`, manifest, stack, SQLite, locks, leases y untracked del
  operador no se tocaron. La deriva `.env` continúa bloqueando el despliegue.
- Siguiente paso único: resolver autoridad/procedencia `.env` y repetir gates
  cerrados; no desplegar desde este ensayo.

## P-L79 - tabla de configuración Streamlit segura para PyArrow

- Candidato: `pl79_arrow_safe_config_table`, versión `0.4.214`, base
  `5e0f41e2`/tree `d00abe9c`.
- `page_config()` ya no entrega valores heterogéneos al serializador: la
  frontera informativa convierte booleanos, números, paths, secuencias y
  missing a texto determinista (`true`/`false`, valor numérico o `n/d`). No
  muta Settings ni añade claves o secretos.
- Suite `2385 passed`, un skip histórico preexistente y una warning externa;
  focales P-L79/P-L78B/P-L78C y flujo con dobles verdes. Ruff, NUL,
  compilación, diff, configuración temporal y kernel temporal (`unsealed`, sin
  violaciones) verdes. La ruta CLI real `run-once` no se lanzó porque exigiría
  adquisición de mercado; no se hizo red/broker/LLM.
- Siguiente paso único: revisar y ensayar integración `--no-ff` del candidato.
  El bloqueo productivo `.env`/kernel de P-L78 continúa intacto; P-L79 no lo
  repara ni autoriza despliegue.

## P-L79I - aislamiento de tests P-L69 respecto del entorno

- Contra `222d2371`, la prueba de defaults heredaba
  `TRADE_FILL_WATCH_ENABLED=true` del entorno del proceso aunque usara
  `DATA_DIR` temporal. La reproducción roja fue `1 failed`.
- Se corrigieron únicamente `tests/test_p69_fill_watch_implementation.py` y
  `tests/test_p76_p69_predeployment_rehearsal.py`: `_env_file=None`, entorno
  saneado con `monkeypatch` y regresión negativa con las seis variables del
  watcher. No cambia `.env`, Settings, watcher ni política.
- QA: `159 passed, 1 warning` con entorno activo externo y `3 passed` limpio;
  Ruff/NUL/diff verdes. Suite completa y smoke se reservan para la integración
  cerrada siguiente.
- Estado: `ready_for_closed_market_redeployment_rehearsal`; candidato limpio
  pendiente de ensayo `--no-ff`, sin despliegue en este lote.
## P-L79L - cierre productivo completado

- Dictamen: deployed el 02-ago-2026 con XNYS cerrado.
- Produccion integro 6c91279f mediante merge --no-ff 9b6c4a7b sobre
  1b88ae4a; padres exactos, tree funcional 8a0622ce y version 0.4.214.
- Preflight: PMR 2026-07-31 completed/pipeline_completed, lease vacio,
  runtime sin jobs activos, paper true, live/auto-apply false, kernel
  sellado/ok y .env autorizado estable (86a8420f...dfc35afb).
- Gates: focales activos/limpios 168 passed cada uno; suite 2387 passed y
  1 warning en 880.33 s; Ruff/NUL/compile/diff/config/kernel/smoke aislado
  verdes. Warning externa: websockets.legacy.
- Health: 02:46:27 y 02:48:08 CEST, separacion 101 s; raiz y /health
  200/200, un scheduler, listener unico, PID/lock/heartbeat coherentes y
  sin orden inesperada/database locked observado. lock_orphan continua siendo
  la etiqueta conocida del launcher/runtime, no un segundo scheduler.
- No tocar .env/manifest/protegidos, no kernel-seal, no broker/red/LLM real,
  jobs manuales, postmarket/reconciliacion, reinicio adicional ni push.

## P-L80A - auditoría del embudo de aprendizaje

Dictamen: `ready_for_implementation`. El worktree aislado documenta la
auditoría read-only de producción `0.4.214` del 02-ago. La actividad de
agentes está confirmada, pero el scoreboard `pmr_dfe5e200c9cc_measure_scoreboard`
recibe 43 ejecuciones sin controles: hay 493–496 filas de misma fecha y
489–496 intersecciones de `source_run_ids` por ejecución, pero las 43 llegan
como `executed_buy` con `gate.execution={}`. El matcher exacto no debe
relajarse ni sustituirse por SPY/régimen.

También quedan cuantificados 36/43 linajes verificados, 7
`legacy_unverified`, 199/200 propuestas PROSA, 0 experimentos de evidencia
admitidos en el digest vigente, WIP 14, 37 anomalías de market-data stale y
la discrepancia entre `duplicate_ratio=0,8433` del artefacto diario y la
proyección de SQLite consultada directamente. No se mezclan sus ventanas ni
denominadores. Runtime productivo se dejó `unavailable` por
`wal_mode_or_sidecar_present`, sin reparar sidecars.

Siguiente lote único: **P-L80B — cierre del carrier same-cycle**. Debe seguir
`signal_learning` → `signal_outcomes.gate_json` →
`learning_observations.gate_json` y conservar `source_run_id`, decisión,
razón/estado de capacidad y linaje; una fixture exacta debe producir pareja
control solo cuando todos esos campos estén presentes. Missing/conflict sigue
sin pareja. Probables fronteras: `signal_learning.py`, `daily_learning.py`,
`counterfactual_analysis.py` y tests; no tocar matcher, trading, risk,
execution, scheduler ni política. No reservar todavía versión.

Precondiciones y gates del siguiente lote: XNYS cerrado, PMR/lease terminales,
DATA_DIR temporal, `_env_file=None`, fakes sin red y suite completa únicamente
cuando no compita con producción. Si el carrier no existe o exige una frontera
protegida, detener y pedir revisión humana. P-L80C…P-L80G quedan únicamente
como cola provisional; no iniciar otro lote en paralelo.
## P-L80B - cierre prospectivo del carrier same-cycle

Dictamen del candidato: `ready_for_integration_rehearsal`. El productor
conserva `signal_id`, `source_run_id`, `cycle_id`, decisión y capacidad en el
carrier exacto hasta `signal_outcomes` y `learning_observations`; el matcher
no fue relajado. La fixture positiva produce un control solo con misma fecha,
source-run, `approved_buy*` y estado/razón allowlisted. Fecha/source distintos,
missing, conflicto o decisión no elegible siguen sin control.

Base P-L80A `b89bef47`; worktree
`pl80b_same_cycle_control_carrier`; rama
`codex/p-l80b-same-cycle-control-carrier`; versión candidata `0.4.215`.
Commits separados: `39ac28c6` (caracterización), `e089f7f3` (implementación)
y `a57c0f67` (QA/version policy). Suite: 2392 passed, 1 skip preexistente,
1 warning externo; focales 147 passed; Ruff/NUL/compile/diff/config y smoke
fake aislado verdes. Protegidos y producción permanecen intactos.

No hay backfill de las 43 filas históricas. El cutoff de cinco sesiones solo
se fija tras despliegue como `deployment_activation_at` UTC más la primera y
cuatro sesiones XNYS posteriores completadas con carrier exacto y outcomes
maduros. Siguiente lote único: ensayo de integración `--no-ff`; no desplegar
ni iniciar P-L80C-G en paralelo.

## P-L80BR - ensayo de integración P-L80B

El ensayo aislado quedó `ready_for_closed_market_deployment` en el merge
`5d7ea285` (`eb662c07` + `b0ff0d94`), versión `0.4.215`, tree idéntico al
candidato. Focales: 110 passed; suite completa reutilizada por identidad exacta
del tree: 2395 passed, 1 skip preexistente, 1 warning externo. Ruff/NUL/
compile/diff/config/smoke aislado verdes; kernel temporal unsealed esperado y
producción ok. No hubo cambios de trading/riesgo/ejecución ni backfill.

Siguiente paso único: cierre de mercado con preflight, suite/gates operativos y
despliegue secuenciado si todas las precondiciones siguen verdes. No iniciar
P-L80C-G ni ejecutar el carrier contra producción en este ensayo.

## P-L80H2 - estado del health DeepSeek

- Candidato aislado v0.4.216 en `codex/pl80h2-opencode-go-health`; script
  `scripts/check_opencode_go_deepseek.py` exige OpenCode Go/DeepSeek Flash y una
  sola llamada sin fallback ni reintento.
- La probe real del 02-ago devolvió `HTTP 403 region_forbidden`, con una sola
  petición y sin contenido/secretos expuestos. El proyecto resuelve de forma
  coherente `opencode-go/deepseek-v4-flash`; Qwen sigue siendo fallback técnico.
- Dictamen: `blocked_external_provider`. No desplegar ni cambiar proveedor.
  La única acción siguiente es habilitar el opt-in regional oficial y repetir
  exactamente este healthcheck una vez.

## P-L80H4 - estado del candidato tras el rollback

El primer gate de P-L80H3 fue una expectativa de version stale: la base
0.4.214 pasa, mientras el candidato 0.4.216 esperaba incorrectamente 0.4.215.
El fix minimo solo modifica esa prueba en `338d0cc0`.

QA cerrada del worktree P-L80H4: 70 focales passed; suite 2410 passed,
1 skip preexistente, 1 warning externo en 815.69 s; Ruff, NUL, compilacion,
diff, config y smoke fake aislado verdes. Kernel temporal unsealed esperado,
sin violaciones. Produccion sigue restaurada en `b1c4cc0f`/tree `2ee61f28`,
v0.4.214, stack sano. Proximo paso unico: redeploy cerrado de `338d0cc0` y
documentacion final, sin repetir probe DeepSeek.

## P-L80H5 - relevo tras despliegue

P-L80 v0.4.216 esta desplegado en el merge productivo `3e3ead0e` (padres
`97af2f24` y `f4b4bc58`, tree funcional `59097b81`). El revert-of-revert fue
auditable; no hubo conflictos. Suite: 2410 passed, 1 skip preexistente,
1 warning externa; focales 70 passed. Kernel/config, paper y stack quedaron
validos y las dos comprobaciones de salud fueron 200/200 con 136 s de
separacion. `lock_orphan` sigue siendo el falso positivo conocido del arbol
launcher/runtime, no un duplicado.

La probe DeepSeek verde existente se reutilizo sin nueva llamada
(`opencode-go/deepseek-v4-flash`, HTTP 200, stop, sin fallback, una request).
Cutoff: `2026-08-02T15:51:41.5484478Z`; cohorte: cinco sesiones XNYS
posteriores, previstas 03-07-ago si completan. Durante la ventana registrar
controles same-cycle, linaje, selected/not_selected, outcomes maduros,
costes/slippage/P-L/MFE/MAE/drawdown/concentracion, DeepSeek/fallback y
overnight. No abrir otro lote funcional antes de cerrar esa cohorte; observar
warnings preexistentes sin repararlos en este lote.
## P-L81 - relevo tras rollback

El candidato `7bc4648c`/tree `fc6916c2` fue integrado como `e8f7874e`, con
`2423 passed` post-merge, pero kernel rechazo el nuevo hash de `broker.py`.
Rollback auditable `6f86f260` restauro `e4fe1ddb` funcional/tree `ce15c1b0`,
v0.4.216; stack arriba y doble salud 200/200. El carry de `last_equity` es el
unico delta. Dictamen `needs_fix`: falta autoridad/procedimiento de sello
especifico antes de otro despliegue. No tocar P-L80, trading ni politica.
## P-L81 - relevo UI y metricas diarias

El candidato `codex/pl81-ui-daily-equity` adopta `daily_equity_pl = current_equity - account.last_equity` y su porcentaje sobre `last_equity`. La tarjeta global, Telegram cuando dispone del carrier oficial y la reconciliacion secundaria de posiciones distinguen diario, abierto, periodo y desde apertura. El chart conecta el punto actual con tramo discontinuo y muestra la fecha visual sin perder la sesion canónica.

Dictamen provisional: `ready_for_next_closed_market_deployment`. QA focal: 168 passed, 1 warning externo. No se requieren cambios en skills/runbooks. No desplegar si no queda margen para rollback, arranque y dos health checks antes de la apertura XNYS; produccion 0.4.216 permanece intacta.
## P-L81 - relevo tras reinicio y hard stop

El candidato `365d855f`/tree `8890f377`, v0.4.217, esta limpio. La primera suite termino `1555 passed, 1 failed, 1 warning` por expectativa stale `0.4.216`; se corrigio solo esa prueba y pasa aislada. La segunda suite fue interrumpida por reinicio sin salida recuperable: queda pendiente, sin repetirla durante la apertura.

Dictamen `ready_for_next_closed_market_deployment`: produccion `e4fe1ddb`/tree `ce15c1b0`, v0.4.216, stack arriba. Siguiente paso unico en cierre: suite completa aislada, gates restantes y despliegue solo si el preflight y el margen son seguros. No tocar broker carry, .env, protegidos ni politica.

## P-L81A - reaplicacion en curso

Se reaplica el contenido funcional validado desde `91ad200b` mediante
revert-of-revert auditable de `6f86f260`; los conflictos fueron solo
documentales y se conservaron las trazas de rollback y P-L81R. Falta ejecutar
la suite fresca y los gates antes de cualquier stack_down, sello o merge
productivo. No iniciar P-L82/P-L83.

## P-L81A - cierre productivo (04-ago-2026)

Dictamen: `deployed`. Merge `32c4025b` sobre `91ad200b`, segundo padre
`dc5df89e`, tree `0619f5b6`, version `0.4.217`. El carry autorizado de
`account.last_equity` se limito a `broker.py` y el resto de protegidos conserva
sus objetos Git; `.env` no cambio.

La suite fresca post-merge fue `2422 passed, 1 skipped preexistente, 1 warning`
en 975.02 s; focales `109 passed`. Ruff/NUL/compile/diff/version policy,
validate-agent-config aislado, kernel temporal y smoke fake pasaron. El sello
canonico unico termino con kernel `ok` sin violaciones. Salud 1
`2026-08-04T08:45:16+02:00` y salud 2 `2026-08-04T08:47:19+02:00` quedaron
separadas 123 s, con HTTP 200/200, scheduler y listener unicos, token/lock
coherentes, paper activo, live/auto-apply off y 0 criticos. Los tres warnings
preexistentes siguen observacionales.

El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` permanece vigente. No hubo probe
DeepSeek adicional, jobs manuales, backfill, reconciliacion forzada ni push.
La siguiente accion es observar la cohorte prospectiva P-L80; no abrir P-L82/P-L83
en este turno.

## P-L82 - relevo de autoridad SPY

El candidato `0.4.218` resuelve la autoridad de apertura SPY por grupo de valor
canónico y no por el primer artefacto leído. La reproducción base fue roja
cuando el genérico del mismo precio precedía a la cache dedicada; el orden
inverso era verde. Autoridades discordantes siguen en `conflict`. La UI expone
sesiones omitidas con fecha, estado, motivo y cobertura sin fabricar puntos.

Worktree `pl82_spy_opening_authority`, rama
`codex/pl82-spy-opening-authority`; commits `e1538614`, `87919ee2`, `d5228ac4`
y `b938eaa9`. Suite fresca `2430 passed, 1 skipped preexistente, 1 warning`;
focales `193 passed, 1 warning`; Ruff, NUL, compile, diff, config y kernel
temporal sin violaciones verdes. Producción P-L81A permanece intacta en
`0.4.217`; no tocar broker/kernel/execution/risk/config/.env ni la captura
P-L80. Siguiente paso único: preflight cerrado y despliegue secuenciado solo
con margen suficiente; no iniciar P-L83.

## P-L82 - relevo tras despliegue

P-L82 esta desplegado en `0.4.218`: merge productivo
`df80dee8` (padres `31b7367b` y `a0ac5eed`), tree funcional `93d8a756`.
La tentativa accidental `098283bf` fue revertida auditablemente por
`31b7367b` antes de la integracion final. La suite post-merge fue `2431
passed, 1 warning`; focales `193 passed, 1 warning`; kernel `ok`, paper
activo, live/auto-apply off. Salud 1 `09:59:51 CEST` y salud 2 `10:02:08
CEST` fueron 200/200 con `136.89s` de separacion, scheduler/listener unicos,
token coherente y 0 criticos. El runtime de `schedule-status` queda
`unavailable` por WAL/sidecars segun el contrato read-only, sin reparacion.

El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` no cambia y no hubo backfill,
jobs manuales, nueva probe DeepSeek ni push. No iniciar P-L83 en este turno.

### P-L82R - cierre productivo

P-L82R queda `deployed` en version `0.4.219`: merge `b0a88b98`, primer padre
`d73a8971`, segundo padre `06152971`, tree `cd75d3de`. El ensayo aislado
`67183356` tuvo el mismo tree y cero conflictos. Suite post-merge `2436
passed, 1 skipped preexistente, 1 warning` en `763.44s`; Ruff, NUL, compile,
diff, version policy, config aislada, kernel temporal/productivo y smoke fake
verdes. Salud 1 `11:07:20 CEST` y salud 2 `11:09:34 CEST`, separadas `134.33s`,
confirmaron HTTP raíz/health 200/200, listener único, wrapper/launcher/runtime,
scheduler con owner/token coherentes, paper activo, live/auto-apply off, kernel
`ok`, 0 críticos y cero órdenes desde el merge. `schedule-status` mantiene
runtime `unavailable` por WAL/sidecars bajo contrato read-only, sin reparación;
PMR 03/08 terminal y coordinación activa vacía. Cutoff P-L80 intacto. No
backfill, jobs manuales, nueva probe DeepSeek, P-L83 ni push.

## P-L82R - continuidad temporal Sistema vs SPY

El candidato `0.4.219` queda listo para integración cerrada, no desplegado.
Base productiva exacta `d73a8971` / tree `f966a725`; worktree
`pl82r_spy_temporal_continuity`, rama `codex/pl82r-spy-temporal-continuity`,
HEAD `1fab7813`, tree `32506e65`. La regresión estaba en la presentación y
comparabilidad: la línea atravesaba omisiones y un SPY stale se trataba como
ganador vigente.

El fix segmenta únicamente intervalos XNYS contiguos, no conecta sobre
omitted/conflict/missing y exige igualdad exacta UTC de los dos `as_of` para
comparar la fila `En curso`. Si no están alineados, ambos valores siguen
visibles con `comparison_status=unavailable`, razón, lag y cobertura; no hay
ganador ni conector. El caso sistema 04/08 08:11Z frente a SPY 03/08 20:12:55Z
queda fuera de comparación. Conflictos y cuatro omisiones P-L82 se preservan.

QA: focales `6 passed`; regresiones UI/SPY/Telegram `200 passed, 1 warning`;
suite `2436 passed, 1 skipped preexistente, 1 warning` en `786.12s`; Ruff,
NUL, compile, diff, version policy, configuración aislada, kernel temporal
`unsealed` sin violaciones y smoke fake aislado verdes. Protegidos iguales a
la base; producción/stack/cutoff P-L80 sin cambios. Siguiente paso único:
ensayo `merge --no-ff`, preflight cerrado renovado y despliegue secuenciado
solo con margen; no iniciar P-L83.

## P-L83D - cierre productivo y congelacion

P-L83D esta `deployed` en `0.4.220`: merge `613aab87` sobre `5d53e24c`,
segundo padre `c3a5e671`, tree `57780f1d`. La UI ancla los buckets diarios a
cierres XNYS, corrige epoch seconds y mantiene el current provisional
separado. No se modificaron broker, kernel, execution, risk, config, `.env`,
trading ni la cohorte P-L80.

Suite `2444 passed, 1 skip preexistente, 1 warning`; focales post-merge `227
passed, 1 warning`; gates verdes. Salud 1 `12:36:06 CEST` y salud 2
`12:37:58 CEST`, separadas `111.83s`: HTTP 200/200, scheduler/listener
unicos, owner/token/heartbeat coherentes, paper activo, live/auto-apply off,
kernel ok, 0 criticos y 0 ordenes abiertas. Los tres warnings preexistentes
siguen observacionales.

Cutoff P-L80 `2026-08-02T15:51:41.5484478Z` intacto. Congelar cambios
funcionales hasta la revision del 08/08; no iniciar P-L82/P-L83 adicionales,
no backfill, no jobs manuales y no push.

## P-L83D - dashboard y fechas temporales

El candidato aislado `codex/pl83d-dashboard-temporal-dates`, version `0.4.220`,
HEAD `d15eb37e` y tree `306a3dae`, corrige la interpretacion de buckets Alpaca
1D: los epoch se normalizan por unidad y cada punto se ancla a la sesion XNYS
de cierre. El current queda separado como provisional, no pisa cierres y la
ventana de siete dias usa `session_date`. Se preservan P-L80 y P-L82R.

QA fresca: `2444 passed, 1 skip preexistente, 1 warning` en 1139.57 s;
focales P-L83D/UI `133 passed` y regresiones adicionales `102 passed`; Ruff,
NUL, compile, diff-check, version, config aislada y smoke fake verdes. Los
archivos protegidos permanecen iguales y produccion continua en `0.4.219`.

Dictamen provisional: `ready_for_closed_market_deployment`. Siguiente accion
unica: ensayo `merge --no-ff` y preflight cerrado con margen; no detener el
stack si no se puede completar rollback, arranque y dos health checks antes de
la apertura. Tras el cierre de P-L83D, congelar cambios hasta la revision del
08/08.

## P-L84 - plan condicional de evidencia multi-agente

Se incorpora al plan maestro una cola condicional inspirada por la arquitectura
publica de BQuant Agents: contrato efectivo de agentes, aportacion ortogonal,
debate auditado, decision no-trade, horizontes y datos point-in-time. Es una
actualizacion exclusivamente documental, sin version ni autorizacion de
implementacion.

La siguiente accion sigue siendo la revision prospectiva P-L80 del 08/08. Si
las cinco sesiones y outcomes estan maduros, se elegira un unico lote por riesgo
y valor de informacion. P-L84A, auditoria read-only del contrato real de cada
agente, es solo el candidato por defecto; queda desplazado si la revision
descubre antes un defecto critico de captura, control same-cycle, linaje,
costes o outcomes. P-L84B-H no se ejecutan en paralelo, no cambian politica y
requieren autorizacion posterior segun su alcance.

## P-L85 - estado para cierre Zen Free

La incertidumbre de la probe Zen quedo caracterizada sin relajar el contrato.
Las cuatro llamadas Zen corregidas y la health Go fueron HTTP 200, `stop`, con
contenido final y `reasoning_content` presentes; se consumio el presupuesto
`10/10` y no se observaron limites de rate ni errores HTTP. La respuesta
historica `length` queda como evidencia invalida de la bateria original y su
causa exacta es `unavailable`.

El candidato aislado configura Zen Free como primario y una sola tentativa Go
como fallback inmediato, con fallbacks locales posteriores. La telemetria no
publica mensajes crudos del proveedor; solo clase/HTTP acotados. Suite fresca:
`2456 passed, 1 skipped preexistente, 1 warning` en `752.91s`; focales
posteriores `106 passed`. Produccion sigue Go/v0.4.220 hasta un preflight
cerrado, gates detenidos, delta `.env` no secreto revisado, eventual sello
canonico unico, stack_up y doble salud >=75 s. No iniciar otro lote en paralelo,
no tocar el cutoff P-L80 ni hacer backfill.

### P-L85 - desplegado

P-L85 queda desplegado en `0.4.221`, merge `78bb0758`, tree funcional
`8ea38dbb`. Zen Free es primario y Go es fallback inmediato de una sola
tentativa; los fallbacks locales existentes siguen después. El sello canónico
único de `.env` terminó `ok`; no se tocaron credenciales ni política. Suite
`2456 passed, 1 skip preexistente, 1 warning`, focales post-merge `161 passed`.
Salud 1 `01:12:25.746` y salud 2 `01:14:15.675` Madrid, separadas `109.9286s`,
confirmaron HTTP 200/200, scheduler/listener únicos, owner/token/heartbeat,
paper/live/auto-apply seguros y cero órdenes abiertas. `activation_at`:
`2026-08-05T23:14:15.6752134Z`; cutoff P-L80 intacto, sin backfill ni nueva
probe. La prioridad siguiente es la revisión de cohorte del 08/08, no otro
lote de proveedores en paralelo.

## P-L86R - página Kindle oculta en Streamlit

P-L86R sustituye la tentativa independiente de servidor/puerto/tarea por una
única ruta `/kindle` dentro de `AgenteBolsaWeb` en el puerto 8501. El candidato
usa Streamlit 1.58 (`st.Page(url_path="kindle", visibility="hidden")` y
`st.navigation(position="hidden")`), conserva la navegación manual en `/` y
no expone la ruta en el menú.

La vista reutiliza `PortfolioSnapshot`, `daily_equity_change`, el consumidor
SPY del dashboard y las posiciones ya cargadas. No crea snapshots, carriers,
archivos, jobs, procesos ni escrituras; no llama a broker/LLM/red desde un
productor nuevo. El HTML es básico, escapado, blanco/negro y sin JavaScript ni
recursos externos. La versión candidata es `0.4.222`.

La caracterización y los focales iniciales pasan `54`. Falta la suite completa
y los gates de cierre en árbol final. Producción sigue `0.4.221`, P-L80/P-L85
permanecen intactos y los componentes independientes antiguos no deben
reaparecer. Solo si el preflight cerrado y el margen hasta XNYS siguen verdes
se hará merge `--no-ff`, stack gestionado, comprobación real de `/kindle` y dos
health checks separados >=75 s. Sin push.

### P-L86R - cierre productivo

P-L86R queda `deployed` en `0.4.222`: merge `849feebd`, primer padre
`faa2e157`, segundo padre `307658f3`, árbol funcional del candidato `bd5e10d4`.
La ruta oculta `/kindle` comparte `AgenteBolsaWeb` y 8501, sin servidor,
snapshot, carrier, tarea o scheduler nuevos. La suite final fue
`2464 passed, 1 skip, 1 warning` en `891.60s`; focales post-merge `54`, gates
breves verdes. Salud 1/2 200/200, separadas `134.66s`, kernel `ok`, scheduler y
listener únicos, paper activo, live/auto-apply off y 0 críticos. El cutoff
P-L80 y P-L85 permanecen intactos. No abrir otro lote ni hacer push.

## P-L86L - habilitación LAN privada

Lote operacional pendiente: actualizar únicamente `install_web_task.ps1` para
`--host 0.0.0.0`, reconciliar la tarea existente y crear una regla TCP 8501
limitada a `Private/LocalSubnet`. La WLAN ya está en `Private`; no tocar
scheduler, trading, configuración protegida ni otros puertos. Tras reiniciar
solo web, validar localhost/LAN, `/health`, `/kindle`, listener y Git limpio.

## P-L86K - ruta Kindle raw

Dictamen: `deployed`. La caracterizacion
confirmo que `/kindle` devolvia el shell JS de Streamlit. El candidato v0.4.223
registra una ruta ASGI oficial `st.App`/Starlette antes de las rutas internas,
sin servidor, proceso, puerto, tarea o persistencia nuevos. Loading y vista
cargada son HTML simple sin JS; la vista usa el snapshot de cuenta, no expone
`Cantidad` y deja SPY en `n/d` si el carrier diario no prueba comparabilidad.
Focales y lint son verdes. Merge `9b9068f3`, tarea web gestionada Running,
HTTP 200 local/LAN y dos saludes separadas 121.28 s. Produccion queda en
v0.4.223; scheduler, LAN, P-L80 y P-L85 no cambian.

## P-L87 - siguiente cierre

P-L87 queda `deployed` en v0.4.224 mediante merge `db5a8584`: añade
la cuarta tarjeta de ganancia/pérdida intradía de posiciones con cobertura K/N
y las ventas desde la apertura XNYS, una fila por sell fill. Reutiliza los
carriers ya cargados, conserva `n/d` cuando falta P/L realizado o apertura y no
altera trading, riesgo, ejecución ni P-L80. La tarea web fue reiniciada de
forma gestionada; raíz, `/health` y `/kindle` quedaron 200 local/LAN y las dos
saludes se separaron 110,6 s. No iniciar P-L88.

## P-L88 - dashboard Sistema vs S&P 500

El candidato aislado `codex/pl88-system-spy-temporal-ui` adopta la ventana
apertura XNYS exacta -> ahora para Sistema y el carrier existente de SPY. Un
SPY solo se dibuja/compara si es el ETF correcto, transporta
`provider_observed_at`/`market_observed_at` explicito y su observacion esta a
<=300 segundos del `account_read_at`; `created_at` de cache no sustituye ese
timestamp. Sin carrier explicito el caso queda `n/d` con razon
`current_observation_timestamp_unverified`, sin ganador. La cabecera conserva
el P/L oficial desde cierre anterior pero lo identifica con ese nombre. El
commit N1 separado etiqueta cada punto visible de `Valor de cartera` con
porcentaje y color semantico, preservando el predecesor oculto.

Base productiva: `0cf8a535` / tree `57ad3370` / v0.4.224 limpia. Candidato
v0.4.225; commits `81a2bcd0`, `64bf9b59`, `7717c20f`, `e04f3ba0`, `7abdfb1f`,
`9350f024`; informe unico `docs/informe_p_l88_sistema_spy_temporal.md`.
P-L88R: caracterizacion roja `1 failed`, despues `10 passed` y `40 passed` de
regresiones SPY; Ruff/NUL/diff verdes. XNYS estaba abierto durante la
ejecucion, por lo que no hubo suite completa, merge, reinicio ni despliegue.
La UI queda lista para un despliegue veraz, pero la comparacion SPY
apertura->ahora sigue `unavailable` hasta resolver fuente/cadencia. P-L80 y la
politica de trading permanecen intactos.

### Cierre productivo P-L88R-D

P-L88R-D queda `deployed` en v0.4.225: merge `8b572948` con primer padre
`0cf8a535` y segundo padre `2884f2ac`, tree `3d0c8650`. Suite definitiva
`2493 passed, 1 skipped, 1 warning`; focal post-merge `111 passed, 1 warning`
y gates estaticos/config/kernel/smoke verdes. Dos saludes: 00:01:49 y
00:04:19 CEST (~150 s), HTTP 200 local/LAN en `/`, `/health` y `/kindle`,
listener unico, scheduler owner/token coherentes, paper activo y live/
auto-apply off. El kernel productivo sigue valido. SPY no comparable sin
`provider_observed_at`/`market_observed_at`; no iniciar una fuente nueva en
este lote.

### Cierre P-L88R-D

La suite cerrada inicial encontro una expectativa de version stale en
`test_p59c_llm_selected_authority.py` (`1567 passed, 1 failed, 1 warning`),
reproducible tambien en la base `0cf8a535`. `de7b9923` corrigio solo el test a
`0.4.225`; la suite fresca definitiva termino `2493 passed, 1 skipped, 1
warning` en `801.14 s`. Smoke fake `1 passed`, Ruff/NUL/compile/diff-check y
configuracion aislada verdes. No se repite la suite por cambios documentales
posteriores; el siguiente paso unico es preflight cerrado, merge gestionado y
dos comprobaciones de salud. SPY sigue honestamente `n/d` si no existe
`provider_observed_at`/`market_observed_at` alineado.

## P-L89B - siguiente paso unico

El candidato `codex/pl89b-capital-observability` queda listo para integracion
cerrada en version `0.4.226`. Completa el carrier observacional append-only
del funnel de capital con IDs exactos y proyecta la cuenta desde el snapshot
ya cargado, sin llamadas broker nuevas ni autoridad sobre sizing, gates,
riesgo, seleccion o ejecucion. El EOD lleva `previous_close_equity` como
`equity_start` y timestamps UTC coherentes; sigue `unavailable` si faltan
ventana XNYS, flows, costes, exposicion temporal o benchmark comparable.

QA final: `2497 passed, 1 skip preexistente, 1 warning` en `797.61s`; focales
36 y policy 47, Ruff/NUL/compile/diff/config/kernel/smoke verdes. Produccion
base `eb9d6bede5a5aa55de10441fb442430028d1fb47` / tree
`250dfa2c527d53c1d3d13ecda1ea5027f496e149` permanece intacta. El cutoff
P-L80 no cambia. No iniciar experimento de capital: esperar dos ventanas
maduras con controles same-cycle y EOD/costes/exposicion validos.

Siguiente accion: renovar preflight cerrado, hacer merge `--no-ff` del
candidato, repetir gates con stack detenido y ejecutar stack_up con dos
saludes separadas. Si falla una precondicion, no desplegar y dejar produccion
intacta. Sin backfill, jobs manuales, kernel-seal, cambios de `.env` ni push.

### Cierre productivo P-L89B

P-L89B fue desplegado en v0.4.226 mediante merge `4efd58ff` (primer padre
`eb9d6bde`, segundo `6a87c589`, tree funcional `505c3ee8`). La suite definitiva
reutilizada por identidad exacta fue `2497 passed, 1 skipped preexistente,
1 warning`; gates post-merge verdes. Salud 1 a las 23:51:33.9799274 CEST y
salud 2 a las 23:53:37.2454445 CEST, separadas 123.27 s: HTTP 200 en las tres
rutas web, listener unico, scheduler owner/token coherentes, paper activo,
live/auto-apply off, kernel/config validos y 0 criticos. El funnel/EOD
historico sigue `unavailable` cuando faltan carriers; no se imputo nada. El
cutoff P-L80 permanece intacto. Siguiente paso unico: observar dos ventanas
maduras con controles same-cycle y EOD/costes/exposicion validos antes de
valorar una dimension shadow, siempre human-gated.
## P-L89-RPI-HARDENING - estado operativo

El lote `codex/operational-hardening` añade un preflight Raspberry read-only y
corrige la detección de ownership Windows en la cadena wrapper -> launcher
`.venv` -> runtime Python. No toca trading, riesgo, broker, `.env`, SQLite
activa ni `whale-copy`.

Preflight real 2026-08-12 23:21 Europe/Madrid: Raspberry `Raspberryi5`,
`aarch64`, USB `/dev/sda1` ext4 `rw`, UUID esperado, espacio suficiente,
contenedores core healthy, imagen `0.4.230-arm64` cargada y flags PAPER
correctos. Dictamen `precondition_not_met`: el host se reinicio a las 23:15:16 y
solo tenia 455 s de uptime; falta receipt de snapshot frio SQLite. La lectura
no produjo mutaciones ni dejo procesos `D`.

Siguiente secuencia: esperar estabilidad, producir y validar el snapshot frio
autorizado, ejecutar el preflight con `--sqlite-receipt`, confirmar postmarket,
leases y exclusividad Windows, y solo despues realizar el corte cerrado con
rollback a `0.4.229-arm64` preparado.

La herramienta `scripts/sqlite_cold_snapshot.py` implementa ese snapshot sin
`VACUUM`, checkpoint ni backfill: exige `--writers-stopped`, no sobrescribe,
conserva los sidecars presentes, valida la copia y genera `receipt.json` con
hashes y resultados de integridad.

Ultimo preflight estricto 2026-08-12 23:37 CEST: Raspberry estable (uptime
1306 s), USB esperado ext4/rw sin I/O reciente, core Docker healthy, candidata
`0.4.230-arm64` cargada y flags PAPER coherentes por contenedor. Dictamen
`precondition_not_met`: falta receipt de snapshot fria y Windows aun mantiene
scheduler/web activos. No detener, reiniciar ni cambiar Compose/env hasta el
corte autorizado; conservar rollback a `0.4.229-arm64`.

Reconciliacion 23:42 CEST: `windows_exclusivity` ya informa `foreign=[]` al
resolver el checkout principal desde `git-common-dir`; la foreign process
anterior era un falso positivo del worktree candidato. Permanecen solo falta
de receipt SQLite y scheduler/web Windows activos.

Ventana 2026-08-12 23:46-23:53 CEST: se detuvo Windows con el helper canonico,
se creo y valido la snapshot fria v2 en
`C:\Antonio\Bref\agenteBolsa_backups\raspberry-cut-20260812-2350` (base
`7fab2f7f...`, WAL `66632ef2...`, SHM `e5e00a5e...`, quick/integrity ok). El
preflight Raspberry bloqueo el corte por `whale-copy` en estado D y memoria
disponible bajo 256 MiB. Se hizo rollback a Windows; despues Raspberry se
reinicio externamente y el preflight final mostro uptime 67 s y core
unhealthy. Dictamen `precondition_not_met`; no transferir ni desplegar hasta
auditoria read-only del reinicio y estabilidad >=600 s. La snapshot y la
candidata se conservan; la exclusividad queda sin demostrar porque Raspberry
conserva el core antiguo `0.4.229-arm64`.

Auditoria 23:56 CEST: Raspberry respondia, USB ext4/rw y `whale-copy`
`running/healthy`, pero uptime solo 4 min. `journalctl` no conserva el boot
anterior ni evidencia OOM/I/O/watchdog; causa del reinicio `unavailable`. No
hacer otro corte hasta superar 600 s y repetir el preflight.
