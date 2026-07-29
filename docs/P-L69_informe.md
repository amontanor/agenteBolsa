# P-L69-W — avisos intradía de fills confirmados

## Dictamen P-L69-R1

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
- Implementación: `6bffedf2`; QA focal: `9a689153`; correcciones QA de
  ordinales de retry (`fc9f7206`) y timeout efectivo del adaptador
  (`8e8da2c1`).
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
- Ruff completo (`src tests`), NUL, compilación Python, `git diff --check` y
  `validate-agent-config --json` aislado: verdes. Version policy: verde.

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

## P-L69-R1 — finalización downstream tras fill intradía

### Causa reproducida y corrección

Contra `ca6912758b0887dbb7f1a039c34756d33dfa2c36`, la prueba de reproducción
mostró la pérdida exacta: una BUY `PENDING_NEW` pasó por el watcher a
`filled`, generó su recibo Telegram y la reconciliación equivalente devolvió
`pending=0` y `changes=[]`. Quedaron en cero las actualizaciones de signal y
learning y no se volvió a adjuntar execution quality. SELL filled y BUY
rejected/cancelled quedaron fuera como terminales sin efectos BUY.

La corrección `584575c1` conserva junto al snapshot exacto la marca
`reconciliation_finalization` con hash, `pending=true` y `applied=false`.
Postmarket incluye esos terminales, usa el snapshot local sin transición remota
adicional y reclama `pending -> processing -> applied` dentro de
`BEGIN IMMEDIATE`. Signal, learning, execution quality y la marca aplicada se
confirman juntos; retries y carreras no duplican efectos. El orden operativo
sigue siendo snapshot remoto -> commit local -> Telegram fail-open, sin
adelantar aprendizaje u outcomes.

### QA R1

- `31560cfb`: reproducción negativa contra el candidato previo.
- `584575c1`: fix de marcador y finalización postmarket.
- `0c121836`, `86b653ce`, `0909ea4b`: BUY, SELL, rejected/cancelled, reinicio,
  attach exacto, carrera concurrente, ausencia de consulta remota terminal y
  fallback público del SDK instalado.
- Focales relacionadas: `133 passed`; focal R1 ampliado: `18 passed`.
- Ruff, `check_no_nulls.py`, `py_compile`, `git diff --check` y
  `validate-agent-config --json` con DATA_DIR temporal: verdes.
- XNYS abierto: suite completa, smoke, proveedor/red/Telegram real, SQLite
  productiva y despliegue permanecen omitidos por seguridad.

El dictamen de este lote permanece `ready_for_closed_market_full_validation`;
la validación cerrada debe comprobar el terminal postmarket y la paridad antes
de cualquier reintegración o despliegue.

## P-L69-R2 — normalización del endpoint Alpaca y rollback de finalización

### Hallazgo y causa

Contra `ce6f86af0db87b043a5251eb355135f9ab2264ff`, el `TradingClient` real
instalado (`alpaca-py 0.43.4`) expone `_base_url` como el enum
`BaseURL.TRADING_PAPER`. Su representación textual era
`BaseURL.TRADING_PAPER/v2/orders/...`, aunque `.value` contenía el endpoint
HTTPS correcto. Los dobles previos con string no cubrían esta frontera.

### Corrección

`de8b250e` normaliza `.value` de enums o strings, exige esquema `http/https` y
conserva el endpoint paper/live de la instancia sin hardcodearlo. Mantiene
headers del SDK, timeout, `allow_redirects=False` y fallback exacto por
`client_order_id`. Un endpoint inválido lanza un error auditable que el watcher
trata fail-open: no cambia la orden, no marca fill y no envía Telegram.

La prueba R1 añadida en `f6c82f85` verifica que una excepción antes del commit
revierte `processing` a `pending`; un retry recupera la finalización. Esto
preserva la transacción única del marcador.

### Evidencia y QA

- `dac98d0b`: reproducción contra la base, dos fallos con URL
  `BaseURL.TRADING_PAPER/v2/...`.
- `de8b250e`: fix del adaptador proveedor-neutral.
- `f6c82f85`, `b819c540`: endpoint inválido fail-open, rollback, GET exacto,
  fallback `client_order_id`, timeout/headers y endpoint live.
- Batería final focal: `138 passed`, una advertencia externa deprecación de
  `websockets`; Ruff, NUL, py_compile, diff-check y validate-config temporal:
  verdes.
- XNYS abierto: sin broker/red/Telegram real, SQLite productiva, suite
  completa, smoke, despliegue o push.

Dictamen R2: `ready_for_closed_market_full_validation`.

## P-L76-PRECLOSE — ensayo previo a validación cerrada (29-jul-2026)

### Dictamen

`ready_for_closed_market_full_validation`.

XNYS estaba abierto (`17:42 CEST`, cierre previsto `22:00 CEST`). Se preparó
el ensayo aislado y se ejecutó únicamente QA focal; suite canónica, smoke y
promoción productiva quedan para una ventana cerrada. No hubo broker, red,
yfinance, LLM, Telegram real, servicios ni SQLite productiva.

### Procedencia y merge

| Referencia | HEAD | tree | versión | estado |
|---|---|---|---|---|
| Producción/base | `36077a0681d3a2bdd487e395052766d8daa5985a` | `b15ac3a28e12dd98fce0f6afe959d7b6c14a88bb` | 0.4.206 | tracked limpio; untracked preservados |
| P-L75 | `08e8f8fab5430008c3c27a7f0412650bd6b728e4` | `86a8b4d77f57692c3fdafd101b41cc7578a8a48a` | 0.4.208 | ancestro de P-L69-R2 |
| P-L69-R2 | `4c3ed11d462a62580fced6e67bc7b0586e46e972` | `f2b5a7728b04e73916c95fec02c5ea1bb0c0bc18` | 0.4.209 | candidato limpio |
| P-L76 merge | `faccc5de42064211276b449d3cc78ebb6c022212` | `f2b5a7728b04e73916c95fec02c5ea1bb0c0bc18` | 0.4.209 | worktree aislado |

Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl76_p69_predeployment_rehearsal`.
Rama: `codex/pl76-p69-predeployment-rehearsal`.
El merge fue un único `--no-ff`, sin conflictos, squash, rebase,
cherry-pick ni amend. El tree resultante coincide con P-L69-R2. Producción,
P-L75 y P-L69-R2 permanecen intactos.

### Revisión adversarial

La frontera durable verificada es:

`snapshot remoto por broker_order_id → commit local de broker_order terminal → Telegram fail-open → recibo append-only`.

El watcher conoce únicamente `CanonicalOrderSnapshot` y
`OrderStatusProvider`; los tipos/payloads específicos de Alpaca quedan en
`tools/fill_provider.py`. R2 admite endpoint SDK enum mediante `.value` o URL
string, valida `http/https`, conserva paper/live, timeout, headers,
`allow_redirects=False` y fallback exacto por `client_order_id`. No hay joins
por símbolo/fecha.

`pending_new`, `accepted`, `new`, `submitted` y `partially_filled` no notifican.
Solo una transición exacta a `filled` genera el aviso final; rejected,
cancelled y expired no generan aviso. Un fill intradía persiste
`reconciliation_finalization` pendiente junto al snapshot. La reconciliación
postmarket vuelve a incluir ese terminal, reclama `pending → processing →
applied` en transacción corta y reutiliza el snapshot local exacto para
signal, learning y execution quality una sola vez. El recibo Telegram no
sustituye la finalización downstream.

El job `trade_fill_watch` está desactivado por defecto, separado de
`market_cycle`/`portfolio_watch`, con `max_instances=1`, `coalesce=True`, cap
25, cadencia 30 s, timeout 5 s y backoff 30→300 s. No retrasa órdenes ni
cambia señales, gates, capacity, sizing, RiskManager, planes, requests,
cantidades, precios, stops/takes, exposición o límites.

`config.py` difiere de producción únicamente por los settings neutrales y
autorizados de P-L69-W y coincide exactamente con el candidato R2. No hay
diferencias en `kernel.py`, `tools/broker.py`, `tools/execution.py`,
`tools/risk.py` ni `.env`. El código desplegado y el watcher activo son
estados distintos: activar el watcher requerirá una configuración explícita
(`TRADE_FILL_WATCH_ENABLED=true` y límites/cadencia/timeout/backoff revisados);
este lote no la activa ni lee secretos de `.env`.

### QA ejecutada con XNYS abierto

- Focal integrada P-L69/R1/R2, Telegram, reconciliación, scheduler, storage,
  P-L72/P-L73/P-L74/P-L75, configuración y version policy: `145 passed`,
  1 warning externo de `websockets.legacy`.
- QA específica de P-L76: `2 passed`.
- Ruff completo: OK.
- `scripts/check_no_nulls.py`: OK, 460 archivos.
- `py_compile` de storage, reconciliación y adaptador: OK.
- `git diff --check`: OK.
- `validate-agent-config --json` con `DATA_DIR` temporal: `ok=true`, sin
  errores ni warnings.
- No se ejecutaron suite completa, smoke, jobs, reconciliación, postmarket,
  proveedor/red/Telegram real ni SQLite productiva por XNYS abierto.

### Matriz exacta para la ventana cerrada

No se ejecuta ahora. Antes de una validación larga debe demostrarse, por rutas
read-only, XNYS cerrado con margen, postmarket terminal, lease vacío, ausencia
de `market_cycle`, `portfolio_watch`, reconciliación, postmarket, pytest y
despliegue efectivos, producción tracked limpia con sus untracked intactos,
paper activo, live y auto-apply desactivados, kernel/config válidos y
referencias exactas.

Secuencia documentada, no ejecutada en P-L76:

1. Preflight read-only con HEAD/tree/version/limpieza.
2. `scripts/stack_down.ps1 -IncludeScheduled` mediante la ruta gestionada.
3. Normalización autorizada del checkout solo si el candidato subsume
   exactamente los cambios tracked del operador; nunca reset, clean, stash o
   checkout destructivo y los untracked quedan fuera.
4. Verificación del merge exacto `faccc5de42064211276b449d3cc78ebb6c022212`.
5. Con `DATA_DIR` temporal y proveedores monkeypatched: `python -m pytest
   tests/ -x -q`, Ruff, `check_no_nulls.py`, `git diff --check`,
   `validate-agent-config --json`, version policy y `kernel-status --json`
   interpretado desde el entorno correcto.
6. Smoke solo si se demuestra que `run-once --skip-crew` usa Store/proveedores
   temporales y no puede tocar red, broker, LLM ni SQLite productiva; en caso
   contrario, `smoke_unavailable_by_safety`.
7. `scripts/stack_up.ps1` y primera comprobación de salud.
8. Segunda comprobación al menos 75 segundos después: HTTP raíz/health 200,
   un scheduler lógico, lock/token/heartbeat coherentes, listener único,
   lease vacío o terminal recuperado por ruta normal, cero alertas críticas,
   cero órdenes inesperadas y cero `database is locked`.

Criterios de aborto: precondición no demostrada, diff tracked no subsumido,
hash protegido distinto, fallo de test/gate, smoke no aislado, `live` o
`auto_apply` activo, duplicación de scheduler/listener, HTTP no 200, alerta
crítica, orden inesperada o lock de SQLite. El rollback autorizado es un
`git revert` auditable, nunca reset/clean; P-L76 no ejecuta rollback ni
despliegue.

### Commits P-L76

- Merge: `faccc5de` — `merge: rehearse P-L69-R2 over P-L75`.
- QA: `deca1285` — `test: verify P-L76 fill watcher boundaries`; aislamiento
  de settings: `aca9cc73`.
- Documentación: commit siguiente de este cierre.
