# P-L43C-T — contrato de autoridad causal de salidas time-stop

## Dictamen

`ready_for_p43c_implementation`.

La caracterización define una captura predecisión inmutable y un enlace
posterior a la orden. La captura se crea antes del intento de envío, pero sus
artefactos se persisten después del envío. Así se puede demostrar la autoridad
sin convertir la telemetría en un bloqueo de una salida protectora.

## Alcance y aislamiento

- Base: `24537e813ff0905696cda0b3925a212045ee7b09`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl43c_exit_authority_tests`.
- Rama: `codex/pl43c-exit-authority-tests`.
- Versión de caracterización: `0.4.192`, exigida por `test_version_policy` al
  detectar el nuevo archivo de tests. Es una reserva documental de
  caracterización, no un release funcional ni un candidato desplegable.
- No se modifican `src/`, archivos protegidos, producción, `.env` ni SQLite
  productiva.

## Contrato caracterizado

### Captura predecisión

`p-l43c.time-stop-exit-authority.v1` usa `decision_id` determinista y contiene:

- `decided_at`, `cycle_id/watch_id`, `position_identity/lot_id`;
- `buy_broker_order_id`, `source_plan_id`, `plan_id`, `qty`;
- `active_authority`, `active_policy_version`, `active_result`,
  `active_eligible`, `active_reason_code`;
- `shadow_authority`, `shadow_policy_version`, `shadow_only`, `shadow_result`,
  `shadow_eligible`, `comparison_status`;
- autoridad y timestamp del fill BUY;
- edad legacy, sesiones XNYS, elegibilidad lógica y primera ventana accionable;
- calidad, razones de unavailable/ambiguous y `content_hash`.

`trigger=time_stop_v2` es únicamente la familia de salida. No se interpreta
como la autoridad activa. `shadow_only=true` tampoco promueve XNYS a activo.

### Enlace posterior

`p-l43c.time-stop-exit-order-link.v1` usa un `event_id` derivado de
`broker_order_id` o `client_order_id` e incluye `decision_id`, hash de la
decisión, plan/source plan, identidad de lote, orden, estado de envío, error,
autoridad activa y un fingerprint seguro de la llamada.

La persistencia se ejecuta después de la llamada activa. El informe lo denomina
`predecision capture persisted post-submit`, no evento durable preorden. La
captura en memoria conserva la precedencia `decided_at < submitted_at`.

## Estados y reglas

- `legacy_calendar_days`, `guarded_xnys`, `active_xnys`, `other` y `unavailable`
  son autoridades; `shadow_authority` es independiente.
- `legacy_only`, `xnys_only`, `both_eligible`, `neither` y `unavailable` son
  comparaciones, no políticas.
- Si legacy no es elegible, XNYS shadow no crea un plan.
- Si source plan, lote, broker order o fill autorizado faltan, el resultado es
  `unavailable` o `ambiguous`; no se usa FIFO, símbolo, fecha ni última compra.
- Recompras del mismo símbolo generan decisiones diferentes.
- `stop_loss` y `take_profit` son `not_applicable` para autoridad time-stop.
- Pending/rejected/cancelled y errores de envío conservan un enlace terminal
  cuando existe identidad.
- `captured_at` y `observed_at` quedan fuera del hash.
- Idéntico es idempotente; contenido distinto crea conflicto y conserva el
  original.

## Fixtures y denominadores

Las pruebas cubren los cinco casos sanitizados `legacy_only`, XNYS unavailable,
`xnys_only` shadow sin plan, ambos elegibles con legacy activa, ninguno elegible,
stop/take, recompras, source plan ausente/duplicado, partial BUY sin
`first_fill_at`, estados pending/rejected/cancelled, excepción de envío,
persistencia posterior, fallo fail-open, hash estable, retry, conflicto,
fingerprint sin secretos y concurrencia temporal.

Los denominadores del lector caracterizado son:

`canonical_decisions`, `linked_orders`, `unlinked_decisions`,
`unlinked_orders`, `legacy_authority`, `shadow_authority`,
`ambiguous`, `unavailable`, `conflicts` y `coverage`.

Sin eventos se publica `collecting` con denominadores `null`; no se interpreta
como cero. Conflictos y reporter genérico quedan fuera del canónico.

## Paridad y fail-open

Las pruebas verifican igualdad de la llamada `close_position` con y sin carrier,
sin alterar trigger, qty, precio, stops, takes, trailing, riesgo, exposición,
límites ni la rama activa. Un fallo de persistencia conserva idéntico el
resultado de envío. La caracterización no mueve la autoridad a XNYS.

## QA permitida y omitida

Se ejecutan las nuevas pruebas y focales relacionadas de P-L43BR5/BR6,
time-stop, history, storage y reconciliación, además de Ruff, NUL y
`git diff --check`. Con XNYS abierto se omiten suite completa, smoke y
benchmark largo; no se ejecutan broker, red, LLM, jobs, reconciliación ni
postmarket productivos.

## Siguiente lote mínimo

Implementar el carrier en una frontera no protegida, preservando el request
broker y persistiendo ambos artefactos después del intento de envío. Debe
mantenerse fail-open y añadir los enlaces exactos autoridad→plan→orden sin
modificar `legacy_calendar_days` ni XNYS shadow.

## P-L43C-W - implementacion shadow del carrier

### Dictamen provisional

`ready_for_closed_market_full_validation`.

El candidato implementa el contrato sin promover XNYS: `legacy_calendar_days`
continua siendo `active_authority` y `time_stop_xnys.v1` permanece separado con
`shadow_only=true`. La captura se construye en memoria despues de crear el plan
`risk_exit` y antes de la llamada activa. El enlace se prepara despues del
retorno o excepcion de envio y ambos eventos se escriben juntos en una
transaccion corta.

### Frontera y flujo real

La ruta conservada es:

`_execute_stop_take_exits` -> `_risk_exit_plan` -> captura P-L43C en memoria ->
metadata local `risk_decision.checks.time_stop_exit_authority` ->
`submit_paper_order_plan` sin cambios -> persistencia P-L43C ->
`save_broker_order` -> reconciliacion existente.

El `execution.py` protegido no se modifica. En la salida completa sigue
recibiendo el mismo `settings`, `plan` y `client_order_id`, y sigue llamando a
`close_position(symbol)`. El carrier solo deja en el plan local
`schema_version`, `decision_id`, `content_hash` y `active_authority`; no se
envia el payload completo al broker.

La identidad de lote procede de los lotes abiertos exactos de P-L43BR6:
`buy_broker_order_id`, `order_plan_id/source_plan_id`, `fill_authority` y
`entry_fill_at`. Un solo lote verificable puede quedar `available`; recompra
multilote, duplicidad, falta de fill autorizado o falta de identidad queda
`ambiguous`/`unavailable`. No existe fallback por simbolo, fecha, texto ni FIFO.

### Persistencia y lectura

Se anaden los eventos append-only:

- `time_stop_exit_authority:<decision_id>`;
- `time_stop_exit_order_link:<broker_order_id|client_order_id|attempt_id>`.

`Store.record_time_stop_exit_authority` usa una unica `BEGIN IMMEDIATE` para
decision y link, sin `INSERT OR REPLACE`, tabla, migracion, backfill ni
`runtime_state` como historia. Mismo hash es `idempotent`; contenido distinto
conserva el original y publica conflicto separado. `captured_at`/`observed_at` no rompen el hash. El lector y `time-stop-exit-authority --json` consumen solo
los tipos canonicos y devuelven `collecting` con denominadores `null` sin
eventos; no reconstruyen por simbolo.

### QA y limites

- P-L43C-T heredado: 29 pruebas verdes.
- P-L43C-W productivo: 40 pruebas verdes.
- Focales P-L43BR5/BR6, time-stop, storage, scheduler, P-L47, P-L48,
  reconciliacion, execution quality y conectividad: 176 pruebas verdes.
- Ruff completo, `check_no_nulls.py`, `git diff --check` y
  `validate-agent-config --json` temporal: verdes.
- La politica de version: 17 pruebas verdes; el valor sigue exactamente en
  `0.4.192`, con una nota de slot en `__init__.py`.
- QA fix separado `1788917041f7f141371ee873739634f4d1826c47`: un
  `source_plan_id` del contexto legacy que difiere del lote BUY exacto deja el
  carrier `unavailable`; la salida activa no cambia.

No se ejecutaron suite completa, smoke, run-once, broker, red, LLM, servicios,
postmarket ni reconciliacion productivos. La validacion cerrada completa y un
smoke totalmente aislado quedan pendientes para el siguiente lote.

### Performance focal de 100 decisiones temporales

Medicion descriptiva sobre SQLite temporal, 100 decisiones y 100 transacciones:

- construccion: p50 0.0793 ms, p95 0.1016 ms, max 0.2020 ms;
- serializacion captura+link: p50 0.0419 ms, p95 0.0525 ms, max 0.2137 ms;
- persistencia de la transaccion post-submit: p50 5.9917 ms, p95
  10.4367 ms, max 13.2141 ms;
- evento decision+link: p50/max 2,221 bytes;
- conexiones/transacciones: 100/100, una de cada por salida;
- WAL final temporal: 3,724,512 bytes; no hubo locks.

La medicion no separa internamente la espera de `BEGIN IMMEDIATE` del
trabajo dentro de la transaccion; el tiempo publicado es la persistencia total
de esa unica transaccion. No se establece un umbral arbitrario. El riesgo
operativo focal es `low` para esta carga porque la persistencia ocurre
despues del envio y no hay trabajo por candidato, pero la validacion larga y
concurrencia integrada siguen pendientes.

### Commits y seguridad

- `0dfc3d2d638a4ec4f8bafb18e819c5cda9479b08` -
  `feat: add time-stop exit authority carrier`.
- `17c6768a8b81b1aaa64cf4877adab8b26fee4ee9` -
  `test: verify authority wiring and parity`.

La documentacion se consolida en este informe y no crea un plan paralelo.
Produccion, otros candidatos, servicios y SQLite productiva permanecen fuera
del lote; no hubo despliegue, reinicio ni push.
