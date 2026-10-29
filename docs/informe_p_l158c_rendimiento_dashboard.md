# P-L158C — rendimiento real del Dashboard (candidato 0.4.254)

Dictamen: `ready_for_review`. Miercoles 28-oct-2026, XNYS abierto
(`11:30-04:00`, cierre `21:00+01:00`). Trabajo aislado en worktree, sin tocar
produccion, sin ordenes, sin escrituras en `data/` productivo. Broker solo GET
paper para el payload de paridad.

## Contexto operativo encontrado

- Stack productivo **parado** (`scripts/stack_status.ps1`: scheduler, web y
  supervisores `PARADO`), lock `stale_dead_owner` con `pid=62356`,
  `created_at=2026-09-17T10:19:17Z`, `pid_alive=false`.
- SQLite productiva sin escribir desde `17/09/2026 23:09:32`
  (1.807.347.712 bytes). La sesion de hoy no tiene sistema en marcha.
- Todo el estudio se hizo sobre una copia en
  `%LOCALAPPDATA%\Temp\opencode\perf-study\data` y una instancia Streamlit
  aislada en `127.0.0.1:8502`, con el mismo HEAD (`b411e9a7`, tree `2458213`).
  El `mtime` de la SQLite productiva no cambio.

## Causa raiz (medida, no inferida)

1. **Sin indice por fecha en `agent_events`.** Solo existia
   `idx_agent_events_agent_created(agent, created_at)`. Cada `latest_events()`
   hacia `SCAN agent_events` + `USE TEMP B-TREE FOR ORDER BY` sobre 229.883
   eventos: 1,154 s con `LIMIT 400` y 0,520 s con `LIMIT 20`. El Dashboard lo
   llama 3 veces por render (400 + 80 + 20), Configuracion 1 vez (500) y Mejora
   continua 1 vez (400).
2. **Sin indice por ciclo.** Decisiones ejecuta 25 consultas
   `WHERE cycle_id = ? ORDER BY created_at`: 1,869 s de 2,084 s de pared.
3. **Mapeo de sesion XNYS cuadratico.** `_portfolio_value_series_from_alpaca`
   calculaba un schedule y luego `_portfolio_session_date_for_timestamp`
   recorria **todas** sus filas con `DataFrame.iterrows()` por cada bucket: 189
   buckets x ~210 filas = 39.690 `iterrows`, 1,95–2,10 s para 146 filas de
   grafico.
4. **Calendario reconstruido.** `_xnys_schedule` y
   `MarketCalendar.session_schedule` llamaban a `pandas_market_calendars` en
   cada uso: 0,157 s por llamada y 15 llamadas por render
   (`opening_performance_context` 1,24 s).
5. **Lectura pesada para contar.** `_daily_learning` pedia
   `learning_observations(limit=5000)`, que deserializa 5 columnas JSON por fila,
   solo para comparar `created_at[:10]`: 0,667 s.

## Cambio

- `storage.py` (SCHEMA): `idx_agent_events_created(created_at)`,
  `idx_agent_events_cycle_created(cycle_id, created_at)`,
  `idx_research_evidence_updated(updated_at)`. Idempotentes (`IF NOT EXISTS`) y
  aplicados por `ensure_schema`; no hay backfill ni reescritura historica.
- `storage.py`: `learning_observation_created_dates(limit)` proyecta solo
  `created_at` con el **mismo** `ORDER BY signal_date DESC, symbol ASC LIMIT ?`
  que `learning_observations`, de modo que el conjunto contado es identico.
- `web_app.py`: `_session_close_index()` construye `(market_close, session_date)`
  ordenado una vez y `_session_date_from_close_index()` resuelve cada bucket con
  busqueda binaria. `_portfolio_value_series_from_alpaca` calcula el indice una
  sola vez por render. `NaN`/`NaT` se descartan (el recorrido anterior podia
  quedarse con un cierre `NaT` si era la primera fila).
- `market_calendar.py` y `tools/performance_benchmark.py`: cache por rango
  (`lru_cache`, 128 entradas) con copia defensiva en cada entrega; ningun
  consumidor puede envenenar la cache.
- `tools/improvement_dashboard.py`: `_observations_today()` usa la proyeccion
  cuando el store la ofrece y cae al lector completo con dobles de test.

## Evidencia antes / despues

Instancia instrumentada, medianas por render (misma copia de datos):

| superficie | antes | despues | delta |
|---|---:|---:|---:|
| `page_dashboard` | 11,608 s | 2,533 s | −7,8× |
| `page_cycle_decisions` | 2,070 s | 0,143 s | −14,5× |
| `page_continuous_improvement` | 1,833 s | 0,689 s | −2,7× |
| `page_config` | 1,280 s | 0,076 s | −16,8× |
| `_render_autonomy_panel` | 1,604 s | 0,811 s | −2,0× |
| `opening_performance_context` | 1,242 s | 0,112 s | −11,1× |
| `_portfolio_value_series_from_alpaca` | 1,949 s | <0,01 s | >100× |
| `store.latest_events` (p50) | 0,725 s | <0,01 s | >70× |

Navegador real (Chromium, click/recarga hasta fin de render): Dashboard
11,10–12,28 s antes; 2,90–3,07 s despues (mediana 2,95 s). Recarga en frio tras
arrancar el proceso: 6,3 s (incluye arranque de Streamlit). CPU del proceso:
27,55 s en 3 renders antes (9,2 s/render); el render actualiza en ~1 s de CPU
mas la espera de broker.

SQL medido sobre copia desechable (`CREATE INDEX` 0,168 s / 0,222 s / 0,084 s):

| consulta | sin indice | con indice |
|---|---:|---:|
| `latest_events(400)` | 1,154 s | 0,0018 s |
| `latest_events(20)` | 0,520 s | 0,0001 s |
| `events WHERE cycle_id = ?` | 0,077 s | 0,012 s |
| `GROUP BY cycle_id` (bounds) | 0,235 s | 0,035 s |
| `research_evidence ORDER BY updated_at` | 0,180 s | 0,0001 s |

## Paridad

Payload de broker congelado (189 buckets diarios, 252 intradia, equity
71.015,14) evaluado con el arbol base y con el candidato:

- `series_rows`: identico.
- `session_dates_by_timestamp` (400 timestamps): identico.
- `opening_context_benchmark_current` y `opening_context_daily_rows`: identicos.
- `opening_context_account_current`: identico salvo `system_end_at`, que es el
  reloj de lectura del consumidor (`15:38:54Z` vs `15:39:12Z`), no un dato.

No se toca decision, sizing, gates, ordenes, riesgo ni politica activa.

## QA

- `tests/test_pl158c_dashboard_performance.py` (13 focales): indices presentes e
  idempotentes, planes de consulta sin `TEMP B-TREE`, paridad del indice de
  sesiones contra la implementacion de referencia (ordenado, desordenado, empates
  y cierres ilegibles), cache de calendario con copia defensiva, sesiones XNYS
  reales (festivo 3-jul-2026), proyeccion de observaciones igual al lector
  completo, un solo `session_schedule` por render.
- Regresiones focales relacionadas: 190 passed
  (`test_web_app`, `test_p63`, `test_p65a`, `test_p83d`, `test_p88*`,
  `test_p123`, `test_p40b`, `test_version_policy`).
- Suite completa y gates en la seccion de validacion del lote.

## Limites y siguiente paso

- El panel de autonomia sigue siendo el mayor coste restante (0,811 s): carga
  2000 lecciones, 780 experimentos, 2823 propuestas y 3087 validaciones para
  contar filas de hoy. Bajarlo exige replicar el mismo `ORDER BY`/`LIMIT` de
  cada lector (las lecciones ya vienen truncadas a 2000), lo que es un lote
  propio: **P-L158D**.
- Los expanders del Dashboard ejecutan su contenido aunque esten plegados
  (aprendizaje, agentes, rendimiento, labs): ~0,35 s evitables con render
  perezoso, tambien en P-L158D.
- El broker sigue siendo red pura (~0,3–2,8 s por historia de cartera). No se
  añade cache de broker: cambiaria la frescura que consume el operador.
- Despliegue: prohibido con XNYS abierto. Requiere ventana cerrada,
  `stack_down.ps1 -IncludeScheduled`, merge `--no-ff`, gates y doble salud. El
  primer `ensure_schema` tras el despliegue crea los tres indices (≈0,5 s en
  1,72 GB) dentro del arranque normal.

## Despliegue (29-oct-2026)

- Integrado en la rama productiva `codex/astra` con merge `--no-ff`
  `2f3374bf`; padres `bf91ccc4` (produccion) y `c37aa697` (candidato).
  Version productiva `0.4.254`. Arbol productivo limpio salvo artefactos no
  versionados del operador (`.worktrees/`, tarballs, `.codex-*`), preservados.
- Kernel sellado (`status=ok`, `sealed_at=2026-09-17T10:28:48Z`): el lote no
  toca ficheros protegidos.
- Gates sobre el arbol productivo: Ruff, `check_no_nulls`, `git diff --check`,
  136 focales/regresiones, `validate-agent-config ok`.
- Migracion medida sobre copia pristina de la base real: `ensure_schema`
  0,804 s la primera vez (crea los tres indices) y 0,001 s la segunda;
  `latest_events(400)` 0,0033 s.
- Artefacto ya mergeado medido contra copia de la base real: Dashboard
  3,7–4,0 s por recarga en navegador (antes 11,5–12,3 s), Configuracion
  0,77 s, Decisiones 1,5 s.
- Activacion: **bloqueada por permisos**. `AgenteBolsaWeb` y
  `AgenteBolsaScheduler` estan `Disabled`; la cuenta `WINDOWS-APPGG4T\Antonio`
  es usuario estandar (grupo Administradores solo-denegar) y el UAC fue
  cancelado. No se arrancan procesos persistentes a mano (regla del repo).
- Comandos de activacion, en shell elevado, cuando el operador lo decida:
  `Enable-ScheduledTask -TaskName AgenteBolsaWeb` y
  `Start-ScheduledTask -TaskName AgenteBolsaWeb` (solo dashboard, sin
  scheduler). Para el sistema completo, ademas `AgenteBolsaScheduler`.
- La tarea `AgenteBolsaDBMaintenance` sigue `Disabled` a proposito: un
  `-Mode apply` implicaria mantenimiento de la base y no esta autorizado.

## Despliegue real en el Jetson (29-oct-2026, 0.4.382-arm64)

El destino de produccion es el Jetson Orin (`antonio@192.168.1.186`), no
Windows. El 28-oct el Jetson corria `agente-bolsa:0.4.381-arm64` (tres
contenedores healthy, 17 h) con otro linaje de version; por eso **no** se
desplego la rama completa (habria sido un downgrade a 0.4.254): se porto solo
el parche a la imagen viva.

Estado medido antes del parche, sobre la base real:

- `agent_events` con **1.036.491 filas**; `latest_events(400)` = **70,58 s**
  con plan `SCAN agent_events` + `USE TEMP B-TREE FOR ORDER BY`.
- Dashboard sin terminar de renderizar en **240 s** (timeout del navegador).

Port aplicado: diff de `storage.py`, `web_app.py`, `market_calendar.py`,
`tools/performance_benchmark.py` y `tools/improvement_dashboard.py` sobre el
codigo extraido de la imagen (`docker create` + `docker cp`), `patch -p1`
(hunk del import resuelto a mano), `compileall`, bump a `0.4.382` y build
incremental `FROM agente-bolsa:0.4.381-arm64`
(digest `sha256:9f924cbbe4ff8f93882ed8daa05f18c428fa8bab0e758c31ca0dbeca15d95681`).

Resultado medido despues, sobre la misma base:

- Los tres indices se crearon en **10 s** al arrancar el scheduler.
- `latest_events(400)` **0,0015–0,0025 s**; `latest_events(20)` 0,0001 s;
  la consulta por `cycle_id` pasa a `SEARCH ... USING INDEX`.
- Dashboard servidor (`dashboard_timing` de la linea 0.4.381): **6,06 s en
  caliente**, 37,8 s en frio de proceso; `opening_context` 5,37 s es ahora el
  coste dominante y `portfolio_value_series_from_alpaca` 0,062 s.
- Contenedores `agente-bolsa-*-1` en `0.4.382-arm64`, `healthy`,
  `RestartCount=0`, `OOMKilled=false`; HTTP `:8081/` y `/_stcore/health` 200;
  kernel `ok` (sellado 2026-10-11, cero violaciones); vecinos
  (`whale-copy`, `terrenos`, `mi-proyecto`) intactos.
- Memoria del contenedor web: 655 MB de 1 GiB.

Incidencia durante el despliegue: el primer `up` se ejecuto sin
`-f docker-compose.raspberry.override.yml`, de modo que los contenedores se
recrearon sin `AGENTE_BOLSA_KERNEL_ENV_PATH/SHA256` y `kernel-status` paso a
`violation` (`.env`, `env_path`). Se corrigio recreando con los dos ficheros
(`docker-compose.yml` + `docker-compose.raspberry.override.yml`) y
`--env-file /etc/agente-bolsa/runtime.env`; el kernel volvio a `ok`. Regla:
replicar siempre la invocacion original de Compose (label
`com.docker.compose.project.config_files`), no solo el fichero base.

Pendiente en Jetson: `opening_performance_context` (5,37 s) es el siguiente
cuello; y el techo de 1 GiB del contenedor web conviene vigilarlo.

## P-L158D en Jetson: consultas por prefijo, pickles e indices de ciclo (0.4.383–0.4.385)

Segunda iteracion sobre la linea 0.4.381, ya con el parche de P-L158C dentro.
Perfilado de `opening_performance_context` (6,6 s): 4,08 s en
`load_cached_spy_open_observations`, de los cuales 2,37 s eran un `fetchall` de
`agent_events WHERE event_type LIKE 'session_open_snapshot%'` sobre 1.036.491
filas, y 1,04 s leer 59 `pickle` de cache de mercado.

Cambios desplegados:

- `0.4.383-arm64` (digest `3ccbc5eabaf9`): indice
  `agent_events(event_type, created_at)` y prefijo por rango de bytes
  (`event_type >= ? AND event_type < ?`) en `agent_events` e
  `iter_agent_events`; cache de `pickle` por `path+mtime+size` con copia
  defensiva. Prefijo: 2,25 s -> 0,0013 s. Dashboard servidor 6,06 -> 2,49 s;
  `opening_performance_context` 5,37 -> 1,80 s.
- `0.4.384-arm64` (digest `bc46d3221d60`): indices
  `continuous_improvement_cycles(created_at)` y
  `trade_recommendations(cycle_id, created_at)`, mas limitador de
  `cleanup_runtime_data` (900 s) porque recorria 40.215 ficheros por pagina.
- `0.4.385-arm64`: corrige un `NameError: name 'time' is not defined` que
  introdujo el limitador (faltaba `import time` en `retention.py`) y dejo dos
  paginas caidas hasta el redespliegue.

Resultado medido en el contenedor web (misma base real):

- Dashboard en caliente 2,47–2,66 s; en frio de proceso 30,8 s (cache de
  pickles y calendario aun vacios).
- `page_cycle_decisions` 5,82 -> 0,62 s (25 ciclos con consultas por `cycle_id`).
- `page_continuous_improvement` 12,37 -> 2,46 s.
- `_store()` 1,83 s la primera vez y 0,005 s despues (limpieza limitada).

Incidencias del lote, para no repetirlas:

- Cerrar la tuberia de salida de un `ssh` que ejecuta acciones (`Select-Object
  -First`) mata el proceso remoto a mitad (SIGPIPE): dejo contenedores
  `Created`. Las ordenes que mutan estado se redirigen a fichero y se leen
  despues.
- Un `python3 -c` de verificacion ejecutado en el host (sin `pydantic`) aborto
  el script antes del `docker build`; el `up` posterior intento descargar una
  imagen inexistente y dejo los tres servicios parados. Verificar siempre
  dentro de la imagen (`docker run --entrypoint python3`).

## P-L158E en Jetson: render en frio (0.4.386–0.4.389)

El primer render tras reiniciar el proceso web costaba 30,8 s (y hasta 75 s en
una medicion con carga). Perfilado: `opening_performance_context` gastaba 67 s
en la primera llamada porque `xnys_sessions_between` se invoca con cientos de
rangos distintos (uno por candidato) y **cada rango reconstruia el calendario**:
65 construcciones de ~0,35 s. El precalentado inicial no lo cubria.

Cambios:

- `0.4.386` / `0.4.387`: modulo `tools/dashboard_warmup.py` con
  `ensure_warmup()`; calienta pickles de apertura, calendarios, `latest_events`,
  snapshots de apertura, ultimo ciclo de mejora y validaciones. Guarda por
  proceso en el modulo importado (no en `web_app`, que se re-ejecuta en cada
  rerun).
- `0.4.388`: el precalentado pasa a sincrono en la primera sesion. Un hilo de
  fondo no ayudaba al primer usuario: solo calentaba despues de que ese render
  ya hubiera pagado el coste.
- `0.4.389`: calendario XNYS cacheado **por ano** (`_xnys_schedule_year`,
  16 anos) y `xnys_sessions_between` filtra ese calendario. Paridad verificada
  contra la imagen anterior en 305 rangos (2024–2026, festivos y rangos
  invertidos): 0 diferencias.

Resultado medido:

- Primer render servidor tras reiniciar: **7,62 s** (antes 30,8–75 s). En
  navegador, primera carga tras reinicio 19,5 s incluyendo arranque de
  Streamlit (12,5 s hasta aceptar conexiones) y precalentado.
- Regimen: 4,0 s servidor y 5,4–5,8 s por recarga en navegador con carga
  compartida del Jetson (load average 3–4).
- Precalentado: 6,3 s una sola vez (pickles 4,6 s, calendario por anos 0,8 s,
  validaciones 0,4 s), registrado como `dashboard_warmup {...}` en el log.

Leccion: el precalentado solo sirve si cubre el coste real; medir la primera
llamada en un proceso nuevo (`docker exec` fresco) antes de elegir que calentar.

## P-L158E5: sin copia defensiva y helpers de sesion cacheados (0.4.390)

Perfil en caliente con 0.4.389: `opening_performance_context` 1,87–3,63 s, de
los cuales 0,62 s eran el `.copy()` de cada una de las 59 tramas cacheadas y
~0,6 s los helpers `_session_open_at` (64.013 llamadas) y `_candidate_settled`
(42.660 llamadas) recalculando la misma fecha y el mismo `fromisoformat`.

Cambios en `tools/opening_performance.py`: la cache de pickles devuelve la trama
compartida (consumidores de solo lectura, comprobado en el modulo);
`_session_open_at`, `_session_settled_at` y un nuevo `_parse_created_at` pasan a
`lru_cache` (4096/8192). Paridad verificada contra 0.4.389 en 876 casos
(sesiones aleatorias, con y sin autoridad explicita, con y sin marca de
tiempo): 0 diferencias.

Medido en el Jetson:

- Dashboard en caliente: 2,54 s (0.4.389: ~4,0 s).
- Primer render tras reiniciar el proceso web: 13,6 s (0.4.389: 19,5 s;
  0.4.385: 30,8–75 s), incluyendo 12,4 s de arranque de Streamlit.
- Navegador: 3,78–4,66 s por recarga.
- Estado: `0.4.390-arm64` (digest `2ce39598726d`), tres contenedores `healthy`,
  `restarts=0`, sin OOM, HTTP 200, kernel `ok`.





