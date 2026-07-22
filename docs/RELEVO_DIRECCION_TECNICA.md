# Relevo de direccion tecnica — agenteBolsa

> Actualizado: **19-jul-2026**. Produccion **0.4.185** (`8cfa0db3`, tree
> `4c3636be`). P-L48B desplegado en mercado cerrado; P-L44B sigue en shadow.

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
