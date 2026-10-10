# Dictamen `ci_digest` — lote Oct10 / 0.4.358

## Dictamen

La ruta nueva reduce el coste de arranque del proceso programado y conserva el
contrato observable del digest en una reproducción aislada. El riesgo OOM
residual sigue abierto: el cambio evita el grafo eager de `main.py`, pero no
convierte en streaming las demás listas grandes de `digest.py` ni elimina la
amplificación de stdout del supervisor. No se afirma que el OOM productivo esté
resuelto.

## Identidad y alcance

- Base: `cb3d8805a9890fab0357b0ba3a3f7afaa8577586` / árbol
  `09ce69a049594006f990ade6004ef1e90be5c591`.
- Rama: `codex/oct10-digest-cli`.
- Commits separados: `d6256f2c` funcional, `9ded0ba9` focales, `dec15088`
  versión `0.4.358`.
- Worktree: `C:\Users\utopi\.codex\worktrees\bolsa-digest-oct10\agenteBolsa`.
- No se modificaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`, históricos, servicios ni configuración
  operativa.
- Intérprete: `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe`.
- Caracterización: `PYTHONPATH` del worktree, `DATA_DIR` temporal,
  `Settings(_env_file=None)` instalado por harness, red/DNS bloqueados. Sin
  broker, LLM, yfinance, SSH, red o SQLite productiva.

## Cambio funcional

`src/agente_bolsa/digest_cli.py` contiene el único despacho compartido. La CLI
histórica `python -m agente_bolsa.main continuous-improvement-lab digest ...`
lo invoca con su `Store` y mantiene parser, argumentos, JSON y texto. El
supervisor usa ahora `python -m agente_bolsa.digest_cli ...`, que importa solo la
ruta necesaria. `continuous_improvement.__init__` conserva el atributo público
`ContinuousImprovementOrchestrator`, pero lo carga de forma lazy.

Ambas rutas mantienen `get_settings`, `configure_logging`, `Store`,
`ensure_schema`, `digest_safety_summary`, `build_lab_digest`,
`format_lab_digest_text`, `--out`, envelope JSON, errores y cierre de la
conexión de lectura. La ruta ligera omite deliberadamente
`ContinuousImprovementLabRuntime`; su constructor crea agentes, memoria y
orquestador aunque el digest no los usa. La CLI histórica sigue construyéndolo
antes de entrar en la rama, por compatibilidad con sus demás subcomandos.

## Evidencia reproducible

Scripts y resultados persistentes:

- [measure_digest_cli_oct10.py](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/scripts/measure_digest_cli_oct10.py)
- [digest_route_isolated_child_oct10.py](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/scripts/digest_route_isolated_child_oct10.py)
- [oct10_digest_cli_measurement_self_rss_v2.json](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/docs/artifacts/oct10_digest_cli_measurement_self_rss_v2.json)
- [oct10_digest_cli_measurement_launcher_invalid.json](C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa/docs/artifacts/oct10_digest_cli_measurement_launcher_invalid.json)

El primer intento de RSS quedó conservado como inválido: el padre medía el
launcher o un proceso reutilizado después de terminar el hijo y produjo ~4,6
MB para ambos casos. No se usa como evidencia. La versión v2 mide
`GetCurrentProcess` dentro de cada hijo, después de `import` y al finalizar la
ruta.

Ejecución v2 sobre base vacía temporal:

| Fase | Ruta ligera | CLI histórica |
|---|---:|---:|
| RSS después de import | 39.194.624 B | 140.738.560 B |
| Módulos después de import | 306 | 1.895 |
| RSS al terminar digest | 137.240.576 B | 151.126.016 B |
| Módulos al terminar | 1.748 | 2.064 |
| returncode | 0 | 0 |
| stdout JSON | 38.030 B | 38.033 B |
| informe Markdown | 5.903 B | 5.903 B |

El probe confirma que la ruta ligera no carga `agente_bolsa.main`,
`scheduler` ni `continuous_improvement.runtime` durante su import. El digest
real carga todavía sus dependencias propias; la reducción observada no equivale
a un presupuesto libre completo frente al límite Linux de 268.435.456 B.

La paridad observada tiene `ok=true`, `days=1`, `safety_ok=true`, sin
violaciones, mismas claves de envelope y mismas 33 claves del digest. La
comparación de payload normaliza solo campos dinámicos de ejecución:
`generated_at`, `as_of`, `from`, `to`, `window_start`, `reference_at` y
`path`; no se borran contadores, estados, denominadores ni claves de negocio.
El legacy de esta comparación ya delega el nuevo handler compartido; por tanto,
la prueba demuestra paridad entre los dos entrypoints candidatos, no una
comparación independiente contra una copia del handler pre-refactor.

## Cierre y fallos

Focales `32 passed in 11.71s`:

```text
C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_digest_cli.py tests\test_ci_digest_reuse.py tests\test_ci_phase3_digest.py tests\test_config_audit.py -q
```

Cubiertos: JSON/out, mismo handler, safety, cierre normal, cierre cuando el
builder falla, import lazy, comando del supervisor. `run_digest_command` cierra
la conexión también si `ensure_schema()` falla; `execute_digest_command` cierra
si falla import, build o I/O después de recibir el Store.

Ruff focal pasó; `git diff --check` pasó antes del commit funcional. No se
ejecutaron fullsuite, smoke, build ni servicios.

## Límites y riesgo residual

La medición es Windows RSS, no memcg Linux. El fixture no contiene datos
productivos. La ruta ligera reduce importación eager y omite constructor
residente, pero `digest.py` conserva materializaciones de propuestas,
experimentos, applied, decisions, artifacts, comparable controls,
`performance_daily(limit=0)`, llm usage y eventos shadow. El supervisor sigue
capturando y parseando stdout JSON completo. Esas listas y amplificación deben
tratarse en lote posterior con medición propia; elevar límite cgroup no es
sustituto de optimización.

El OOM exacto de producción queda acreditado para el contenedor auxiliary y el
instante reportado por kernel, pero este lote no atribuye causalidad a una única
fase ni declara resolución total.
