# Informe único — controlled position adds (12-oct-2026)

Dictamen: `ready_for_integration_rehearsal` como guardia aislada en `shadow`.
No existe autoridad de ejecución ni activación productiva.

## Alcance y contrato

El lote implementa `evaluate_controlled_position_add(context, *, policy=None)`
en `src/agente_bolsa/tools/controlled_position_adds.py`. La función es pura,
ducktyped y fail-closed: consume `Mapping` o carriers sencillos con
`as_dict()`, devuelve razones estructuradas y nunca importa broker, ejecución,
red, LLM o SQLite.

La salida estable incluye:

- `authority="guard_only"`, `execution_authority=false`;
- `eligible`, `guard_eligible`, `status`, `policy_enabled`, `policy_mode`;
- `reason_codes` y `eligibility_reasons`;
- IDs exactos de señal/captura nueva y fill BUY precedente;
- cantidades, capital calculado (incluidos `pending_cash_reserved`,
  `pending_risk_pct` y `add_risk_pct`) y garantías
  `preserve_existing_protection=true`, `cancel_existing_orders=false`.

`build_controlled_position_add_carrier` envuelve la salida para el coordinador
sin conceder capacidad de orden. La política por defecto es `enabled=false`,
`mode="shadow"`. El único modo que puede marcar `eligible=true` es pasar
explícitamente `policy={"enabled": True, "mode": "guarded"}` y satisfacer todos
los checks; incluso entonces la salida sigue siendo `authority="guard_only"`
y no concede autoridad de ejecución. `mode="shadow"` conserva la evaluación y
razones para observación.

## Controles fail-closed

La evaluación exige señal BUY nueva con `signal_id` y `signal_capture_id`
distintos de los IDs del fill BUY precedente, timestamps aware y señal posterior
al fill. El fill exige `broker_order_id`, IDs exactos, estado confirmado,
`filled_at`, cantidad positiva y estado explícito de autoridad/verificación.
También exige posición existente con `unrealized_pl > 0`, thesis válida,
gates válidos y al menos una sesión XNYS completa (`status=completed`) con fecha
estrictamente posterior a la sesión del fill y cierre posterior al fill. El
cierre de cada sesión se contrasta con `MarketCalendar("XNYS").session_schedule`
del proyecto y debe ser <= `decision_at`/captura nueva; no se acepta una fecha
futura, festivo o fin de semana declarado por el caller.

Se bloquean segunda alta del mismo símbolo/sesión, plan pendiente duplicado,
BUY pendiente y EXIT activo. Órdenes SELL solo se toleran cuando coinciden con
legs protectoras confirmadas del bracket existente. La exposición agregada del
símbolo incluye posición, alta y planes pendientes y queda limitada por defecto
a 5% de equity; la alta queda limitada a 2,5%, exige cash disponible (nunca
`buying_power`) después de reservar notionales BUY pendientes y riesgo total
posterior conocido y <=3% de equity. El riesgo de la alta exige un valor finito
y no negativo y queda limitado a 1% por trade. Un plan BUY pendiente sin
notional o riesgo verificable bloquea; no se ignora. Estados/símbolos/side desconocidos
en órdenes abiertas, booleanos numéricos y conflictos entre lineage raíz y
anidada bloquean.

La protección existente debe aportar símbolo, cantidad protegida igual a la
posición, `lot_filled_qty` igual al fill, parent igual al `broker_order_id` del
BUY precedente, OCO exacto y al menos legs stop loss/take profit confirmadas.
Cada leg debe ser SELL, tener símbolo/cantidad/parent/OCO/estado válidos y un
`broker_order_id` único. El broker debe probar explícitamente ruta
`canonical_bracket`, soporte parent/legs, estado `supported=true` y verificación
`verified/confirmed/demonstrated`. `OrderSnapshot` legado no aporta parent ni
legs; por tanto resulta en `controlled_add_protection_unavailable`. No se
fabrica soporte ni aprobación. La revisión posterior añade validación contra
el calendario XNYS real y bloquea cualquier SELL cuyo ID no esté en legs
protectores exactos; el rol textual por sí solo no exime. Cada alta ya
`filled`, `partially_filled` o `completed` ocupa el slot de símbolo/sesión;
solo una cancelación o rechazo sin cantidad ejecutada libera el slot. Cada leg debe ser
SELL, del mismo símbolo, con cantidad igual a la posición, parent igual al BUY
precedente, OCO coincidente, estado confirmado e ID único. Conflictos de
lineage raíz/anidada, booleanos numéricos y estados/símbolos/side desconocidos
en órdenes abiertas también fallan cerrados.

## Carrier mínimo para integración

El coordinador debe construir el contexto desde carriers canónicos existentes,
sin unir por símbolo/fecha ni por “última compra”:

```python
{
    "symbol": "AAPL",
    "position": {"symbol": "AAPL", "qty": 100, "market_value": 4000,
                  "unrealized_pl": 250},
    "prior_fill": {
        "side": "buy", "status": "filled", "broker_order_id": "...",
        "signal_id": "...", "signal_capture_id": "...", "filled_qty": 100,
        "filled_at": "2026-10-05T15:00:00+00:00",
        "session_date": "2026-10-05", "lineage_status": "verified",
    },
    "new_signal": {
        "side": "buy", "signal_id": "...", "signal_capture_id": "...",
        "captured_at": "2026-10-08T14:00:00+00:00",
        "session_date": "2026-10-08",
    },
    "session_carrier": {
        "calendar": "XNYS", "current_session_date": "2026-10-08",
        "completed_sessions": [{"session_date": "2026-10-06",
                                "status": "completed",
                                "close_utc": "2026-10-06T20:00:00+00:00"}],
    },
    "existing_protection": {
        "status": "confirmed", "protected_qty": 100, "lot_filled_qty": 100,
        "parent_order_id": "...", "oco_group_id": "...",
        "legs": [{"id": "...", "role": "stop_loss",
                  "status": "confirmed", "parent_order_id": "...",
                  "oco_group_id": "..."}, ...],
    },
    "broker": {"provider": "alpaca", "canonical_bracket": {
        "supported": True, "verified": True, "supports_parent_legs": True,
        "route": "canonical_bracket",
    }},
    "add_qty": 10, "add_price": 100, "equity": 100000,
    "cash_available": 20000, "total_risk_pct": 0.01,
    "add_risk_pct": 0.005,
}
```

El cambio canónico mínimo pendiente para integración es ampliar el carrier
provider-neutral de orden/protección con `parent_order_id`, `oco_group_id`,
`legs[]`, rol de leg, estado de cada leg y cantidad protegida. No se modifica
`OrderSnapshot`, broker, execution, risk ni configuración en este lote.

## Identidad y validación

Base exacta: HEAD `63cb6f9883f22c0d11dba20dd59c315ceae5dc0e`, tree
`a7167bca1b9387c40eb37d32d3497505dd573bf7`. Review-fix commit:
`60b98d5b1736ee2608124bd8060f188fbb8ae2f2`, tree
`90ae341a844b2d98bcecc7419bd614cf74c5bada`.

Worktree aislado: `C:/Users/utopi/.codex/worktrees/bolsa-adds-oct12/agenteBolsa`.
No se leyeron datos productivos ni se ejecutaron broker, red, LLM, servicios,
SQLite productiva, smoke, suite completa, merge, push, deploy o activación.

Validación focal prevista/ejecutada con
`C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe`, `PYTHONPATH` al `src`
del worktree, `DATA_DIR` temporal y `PYTHON_DOTENV_DISABLED=1`:

- `tests/test_controlled_position_adds.py`: 25 casos; protective vs active
  exit, lineage ausente/conflictivo, repetición incluida alta ya filled, señal
  nueva/fill viejo, sesión frontera, fecha futura/festivo falso, pérdida,
  exposición agregada, plan duplicado y notional pendiente desconocido, cash
  explícito cero frente a buying power, riesgo de alta ausente, límites de
  política, qty/IDs/SELL de legs, estado abierto desconocido, broker no
  soportado, booleano numérico y shadow por defecto.
- Ruff focal de los dos ficheros Python: `All checks passed!`.
- `git diff --check`: limpio.

Los tests se ejecutaron sin plugin `anyio`, que en este entorno deja el proceso
abierto después de publicar el resultado; no afecta al contenido de la prueba
focal síncrona. Suite completa y gates de producción quedan fuera del encargo.

## Límites y siguiente paso

El guardia no autoriza, crea, cancela, reemplaza ni envía órdenes. La política
debe permanecer en `shadow` durante al menos cinco sesiones; cualquier paso a
guarded/active requiere revisión coordinada, paper y evidencia. La escalera
propuesta por dirección queda fuera de este módulo: paper 15%, luego 20/25%,
cap de alta 2,5%; solo una política con carrier explícito
`validated_higher_guard=true` y evidencia `validation_evidence.status` en
`validated`, `verified` o `confirmed` puede pedir límites mayores. Sin esa
evidencia se rechaza cualquier política que supere 5% compañía, 2,5% alta,
1% riesgo de alta o 3% open risk. Pullback permanece en shadow.
