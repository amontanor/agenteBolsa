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
