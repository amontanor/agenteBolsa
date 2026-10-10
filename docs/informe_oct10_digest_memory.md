# Dictamen `ci_digest` — lote Oct10 / 0.4.358

## Dictamen

La ruta ligera reduce el coste de importación del proceso programado y
conserva el contrato observable del digest en una reproducción aislada. El
riesgo OOM productivo sigue abierto: este cambio evita el grafo eager de
`main.py`, pero no convierte en streaming las demás listas grandes de
`digest.py` ni elimina la amplificación de stdout del supervisor. No se afirma
que el OOM esté resuelto.

## Identidad y alcance

- Base: `cb3d8805a9890fab0357b0ba3a3f7afaa8577586` / árbol
  `09ce69a049594006f990ade6004ef1e90be5c591`.
- Rama: `codex/oct10-digest-cli`; versión reservada `0.4.358`.
- Worktree: `C:\Users\utopi\.codex\worktrees\bolsa-digest-oct10\agenteBolsa`.
- Intérprete: `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`.
- Caracterización: `PYTHONPATH` del worktree, `DATA_DIR` temporal,
  `Settings(_env_file=None)` instalado dentro de cada hijo, y red/DNS
  bloqueados dentro de cada hijo. Sin broker, LLM, yfinance, SSH, red ni
  SQLite productiva.
- No se modificaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`, históricos, servicios ni configuración
  operativa.

## Cambio funcional

`src/agente_bolsa/digest_cli.py` contiene el único despacho compartido. La CLI
histórica `python -m agente_bolsa.main continuous-improvement-lab digest ...`
lo invoca con su `Store` y mantiene parser, argumentos, JSON y texto. El
supervisor usa ahora `python -m agente_bolsa.digest_cli ...`, que evita importar
el grafo residente de `main.py`. `continuous_improvement.__init__` conserva el
atributo público `ContinuousImprovementOrchestrator`, pero lo carga de forma
lazy.

Ambas rutas mantienen `get_settings`, `configure_logging`, `Store`,
`ensure_schema`, `digest_safety_summary`, `build_lab_digest`,
`format_lab_digest_text`, `--out`, envelope JSON, errores y cierre de la
conexión de lectura. La ruta ligera omite deliberadamente
`ContinuousImprovementLabRuntime`; su constructor crea agentes, memoria y
orquestador aunque el digest solo necesita el `Store` y el resumen de safety.
La CLI histórica sigue construyéndolo antes de entrar en su rama por
compatibilidad con los demás subcomandos.

## Evidencia reproducible

Scripts y resultados persistentes:

- [measure_digest_cli_oct10.py](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/scripts/measure_digest_cli_oct10.py)
- [digest_route_isolated_child_oct10.py](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/scripts/digest_route_isolated_child_oct10.py)
- [oct10_digest_cli_measurement_self_rss_v3.json](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/docs/artifacts/oct10_digest_cli_measurement_self_rss_v3.json)
- [oct10_digest_base_cb3_fingerprint.json](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/docs/artifacts/oct10_digest_base_cb3_fingerprint.json)
- [oct10_digest_cli_measurement_launcher_invalid.json](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/docs/artifacts/oct10_digest_cli_measurement_launcher_invalid.json)

La v3 mide `GetCurrentProcess` dentro de cada hijo con una estructura
`PROCESS_MEMORY_COUNTERS` y reporta PID, `sys.prefix`, working set y peak por
fase. El harness congela el reloj a `2026-10-10T09:00:00Z` antes del despacho;
la comparación normaliza únicamente la raíz temporal de artefactos. Conserva
`from`, `to`, `window_start`, `reference_at`, `as_of`, `generated_at` y el
resto del payload. Las dos rutas pasan `returncode=0`, `ok=true`,
`safety_ok=true` y paridad exacta en los casos vacío y fixture.

El caso vacío usa un `DATA_DIR` temporal nuevo. El fixture usa el `Store`
existente para insertar una recomendación sintética `SYNTH` en el esquema
normal, y luego ejecuta el mismo digest por ambos entrypoints. Así la paridad
incluye contenido de una muestra relevante y no solo las claves del envelope.
El fixture no contiene datos productivos.

### Fases RSS efectivas

Valores de working set observados dentro del hijo; `peak` queda registrado en
el JSON v3. La fase `prepared` de la ruta ligera precarga únicamente los
módulos existentes que el handler importa lazy para congelar el reloj del
harness; no es un paso de producción.

| Fase | Ruta ligera: working set / módulos | CLI histórica: working set / módulos |
|---|---:|---:|
| before import | 39.129.088 B / 306 | 39.170.048 B / 306 |
| imported | 39.145.472 B / 307 | 142.172.160 B / 1.895 |
| prepared | 124.723.200 B / 1.580 | 142.172.160 B / 1.895 |
| completed | 137.551.872 B / 1.748 | 151.625.728 B / 2.064 |

El probe de importación confirma que `agente_bolsa.digest_cli` no carga
`agente_bolsa.main`, `scheduler` ni `continuous_improvement.runtime`; el
probe de `main` sí carga esos módulos. La reducción de arranque no equivale a
un presupuesto libre completo frente al límite Linux de 268.435.456 B.

La referencia al comportamiento pre-refactor de `cb3` se conserva como huella
AST y SHA-256 en el artefacto de fingerprint. No se duplicó ni ejecutó una
segunda implementación de negocio; por tanto, la paridad ejecutada es entre
los dos entrypoints candidatos actuales, con la procedencia pre-refactor
verificable por hash.

## Cierre, safety y fallos

`tests/test_digest_cli.py` tiene 10 pruebas focales y cubre JSON con y sin
`--out`, texto sin `--out`, propagación del resumen de safety, cierre normal,
cierre en fallo del builder, fallo de importación, fallo de I/O, fallo de
safety, fallo de `ensure_schema`, API pública lazy y comando del supervisor.
Los fallos conservan la excepción original y cierran el Store. El bootstrap de
subprocess prueba también `DATA_DIR` frente a un `.env` hostil y el bloqueo de
DNS dentro del hijo.

No se ejecutaron fullsuite, smoke, build, servicios, red, broker, LLM ni SSH.
La ejecución focal de cuatro archivos terminó con `38 passed in 9.51s`.

## Medición inválida preservada con límite explícito

El primer intento parent-side produjo aproximadamente 4,6 MB porque midió el
launcher o un proceso reutilizado después de terminar el hijo. El resultado
original de 94.506 bytes con `parity=false` ya no está disponible en este
worktree; `oct10_digest_cli_measurement_launcher_invalid.json` es solo un
resumen retrospectivo y lo declara como tal, no una copia exacta. La evidencia
válida es la v3 dentro de los hijos.

## Límites y riesgo residual

La medición es Windows RSS, no memcg Linux, y los hijos usan un fixture
sintético. `digest.py` conserva materializaciones de propuestas,
experimentos, applied, decisions, artifacts, comparable controls,
`performance_daily(limit=0)`, uso LLM y eventos shadow. El supervisor sigue
capturando y parseando stdout JSON completo. Esas listas y la amplificación de
stdout son hotspots pendientes para otro lote medido; elevar el límite cgroup
no es sustituto de optimización.

El OOM exacto reportado por kernel queda acreditado para el contenedor
auxiliary y el instante indicado por el padre. Este lote demuestra reducción
de importación y paridad de contrato en hijos locales, pero no atribuye el OOM
a una única fase ni declara resolución total.

## Diagnóstico residual de memoria: `digest.py` y supervisor

La ruta ligera elimina el grafo eager de `main.py`, pero el propio digest
todavía conserva varias colecciones completas. Las cuatro lecturas principales
en `build_lab_digest` (`digest.py:86-89`) son listas de Python obtenidas con
`fetchall`: propuestas, experimentos, cambios aplicados y decisiones, todas con
límite 50.000 en esta llamada. Sus órdenes SQL son autoridad del resultado:
propuestas se ordenan por `updated_at DESC`, experimentos y applied por
`updated_at DESC`, y decisiones por `created_at DESC`. El límite actual también
forma parte de la semántica observable: cambiarlo altera los contadores cuando
la tabla supera 50.000 filas.

Esas listas sobreviven a la lectura inicial porque se reutilizan en varias
secciones. `build_kpi_funnel` (`digest.py:630-710`) necesita sus identificadores
y fechas para las cuatro semanas, WIP, conversiones y edades de decisión;
`build_proposal_quality_report` conserva la muestra de 200 propuestas más
recientes por `created_at`; `build_evidence_factory_metrics` recorre propuestas
y applied; y `build_origin_utility_metrics` recorre propuestas, experimentos,
applied y artifacts. Las funciones no devuelven las listas completas, pero sí
retienen durante el cálculo los payloads anidados que leen. Una futura
proyección debe conservar, como mínimo, los identificadores/ciclos/estados,
targets, `created_at`/`updated_at`, `payload` y `guard` de propuestas; tipo,
estado, proposal/cycle ids, métricas y fechas de experimentos; y estado,
proposal/cycle ids, decisión, validaciones y fechas de applied. No se debe
recortar por ventana temporal sin demostrar que cada consumidor mantiene sus
cuatro semanas y su límite histórico.

La lectura de artifacts en `digest.py:247` es especialmente ancha: el Store
trae hasta 50.000 filas con `content_text` completo y `payload_json`. El
consumidor de origin utility solo usa `proposal_id` y `payload.status/tests_ok`
(`digest.py:380-389`); la aprobación humana obtiene por separado hasta 200
`code_diff_preview` y sí usa `content_text` (`digest.py:854-905`). Por ello, el
primer cambio mínimo y aislable recomendado es un lector read-only proyectado
para origin utility que conserve el mismo `ORDER BY updated_at DESC` y límite,
pero solo decodifique `proposal_id` y `payload_json`, dejando intacta la
consulta de aprobación. Mantiene los contadores y estados del payload, no toca
aprendizaje ni riesgo, y evita retener diffs históricos que esa sección nunca
consulta. Reduce el ancho de la colección, pero por sí solo no demuestra
resolver el OOM: seguiría existiendo el límite de 50.000 objetos.

Hay optimizaciones existentes que sí cubren parte del pico. El lector de
decision context (`storage.py:1124-1223`) usa cuatro cursores independientes,
`fetchmany(512)` y conserva solo contadores/hash de snapshot en
`decision_context.py:423-540`; sus límites de autoridad son 50.000 para
recommendations/plans y 200.000 para observations/outcomes, excluyendo las
fuentes lab book y learning experiment. El lector de productividad de agentes
usa `iter_agent_events(limit=None)` en orden ascendente
(`agent_run.py:342-356`), por lo que no hace `fetchall`, pero retiene un estado
por `agent_run_id` y los agregados de roles; ese crecimiento histórico queda
abierto. Estos caminos no deben recibir otra lista intermedia durante una
optimización.

Persisten otros lectores completos que explican el riesgo residual:

- `performance_daily(limit=0)` en `digest.py:209` desactiva el `LIMIT`; el
  Store devuelve todas las filas en orden `session_date ASC`. `benchmark_summary`
  necesita el último contrato, recuento de legacy/conflictos y estado de
  freshness, mientras `_drawdown` necesita la secuencia de equity. El objeto
  realmente necesario es un acumulador ordenado con esos contadores, último
  contrato y estado de drawdown; sustituirlo por una ventana reciente cambiaría
  resultados.
- `build_comparable_control_quality` materializa hasta 50.000
  `trade_recommendations`, conserva los control sets aceptados y crea un mapa
  de hasta 200.000 `signal_outcomes` (`comparable_controls.py:741-780`). Para
  paridad hay que retener solo los control sets que sobreviven al filtro y los
  outcomes referenciados por treatment/control, respetando el orden de entrada
  y los contadores de madurez; eliminar outcomes legacy antes de demostrar el
  filtro cambiaría cobertura.
- `canonical_operation_telemetry_digest` materializa hasta 50.000 eventos,
  filtra snapshots/conflictos y ordena el último snapshot por `created_at`
  (`canonical_operation_telemetry.py:642-660`). `learning_penalty_shadow_digest`
  hace una lectura equivalente de hasta 50.000 eventos, deduplica un evento
  canónico por ciclo y conserva la lista ordenada (`storage.py:2671-2730`). La
  autoridad es el `event_id`, schema/hash y ciclo; un streaming futuro debe
  retener solo el último canónico por ciclo y los contadores de inválidos,
  duplicados y conflictos.
- `latest_overlay_shadow_signal` y `latest_core_sleeve_signal` leen el JSONL
  completo con `read_text().splitlines()` (`digest.py:918-980`) aunque solo
  usan el último JSON válido. Iterar el archivo línea a línea conserva exactamente
  la regla “último registro válido” y elimina una copia completa del log.

El supervisor añade una copia independiente del pico en
`docker_supervisor.py:209-230`: `subprocess.run(..., stdout=PIPE)` conserva
todo el stdout del hijo en `CompletedProcess.stdout`, lo escribe entero al log
y después `json.loads` construye el payload. En el fallback de JSON inválido,
`find`/`rfind` crea además una subcadena antes de decodificarla. El contrato
exige que el payload JSON completo llegue al llamador, que `ok=false` y
returncodes fallen, y que el log conserve stdout/stderr; por tanto, no se puede
truncar ni resumir el envelope como arreglo de memoria. El cambio mínimo de
ese borde sería redirigir el stdout a un archivo temporal y parsearlo desde
allí, manteniendo copia íntegra al log y el mismo parser/error envelope; debe
medirse por separado porque `_run_json_command` sirve a más servicios.

La evidencia actual solo prueba la reducción del arranque y la paridad del
payload en vacío/fixture. No mide todavía el pico con 50.000 filas, diffs
grandes, outcomes de 200.000, JSONL extensos ni stdout proporcional a esos
datos. Esos son los hotspots restantes y requieren una caracterización focal
antes de integrar cualquier proyección o streaming.
