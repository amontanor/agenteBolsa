# Ensayo combinado P-L137-R + P-L133-R + P-L140A-R + P-L140B-R (rehearsal 0.4.320, 26-sep-2026)

Estado final: **`deployed`**. Este fichero se conserva como informe unico
del lote; el corte y la doble salud estan al final. El dictamen de
ensayo original fue `ready_for_closed_market_full_validation`; la
validacion cerrada por particiones y el preflight con el corte estan
documentados mas abajo.

Alcance del despliegue: port de 4 ficheros de `src` sobre la imagen
`0.4.316-arm64` ya productiva. Sin migracion de datos, sin cambio de
Compose, sin `kernel-seal`, sin tocar `.env` ni sus permisos, sin
`whale-copy`, sin push.

## Base, candidato y merge exactos

- Base: P-L158-B rehearsal/deploy source `85e28447ce65c26beb58702896d28b31ce1f1ad9`,
  tree `70d487e700d4f5eaa5b2d916af23671b9ab7ed84`, v0.4.316.
- Candidato extremo exacto: `0998087599eeb4472e2668142871d5a5ac9bc61b`,
  tree `00e5bdeadf1a7d6cd9340e76fbd9b136c3583412`, v0.4.320, rama
  `codex/pl140b-readd-0320`. Su cadena contiene P-L137 (`26f144fa`),
  P-L133 (`baba2dd9`), P-L140A docs-corrected (`49f3b19f`) y P-L140B.
- Worktree NUEVO exclusivo
  `C:\Antonio\Bref\agenteBolsa_worktrees\pl137_140_readd_rehearsal`,
  rama `codex/pl137-140-readd-rehearsal`, creado desde la base exacta.
- Merge `git merge --no-ff` del candidato exacto sobre la base, sin
  squash/rebase/cherry-pick/amend, sin conflictos (merge limpio por
  ser el candidato descendiente directo de la base):
  `338136fa2e681157787d864edae4ce2bd26c77a9`, parents
  `85e28447ce65c26beb58702896d28b31ce1f1ad9` (P1, base) +
  `0998087599eeb4472e2668142871d5a5ac9bc61b` (P2, candidato).
- Tree del merge `00e5bdeadf1a7d6cd9340e76fbd9b136c3583412`,
  identico al tree del candidato (`git diff HEAD <candidato>`
  vacio): equivalencia funcional exacta salvo la documentacion de
  rehearsal posterior (este informe + entradas de plan/relevo; este
  informe no autorreferencia su propio hash final).
- Alcance: integracion y QA focal/relacionada proporcional. Cero
  cambios en `src`/`tests`/version en este lote (el defecto
  reproducible no aparecio; no se amplio el alcance).
- Protegidos (`kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`): sin diff base→merge.

## Contenido integrado (verificado por fuente en el merge)

- P-L137 (N2): `trim_to_completed_sessions` +
  `last_completed_session` en `tools/signal_learning.py`; recorte
  antes del bucle de outcomes (`update_signal_outcomes` publica
  `bars_trimmed_universe`/`last_completed_session`/
  `session_seal_degraded`).
- P-L133 (N2): `scheduler_skip_summary` +
  `signal_outcome_emptiness` en `tools/operational_health.py`;
  wiring health fail-open (`except Exception` → `unavailable`), sin
  alertas nuevas; `pct_empty=None` con denominador 0, excepciones
  `unavailable`.
- P-L140A (N1): `_invested_day_metric` + `_investments_group` en
  `web_app.py` (4 tarjetas Mis inversiones, misma fuente/
  denominador que exposure/cartera/cash ya cargados, solo lectura).
- P-L140B (N1): `_spy_alpha_summary` puro (filas `final` +
  `comparable`, composicion geometrica, `None` sin filas, nunca
  cero); leaderboard movido a Config via `session_state`
  (`leaderboard_total_pct`); baseline duplicado deja de
  renderizarse (`_render_performance_baseline` definido pero sin
  llamadas en `page_dashboard`); helpers baseline conservados por
  contrato P-L140C.
- Timers P-L158 (`dashboard_timing`/`total_seconds`) intactos en
  `web_app.py`. Denominadores missing/`unavailable` intactos (sin
  ceros inventados). Paridad de trading, riesgo y ejecucion:
  ningun lote toca la ruta activa (cambios observacionales/UI
  read-only + version/pins).

## QA minima (Python del proyecto, `PYTHONPATH=<worktree>/src`)

- Bateria combinada minima del encargo (12 ficheros, una sola
  ejecucion, baterias solapadas declaradas, no sumadas como
  pruebas unicas):
  `tests/test_p137_session_seals.py` +
  `tests/test_p133_misfire_health.py` +
  `tests/test_p140a_mis_inversiones.py` +
  `tests/test_p140b_spy_unico.py` +
  `tests/test_p65a_daily_vs_spy_contract.py` +
  `tests/test_p65a_r1_actual_ui_characterization.py` +
  `tests/test_p158a_dashboard_timing.py` +
  `tests/test_p158b_dashboard_perf.py` +
  `tests/test_operational_health.py` + `tests/test_web_app.py` +
  `tests/test_p59c_llm_selected_authority.py` +
  `tests/test_version_policy.py`: **186 passed en 24.66 s**,
  cero skips/xfails nuevos.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (536 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Gates omitidos: suite completa, smoke, benchmark, kernel-status,
  validacion cerrada completa, despliegue, doble salud. Sin
  broker/red/LLM/yfinance, sin SQLite productiva, sin
  servicios/locks/leases, sin reinicio, sin push.

## Validacion cerrada por particiones (26-sep-2026 19:55-20:27, XNYS cerrado)

Dictamen: `ready_for_closed_market_deployment` sujeto a preflight
renovado y autorizacion explicita del operador. Sin despliegue ejecutado.

### Por que no se repitio la suite completa

La suite unica `pytest tests/ -q --continue-on-collection-errors` se
detuvo a las 18:57 tras 2 h 40 min sin superar 51%, con >1,1 M handles y
~964 MiB privados: supero el presupuesto 2x de AGENTS. Causa raiz
aclarada, no nueva: `tests/test_p45b2_learning_observation_batch_characterization.py::test_current_sequential_baseline_records_one_connection_and_commit_per_row[33336]`
es una caracterizacion deliberadamente lenta. Medida aislada: **181,62 s**
para ese nodo; `storage.py` **sin diff** frente a la base 0.4.316. En la
base 0.4.316 ese fichero tardaba 23:57 min de suite completa; aqui el
coste esta contenido en dos ficheros. Evidencia: log
`Temp\opencode\pl137140_slow_focus.log`.

### Particiones ejecutadas (cada una una sola vez, sin solapes)

| Particion | Ficheros | Resultado | Duracion |
| --- | ---: | --- | ---: |
| A (deuda conocida) | 18 | 41 failed, 153 passed | 13,72 s |
| B (lotes re-add) | 10 | 164 passed | 18,60 s |
| C (resto del arbol) | 248 | 2310 passed, 1 skipped | 573,52 s |
| P-L45B2 (lento aislado) | 2 | 33 passed | 232,05 s |

Denominador total: **2660 passed, 41 failed, 1 skipped, 0 collection
errors**. Los 4 errores de coleccion de 0.4.316 (p133, p137, p140a,
p140b) **desaparecen**: los simbolos re-add ya importan.

### Comparacion con la base 0.4.316 (46 failed / 2586 passed / 1 skip / 4 errors)

- Los 41 fallos son **subconjunto exacto** de los 46 del baseline, uno a
  uno por node id. Cero regresiones nuevas.
- Los 5 del baseline que ya no fallan:
  - `test_p59c_llm_selected_authority.py::test_version_policy_requires_bump`
    (ancla actualizada a 0.4.320 dentro del lote),
  - `test_p65a_daily_vs_spy_contract.py::test_spy_comparison_has_single_surface_without_baseline_renderer`
    (superficie unica P-L140B; el baseline duplicado deja de renderizarse),
  - `test_p78b_deepseek_default.py` x2 y `test_web_research.py` x1:
    **no reproducibles en este entorno**. El triage los atribuyo a
    contaminacion de `os.environ` heredado (`OPENCODE_*` /
    `TAVILY_API_KEY`) en el proceso que genero el baseline. Hecho, no
    mejora de producto: no se claima fix.
- El skip es el preexistente `test_score_study_regression_current_sqlite`
  (historia SQLite local insuficiente).

### Gates

Verde en este cierre: `git diff --check` limpio; sin `pytest` activo
tras cerrar; particiones A/B/C y P-L45B2 con codigo de salida 1 solo en
A (por la deuda preexistente) y 0 en B, C y P-L45B2.

Heredados por identidad exacta del tree funcional `00e5bdea` (sin cambio
semantico posterior): Ruff `All checks passed`, `check_no_nulls.py` OK
(536 archivos), `validate-agent-config --json` `ok=true`, smoke aislado
`run-once --skip-crew` exit 0 con 52 eventos y 0 ordenes/planes,
kernel temporal `unsealed` esperado. Gates NO repetidos aqui: suite
completa en un unico proceso, benchmark 33.336 (medido y contenido en la
particion P-L45B2), `kernel-status` productivo, preflight productivo,
corte y doble salud.

### Estado Git al cierre

HEAD `ffa4dbe7b95c9bf32c25c09b1caf2e2af7b32953`, tree
`1df99159a5f79e8891cc8ad7c06fba465a801fae`, v0.4.320, arbol limpio. Este
commit documental no cambia `src`, `tests` ni version. Principal
`c0b6578e6af9a6c41f49e6c1b92b51c55d203de8` / tree `c4ee7c8f` / v0.4.253
limpio. Produccion Jetson 0.4.316 intacta: `/` y `/health` 200 (1522 B)
leidos el 26-sep 20:18. Sin broker/red/LLM operativo, sin SQLite
productiva, sin locks/leases tocados, sin push.

## Corte y doble salud (26-sep-2026 20:32-20:35 Europe/Madrid) — `deployed`

Autorizacion: "Si, despliega 0.4.320 ahora" del operador, 26-sep 20:31.

### Preflight read-only (20:30, SSH, SQLite `mode=ro` + `query_only=ON`)

- XNYS cerrado, `next_open` 2026-09-28 15:30 Europe/Madrid.
- `agente-bolsa:0.4.316-arm64`: scheduler/web/auxiliary healthy,
  `RestartCount=0`, `OOMKilled=false`; `whale-copy-jetson` healthy,
  fuera del stack de trading.
- HTTP `/` y `/health` 200 (1522 B). Kernel `ok`, sellado
  2026-08-22T12:57:26Z, 0 violaciones, 4/4 hashes coinciden (incluye
  `.env`, sin revelar).
- Lock `p-l47b1.scheduler-lock.v1` pid 7 / token 2377158.
- Flags: `TRADING_MODE=paper`, `ALPACA_PAPER=true`,
  `AUTO_PAPER_TRADING=true`, `ALLOW_LIVE_TRADING=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- 0 leases activos. PMR 25-sep `completed`/`pipeline_completed`
  (`pmr_a2c364c6dbc5`); PMR 26-sep `skipped`/`market_not_ready`
  (terminal, esperado en sabado con mercado cerrado). `MAX_EVENT`
  18:27:39Z. 1 orden en 24 h = compra AAPL del 25-sep ya auditada
  (`deterministic_fallback`).
- `application.env` `root:root:600`, SHA-256 `4e60333c…5827f`, igual al
  esperado por el wrapper `jetson-ops`.

### Port y build

- Paquete `port/src/agente_bolsa/{__init__.py, web_app.py, tools/operational_health.py, tools/signal_learning.py}`.
- SHA-256 de los 4 ficheros, iguales local y remoto:
  `c65cc2e8…5cdb9` (`__init__.py`),
  `b86e3329…500daf` (`web_app.py`),
  `ef3a67e9…5cdb9` (`tools/operational_health.py`),
  `b4c51bf0…69f0` (`tools/signal_learning.py`).
- Objetos Git de los 4 ficheros en `338136fa` y en `d39ed702`
  identicos: el commit documental no altera el tree funcional
  `00e5bdea`.
- Release `/opt/agente-bolsa/releases/0.4.320-port/` (Dockerfile +
  `port/`), siguiendo el patron de `0.4.316-port`.
- Imagen `agente-bolsa:0.4.320-arm64`,
  `sha256:35f1cca4871d54247d92ae5c41c6976c00da9a5c024b449218e3f5ea895f9683`.
  LABELs: `agente_bolsa_version=0.4.320`,
  `agente_bolsa_revision=d39ed702ea511fc33893bfd26564d103cea44da8`,
  `io.agente-bolsa.source-tree=00e5bdeadf1a7d6cd9340e76fbd9b136c3583412`,
  `io.agente-bolsa.port-base=agente-bolsa:0.4.316-arm64`.
  Runtime verificado en imagen: `0.4.320`.

### Secuencia de corte

1. `ACTIVE 0` y `MAX_EVENT 18:31:34Z` inmediatamente antes de parar.
2. `docker stop` de scheduler, auxiliary y web. Cero contenedores
   `agente-bolsa` en ejecucion.
3. Selector: copia `runtime.env.bak-pl-0320` (`root:root:600`) y
   `AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.320-arm64`.
4. `jetson-ops deploy-agente-bolsa`: valida env y flags, valida
   compose, `up -d --force-recreate`, espera salud; resulto
   `agenteBolsa desplegado y saludable`. `init-db` `Exited(0)`.
   No se uso `docker compose down` global ni se toco `whale-copy`.

### Doble comprobacion de salud

| Comprobacion | Hora UTC | Separacion | Resultado |
| --- | --- | ---: | --- |
| Salud 1 | 2026-09-26T18:33:28Z | — | healthy x3, restart 0, OOM false |
| Salud 2 | 2026-09-26T18:35:22Z | 114 s | healthy x3, restart 0, OOM false |

En ambas: runtime `0.4.320`; HTTP `/`, `/health`, `/_stcore/health` y
`/kindle` 200; kernel `ok` con 0 violaciones; flags paper activo,
live y auto-apply falsos; lock pid 7 / token `4298981` escrito
18:32:50Z; listener unico `0.0.0.0:8081`; 0 leases activos; 0 ordenes y
0 planes desde el despliegue; `MAX_EVENT` avanza 18:33:04Z -> 18:34:52Z
(heartbeat vivo); sin `critical`, `traceback`, `database is locked` ni
`error` en los logs del scheduler desde el arranque.

### Observacion fuera de alcance

`whale-copy-jetson` reinicio otra vez durante la ventana
(`RestartCount=14`, `OOMKilled=false`, arrancado 18:34:54Z). No pertenece
al stack de trading, no se toco y no es gate de este despliegue. Queda
como deuda operativa del contenedor del operador.

### Limites del despliegue

- No hubo migracion de datos: la SQLite de `/var/lib/agente-bolsa` se
  conservo. No hubo `VACUUM`, checkpoint ni backfill.
- No se ejecuto `kernel-seal`; el manifiesto vigente (22-ago) sigue
  coherente y los 4 hashes protegidos coinciden.
- Rollback disponible: `AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.316-arm64`
  en `/etc/agente-bolsa/runtime.env` (backup
  `runtime.env.bak-pl-0320`) y re-`up -d --force-recreate`; imagen
  0.4.316-arm64 conservada.
- Bootstrap posterior al cierre: `post_market_coordination:session:2026-09-26`
  `skipped`/`market_not_ready`, terminal. No se ejecuto postmarket,
  reconciliacion ni outcomes a mano.
- Sin push. La rama candidata queda en `codex/pl137-140-readd-rehearsal`;
  el corte fue por port, no por merge al principal.
