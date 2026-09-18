# P-L141 — port Jetson 0.4.305 (DESPLEGADO 18-sep-2026)

Dictamen: `precondition_not_met` para el corte. XNYS cerrado; sin
merge productivo pendiente (P-L139/P-L142 ya en `codex/astra`
`39362317`), sin push, sin mutaciones en Jetson salvo la construccion
de imagen (solo lectura + `docker build`, sin tocar servicios/datos).

## Causa del lote

La sesion del 17-sep murio en produccion Jetson 0.4.304: 22/22 ciclos
`missed` (grace 1 s vs despertares 1.4-2.7 s), 1 ciclo `failed`
(`agent_run_terminal_conflict:failed->blocked` desde `crew_observer`),
LLM caido (400 `MissingSessionID` + fallback sin conexion). La linea
Windows tenia los fixes; Jetson no.

## Metodo (splice, patron P-L125)

Imagenes Jetson = `FROM` anterior + `COPY` de ficheros. Sin rama local
0.4.304: fuente extraida de la propia imagen (solo lectura,
`docker create` + `cp`, contenedor efimero eliminado).

## Contenido del splice (`FROM agente-bolsa:0.4.304-arm64`)

Verificado byte a byte contra la linea Windows donde aplica:

- `llm_router.py`, `continuous_improvement/llm_client.py`: identicos
  al tip Windows (P-L142) tras aplicar el delta — Jetson ya estaba al
  dia salvo las cabeceras. Cubierto por 68+82 tests Windows.
- `scheduler.py`: `SCHEDULER_INTRADAY_MISFIRE_GRACE_SECONDS` 1 → 120
  (se conserva `MAX_WORKERS=2`; no tocar concurrencia y timing a la
  vez) + `_skip_delay_seconds` y campo `delay_seconds` (lectores en
  oleada 2).
- `crew_observer.py` (solo Jetson): helper `_settle_tracker` fail-open
  en `finalize`/`on_task_failed`/`on_task_complete`; el guard de
  `agent_run` queda intacto. Repro del fallo real con tracker genuino:
  el conflicto se conserva como `failed` + evento `*_superseded`,
  sin excepcion.
- `tools/cash_flow_ledger.py`, `tools/llm_uplift.py`: nuevos,
  verbatim del tip Windows (durmientes hasta la oleada 2).
- `__init__.py`: 0.4.305 + comentario P-L141.
- Ya presentes en Jetson (0 diff, sin tocar): fixes P-L130/P-L95,
  `storage.py`/`scoreboard`/`operational_health`/`signal_learning`/
  `web_app.py` quedan pristinos para la oleada 2 diurna (divergencia
  real: scoreboard +28, signal_learning +2000 lineas Jetson).

## Imagen `agente-bolsa:0.4.305-arm64`

- ID `54a713d4fac0`, labels version 0.4.305 revision
  `port-p141-0.4.305`, base `0.4.304-arm64`. Verificada: version,
  grace 120, `_settle_tracker` x5, cabeceras.
- Dockerfile y bundle en `/tmp/ab305` del Jetson (auditable).

## Corte EJECUTADO 18-sep (~07:50Z) — dictamen `deployed`

- Precondiciones: XNYS cerrado; postmarket `failed` terminal conocido
  (causa infra en estudio, sin reintento manual); escritores detenidos
  via `systemctl stop`; snapshot frio `cold-pre-0.4.305-20260918T0745Z`
  (`quick_check`/`integrity_check` ok, sha256 `7de4e39c...`).
- Preflight `jetson-ops diagnose` fallaba por hash stale de
  `application.env` (operador subio modelos a v4.1-flash el 17-sep):
  hash actualizado a `4e60333c...` con backup `jetson-ops.bak-p141`
  (precedente documentado). PAPER/live/auto-apply verificados.
- Selector `AGENTE_BOLSA_IMAGE` 0.4.297 → `0.4.305-arm64` (backup
  `runtime.env.bak-p141`); `deploy-agente-bolsa` recreo (gate 120 s
  justo en primer arranque; verde a los +3 min).
- Doble salud: HTTP / y /health 200/200; scheduler+web healthy,
  RestartCount 0, OOM false; lock owner_alive/token_match; kernel
  `ok=true violations=[]` (el sello resuelve con el env actual);
  version runtime 0.4.305; 0 ordenes, 0 `database is locked`, 0
  Traceback/KeyError/terminal_conflict/MissingSessionID desde boot.
- Residual conocido (no bloqueante): auxiliary `unhealthy` por latch
  `ci_digest failed` de las 06:30Z (pre-corte; las cabeceras 0.4.305
  deben sanar la causa 400 en la proxima pasada).

1. Postmarket sesion 17-sep terminal `failed` (04:01Z) con
   `OperationalError('database or disk is full')`, causa infra sin
   resolver (ver punto 3). Reintentos (`postmarket_run`) siguen sin
   terminal nuevo.
2. Oleada 2 pendiente (observabilidad/UI divergente): el corte
   llevaria salud parcial (sin `delay_seconds`/linkage en health).
3. **Presion de memoria**: Jetson 7.3G sin swap, ~109M libres;
   whale-copy (fuera del proyecto) muerto por OOM 4+ veces esta noche
   (03:58/06:12/07:00/07:27) y en loop de reinicios. Disco OK (309G
   libres): el "disk full" de SQLite es fallo de asignacion bajo
   presion de memoria (inferencia etiquetada; sin presion de disco,
   con OOM coincidentes). Cortar ahora (snapshot+recreate+health)
   bajo 109M libres arriesga otro fallo a mitad de migracion.
4. `whale-copy` es del operador: no tocar sin su decision (pausa,
   limite de memoria o reprogramar fuera de postmarket).

## Siguiente paso (requiere operador + capacidad recuperada)

1. Operador: aliviar presion de memoria (whale-copy) y decidir
   reintento de postmarket por la ruta normal (nunca manual fuera de
   lote).
2. Con postmarket terminal `completed` (o `failed` comprendido),
   leases vacios y memoria sana: preflight con
   `--require-core-restart-zero` → snapshot frio con receipt →
   `jetson-ops deploy-agente-bolsa` 0.4.305 → kernel/PAPER/HTTP/
   lock/listener → doble salud ≥75 s → verificar en logs: cero
   `missed` de ciclo, cero `MissingSessionID`, cero
   `terminal_conflict`.
3. Oleada 2 diurna: scoreboard/signal_learning/web_app/storage con
   tests adaptados. Sin push salvo peticion.

## Anexo: poda de imagenes 18-sep (autorizada por el operador)

- Conservadas: 0.4.303 (rollback), 0.4.304 (actual), 0.4.305 (candidata).
- Incidente propio: el primer filtro borro tambien la 0.4.305 recien
  construida; reconstruida en 1.2 s desde `/tmp/ab305` (nuevo ID
  `0e59b76b...`, labels verificados). Sin impacto: la imagen es
  reproducible desde el bundle versionado.
- Resultado: imagenes 53G → 30G; disco 125G → 109G usados (325G
  libres, 26%). Quedan 25G reclamables en build cache (no tocado:
  fuera del alcance autorizado).
- Snapshots 17G: el operador pidio explicacion antes de decidir;
  propuesta standing: conservar 3 recientes + pre-corte, borrar 6 de
  agosto (~11G).
