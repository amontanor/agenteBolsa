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
