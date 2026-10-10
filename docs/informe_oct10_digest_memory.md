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
