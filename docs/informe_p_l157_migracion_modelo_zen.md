# P-L157 — migración exacta del ID de modelo OpenCode Zen

## Dictamen de dirección (24-sep-2026, ~23:50 Madrid)

`precondition_not_met`. No hay corte ni push. El usuario autorizó el cambio
de modelo y el despliegue; esa autorización queda registrada y no se pide de
nuevo. El corte no se fuerza porque la inferencia real del modelo nuevo falla
(403 `error code: 1010` en Zen con la clave productiva) y la suite completa
sigue roja también en la base. Detalle y comandos exactos en
`## Revision de direccion 24-sep noche` al final de este informe.

## Dictamen inicial de Luna (desactualizado)

`partially_verified_open_market`. El candidato normaliza el ID exacto
`deepseek-v4-flash-free` a `deepseek-v4.1-flash` en las llamadas efectivas de
agentes, roles, orquestador, codegen y probes. Los tests focales pasan. Falta
revisión de dirección para el cambio protegido en `config.py`, validación N3 con
XNYS cerrado y prueba de identidad exacta entre la reconstrucción Git y la
imagen Jetson. No hay autorización ni evidencia de integración o despliegue.

## Base, producción y mercado

- Base candidata: HEAD `784e6cd7d3170681d6f03c5d39f95442d3fc865a`, tree
  `58fc1824e387b6e72c432119a6c1b60d2b8fb05d`, versión `0.4.310`; worktree
  inicialmente limpio. Rama candidata: `codex/p-l157-deepseek-v41-id-migration`.
- La dirección informó producción Jetson con tres contenedores, imagen
  `0.4.310-arm64`, etiquetas `agente_bolsa_revision=port-p153b-0.4.310` y
  `agente_bolsa_version=0.4.310`, y source hash declarado
  `82708495d8b9c7942d461daed38efee54b0aeaf7`.
- El source hash declarado por imagen difiere del commit reconstruido. El
  identificador puede pertenecer a otro formato; no se afirma equivalencia.
  Tampoco se integró P-L155 ni su rango de 79 commits, ni P-L154 C5/C9/C10/C11.
- Contexto recibido de dirección: `LLM_MODEL_SELECTOR=opencode-zen`,
  `OPENCODE_MODEL=deepseek-v4-flash-free`; roles sentiment/decision,
  `IMPROVEMENT_LLM_MODEL` y modelo de orquestador ya tenían el ID nuevo. No se
  leyeron ni modificaron credenciales o `.env`.
- `schedule-status` de solo lectura, con código de este worktree y `DATA_DIR`
  temporal, dio `is_open=true` el `2026-09-24T19:43:10Z` (`21:43:10`
  Europe/Madrid), cierre `22:00`. La misma consulta aislada indicó
  `missing_lock` y `runtime_state.available=false/database_missing`, esperado
  para el directorio temporal. El encargo informó scheduler local
  `stale_dead_owner` y `runtime_state` unavailable; no se inspeccionó ni reparó
  ese estado local.
- Segunda comprobación aislada: XNYS cerrado a `2026-09-24T20:03:25Z`
  (`22:03:25` Europe/Madrid); siguiente apertura `2026-09-25T15:30:00+02:00`.
  Los commits se crearon después de este cierre confirmado.

## Causa y cambio

En `.310`, `Settings` y las rutas de envío aceptaban y propagaban sin
normalización el ID retirado. Los defaults, catálogo Zen y probes también lo
mostraban. La evidencia de un nombre en configuración o en informes no bastaba;
la caracterización nueva inspecciona el `model` del payload entregado al cliente
simulado en la frontera de envío.

P-L157 añade un único mapa exacto en
`src/agente_bolsa/llm_model_ids.py`. Solo el ID retirado se reemplaza; los demás
strings se devuelven sin cambios. El mapa se aplica a defaults y entradas de
Settings, endpoints de roles, requests de ImprovementLLMClient, override de
codegen, sondas de salud, probes Zen y catálogo UI. Se preservan proveedor
`opencode-zen`, endpoint `https://opencode.ai/zen/v1`, fallback OpenCode Go
`deepseek-v4-flash`, fallback local y cualquier modelo distinto.

No se tocaron kernel, broker, execution, risk, `.env`, SQLite operativa ni
servicios. No se hicieron llamadas LLM, de red o broker. La versión candidata
sube a `0.4.311`.

## Revisión explícita de `config.py` protegido

Este archivo está protegido por `AGENTS.md`. El cambio queda propuesto para
revisión humana de dirección antes de integración. Cambios exactos:

- En imports: agregar `field_validator` de Pydantic y los imports
  `DEEPSEEK_V4_1_FLASH_MODEL_ID`/`normalize_model_id` desde
  `agente_bolsa.llm_model_ids`.
- En `Settings`: agregar un `field_validator(mode="before")` sobre
  `opencode_model`, `openai_model`, `mimo_model`, `llm_local_fallback_model`,
  `secondary_review_llm_model`, los cuatro modelos de rol fast/sentiment/
  decision/deep, `improvement_llm_model` y
  `improvement_llm_orchestrator_model`. El validador ejecuta únicamente el mapa
  exacto descrito arriba.
- Referencias precisas en el diff: imports `config.py:10,14`; validador
  `config.py:22-38`.
- `OPENCODE_MODEL` (`opencode_model`): cambiar default del ID retirado al ID
  canónico, `config.py:46`.
- `OPENAI_MODEL_NAME` (`openai_model`): cambiar default del ID retirado al ID
  canónico, `config.py:56-58`; el selector/provider no cambia.
- `IMPROVEMENT_LLM_MODEL` (`improvement_llm_model`): cambiar default al ID
  canónico, `config.py:816-820`.
- `IMPROVEMENT_LLM_ORCHESTRATOR_MODEL`
  (`improvement_llm_orchestrator_model`): cambiar default al ID canónico,
  `config.py:832-834`.

No cambian endpoints, credenciales, fallbacks, roles activos, límites ni política
de trading. Dirección debe aprobar o rechazar este diff de `config.py` antes de
cualquier integración.

## Caracterización y validación

Python del proyecto: `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`;
`PYTHONPATH` apuntó al `src` de este worktree. Todas las pruebas usaron datos
temporales y transportes/clientes simulados.

```text
& 'C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe' -m pytest `
  tests\test_p78b_deepseek_default.py `
  tests\test_llm_router.py::test_zen_primary_adds_exact_go_fallback_before_local_fallback `
  tests\test_llm_router.py::test_retired_zen_model_is_sent_canonically_by_role_call `
  tests\test_continuous_improvement.py::test_improvement_zen_chain_inserts_one_shot_go_before_local `
  tests\test_continuous_improvement.py::test_improvement_agent_request_migrates_retired_model_id `
  tests\test_check_opencode_zen_failover.py::test_zen_success_is_one_request_and_reports_safe_identity `
  tests\test_check_opencode_zen_failover.py::test_retired_model_is_migrated_in_health_probe_request `
  tests\test_llm_health_check_script.py::test_health_specs_migrate_retired_id_for_roles_and_codegen `
  tests\test_llm_health_check_script.py::test_health_probe_migrates_model_before_sending `
  tests\test_web_app.py::test_zen_model_catalog_uses_current_model_id -q
```

Resultado: `21 passed in 2.65s`. Se observaron directamente payloads de salida
para la ruta `decision`, rutas de agentes y orquestador del laboratorio, y ambos
health probes. Ruff focal sobre todos los archivos fuente/tests tocados:
`All checks passed!`. `git diff --check`: pasa. `scripts/check_no_nulls.py`
terminó con código `1` porque `docs/plan_mejoras_y_tareas.md` contiene un byte
`0x97` que no es UTF-8. Se reprodujo en el mismo archivo de la base `.310` en el
offset `285406`; el offset actual `286530` refleja solo el texto insertado.
El escaneo raw de bytes NUL cubrió los 18 archivos cambiados y no encontró
ninguno. No se normalizó el histórico.

## Identidad Git y artefactos

- Versión base `0.4.310`; candidata `0.4.311`.
- Base commit/tree: `784e6cd7d3170681d6f03c5d39f95442d3fc865a` /
  `58fc1824e387b6e72c432119a6c1b60d2b8fb05d`.
- Rama: `codex/p-l157-deepseek-v41-id-migration`.
- Commit de caracterización: `6c68b33f194ceaa84e3154866ef9fa4425f35ba5`.
- Commit de implementación/version: `bea56fb7992103ff267edbf1a6ac693fcc047233`,
  tree funcional `9995ff90a6116c5a84b15d98e78ac77135fc073d`.
- El commit documental contiene este informe, el plan maestro y el relevo; su
  hash final queda en el dictamen de entrega.
- La caracterización cubre entradas de compatibilidad, rutas efectivas,
  payloads salientes y catálogo UI. La implementación contiene mapa, wiring,
  defaults y bump. No hay mezcla con lotes P-L154/P-L155.
- Ambos commits terminaron con código `0` y HEAD fue verificado. Git también
  informó `fatal: bad object refs/codex/turn-diffs/captures/1786628847747/4ee266fa-eceb-479d-a4a7-b513226192d9/base`
  y `failed to perform geometric repack`; no se ejecutó mantenimiento ni se
  modificaron refs de captura.

## Referencias restantes al ID retirado

- Código activo: solo el valor de compatibilidad en
  `src/agente_bolsa/llm_model_ids.py`; ningún default, selector, endpoint,
  request producer o probe activo conserva el ID anterior.
- Tests: valores de entrada de compatibilidad en
  `tests/test_check_opencode_zen_failover.py`,
  `tests/test_continuous_improvement.py`,
  `tests/test_llm_health_check_script.py` y `tests/test_llm_router.py`;
  `tests/test_p78b_deepseek_default.py` usa la constante de compatibilidad.
- Historial documental preservado: contrato P-L85 en
  `docs/plan_mejoras_y_tareas.md` y `docs/informe_p_l85_zen_primary_failover.md`;
  error HTTP histórico en `docs/informe_p_l141_port_jetson.md`. El resumen
  actual del plan y este informe identifican el ID antiguo como alias retirado.
  No se reescribe historia.

## Riesgos y siguiente gate

- Cambio protegido en `config.py` espera revisión explícita de dirección.
- Focales prueban el modelo pedido en un transporte simulado; no demuestran que
  Zen acepte la llamada remota ni se ejecutó LLM real.
- Hay divergencia entre source hash declarado por la imagen y commit/tree
  reconstruidos; antes de integrar/desplegar se requiere una fuente de imagen
  verificable o una resolución documentada de la identidad.
- XNYS estaba abierto durante la edición y pruebas. No se ejecutaron suite
  completa, smoke, red, LLM, merge, integración productiva ni despliegue.
- La comprobación NUL integrada permanece `precondition_not_met` por el byte
  UTF-8 histórico del plan; no implica un NUL nuevo en los archivos cambiados.
- `stale_dead_owner` y `runtime_state` unavailable permanecen sin reparar.
  Para integración/despliegue: XNYS cerrado, postmarket terminal,
  sin jobs/reintentos/leases activos, identidad exacta de candidato revisada,
  PAPER=true, live=false, auto-apply=false, kernel/config válidos, validación N3
  completa aislada, worktree limpio y preflight operativo positivo.

## Revision de direccion 24-sep noche (XNYS cerrado)

Hora: 23:00-23:55 Madrid (`2026-09-24T21:00-21:55Z`). XNYS cerrado verificado
por `schedule-status` local y en contenedor; proxima apertura
`2026-09-25T15:30:00+02:00`. Autorizacion del usuario para cambio de modelo y
despliegue: concedida; no se solicita de nuevo.

### Produccion Jetson (solo lectura, sin secretos)

- Contenedores `agente-bolsa:0.4.310-arm64` healthy: scheduler, web, auxiliary.
  `whale-copy` es otro proyecto, no tocado. Lock scheduler `owner_alive`
  PID 7/token 2195. Flags: `ALPACA_PAPER=true`, `ALLOW_LIVE_TRADING=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`. Kernel productivo `ok`
  (sello 2026-08-22, 0 violaciones).
- Env del scheduler (solo nombres): `LLM_MODEL_SELECTOR=opencode-zen`,
  `OPENCODE_MODEL=deepseek-v4-flash-free` (ID retirado),
  roles/improvement/orquestador ya en `deepseek-v4.1-flash`.
- Postmarket sesion `2026-09-24` run `pmr_64be403886f2`: terminal `completed`
  `2026-09-24T20:23:07Z` (`pipeline_completed`) + `lease_released` de
  `post_market_coordination:active`. Reconciliacion `brkrec_69a74718c6e5`:
  `completed` 21:12:37Z + `lease_released` 21:12:42Z. Coordinaciones
  posteriores: `skipped`/`session_already_completed`. Evidencia via
  `log --raw --all-events` (10 MB, solo lectura).
- `operational-health` en contenedor devolvio `database is locked`
  (escritores activos en ese momento); no se reparo nada.

### Procedencia de la imagen .310: EQUIVALENCIA DEMOSTRADA a nivel de ficheros

- La etiqueta `io.agente-bolsa.source-tree=82708495...` no es un objeto Git
  local (formato distinto); no se asume nada por ella.
- sha256 (bytes exactos) de ficheros efectivos en imagen vs blobs del commit
  base `784e6cd7`: `__init__.py` `78c60e55...`, `config.py` `8b3e9572...`,
  `kernel.py` `89f62f75...`: IDENTICOS. `broker.py`/`execution.py` coinciden
  ademas con el manifiesto del kernel. Revision `port-p153b-0.4.310`,
  version runtime `0.4.310`.

### Revision del protegido `config.py`: ALCANCE APROBADO

- Diff exacto `config.py:10,14` (imports), `:22-38` (validador
  `normalize_retired_model_ids`), `:46`, `:56-58`, `:816-820`, `:832-834`
  (defaults al ID canonico). Solo migracion exacta del ID; endpoints,
  proveedores, fallbacks, limites y trading intactos. `.env.example`: seis
  ejemplos al ID nuevo. `grep` en candidato: ninguna ruta activa conserva el
  ID retirado salvo la constante de compatibilidad en `llm_model_ids.py`.

### Inferencia real minima en Zen (una llamada, sin trading, clave sin revelar)

- `deepseek-v4.1-flash` en `https://opencode.ai/zen/v1` con clave productiva:
  HTTP 403, cuerpo `error code: 1010`. Modelo NO provisionado para la clave.
- Referencia productiva misma noche: ID retirado -> 400 `Model is unavailable`;
  fallback Go `deepseek-v4-flash` -> 403 `Model access is disabled`; local
  `qwen3.6-27b` -> connection error. BLOQUEADOR: desplegar no restaura LLM.

### Validacion N3 en candidato (venv proyecto, `PYTHONPATH=<worktree>/src`)

- Focales lote (6 ficheros): `202 passed in 20.76s`.
- `ruff check src tests`: `All checks passed!`.
- `scripts/check_no_nulls.py`: `OK (534 archivos)` tras correccion minima del
  byte historico `0x97` (em-dash cp1252 en `plan_mejoras_y_tareas.md:286530`)
  a em-dash UTF-8; ningun NUL; resto de `0x97` son `x` (`C3 97`) validos.
- `git diff --check`: pasa. `validate-agent-config --json` aislado: `ok=true`.
  `kernel-status --json` aislado: `unsealed` esperado (sin manifiesto en
  `DATA_DIR` temporal); hashes reales coinciden con manifiesto productivo.
- Smoke `run-once --skip-crew` con `DATA_DIR` temporal: ciclo `completed`,
  cero ordenes, sin crew.
- Suite completa `--ignore` de 4 ficheros con error de coleccion preexistente
  (reproducido en base `784e6cd7` en worktree temporal `p157_base_check`,
  despues retirado): candidato `2578 passed, 46 failed, 1 skipped`;
  base `2567 passed, 48 failed, 1 skipped`. Cero fallos nuevos; +11 pases
  (reescritura `test_p78b`). Fallos restantes = deriva preexistente
  base-vs-tests (version_policy anclada a `.253`, copy Telegram, p131/132,
  p134/135, p71/72/81, p65a, p139, p80b, learning/scoreboard, web_research);
  `test_p78b` solo en verde (11/11) y cae en suite por polucion de entorno de
  otro modulo (misma familia en base). Paridad trading/riesgo/ejecucion: el
  lote no toca esas rutas; la comparativa base lo confirma.

### Dictamen final y siguiente paso

`precondition_not_met` (anoche): (1) falso 403/1010 por artefacto de sonda
(ver R1: el modelo SI responde); (2) suite completa roja tambien en base
(requiere lotes de reparacion separados, sin mezclar); (3) procedimiento
canonico Jetson (build nativo + snapshot frio + `jetson-ops`) no ejecutado.
Sin corte, sin push, sin cambios en principal (sucio preexistente intacto).
Siguiente (ver R1 abajo): build `.312`, leases/lock frescos y N3 final.

## P-L157-R1 25-sep: el ID es correcto; el fallback Go estaba mal (ARREGLADO)

### Los modelos existen de verdad

- Documentacion oficial Zen (`opencode.ai/docs/zen`, lista de precios y
  `models.dev`): `deepseek-v4-flash-free` (free, tiempo limitado, 200K
  contexto), `deepseek-v4-flash` (pago $0.14/$0.28), `deepseek-v4.1-flash`
  (pago, release sep-2026). Los tres IDs son reales; ninguno estaba inventado.
- `GET /models` en Zen con cliente OpenAI real: 42 modelos; IDs deepseek:
  `['deepseek-v4-pro', 'deepseek-v4.1-flash']`. El free ya no se lista
  (retirado) y `deepseek-v4-flash` tampoco aparece en Zen.
- Conclusion: migrar a `deepseek-v4.1-flash` era lo correcto. El 403
  `error code: 1010` de anoche fue un artefacto de mi sonda (urllib con
  User-Agent generico, bloqueado por Cloudflare), NO del modelo. Queda
  corregido aqui; el dictamen `precondition_not_met` por ese motivo CAE.

### Verificacion viva con cliente real (clave productiva, sin revelarla)

- Zen + `deepseek-v4.1-flash` -> OK (`finish=length` con max_tokens=8).
- Zen + `deepseek-v4-flash` -> 403 `Model access is disabled`.
- Zen + `deepseek-v4-flash-free` -> 400 `Model is unavailable`.
- Go (con cabecera `x-opencode-session` + UA propio, como P-L147) +
  `deepseek-v4.1-flash` -> OK. Go + `deepseek-v4-flash` -> 403 disabled.

### Fallo real encontrado y corregido (R1)

- El fallback Go tenia hardcodeado el ID muerto `deepseek-v4-flash` en
  `llm_router.py:GO_MODEL`, `llm_client.py:271` y los scripts
  `check_opencode_zen_failover.py` / `check_opencode_go_deepseek.py`.
  Con el primario caido, el fallback tambien fallaba (403).
- Fix R1 (version `0.4.312`): los cuatro puntos usan el ID vivo
  `deepseek-v4.1-flash`. Cadena efectiva comprobada en candidato:
  `opencode-zen|deepseek-v4.1-flash` -> `opencode-go|deepseek-v4.1-flash` ->
  `openai-local|qwen3.6-27b`. Ambos niveles Zen/Go verificados en vivo.
- Catalogos UI (`web_app.py:126-136`, `:8599-8611`) listan opciones y se
  conservan; ningun default activo usaba el ID muerto salvo los corregidos.
- Tests R1: 217 passed (router, improvement, failover, go-deepseek,
  health-check, p78b, web_app); Ruff y `git diff --check` verdes.
  Commits `54b3ba19` (fix+version) y `257b9f26` (tests). Suite completa no
  repetida para R1: los 217 cubren el area tocada y el estado rojo
  preexistente de base no cambia con este lote.
- Coste: el free era $0; `v4.1-flash` es de pago (~$0.30/$1.20 por 1M).
  Vigilar `llm_usage` tras desplegar.
- Dictamen R1: `ready_for_closed_market_deployment` PENDIENTE de: build
  `.312` nativo + snapshot frio + `jetson-ops`, leases/lock frescos y
  repeticion de N3 sobre el arbol final. Sin corte ni push en esta ventana.

## P-L157-R2 25-sep: intento de corte ABORTADO + rollback a .310 (incidente)

Hora: 09:26-10:35 Madrid. Margen a apertura 15:30 sobrado. Autorizacion de
despliegue vigente.

### Precondiciones frescas (todas pasaban)

- XNYS cerrado; postmarket 24-sep terminal `completed` + leases liberados;
  bootstraps de hoy `skipped`/`market_not_ready` con lease liberado.
- Jetson: 3x `.310` healthy, lock coherente, kernel `ok`, PAPER/live/auto
  correctos. N3 arbol final: focales R1 217, suite 2578/46 (deriva
  preexistente), Ruff/NUL(534)/diff/config/smoke verdes.
- Build `.312` nativo desde arbol exacto `5ba5ec01` (6/6 sha256 identicos en
  release `/opt/agente-bolsa/releases/0.4.312`): imagen `0b17852e` arm64,
  labels version/revision/source-tree correctos, ficheros internos identicos.
- Stop escritores (`systemctl stop agente-bolsa`, verificado) + snapshot frio
  receipt v2 `cold-pre-0.4.312-20260925T080500Z`: DB sha256
  `b3345059...`, `quick_check=ok`, `integrity_check=ok`, sidecars preservados.

### Causa del aborto: imagen incompatible con el layout productivo

- El `deploy-agente-bolsa` quedo atascado en `init-db` (Up 10 min): el
  Dockerfile del arbol Git corre como ROOT (sin `USER`), y con
  `cap_drop: ALL` ni root atraviesa `/data` 750 -> `Permission denied` en
  `mkdir` y `ensure_runtime_dirs`. Ademas el entrypoint espera la DB en
  `/data/state/` (prod la tiene en `/data/`) y sirve Streamlit en 8080
  (prod usa 8501). Las imagenes `.305-.310` son ports (USER app), no builds
  de este Dockerfile. Construir el arbol Git con este Dockerfile NO es
  desplegable en Jetson.
- Incidente propio: dos `docker run` de inspeccion arrancaron entrypoints
  huesped (`tender_liskov`, `nifty_hodgkin`); detenidos y eliminados, sin
  volumenes huerfanos, sin tocar datos (sin mounts). Leccion: inspeccionar
  imagenes solo con `docker create` + `cp`, jamas `docker run`.

### Rollback auditable (completado y verificado dos veces)

- `docker stop/rm init-db`; selector restaurado desde
  `runtime.env.bak-p157` a `0.4.310-arm64`; `jetson-ops deploy-agente-bolsa`
  -> `desplegado y saludable` (init-db Exited correcto).
- Validacion x2 separadas >75 s (la segunda tras un reboot no solicitado del
  host ~10:22, con auto-recuperacion por systemd): 3x `.310` healthy, HTTP
  200 en `/`, `/health`, `/kindle`, lock coherente (PID 7/token 2257),
  kernel `ok`, version `0.4.310`, leases apareados, cero ordenes, sin
  `database is locked`, listener unico, unidad `active`.
- Host reiniciado dos veces sin orden (09:23 y ~10:22); stack se autolevanta.
  Imagen `.312` eliminada (`rmi 0b17852e`) para evitar uso accidental.
  Release `/opt/.../0.4.312`, snapshot frio y backups de selector conservados.
- Dictamen: `precondition_not_met` para corte por build de arbol. Siguiente:
  portar el diff R1 sobre la linea de imagen `.310` (procedimiento port) o
  lote de alineacion Dockerfile/entrypoint a spec productiva (USER app,
  DB en `/data`, puerto 8501); despues, gates frescos + corte. Sin push.

## P-L157-R3 25-sep: DESPLEGADO 0.4.312 por port (dictamen `deployed`)

Ventana 09:26-11:00 Madrid. XNYS cerrado todo el corte (apertura 15:30).

### Via elegida: port sobre `.310` (el build de arbol era incompatible)

- 3-way verificado: imagen `.310` == base `784e6cd7` en los 10 ficheros
  runtime (sha256); `llm_model_ids.py` solo existe en candidato. Port =
  10 ficheros del arbol final `09f54f0f`/`0776677d` sobre
  `agente-bolsa:0.4.310-arm64` (USER app, `--chown=1000:1000`), mas
  `pip install --no-deps --no-build-isolation -e /app` (metadata 0.4.312).
- Receta en `/opt/agente-bolsa/releases/0.4.312-port/Dockerfile`
  (+`port/` con los 10 ficheros de `git archive 09f54f0f`).
- Imagen `agente-bolsa:0.4.312-arm64` ID
  `sha256:72ad000f08f7bf63ee5f036d10e6f75180ee4cd9c860ff88ca9b18730296cf86`,
  arm64; labels version=0.4.312, revision=09f54f0f, source-tree=0776677d,
  port-base=.310.
- Verificacion en imagen (sin arrancar entrypoint): 7/7 sha256 src ==
  candidato; cadena `zen|v4.1-flash -> go|v4.1-flash -> local`;
  `version=0.4.312`.

### Corte 10:43-10:50 Madrid

- Pre: 3x `.310` healthy, leases apareados (bootstrap `skipped`),
  postmarket 24-sep `completed`, kernel `ok`, PAPER/live/auto ok.
- `systemctl stop agente-bolsa` (verificado) + snapshot frio receipt v2
  `cold-pre-0.4.312-port-20260925T085000Z`: DB sha256 `b3345059...`
  (identico al anterior: cero escrituras intermedias), `quick_check=ok`,
  `integrity_check=ok`.
- Flip `runtime.env` a `0.4.312-arm64` (backup `.bak-p157`);
  `application.env` INTACTO (hash gate verde; el codigo normaliza el ID
  viejo en runtime, verificado en vivo). `jetson-ops deploy-agente-bolsa`
  -> `desplegado y saludable` (init-db Exited correcto).
- Validacion x2 separadas >75 s: 3x `.312` healthy, HTTP 200 en `/`,
  `/health`, `/kindle`, lock coherente (PID 7/token 46580 y post-reboot),
  kernel `ok` (sello intacto: `config.py` no esta en el manifiesto),
  version `0.4.312`, cero jobs activos, leases apareados, cero ordenes,
  sin `database is locked`, listener unico, unidad `active`.
- Prueba viva en produccion por ruta de codigo desplegada:
  `Settings.opencode_model` (env=free) -> efectivo
  `opencode-zen|deepseek-v4.1-flash`; llamada real OK (`finish=length`).
  Go fallback `v4.1-flash` verificado anoche a nivel de gateway.

### Incidentes de la ventana (documentados, sin dano)

- Host reiniciado 4 veces esta manana (09:12/09:17/10:18/10:29) sin orden;
  causa sin determinar (dmesg limpio de OOM/panic/NVMe; memoria libre);
  stack se autolevanta por systemd cada vez. Requiere seguimiento del
  operador fuera de este lote.
- `whale-copy` (otro proyecto) flapea healthy/unhealthy solo; no tocado.
- Contenedores huesped de inspeccion y etiqueta `.bak-p157` / release
  `0.4.312` (build de arbol fallido) conservados como evidencia; imagen
  de arbol `.312` eliminada (`rmi 0b17852e`).
- Coste: primario y fallback pasan de free ($0) a `v4.1-flash` de pago
  (~$0.30/$1.20 por 1M). Vigilar `llm_usage` en la sesion de hoy 15:30.
