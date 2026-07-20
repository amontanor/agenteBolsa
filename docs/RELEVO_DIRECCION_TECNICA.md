# Relevo de direccion tecnica — agenteBolsa

> Actualizado: **20-jul-2026**. Produccion **0.4.185** (`8cfa0db3`, tree
> `4c3636be`). P-L48B desplegado en mercado cerrado; P-L44B sigue en shadow.

> P-L50BR1: el worktree combinado queda en candidato **0.4.188**, con la
> secuencia P-L49B 0.4.186 -> P-L46BR3 0.4.187 -> P-L50B 0.4.188. No es un
> despliegue productivo.

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
solo lectura. QA focal: 607 passed; interacción: 3 passed. XNYS estaba abierto,
por lo que no se ejecutaron suite completa, smoke ni despliegue.

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
