# P-L69-W — avisos intradía de fills confirmados

## Dictamen provisional

`ready_for_closed_market_full_validation`.

XNYS estaba abierto durante este lote. El candidato queda aislado y no está
autorizado para despliegue. La suite completa, smoke y cualquier comprobación
con proveedor real quedan pendientes de una ventana cerrada segura.

## Base y procedencia

- Base P-L75: `08e8f8fab5430008c3c27a7f0412650bd6b728e4`, árbol
  `86a8b4d77f57692c3fdafd101b41cc7578a8a48a`, versión 0.4.208.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl69_fill_watch_impl`.
- Rama: `codex/pl69-fill-watch-impl`.
- P-L69-T (`be48b57a`) no era ancestro de P-L75; su contrato se portó mediante
  la caracterización explícita `581f6bfc`, sin cherry-pick oculto.
- Implementación: `6bffedf2`; QA focal: `9a689153`.
- Versión candidata: 0.4.209.

## Frontera canónica

El dominio solo conoce `CanonicalOrderSnapshot` y `OrderStatusProvider`.
La única consulta acepta `broker_order_id` exacto y devuelve estado, cantidad,
precio medio, timestamps e IDs del proveedor/cliente. El adaptador específico
queda confinado en `tools/fill_provider.py`; `fill_watch`, scheduler, Store y
Telegram no importan tipos ni payloads SDK.

La secuencia durable es:

`snapshot remoto exacto -> UPDATE local broker_order/reconciliation payload ->
commit -> claim append-only -> Telegram fail-open -> receipt
telegram_trade_fill:<broker_order_id>`.

`submitted`, `accepted`, `new`, `pending_new` y `partially_filled` no publican.
Solo una transición local a `filled` publica el aviso final. Rejected,
cancelled, expired y demás estados terminales no publican. Un fill parcial se
acumula en el snapshot local y se avisa una vez cuando llega `filled`.

BUY usa cantidad, precio y hora reales. SELL reutiliza únicamente
`source_plan_id` y una compra filled exacta; si falta o es ambiguo, entrada y
P/L bruto permanecen `n/d`. No hay joins por símbolo, fecha ni “última compra”.

## Job y configuración

El job separado `trade_fill_watch` se registra solo cuando está habilitado,
con `max_instances=1`, `coalesce=True` y cadencia configurable. Consulta como
máximo `TRADE_FILL_WATCH_MAX_PENDING_PER_RUN` órdenes locales no terminales; no
bloquea `market_cycle` ni `portfolio_watch` y no retrasa el submit.

Defaults desactivados/prudentes:

| Setting | Default | Propósito |
|---|---:|---|
| `TRADE_FILL_WATCH_ENABLED` | `false` | Activación explícita |
| `TRADE_FILL_WATCH_CADENCE_SECONDS` | `30` | Intervalo del job |
| `TRADE_FILL_WATCH_MAX_PENDING_PER_RUN` | `25` | Cap de órdenes |
| `TRADE_FILL_WATCH_REQUEST_TIMEOUT_SECONDS` | `5` | Timeout del adaptador |
| `TRADE_FILL_WATCH_BACKOFF_SECONDS` | `30` | Backoff inicial |
| `TRADE_FILL_WATCH_MAX_BACKOFF_SECONDS` | `300` | Tope por orden |

Los fallos de proveedor mantienen estado latest con intento, razón y próximo
intento; no generan polling adicional ni tormenta. Los fallos conocidos de
Telegram crean un evento de claim fallido y permiten retry. Si el proceso cae
después de un envío aceptado y antes del recibo, el claim permanece ocupado:
no se fabrica exactly-once ni se reenvía automáticamente sin evidencia.

## Persistencia e idempotencia

No hay tabla, migración, backfill ni `INSERT OR REPLACE` nuevo. Los claims,
fallos y recibos usan `agent_events` append-only. Mismo ID y contenido es
idempotente; distinto contenido conserva el original y queda como conflicto.
La persistencia del fill ocurre antes de cualquier llamada Telegram. Las
consultas al proveedor están fuera de transacciones SQLite; las escrituras son
cortas. La carrera watcher/PMR tiene un único ganador del claim y una única
transición local.

`trade-fill-watch-status --json` es lectura de métricas latest sin consultar al
proveedor y publica `collecting` si todavía no existe una ejecución.

## QA ejecutada

- Caracterización portada: 8 pruebas.
- Implementación/QA: 11 pruebas adicionales.
- Telegram existente: 4 pruebas.
- Focales P-L73/P-L74/P-L72/web/Telegram/reconciliación/scheduler/storage:
  92 pruebas verdes.
- Ruff focal, compilación Python y `git diff --check`: verdes.

Los tests cubren pending/partial/filled/rejected/cancelled, proveedor fake no
Alpaca, timeout/malformed, cap y backoff, commit antes de Telegram, retry de
fallo conocido, claim concurrente, watcher/PMR concurrentes, idempotencia y
ausencia de secreto en payloads. No se ejecutaron broker, red, Telegram real,
SQLite productiva, jobs manuales, suite completa, smoke ni despliegue porque
XNYS estaba abierto.

## Paridad y límites

No se modificaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
`risk.py`, `.env`, selección, gates, sizing, RiskManager, planes, requests,
órdenes, stops/takes, exposición, límites ni política. `config.py` fue
modificado únicamente para los settings neutrales autorizados. La
reconciliación postmarket existente conserva su fallback y comparte el mismo
event ID de recibo.

Pendiente único: ensayo cerrado completo con DATA_DIR temporal, suite canónica,
Ruff/NUL/diff/config/kernel y smoke completamente aislado antes de cualquier
reintegración o despliegue.
