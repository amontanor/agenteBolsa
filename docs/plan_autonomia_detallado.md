# Plan detallado de implementación: grupo de agentes autónomo

Fecha: 2026-06-10
Audiencia: un agente LLM de desarrollo que ejecutará cada tarea sobre este repositorio.
Objetivo final: un sistema de agentes que opera solo (paper primero, live después), entiende el mercado, se auto-modifica el código, los prompts y los agentes, y mejora de forma medible cada día.

---

## 0. Instrucciones globales para el agente ejecutor

Lee esta sección antes de cada tarea. Aplica siempre.

### 0.1 Convenciones del repositorio

- Código fuente en `src/agente_bolsa/`. Paquete instalable (`pip install -e .`).
- Configuración: clase `Settings` (pydantic) en `src/agente_bolsa/config.py`. Cada parámetro tiene `alias` en MAYÚSCULAS que se lee de `.env`. Todo parámetro nuevo se añade ahí Y en `.env.example` con comentario.
- Persistencia: SQLite vía `src/agente_bolsa/storage.py` (clase `Store`). Las tablas se definen como `CREATE TABLE IF NOT EXISTS` en el schema del módulo. Toda tabla nueva sigue ese patrón (idempotente, sin migraciones destructivas).
- Eventos: usar `log_system_event` de `logging_utils.py` y `AgentEvent` de `models.py`. Nada importante sin evento.
- IDs: `new_id(prefix)` de `models.py`.
- CLI: todo subsistema nuevo expone comandos en `src/agente_bolsa/main.py` (patrón `subparsers.add_parser`), con opción `--json`.
- Tests: pytest en `tests/`, un archivo `test_<modulo>.py` por módulo nuevo. Los tests no llaman a red ni a LLM: usar fixtures y monkeypatch como en `tests/test_continuous_improvement.py`.
- Lint: `ruff` (config en `pyproject.toml`).
- Mensajes de usuario/log en español, identificadores de código en inglés (es el estilo existente).

### 0.2 Definition of Done de CUALQUIER tarea

1. `python -m pytest tests/ -x -q` pasa completo.
2. `ruff check src tests` sin errores.
3. `python -m agente_bolsa.main status` y `python -m agente_bolsa.main validate-agent-config --json` funcionan.
4. Smoke: `python -m agente_bolsa.main run-once --skip-crew` termina sin traceback.
5. Tests nuevos cubren el camino feliz Y el camino de bloqueo/error de lo añadido.
6. `.env.example`, `README.md` (sección correspondiente) y `docs/architecture.md` actualizados si la tarea introduce conceptos nuevos.
7. Commit atómico por tarea con mensaje `[T<etapa>.<n>] <resumen>`.

### 0.3 Regla de oro de seguridad

Existe (lo crearás en T0.1) un **kernel inmutable**. Ningún cambio de ninguna etapa puede:
- tocar `src/agente_bolsa/kernel.py`, `.env`, credenciales, ni los flags `TRADING_MODE` / `ALLOW_LIVE_TRADING`;
- eliminar un gate de riesgo existente sin sustituirlo por uno equivalente o más estricto;
- desactivar el kill switch de `tools/operational_health.py`.

---

## ETAPA 0 — Kernel, medición y sandbox (prerequisito de todo)

Propósito: antes de dar libertad a los agentes, construir la jaula mínima (kernel), la regla de medir (baseline) y el mecanismo de deshacer (sandbox git + watchdog). Sin esto, la autonomía degrada el sistema más rápido de lo que aprende.

### T0.1 — Kernel inmutable

**Objetivo:** concentrar en un único módulo los límites que los agentes JAMÁS podrán modificar, y verificar su integridad en runtime.

**Contexto actual:** los límites duros están dispersos: `risk.py` (exposición, drawdown), `operational_health.py` (kill switch), `config.py` (`ALLOW_LIVE_TRADING`, `TRADING_MODE`), `experiments.py` → `AutoApplyCodeAgent.BLOCKED_PREFIXES/BLOCKED_TERMS`.

**Cambios:**

1. Crear `src/agente_bolsa/kernel.py`:
   - Dataclass congelada `KernelLimits` con: `absolute_max_drawdown_pct` (default 0.20), `absolute_max_daily_loss_pct` (0.05), `absolute_max_position_exposure` (0.15), `absolute_max_portfolio_exposure` (1.0), `live_trading_locked: bool` (True), `min_reward_risk` (1.2).
   - Función `kernel_check_order(plan: dict, portfolio: PortfolioSnapshot, settings: Settings) -> tuple[bool, str]`: última validación antes de cualquier envío a broker. Es ADICIONAL a `risk.py`, no lo sustituye: el kernel es el suelo absoluto; `risk.py` sigue siendo el límite operativo (más estricto) que los agentes sí pueden tunear.
   - Función `kernel_integrity() -> dict`: calcula SHA-256 de `kernel.py`, `tools/broker.py`, `tools/execution.py` y `.env` y lo compara con `data/state/kernel_manifest.json` (creado por el comando `kernel-seal`).
2. En `tools/execution.py`: llamar a `kernel_check_order` justo antes de cada `submit_order`; si devuelve `(False, reason)`, registrar evento `kernel_block` y abortar.
3. En `scheduler.py` → `portfolio_watch_job`: llamar a `kernel_integrity()` una vez por sesión; si hay mismatch, activar el kill switch de `operational_health.py` y emitir evento `kernel_integrity_violation`.
4. CLI en `main.py`: `kernel-seal` (regenera manifest, solo manual), `kernel-status --json`.
5. Añadir `src/agente_bolsa/kernel.py` a `AutoApplyCodeAgent.BLOCKED_PREFIXES` en `continuous_improvement/experiments.py`.

**Medición:** ninguna métrica de mercado; es infraestructura.

**Verificación:**
```
python -m pytest tests/test_kernel.py -q
python -m agente_bolsa.main kernel-seal && python -m agente_bolsa.main kernel-status --json
# editar a mano un byte de tools/broker.py → kernel-status debe reportar violation → restaurar
```
Tests requeridos: orden que viola drawdown absoluto se bloquea aunque `risk.py` la apruebe; manifest alterado dispara violación; `kernel_check_order` aprueba una orden válida.

**Aceptación:** ninguna orden puede llegar a `broker.py` sin pasar el kernel; la integridad se verifica cada sesión.
**Rollback:** revertir el commit; el kernel no altera lógica existente, solo añade una capa.

### T0.2 — Baseline de rendimiento y métrica única de progreso

**Objetivo:** una serie diaria objetiva contra la que se medirá TODA mejora futura. "Más listo y rentable" debe ser un número.

**Contexto actual:** existen `signal_outcomes` y `learning_daily_summaries` en `storage.py`, `weekly-review` y `learning-digest` en CLI, pero no hay una serie consolidada de rendimiento del sistema completo.

**Cambios:**

1. Crear `src/agente_bolsa/tools/performance_baseline.py`:
   - `build_daily_performance(store, settings, session_date) -> dict` con: equity paper (de `PortfolioSnapshot`), PnL diario y acumulado, nº señales/compras/ventas, hit rate rodante 20 sesiones, profit factor, Sharpe rodante 60 sesiones, max drawdown rodante, exposición media, PnL del benchmark SPY del mismo día, y `alpha_vs_spy` (PnL% − SPY%).
   - `system_iq_score(window_days=20) -> float`: score compuesto 0-100 = 40% alpha_vs_spy normalizado + 25% hit rate + 20% profit factor + 15% ratio de propuestas del laboratorio promovidas que mejoraron métricas. Es LA métrica de "cada día más listo".
2. Tabla nueva `performance_daily` en `storage.py`: `(session_date PK, payload JSON, equity, pnl_pct, spy_pct, alpha, hit_rate_20, sharpe_60, max_dd, iq_score, created_at)`.
3. En `scheduler.py` → `post_market_review_job`: al final, llamar a `build_daily_performance` y persistir.
4. CLI: `performance --days 30 --json` y `iq-score --json`.
5. En `web_app.py`: gráfico de equity vs SPY e iq_score (seguir el patrón de los gráficos altair existentes).

**Medición:** la propia tarea crea el sistema de medición.

**Verificación:**
```
python -m pytest tests/test_performance_baseline.py -q
python -m agente_bolsa.main job-once post-market   # o el alias del job en main.py
python -m agente_bolsa.main performance --days 7 --json
```
Tests: cálculo con datos sintéticos de 30 sesiones produce Sharpe/drawdown correctos (verificar contra cálculo manual en el test); día sin trades no rompe; SPY ausente degrada con `alpha=null`, no con excepción.

**Aceptación:** tras una sesión de paper, `performance` devuelve la fila del día; `iq-score` devuelve un número estable.
**Rollback:** tabla y módulo aislados; revertir commit.

### T0.3 — Sandbox git real para cambios autónomos

**Objetivo:** que cada cambio de código propuesto por agentes se aplique en una rama git aislada, pase la suite COMPLETA, y se fusione o destruya automáticamente.

**Contexto actual:** `AutoApplyCodeAgent.try_apply` (en `continuous_improvement/experiments.py`, línea ~412) aplica `file_edits`/`patch` directamente sobre `settings.improvement_workspace_dir` con snapshot/restore propio y ejecuta solo `tests/test_continuous_improvement.py` por defecto. No usa ramas, no corre la suite completa ni ruff.

**Cambios:**

1. Crear `src/agente_bolsa/continuous_improvement/sandbox.py` con clase `GitSandbox`:
   - `open(change_id) -> Path`: `git worktree add <workspace>/sandboxes/<change_id> -b ci/auto/<change_id>` desde HEAD del repo.
   - `apply(file_edits, patch_text)`: reutilizar la lógica de escritura existente de `AutoApplyCodeAgent._apply_payload`.
   - `validate() -> dict`: ejecutar en el worktree, capturando stdout/rc: `ruff check src tests`, `python -m pytest tests/ -x -q` (suite completa, no solo CI), `python -m agente_bolsa.main run-once --skip-crew` con `DATA_DIR` temporal. Timeout configurable `CI_SANDBOX_VALIDATE_TIMEOUT_SECONDS` (default 900).
   - `merge()`: `git merge --no-ff ci/auto/<id>` sobre la rama de trabajo + tag `ci-auto/<id>`.
   - `destroy()`: `git worktree remove --force` + `git branch -D`.
2. Refactorizar `AutoApplyCodeAgent.try_apply` para usar `GitSandbox`: blocked→BLOCKED como ahora; validación falla→guardar artefactos (logs de pytest/ruff) en `continuous_improvement_proposal_artifacts` y status `REJECTED_BY_TESTS`; validación pasa→merge y status `APPLIED` con el hash del commit en el registro de `continuous_improvement_applied_changes`.
3. Nuevo setting `CI_SANDBOX_FULL_SUITE` (bool, default true).
4. `ci-lab rollback <id>` (ya existe el subcomando en `main.py`): implementarlo como `git revert` del commit taggeado + re-ejecución de la suite.

**Medición:** % de propuestas que llegan a APPLIED vs REJECTED_BY_TESTS (consulta sobre `continuous_improvement_applied_changes`).

**Verificación:**
```
python -m pytest tests/test_ci_sandbox.py -q
# test de integración: proposal sintética con un edit válido en docs/ → APPLIED con commit;
# proposal que rompe un test → REJECTED_BY_TESTS y worktree destruido;
# proposal que toca src/agente_bolsa/kernel.py → BLOCKED sin crear worktree.
python -m agente_bolsa.main ci-lab applied-changes --json
```

**Aceptación:** ningún cambio autónomo puede tocar la rama principal sin suite completa verde; todo APPLIED tiene commit revertible.
**Rollback:** restaurar el `try_apply` anterior (mantenerlo como `_legacy_apply` durante una versión).

### T0.4 — Router LLM por roles (barato/profundo)

**Objetivo:** que las tareas de razonamiento profundo (escribir código, diseñar estrategias, retrospectivas) usen un modelo potente, y las rutinarias (sentimiento por símbolo, resúmenes) el local barato.

**Contexto actual:** `llm_router.py` tiene `LLMEndpoint`, `configured_llm_endpoints`, `select_preferred_endpoint` y `chat_completion_with_fallback` (fallback local Qwen ↔ Gemini). El laboratorio usa `ImprovementLLMClient` (`continuous_improvement/llm_client.py`) con settings `IMPROVEMENT_LLM_*` ya existentes. No hay concepto de "rol".

**Cambios:**

1. En `llm_router.py`: añadir `ROLE_PROFILES: dict[str, dict]` con roles `fast` (sentimiento, resúmenes: modelo local, max_tokens 1200), `decision` (trade_decision: modelo medio, temperature 0.2), `deep` (ProgrammerAgent, estrategas, retrospectivas: modelo potente, max_tokens 16000, timeout 600). Cada rol resuelve a settings `LLM_ROLE_<ROL>_MODEL`, `LLM_ROLE_<ROL>_BASE_URL`, `LLM_ROLE_<ROL>_API_KEY`, `LLM_ROLE_<ROL>_MAX_TOKENS` con fallback a la cadena actual si no están definidos.
2. Nueva función `chat_for_role(role, messages, settings, **kw)` que envuelve `chat_completion_with_fallback`.
3. Migrar llamadas: `news_sentiment.py` → `fast`; `trade_decision.py` → `decision`; `continuous_improvement/llm_client.py` → `deep` para `ProgrammerAgent`, `ChiefInvestmentOrchestratorAgent`, `ExperimentDesignerAgent`; `fast` para reporters.
4. Registrar coste/uso por rol en la tabla existente `llm_usage` (añadir columna `role` si no existe, vía `ALTER TABLE` defensivo).
5. CLI: `llm-usage --by-role --json`.

**Medición:** coste diario por rol; latencia p50/p95 por rol.

**Verificación:** `python -m pytest tests/test_llm_router.py -q` (extender el test existente: rol sin config cae al endpoint por defecto; rol configurado selecciona su endpoint; registro de uso guarda el rol).

**Aceptación:** los agentes del laboratorio usan el modelo `deep` configurable sin tocar el resto del sistema.
**Rollback:** los roles con fallback a la cadena actual hacen el cambio inocuo si se desconfiguran.

### T0.5 — Watchdog de cambios aplicados (rollback por métricas)

**Objetivo:** todo cambio promovido queda en observación; si las métricas empeoran, se revierte solo.

**Contexto actual:** `continuous_improvement_applied_changes` registra cambios; `ci-lab rollback` es manual. No hay vigilancia post-aplicación.

**Cambios:**

1. Crear `src/agente_bolsa/tools/change_watchdog.py`:
   - `evaluate_applied_changes(store, settings) -> list[dict]`: para cada cambio APPLIED con menos de `CHANGE_WATCHDOG_WINDOW_SESSIONS` (default 5) sesiones de antigüedad, comparar `performance_daily` (T0.2) de la ventana post-cambio contra la ventana previa equivalente: si `iq_score` cae > `CHANGE_WATCHDOG_MAX_IQ_DROP` (default 10 puntos) o el hit rate cae > 15 puntos con ≥5 trades, marcar `ROLLBACK_REQUESTED`.
   - `execute_rollbacks(store, settings)`: invocar la lógica de T0.3 (`git revert` + suite). Si dos cambios solapan ventana, revertir el más reciente primero.
2. Engancharlo al final de `post_market_review_job` en `scheduler.py`.
3. Evento `change_rolled_back` con cifras antes/después.
4. Settings nuevos con alias: `CHANGE_WATCHDOG_ENABLED` (true), los dos umbrales de arriba.

**Medición:** nº de rollbacks automáticos; tiempo medio cambio→detección.

**Verificación:** `tests/test_change_watchdog.py`: series sintéticas donde la métrica cae → solicita rollback; donde mejora → no hace nada; ventana insuficiente → espera.

**Aceptación:** un cambio dañino se revierte sin intervención humana en ≤ N sesiones.
**Rollback:** desactivar `CHANGE_WATCHDOG_ENABLED`.

---

## ETAPA 1 — Autonomía de código sobre estrategia y decisión

Propósito: que los agentes puedan modificar y CREAR la lógica que decide qué comprar, con promoción por evidencia en lugar de aprobación humana.

### T1.1 — Niveles de autonomía y ampliación del allowlist

**Objetivo:** sustituir el allowlist fijo de `AutoApplyCodeAgent` por niveles configurables y progresivos.

**Contexto actual:** `AutoApplyCodeAgent.ALLOWED_PREFIXES` solo permite `continuous_improvement/`, `tools/operational_*`, `reporting.py`, `retention.py`, `tests/`, `docs/`, `.env.example`. `BLOCKED_TERMS` impide hasta mencionar `ORDER` o `EXECUTION` en el contenido.

**Cambios:**

1. En `continuous_improvement/experiments.py`, reemplazar las constantes por `AUTONOMY_TIERS: dict[int, dict]`:
   - **Nivel 1** (actual): el allowlist de hoy.
   - **Nivel 2**: + `src/agente_bolsa/tools/` completo EXCEPTO `broker.py`, `execution.py`, `risk.py` + `src/agente_bolsa/strategies/` (T1.2).
   - **Nivel 3**: + `trade_decision.py`, `position_sizing.py`, `portfolio_optimizer.py`, `scheduler.py`, prompts (T2.1).
   - **Bloqueado siempre** (todos los niveles): `kernel.py`, `broker.py`, `execution.py`, `.env`, `.github/`, `config.py` (las settings se cambian por `AutoApplyConfigAgent`, no editando el archivo).
2. Setting `CODE_AUTONOMY_LEVEL` (int, default 1). Revisar `BLOCKED_TERMS`: en nivel ≥2 quitar `ORDER`/`EXECUTION` como términos (impiden trabajo legítimo) y sustituirlos por la lista de rutas bloqueadas + un check AST: rechazar diffs que importen `tools.broker` o `tools.execution` desde archivos donde antes no se importaban.
3. La subida de nivel NO es manual: `autonomy_promotion_check(store)` sube de nivel automáticamente cuando se cumplen: ≥ `AUTONOMY_PROMOTION_MIN_APPLIED` (default 10) cambios APPLIED en el nivel actual, 0 rollbacks del watchdog en `AUTONOMY_PROMOTION_CLEAN_SESSIONS` (default 15) sesiones, e `iq_score` medio de las últimas 10 sesiones ≥ al de las 10 previas. Baja de nivel automática si hay 2 rollbacks en 10 sesiones. Persistir en `runtime_state` con clave `code_autonomy_level` y emitir evento `autonomy_level_changed`.
4. `ci-lab autonomy-status` (subcomando ya existente): mostrar nivel vigente, progreso hacia el siguiente y motivos.

**Medición:** nivel vigente en el tiempo; cambios APPLIED por nivel; rollbacks por nivel.

**Verificación:** `tests/test_autonomy_tiers.py`: edit a `tools/breakout_scanner.py` BLOCKED en nivel 1 y permitido en nivel 2; `kernel.py` bloqueado en todos; promoción/degradación automática con historiales sintéticos.

**Aceptación:** el sistema gana permisos solo, en función de su propio historial de fiabilidad.
**Rollback:** fijar `CODE_AUTONOMY_LEVEL=1` congela el comportamiento actual.

### T1.2 — Registro de estrategias plugables

**Objetivo:** que una "estrategia" sea un artefacto creado, versionado, activado y retirado por los agentes, no código entrelazado en el pipeline.

**Contexto actual:** la estrategia base vive implícita en `technical_study.py` + `trade_decision.py` + gates. La tabla `strategy_versions` existe en `storage.py` pero está infrautilizada; hay CLI `strategy-registry`.

**Cambios:**

1. Crear paquete `src/agente_bolsa/strategies/`:
   - `base.py`: ABC `Strategy` con `name`, `version`, `generate_candidates(market_data, market_state) -> list[CandidateSignal]`, `exit_rules(position) -> ExitPlan`, `required_history_days`, `metadata()`. `CandidateSignal` reutiliza el formato de candidato de `technical_study.py` (mismas claves: symbol, side, entry, stop, take, score, setup, features) para que los gates y `signal_learning` funcionen sin cambios.
   - `registry.py`: `discover()` carga módulos de `strategies/` + estrategias registradas en `strategy_versions` con status ACTIVE/SHADOW; `register(strategy_module_path, status)`; validación de firma con AST (sin imports de broker/execution, sin red).
   - `builtin_breakout.py`: PRIMERA estrategia = extraer la lógica actual de candidatos de `technical_study.py` detrás de la interfaz, sin cambiar su comportamiento (refactor puro, verificable porque los candidatos generados sobre un snapshot fijo de test son idénticos antes/después).
2. En `technical_study.py`: iterar sobre `registry.discover()` con status ACTIVE; etiquetar cada candidato con `strategy_name`/`strategy_version` (propagar a `signal_outcomes` añadiendo columnas defensivas).
3. Estrategias SHADOW: generan candidatos que se registran en `signal_outcomes` con flag `shadow=1` pero NUNCA llegan a `trade_decision` ni a ejecución. Esto reutiliza `record_signal_candidates` y `update_signal_outcomes` de `signal_learning.py`, que ya maduran outcomes de señales no ejecutadas.
4. CLI: ampliar `strategy-registry` con `--activate/--shadow/--retire <name>`.

**Medición:** por estrategia: nº señales, hit rate, profit factor, alpha (de outcomes madurados).

**Verificación:** `tests/test_strategy_registry.py` + test de regresión: snapshot fijo → `builtin_breakout` produce exactamente los mismos candidatos que el código previo.

**Aceptación:** el pipeline corre con N estrategias; una estrategia SHADOW acumula outcomes sin tocar dinero.
**Rollback:** registry con solo `builtin_breakout` ACTIVE = comportamiento actual.

### T1.3 — Champion/challenger con promoción automática por métricas

**Objetivo:** cerrar el ciclo: una propuesta validada se promueve a SHADOW, y de SHADOW a ACTIVE, por métricas, sin humano (en paper).

**Contexto actual:** `ContinuousImprovementLabRuntime.CHAMPION_CHALLENGER_REQUIRED` ya define las validaciones (`in_sample`, `walk_forward`, `out_of_sample`, `paper_or_shadow_window`, `risk_review`); `ExperimentRunner` ejecuta backtest/walk-forward/retrospectiva; pero `paper_or_shadow_window` no tiene implementación real de ventana y la decisión final pasa por comité/humano.

**Cambios:**

1. Crear `src/agente_bolsa/continuous_improvement/promotion.py` con clase `PromotionManager`:
   - `start_shadow(strategy_name, version)`: marca SHADOW en el registry (T1.2) y crea fila en tabla nueva `promotion_windows` (`window_id, strategy, version, started_at, min_sessions, min_signals, status`).
   - `evaluate_windows(store, settings)`: una ventana se resuelve cuando acumula ≥ `PROMOTION_MIN_SESSIONS` (default 10) sesiones y ≥ `PROMOTION_MIN_SIGNALS` (default 20) señales shadow madurada. Criterio de promoción: hit rate shadow ≥ hit rate del champion en el mismo período − 2 puntos, Y expectancy (media de pnl_pct por señal) > la del champion, Y max drawdown simulado ≤ 1.2× champion. Si falla → `REJECTED_SHADOW`, retirar. Si pasa → status ACTIVE; si reemplaza a otra (mismo "slot"), la anterior pasa a SHADOW de vigilancia 10 sesiones (degradación reversible).
   - Empates/datos insuficientes → extender ventana hasta `PROMOTION_MAX_SESSIONS` (default 25); al vencer sin evidencia → rechazo conservador.
2. En `runtime.py` → `run_once`: cuando una proposal de tipo `STRATEGY_RULE_CHANGE`/código de estrategia queda APPLIED por T0.3, llamar a `PromotionManager.start_shadow` automáticamente en vez de requerir decisión de comité.
3. `evaluate_windows` se engancha a `post_market_review_job`.
4. Tabla `promotion_windows` en `storage.py`; CLI `promotions --json`.
5. El humano conserva un freno, no un gate: setting `PROMOTION_HUMAN_VETO_HOURS` (default 0 = sin espera; configurable a 24 para que un `ci-lab rollback` manual pueda adelantarse).

**Medición:** nº ventanas abiertas/resueltas; % promociones que el watchdog (T0.5) no revierte después = calidad del criterio.

**Verificación:** `tests/test_promotion.py` con outcomes sintéticos: challenger claramente mejor → ACTIVE; peor → rechazo; insuficiente → extensión y rechazo al vencer; degradación del champion reemplazado es reversible.

**Aceptación:** una estrategia escrita por un agente puede llegar a operar paper real sin que ningún humano apruebe nada, habiendo pasado backtest + walk-forward + ventana shadow.
**Rollback:** `PROMOTION_MIN_SESSIONS=999999` congela promociones.

### T1.4 — ProgrammerAgent end-to-end: de pérdida a código

**Objetivo:** que el `ProgrammerAgent` del laboratorio escriba estrategias/módulos nuevos completos, no solo parches.

**Contexto actual:** `continuous_improvement/agents.py` tiene `ProgrammerAgent(SpecialistAgent)` y `SoftwareReliabilityAgent(ProgrammerAgent)`; producen propuestas con `file_edits`/`patch` que consume `AutoApplyCodeAgent`. El prompt no conoce la interfaz `Strategy` ni el layout del repo.

**Cambios:**

1. Crear `continuous_improvement/repo_context.py`: `build_repo_context(targets: list[str]) -> str` que arma para el prompt: árbol de `src/agente_bolsa/` (solo nombres), contenido de `strategies/base.py`, la estrategia más parecida al objetivo, el test de ejemplo, y las reglas de DoD de la sección 0.2. Cap de tokens con `context_compaction.py` (ya existe).
2. Ampliar el prompt de `ProgrammerAgent` con: (a) contrato estricto de salida: JSON con `file_edits` (lista de `{path, content}` completos, no diffs parciales), `test_commands`, `rationale`, `expected_metric_impact`; (b) obligación de incluir SIEMPRE un archivo de test nuevo; (c) la interfaz `Strategy` y un ejemplo completo.
3. Flujo: hipótesis del laboratorio (tabla `continuous_improvement_hypotheses`) → `ExperimentDesignerAgent` la convierte en spec → `ProgrammerAgent` (rol `deep` de T0.4) genera los archivos → T0.3 sandbox valida → T1.3 shadow → promoción. Implementar el cableado en `runtime.py::run_once` como nuevo tipo de tarea `BUILD_STRATEGY`.
4. Reintentos: si el sandbox rechaza por tests, devolver al `ProgrammerAgent` el log de pytest (truncado por `context_compaction`) hasta `PROGRAMMER_MAX_REPAIR_ATTEMPTS` (default 2); después, archivar como `FAILED_BUILD` con todo el material en `continuous_improvement_proposal_artifacts`.

**Medición:** tasa de éxito de build (APPLIED / intentos); tasa de éxito tras repair; % de estrategias construidas que llegan a ACTIVE.

**Verificación:** `tests/test_programmer_flow.py` con LLM mockeado (respuestas fijas): respuesta válida → archivos en sandbox → APPLIED; respuesta con test roto → repair loop → FAILED_BUILD a la segunda.

**Aceptación:** desde una hipótesis en la base de datos hasta una estrategia SHADOW operando, cero intervención humana.
**Rollback:** desactivar el tipo de tarea `BUILD_STRATEGY` por setting `CI_BUILD_STRATEGY_ENABLED`.

---

## ETAPA 2 — Agentes que se mejoran a sí mismos

Propósito: prompts, agentes y memoria dejan de ser estáticos; el sistema aprende de cada sesión de forma estructural.

### T2.1 — Prompts como datos versionados con replay

**Objetivo:** que los agentes puedan editar sus propios prompts y los de `trade_decision`, midiendo el efecto antes de promover.

**Contexto actual:** prompts en `config/tasks.yaml` (`prompt_template`), en `_llm_prompt_payload` de `trade_decision.py` y hardcodeados en `continuous_improvement/agents.py`. Las decisiones históricas con su contexto completo están en `trade_recommendations`, `decisions` y los reports JSON de `data/reports/` — esto permite replay.

**Cambios:**

1. Tabla `prompt_versions` en `storage.py`: `(prompt_key, version, template, status [ACTIVE|CANDIDATE|RETIRED], parent_version, created_by, metrics_payload, created_at)`. Cargar los prompts actuales como version 1 ACTIVE mediante comando `prompts-import` (idempotente).
2. Crear `src/agente_bolsa/prompt_store.py`: `get_prompt(key) -> str` (ACTIVE, con caché), `propose(key, template, created_by)`, `promote(key, version)`. Migrar `trade_decision._llm_prompt_payload`, `crew.py` (lectura de tasks.yaml) y los prompts de agentes del laboratorio a `get_prompt`, dejando los YAML/hardcode como fallback si la tabla está vacía.
3. Crear `src/agente_bolsa/tools/prompt_replay.py`: `replay_decisions(prompt_key, candidate_version, sessions=10) -> dict`. Para `trade_decision`: re-ejecutar el prompt CANDIDATE sobre los snapshots históricos (`market_snapshot_*`, `technical_context`, sentimiento y cartera guardados), comparar las recomendaciones nuevas contra los outcomes reales ya madurados en `signal_outcomes`: ¿el prompt nuevo habría comprado más ganadoras y menos perdedoras? Métricas: expectancy simulada, nº de cambios de decisión, % de decisiones que violan gates (deben ser 0).
4. Promoción de prompts vía `PromotionManager` (T1.3) con criterio: expectancy simulada del replay ≥ ACTIVE y 0 violaciones de formato JSON en ≥ 30 decisiones re-ejecutadas. Después, ventana shadow real no aplica (los prompts no tienen shadow); en su lugar el watchdog T0.5 vigila las sesiones posteriores.
5. `PROMPT_SELF_EDIT_ENABLED` (default false hasta completar T2.3) habilita que el laboratorio genere propuestas de tipo `PROMPT_CHANGE`.

**Medición:** expectancy del replay por versión; evolución del hit rate real tras cada promoción de prompt.

**Verificación:** `tests/test_prompt_store.py` y `tests/test_prompt_replay.py` (replay con LLM mockeado sobre 3 decisiones sintéticas con outcomes conocidos produce el ranking esperado).

**Aceptación:** un prompt editado por un agente solo entra en producción si el replay histórico demuestra mejora.
**Rollback:** `promote(key, version_anterior)`; el fallback a YAML garantiza arranque siempre.

### T2.2 — Fábrica de agentes: especialistas definidos como datos

**Objetivo:** que el comité pueda crear agentes especialistas nuevos (p. ej. "especialista en semiconductores", "vigilante de short squeeze") sin tocar código Python.

**Contexto actual:** los especialistas del laboratorio son clases fijas en `continuous_improvement/agents.py` registradas en `SPECIALIST_AGENT_CLASSES`; `DecisionCommitteeAgent` ya contempla "crear expertos adicionales" en su backstory pero no hay mecanismo.

**Cambios:**

1. Tabla `agent_definitions` en `storage.py`: `(agent_key PK, role, goal, prompt_key (FK a prompt_versions), inputs [lista de reports/tablas que recibe], output_schema JSON, status, created_by, created_at, performance_payload)`.
2. Crear `continuous_improvement/dynamic_agents.py`: clase `DynamicSpecialistAgent(SpecialistAgent)` que se instancia desde una fila de `agent_definitions`: construye su prompt desde `prompt_store`, recibe los inputs declarados (resueltos contra `data/reports/` y el Store) y valida su salida contra `output_schema` (rechazo + evento si no cumple).
3. En `runtime.py::describe_agents` y en la orquestación: fusionar `SPECIALIST_AGENT_CLASSES` con los `agent_definitions` ACTIVE.
4. Proposals de tipo nuevo `CREATE_AGENT` generadas por `DecisionCommitteeAgent`/`ChiefInvestmentOrchestratorAgent`: payload = fila completa de definición. Gate determinista: máximo `MAX_DYNAMIC_AGENTS` (default 8) activos; inputs solo del catálogo permitido; el output_schema debe declarar `confidence` y `evidence`.
5. Evaluación de utilidad: cada 10 sesiones, `PerformanceEvaluatorAgent` puntúa cada agente dinámico (¿sus señales/vetos correlacionan con outcomes?) y retira los inútiles (`status=RETIRED`, evento `agent_retired`). Implementar en `continuous_improvement/agents.py::PerformanceEvaluatorAgent` un método `score_dynamic_agents(store)`.

**Medición:** nº agentes dinámicos activos; score de utilidad por agente; % retirados.

**Verificación:** `tests/test_dynamic_agents.py`: definición válida se instancia y produce salida conforme al schema (LLM mock); schema violado → rechazo; el cupo máximo se respeta; retiro por score bajo.

**Aceptación:** el sistema crea, usa, mide y retira especialistas solo.
**Rollback:** `MAX_DYNAMIC_AGENTS=0` desactiva la fábrica sin tocar lo demás.

### T2.3 — Retrospectiva generativa nocturna (pérdidas → hipótesis)

**Objetivo:** que cada pérdida, cada oportunidad perdida y cada acierto raro se conviertan automáticamente en hipótesis falsables que alimentan T1.4.

**Contexto actual:** existen `build_session_retrospective_report` y `build_walk_forward_validation_report` (`counterfactual_analysis.py`), el comando `missed-opportunities`, `post_market_review.py` y la tabla `continuous_improvement_hypotheses`. Pero el resultado son informes, no hipótesis accionadas.

**Cambios:**

1. Crear `src/agente_bolsa/tools/nightly_retrospective.py`:
   - `collect_evidence(store, settings, session_date) -> dict`: empaquetar pérdidas del día (de `signal_outcomes` con verdict negativo), misses (lógica de `missed_opportunities` del CLI, extraída a función reutilizable), top ganadores no comprados, y el contexto de mercado de cada caso.
   - `generate_hypotheses(evidence) -> list[dict]`: llamada LLM rol `deep` con prompt (vía `prompt_store`, clave `nightly_retrospective`) que exige por hipótesis: `pattern_description`, `entry_rule` medible, `exit_rule`, `invalidation`, `expected_improvement`, `evidence_refs` (ids de señales concretas). Descartar las que no citen ≥3 casos de evidencia (gate determinista anti-fabulación).
   - Deduplicación contra hipótesis existentes con `initiative_topic_key`/`proposal_fingerprint` de `continuous_improvement/agents.py` (ya existen).
   - Insertar en `continuous_improvement_hypotheses` con prioridad por nº de casos de evidencia.
2. Nuevo job en `scheduler.py`: `nightly_retrospective_job`, tras `post_market_review_job` (encadenar, no cron separado, para garantizar orden). Encolar evento al laboratorio (`runtime.enqueue_event`) para que el siguiente tick procese las hipótesis nuevas.
3. CLI: `retrospective --date YYYY-MM-DD --json` para ejecución manual.

**Medición:** hipótesis generadas/día; % que sobreviven a backtest; % que llegan a estrategia ACTIVE (el embudo completo: pérdida → hipótesis → código → shadow → ACTIVE).

**Verificación:** `tests/test_nightly_retrospective.py` con LLM mock: día con 2 pérdidas y 1 miss produce hipótesis con evidence_refs válidos; hipótesis duplicada se descarta; día sin actividad no genera nada.

**Aceptación:** cada mañana hay hipótesis nuevas trazables a operaciones concretas de ayer, y entran solas al pipeline de construcción.
**Rollback:** desactivar el job (`NIGHTLY_RETROSPECTIVE_ENABLED`).

### T2.4 — Memoria de largo plazo destilada

**Objetivo:** que las lecciones acumuladas (qué funciona en qué régimen) se compriman y se inyecten en los prompts de decisión, en vez de perderse en JSONL.

**Contexto actual:** `continuous_improvement/memory.py` (`SharedMemory`), `continuous_improvement_memories`, `learning_observations`, `trade_memory` y `context_compaction.py`. La decisión de trading ya recibe digests (`_compact_daily_learning_for_prompt` en `trade_decision.py`) pero son de corto plazo.

**Cambios:**

1. Tabla `distilled_lessons`: `(lesson_id, scope [setup|regime|symbol|sector|process], statement, supporting_cases int, contradicting_cases int, confidence float, status [ACTIVE|WEAKENED|RETIRED], last_validated_at, source_refs JSON)`.
2. Crear `continuous_improvement/lesson_distiller.py`:
   - Semanal (engancharlo al `weekly-review` o job propio domingo): leer outcomes de las últimas N semanas agrupados por setup/régimen (reutilizar `_setup_key`, `_combo_key` y buckets de `signal_learning.py`), pedir al LLM `deep` la destilación a ≤ `MAX_ACTIVE_LESSONS` (default 40) lecciones, con validación determinista: toda lección debe ser verificable contra los números agregados que se le pasaron (incluir los números en `source_refs`).
   - Re-validación: cada semana, recalcular supporting/contradicting de lecciones ACTIVE con los outcomes nuevos; confidence baja → WEAKENED → RETIRED. Las lecciones mueren si los datos dejan de apoyarlas.
3. Inyección: en `trade_decision._llm_prompt_payload`, añadir bloque `lecciones_validadas` con las top-K lecciones ACTIVE relevantes al candidato (match por setup/régimen/sector), cap 600 tokens vía `context_compaction`.
4. CLI: `lessons --json`, `lessons --retire <id>`.

**Medición:** ¿las decisiones alineadas con lecciones ACTIVE tienen mejor expectancy que las contrarias? Añadir esa comparación a `learning-digest`.

**Verificación:** `tests/test_lesson_distiller.py`: destilación con datos sintéticos produce lecciones con refs correctas; lección contradicha pierde confidence; inyección respeta el cap de tokens.

**Aceptación:** el prompt de decisión contiene conocimiento acumulado y auto-corregible del propio historial.
**Rollback:** no inyectar el bloque (`LESSONS_INJECTION_ENABLED=false`).

---

## ETAPA 3 — Comprensión del mercado (paralelizable con Etapa 2)

### T3.1 — Contexto macro continuo y tesis de mercado viva

**Objetivo:** que el sistema lea el mercado como un gestor: calendario económico, Fed, earnings de la semana, titulares amplios — no solo noticias por símbolo.

**Contexto actual:** `news_sentiment.py` descarga noticias por símbolo (FMP/yfinance); `market_state.py` calcula régimen técnico; el agente `macro_news_researcher` existe en `agents.yaml` pero solo participa en el estudio nocturno.

**Cambios:**

1. Crear `src/agente_bolsa/tools/macro_context.py`:
   - `fetch_macro_events(settings) -> list[dict]`: calendario económico (FMP tiene endpoint `economic_calendar`; fallback: lista vacía con flag de calidad), earnings de la semana del universo (FMP `earning_calendar`), y titulares generales de mercado (FMP `stock_news` sin símbolo o `general_news`). Cachear con el mismo patrón de `data/cache/market_data/`.
   - `build_market_thesis(store, settings) -> dict`: LLM rol `deep` una vez al día (con mercado cerrado) sobre: macro events próximos 5 días, market_state, performance reciente del sistema y la tesis anterior. Salida JSON: `stance` (risk_on|neutral|risk_off), `key_risks`, `key_catalysts`, `sector_bias`, `confidence`, `changes_vs_previous`. Persistir en tabla `market_thesis` (`thesis_date PK, payload, stance, confidence`).
2. Integración: añadir `market_thesis` al payload de `market_state.py` (campo `thesis`) y al prompt de `trade_decision` (compactado). Regla determinista (no LLM): si `stance=risk_off` con `confidence>0.7`, multiplicar el límite de compras diarias (`_effective_daily_buy_limit` en `trade_decision.py`) por `RISK_OFF_BUY_FACTOR` (default 0.5).
3. Job diario `macro_thesis_job` en `scheduler.py` antes del estudio de mercado cerrado.
4. CLI: `market-thesis --latest --json`.

**Medición:** ¿el stance predice? Correlación stance vs retorno SPY a 5 días, registrada en `performance_daily`; precisión direccional de la tesis.

**Verificación:** `tests/test_macro_context.py` (fetch mockeado, tesis con LLM mock, regla risk_off reduce el límite de compras).

**Aceptación:** cada día de mercado hay una tesis fechada, versionada, con su precisión histórica medible.
**Rollback:** `MACRO_THESIS_ENABLED=false`; el campo `thesis` ausente no rompe nada (acceso defensivo).

### T3.2 — Fábrica de hipótesis + granja de backtests en lote

**Objetivo:** explorar sistemáticamente el espacio de variantes: cada noche, decenas de hipótesis baratas se backtestan en lote y solo las supervivientes consumen atención del pipeline caro (T1.4).

**Contexto actual:** `tools/backtest.py` (`build_symbol_backtest`), `counterfactual_analysis.py` (walk-forward), hipótesis una a una vía laboratorio.

**Cambios:**

1. Crear `src/agente_bolsa/tools/hypothesis_factory.py`:
   - `generate_variants(store, settings) -> list[dict]`: producir variantes PARAMÉTRICAS (sin LLM, baratas) de las estrategias ACTIVE y de las hipótesis de T2.3: mallas sobre umbrales (score mínimo, RSI máx, distancia SMA20, ATR stop multiple, holding days) acotadas a ±30% del valor vigente, máximo `FACTORY_MAX_VARIANTS_PER_NIGHT` (default 50).
   - `run_batch(variants) -> list[dict]`: para cada variante, backtest vectorizado sobre el universo cacheado (reutilizar `build_symbol_backtest` y los datos de `data/cache/market_data/`) con costes/slippage de `tools/costs.py`, split temporal: in-sample hasta hace 6 meses, out-of-sample los últimos 6. Paralelizar con `concurrent.futures` cap `FACTORY_WORKERS` (default 4).
   - Filtro de supervivencia determinista: Sharpe OOS > 0.8, ≥30 trades, profit factor > 1.3, drawdown < 20%, y mejora ≥10% sobre la variante vigente. Corrección por múltiples comparaciones: exigir además que la mejora se mantenga en 3 sub-períodos de la OOS (guard anti data-mining).
   - Supervivientes → insertar como hipótesis de alta prioridad en `continuous_improvement_hypotheses` (las paramétricas van directas a `AutoApplyConfigAgent`/`adaptive_tuning` si el target está en su allowlist; las estructurales a T1.4).
2. Job nocturno `hypothesis_factory_job` (después de T2.3; presupuesto de tiempo `FACTORY_MAX_MINUTES`, default 60, con corte limpio).
3. Tabla `factory_runs` (resumen por noche: variantes, supervivientes, mejores métricas) y CLI `factory-status --json`.

**Medición:** supervivientes/noche; % de supervivientes que confirman en shadow (mide cuánto sobreajuste se cuela); mejora acumulada de parámetros vigentes.

**Verificación:** `tests/test_hypothesis_factory.py`: malla genera variantes acotadas; filtro rechaza variante con 5 trades; guard de sub-períodos rechaza mejora inestable; presupuesto de tiempo corta limpio.

**Aceptación:** cada mañana el laboratorio despierta con una cola priorizada de mejoras pre-validadas cuantitativamente.
**Rollback:** desactivar el job.

### T3.3 — Estudio de figuras ampliado y auto-evaluado

**Objetivo:** que el reconocimiento de figuras (velas y chartismo) se mida a sí mismo y pondere cada patrón por su acierto real histórico, no por teoría.

**Contexto actual:** `chart_patterns.py` y patrones de velas en `technical_analysis.py`; los patrones suman/restan score fijo. `signal_outcomes` ya guarda features con patrones (`_chart_pattern_summary` en `signal_learning.py`).

**Cambios:**

1. Crear `tools/pattern_scorecard.py`: `build_pattern_scorecard(store) -> dict`: por patrón y régimen, calcular sobre outcomes madurados: nº ocurrencias, hit rate, expectancy, lift vs señales sin el patrón. Persistir en report `pattern_scorecard_<date>.json` + tabla `pattern_stats`.
2. En el scoring de candidatos (`technical_study.py` / `technical_state_validator.py`): sustituir los pesos fijos de patrones por peso dinámico = `base_weight × lift_observado` (acotado [0, 2×base]), con fallback al peso fijo si <30 ocurrencias. El mapa de pesos se lee de `pattern_stats`, así `adaptive_tuning`/el laboratorio pueden razonarlo.
3. Mensual: si un patrón tiene lift < 0.8 con ≥50 casos, el sistema lo degrada a peso 0 y emite evento `pattern_retired` (reversible si el lift se recupera).

**Medición:** lift por patrón; mejora del hit rate global tras activar pesos dinámicos (comparar 20 sesiones antes/después vía `performance_daily`).

**Verificación:** `tests/test_pattern_scorecard.py` (cálculo de lift correcto con datos sintéticos; fallback con pocas muestras; retiro y recuperación).

**Aceptación:** los patrones que no funcionan dejan de influir solos; los que funcionan pesan más.
**Rollback:** `PATTERN_DYNAMIC_WEIGHTS_ENABLED=false`.

---

## ETAPA 4 — Gobierno por presupuesto de riesgo y camino a live

### T4.1 — Presupuesto de riesgo como única correa

**Objetivo:** sustituir la maraña de límites finos por un contrato simple: los agentes hacen LO QUE QUIERAN mientras el riesgo agregado quepa en el presupuesto; el kernel corta si se viola.

**Contexto actual:** decenas de settings de gates finos (ver los `entry_quality_fallback_*` en `config.py`); `risk.py` valida por orden; los agentes ya pueden tunear muchos umbrales vía `adaptive_tuning`/`AutoApplyConfigAgent`.

**Cambios:**

1. Crear `src/agente_bolsa/risk_budget.py`:
   - `RiskBudget`: `daily_var_budget_pct` (riesgo total comprometido en stops abiertos / equity, default 3%), `max_new_risk_per_day_pct` (1.5%), `max_correlated_cluster_pct` (riesgo en posiciones del mismo sector, 1.2%).
   - `consume(plan) / release(closed_position) / available() -> dict`. Persistir el estado en `runtime_state`.
2. En `trade_decision.py` y `execution.py`: las compras consultan `available()` en vez de (no además de) la mayoría de gates finos de cantidad — los gates de CALIDAD se mantienen, los de CANTIDAD se subsumen. Marcar los settings subsumidos como deprecated en `.env.example`.
3. El presupuesto es tuneable por los agentes DENTRO de los límites del kernel (T0.1): `risk_budget ≤ kernel.absolute_*`. Añadir los tres parámetros al `ALLOWED_TARGETS` de `AutoApplyConfigAgent`.
4. Adaptativo: tras `CHANGE_WATCHDOG` limpio y `iq_score` creciente 20 sesiones, el laboratorio puede proponer +10% de presupuesto (cap kernel); tras una semana mala, el watchdog lo recorta −25% automáticamente (función `risk_budget_throttle` en `change_watchdog.py`).

**Medición:** utilización del presupuesto; PnL por unidad de riesgo consumida (retorno sobre VaR usado) — esta pasa a ser la métrica de eficiencia en `performance_daily`.

**Verificación:** `tests/test_risk_budget.py`: consumo/liberación correctos; compra que excede presupuesto bloqueada; throttle reduce tras pérdidas; kernel siempre manda.

**Aceptación:** los agentes deciden tamaño y frecuencia con libertad real, y el sistema sigue siendo incapaz de arruinarse más allá del kernel.
**Rollback:** `RISK_BUDGET_ENABLED=false` reactiva los gates finos (mantener el código de ambos caminos una versión).

### T4.2 — Dashboard de autonomía y freno humano

**Objetivo:** el humano observa, no aprueba. Una vista única de qué ha cambiado el sistema, por qué, y un botón rojo.

**Cambios:**

1. En `web_app.py`, pestaña "Autonomía": nivel de autonomía vigente (T1.1), cambios aplicados/revertidos (de `continuous_improvement_applied_changes`), promociones en curso (T1.3), agentes dinámicos y su score (T2.2), lecciones top (T2.4), tesis de mercado (T3.1), iq_score y equity vs SPY (T0.2).
2. Botón "PAUSA TOTAL": activa el kill switch existente de `operational_health.py` + congela el laboratorio (`CONTINUOUS_IMPROVEMENT_ENABLED` en runtime_state) + cancela órdenes abiertas vía `broker.py`. Y botón "reanudar" con confirmación.
3. Digest diario por email/archivo: `tools/ops_reports.py` ya genera informes; añadir `build_autonomy_digest()` con: qué cambió ayer, qué se promovió, qué se revirtió, hipótesis nuevas, métricas. Guardarlo en `data/reports/autonomy_digest_<date>.md`.

**Verificación:** `tests/test_web_app.py` (extender) + prueba manual del kill switch end-to-end en paper.

**Aceptación:** puedes entender en 2 minutos qué hizo el sistema ayer y pararlo todo con un clic.
**Rollback:** UI aditiva, sin riesgo.

### T4.3 — Camino a live con capital progresivo

**Objetivo:** transición a dinero real gobernada por evidencia, irreversiblemente prudente.

**Contexto actual:** `tools/live_readiness.py` ya existe con checks; `ALLOW_LIVE_TRADING=false` y kernel `live_trading_locked`.

**Cambios:**

1. Ampliar `live_readiness.py` con criterios automáticos verificables: ≥60 sesiones de paper con el ciclo autónomo completo activo (etapas 1-3), alpha_vs_spy acumulado > 0, Sharpe 60 sesiones > 0.8, max drawdown < 12%, watchdog con <10% de rollbacks, 0 violaciones de kernel. `live-readiness --json` muestra el semáforo por criterio.
2. El desbloqueo live SIEMPRE es humano y doble: editar `.env` (`ALLOW_LIVE_TRADING=true`) + comando `kernel-unlock-live` que exige confirmación interactiva y re-sella el manifest. Los agentes no pueden hacerlo (T0.1 lo garantiza).
3. Escalado de capital codificado en kernel: live empieza con `LIVE_CAPITAL_FRACTION=0.10` del capital; cada 20 sesiones live con métricas ≥ paper, el HUMANO puede subir la fracción (el sistema solo lo recomienda en el digest). Cualquier semana con pérdida > 3% recorta la fracción a la mitad automáticamente (esto sí es automático: reducir riesgo nunca requiere aprobación).

**Aceptación:** live solo ocurre tras evidencia prolongada, con capital pequeño y des-escalado automático.

---

## ETAPA 5 — Robustez de trading: edge, estadística y realismo

Propósito: las etapas 0-4 construyen la máquina autónoma; esta etapa corrige los puntos débiles que deciden si la máquina gana dinero o automatiza una estrategia mediocre. Surge de la auditoría post-implementación (2026-06). Prioridad: T5.1 y T5.8 antes que nada; el resto en el orden listado.

### T5.1 — Validación del edge base (modo congelado)

**Objetivo:** demostrar que la estrategia semilla tiene edge ANTES de dejar que la autonomía la optimice. Si el base no bate a benchmarks ingenuos, hay que cambiar la semilla, no el proceso.

**Contexto actual:** `performance_daily` (T0.2) mide alpha vs SPY, pero nada impide que el laboratorio mute el sistema mientras se intenta medir el edge base. No existe benchmark de momentum simple.

**Cambios:**

1. Setting `SYSTEM_FREEZE_MODE` (bool, default false, alias en `.env.example`). Con freeze activo: `AutoApplyCodeAgent.try_apply` y `AutoApplyConfigAgent.try_apply` devuelven `BLOCKED` con razón `system_freeze`; `PromotionManager.start_shadow/evaluate_windows` no abre ni resuelve ventanas; `adaptive_tuning.update_adaptive_config` rechaza cambios. El laboratorio SÍ sigue generando hipótesis y reports (aprende sin tocar).
2. Crear `src/agente_bolsa/tools/naive_benchmarks.py`: simular a diario, con los mismos datos cacheados y costes de `tools/costs.py`, dos benchmarks: `spy_buy_hold` y `naive_momentum` (comprar los 5 símbolos con mayor `return_20d` del S&P 500, rebalanceo semanal, mismo sizing por riesgo). Persistir sus retornos diarios en `performance_daily` (columnas o payload `benchmarks`).
3. En `performance_baseline.py`: añadir `edge_report(store, sessions=60) -> dict` con: alpha vs SPY, alpha vs naive_momentum, t-stat de la media de retornos diferenciales, y veredicto `EDGE_CONFIRMED | EDGE_WEAK | NO_EDGE` (t-stat > 2 / entre 1 y 2 / < 1).
4. CLI `edge-report --sessions 60 --json`. Mostrar veredicto en el panel de autonomía de `web_app.py`.
5. Regla operativa documentada en README: freeze activo hasta `EDGE_WEAK` como mínimo; con `NO_EDGE` tras 60 sesiones, la acción es reformular la estrategia semilla (`strategies/builtin_breakout.py`), no activar la autonomía.

**Medición:** el propio `edge_report`.
**Verificación:** `tests/test_naive_benchmarks.py` (retornos sintéticos → t-stat y veredicto correctos; freeze bloquea apply/promoción/tuning con razón `system_freeze`).
**Aceptación:** se puede afirmar con un número si el sistema base tiene edge frente a no hacer nada y frente a momentum trivial.
**Rollback:** `SYSTEM_FREEZE_MODE=false`.

### T5.2 — Disciplina estadística: deflated Sharpe y change budget

**Objetivo:** que la fábrica y las promociones no industrialicen el sobreajuste, y que el watchdog pueda atribuir causa.

**Contexto actual:** `hypothesis_factory.py` genera hasta 50 variantes/noche con filtro de sub-períodos; `promotion.py` usa ventanas de 10 sesiones / 20 señales; no hay límite de promociones simultáneas.

**Cambios:**

1. En `hypothesis_factory.py`: añadir `deflated_sharpe(sharpe, n_trials, n_obs, skew, kurt) -> float` (fórmula de Bailey & López de Prado: ajustar el Sharpe observado por el nº de variantes probadas esa noche y la longitud de la muestra). El gate de supervivencia pasa a exigir `deflated_sharpe > 0` con `n_trials` = variantes probadas en la misma tanda. Registrar `n_trials` en `factory_runs`.
2. En `promotion.py`: subir defaults `PROMOTION_MIN_SESSIONS=25`, `PROMOTION_MIN_SIGNALS=40`, `PROMOTION_MAX_SESSIONS=45`; añadir al criterio un test binomial simple del hit rate del challenger vs el del champion (promoción solo si p < 0.10 además de las condiciones existentes).
3. Change budget: setting `MAX_CONCURRENT_PROMOTIONS` (default 2) y `MAX_PROMOTIONS_PER_WEEK` (default 1 a ACTIVE). `PromotionManager.start_shadow` encola (status `QUEUED`) si se excede; `evaluate_windows` respeta el cupo semanal de paso a ACTIVE. Así toda ventana del watchdog tiene como máximo 1-2 cambios que evaluar.
4. En `change_watchdog.py`: registrar el régimen de mercado (`market_state`) en cada evaluación pre/post, y no comparar ventanas de regímenes distintos (extender la ventana en su lugar).

**Medición:** % de promociones revertidas por el watchdog (debe bajar); supervivientes de fábrica que confirman en shadow (debe subir).
**Verificación:** `tests/test_hypothesis_factory.py` y `tests/test_promotion.py` ampliados: deflated Sharpe penaliza correctamente con n_trials alto; cupo de promociones encola; binomial rechaza challenger con ventaja no significativa.
**Aceptación:** ningún cambio llega a ACTIVE sin significancia ajustada por búsqueda múltiple, y nunca hay más de 2 cambios en vigilancia simultánea.
**Rollback:** restaurar defaults anteriores por settings.

### T5.3 — Desacoplar iq_score de la actividad del laboratorio

**Objetivo:** eliminar el incentivo Goodhart: hoy el `iq_score` premia el % de propuestas promovidas, así que "promover más" sube la nota sin ganar más.

**Contexto actual:** `performance_baseline.py::_lab_promotion_quality` puntúa promociones; `system_iq_score` la pondera al 15%.

**Cambios:**

1. Redefinir `_lab_promotion_quality`: una promoción solo suma si su ventana post (medida por el watchdog) mejoró PnL/expectancy; resta si fue revertida; las promociones sin ventana resuelta no cuentan. Fuente: `continuous_improvement_applied_changes` + evaluaciones del watchdog.
2. Separar en el payload de `performance_daily` dos bloques: `result_metrics` (alpha, Sharpe, drawdown, expectancy) y `process_metrics` (promociones, hipótesis, rollbacks). El `iq_score` se calcula SOLO con result_metrics + la calidad de promoción corregida.
3. En `autonomy_digest.py`: mostrar ambos bloques por separado con etiqueta explícita "el proceso no es el resultado".

**Verificación:** `tests/test_performance_baseline.py` ampliado: promover 10 cambios neutros no mueve el iq_score; un cambio revertido lo baja.
**Aceptación:** la única forma de subir iq_score es mejorar resultados de trading.
**Rollback:** revertir la fórmula (función pura, cambio aislado).

### T5.4 — Lecciones como hipótesis, no como verdad

**Objetivo:** que las lecciones destiladas de muestras pequeñas no contaminen el prompt de decisión como si fueran conocimiento validado.

**Contexto actual:** `lesson_distiller.py` destila lecciones con supporting/contradicting cases y las inyecta vía `_lessons_block_for_prompt` en `trade_decision.py`.

**Cambios:**

1. En `lesson_distiller.py`: toda lección nace con status `HYPOTHESIS`. Solo pasa a `ACTIVE` (inyectable en prompt) si: `supporting_cases >= 30`, intervalo de confianza Wilson del 90% del hit rate asociado no cruza el hit rate base del sistema, y la fábrica (T3.2) confirmó la regla derivada en backtest OOS. Añadir campo `derived_variant_id` que enlaza la lección con la variante de fábrica que la testea.
2. Pipeline: al crear una lección `HYPOTHESIS`, generar automáticamente su variante testeable y encolarla en `hypothesis_factory` (función `lesson_to_variant(lesson) -> dict`). Resultado del test → promoción o `RETIRED`.
3. `_lessons_block_for_prompt`: filtrar a status `ACTIVE` (ya filtra; verificar) y añadir al bloque el n y el intervalo de confianza de cada lección para que el LLM pondere.

**Medición:** % de lecciones HYPOTHESIS que sobreviven al test (esperable <30%; si es >70%, el gate es débil).
**Verificación:** `tests/test_lesson_distiller.py` ampliado: lección con n=12 no llega a ACTIVE; Wilson CI calculado correctamente contra valores conocidos.
**Aceptación:** ninguna afirmación llega al prompt de decisión sin n suficiente y test OOS aprobado.
**Rollback:** `LESSONS_INJECTION_ENABLED=false`.

### T5.5 — Realismo de ejecución: slippage, limit orders y costes calibrados

**Objetivo:** que el paper deje de mentir: fills castigados, gaps controlados y costes calibrados con fills reales.

**Contexto actual:** órdenes market (bracket) vía `execution.py`; el estudio es nocturno y la compra ocurre a la apertura siguiente (gap sin control); `tools/costs.py` usa bps fijos.

**Cambios:**

1. Slippage sintético en paper: en `signal_learning.py::_outcome_for_signal` y en la maduración de fills, aplicar penalización adversa configurable `PAPER_SYNTHETIC_SLIPPAGE_BPS` (default 10) + media horquilla estimada por ATR. Registrar PnL bruto y neto-de-slippage en `signal_outcomes`.
2. Limit orders con techo de gap: en `build_buy_order_plans`/`build_order_plans` (`trade_decision.py`), añadir `limit_price = entry_price × (1 + MAX_ENTRY_GAP_PCT)` (default 1.5%); en `execution.py::build_market_order_request`, soportar `LimitOrderRequest` cuando `USE_LIMIT_ENTRIES=true` (default true en paper). Si el gap de apertura supera el techo, la orden no se llena y se cancela al final del día (`time_in_force=day`) — eso ES el comportamiento deseado.
3. Calibración de costes: crear `tools/cost_calibration.py` que compara mensualmente los fills reales de Alpaca (`broker_orders` + `trade_memory`) contra los precios teóricos de señal y actualiza los bps de `costs.py` vía `adaptive_tuning` (target nuevo en su allowlist). El backtest y la fábrica consumen los bps calibrados.

**Medición:** gap medio señal→fill; diferencia PnL bruto vs neto; deriva de los bps calibrados.
**Verificación:** `tests/test_execution.py` y `tests/test_signal_learning.py` ampliados: limit respeta el techo; outcome neto < bruto; calibración con fills sintéticos produce bps esperados.
**Aceptación:** los backtests, el paper y la promoción usan los mismos costes realistas; las entradas con gap excesivo no se ejecutan.
**Rollback:** `USE_LIMIT_ENTRIES=false`, `PAPER_SYNTHETIC_SLIPPAGE_BPS=0`.

### T5.6 — Sesgo de supervivencia en backtests

**Objetivo:** dejar de backtestear el pasado con los ganadores del presente.

**Contexto actual:** `universe.py` carga el S&P 500 actual; la fábrica y los backtests lo usan para todo el histórico.

**Cambios:**

1. En `universe.py`: función `universe_as_of(date) -> list[str]` con constituyentes históricos. Fuente: dataset estático embebido `data/universe/sp500_changes.csv` (cambios de composición públicos; incluir instrucciones de actualización en docs) con fallback al universo actual + flag `survivorship_biased=true`.
2. `tools/backtest.py` y `hypothesis_factory.py`: usar `universe_as_of` en cada fecha simulada cuando el dataset esté disponible; propagar el flag de sesgo al report.
3. Mientras el flag sea true, los gates de la fábrica y promoción aplican un haircut: exigir +25% en los umbrales de Sharpe/profit factor (setting `SURVIVORSHIP_HAIRCUT`, default 0.25).

**Verificación:** `tests/test_reporting_and_universe.py` ampliado: `universe_as_of` resuelve composición en fechas con cambios conocidos del CSV; haircut se aplica con flag true.
**Aceptación:** ningún backtest informa métricas sin declarar si su universo es point-in-time.
**Rollback:** fallback automático ya incluido.

### T5.7 — Cash activo y estrategias por régimen

**Objetivo:** romper la dependencia del régimen alcista: que estar fuera del mercado sea una decisión, y que existan estrategias para rango y caída.

**Contexto actual:** long-only breakout; `market_thesis` solo recorta el límite de compras (factor 0.5 en risk_off).

**Cambios:**

1. Cash como posición: nueva pseudo-estrategia `strategies/cash_allocation.py` que emite una señal diaria `target_cash_pct` en función de régimen (`market_state`), tesis y drawdown rodante. `portfolio_optimizer.py` la respeta como restricción dura (no comprar si la caja objetivo no lo permite; vender lo más débil si se excede). Settings `CASH_FLOOR_RISK_OFF` (default 0.60), `CASH_FLOOR_NEUTRAL` (0.25).
2. Encargo permanente a la fábrica: en `hypothesis_factory.py::generate_variants`, etiquetar cada variante con el régimen objetivo y reservar cuota mínima (`FACTORY_REGIME_QUOTA`, default 30%) para variantes de régimen lateral/bajista (mean-reversion, pullback-to-support, calidad defensiva). El registro de estrategias (T1.2) gana campo `target_regime`; el pipeline solo activa señales de estrategias cuyo `target_regime` coincide con el régimen vigente.
3. Shorts: mantener desactivados en producción; permitir SHADOW-only (señales cortas maduran en `signal_outcomes` con `shadow=1`) para acumular evidencia sin riesgo (`SHORTS_SHADOW_ENABLED`, default true).

**Medición:** PnL y drawdown por régimen en `performance_daily` (desglose nuevo); % de sesiones risk_off con caja ≥ floor.
**Verificación:** `tests/test_portfolio_optimizer.py` y `tests/test_strategy_registry.py` ampliados: floor de caja bloquea compras; estrategia con `target_regime=range` no emite en régimen trend; shorts nunca generan order_plans.
**Aceptación:** en un backtest de régimen bajista sintético, el sistema termina mayoritariamente en cash en vez de comprar breakouts fallidos.
**Rollback:** floors a 0 y cuota de fábrica a 0%.

### T5.8 — Endurecer la auto-escritura (lección del incidente de truncamiento)

**Objetivo:** que la corrupción de archivos detectada en la implementación (12 archivos truncados/null bytes) sea estructuralmente imposible.

**Contexto actual:** el sandbox T0.3 existe, pero hubo escrituras directas; no hay CI remota obligatoria.

**Cambios:**

1. Única vía de escritura: eliminar de `AutoApplyCodeAgent` cualquier camino que escriba fuera del worktree del `GitSandbox`; `_apply_payload` falla si `workspace` es el repo principal.
2. Validación de integridad de escritura en `sandbox.py::apply`: tras escribir cada archivo, releerlo y verificar (a) sin bytes nulos, (b) `ast.parse` si es `.py`, (c) el contenido termina en newline y coincide byte a byte con lo solicitado. Fallo → abortar y destruir worktree.
3. CI remota: `.github/workflows/ci.yml` con `pytest -q` + `ruff check` + chequeo de bytes nulos en push y PR a la rama principal; documentar protección de rama (require status checks) en `docs/startup_runbook.md`.
4. Hook local `pre-commit` (archivo `.pre-commit-config.yaml` o script en `scripts/`): compilar con `ast` todo archivo staged y bloquear nulls.

**Verificación:** `tests/test_ci_sandbox.py` ampliado: payload con `\x00` → rechazado; payload `.py` truncado (SyntaxError) → rechazado antes de correr tests; intento de aplicar sobre el repo principal → RuntimeError.
**Aceptación:** un archivo corrupto no puede llegar ni siquiera a la fase de tests del sandbox, y nada llega a la rama principal sin CI verde.
**Rollback:** no aplica (es defensa pura).

### T5.9 — Presupuesto económico del laboratorio

**Objetivo:** que el coste de pensar no supere el valor de lo pensado.

**Contexto actual:** `llm_usage` registra uso por rol (T0.4); no hay límites de gasto.

**Cambios:**

1. Settings `LLM_DAILY_BUDGET_USD` (default 5.0) y `LLM_ROLE_DEEP_DAILY_BUDGET_USD` (default 3.0); tabla de precios por modelo en `llm_usage.py` (editable por settings `LLM_PRICE_PER_MTOKEN_<MODEL>`).
2. En `llm_router.py::chat_for_role`: antes de cada llamada, consultar gasto acumulado del día; si excede el budget del rol, degradar a endpoint local; si excede el total, devolver error controlado `llm_budget_exhausted` que el laboratorio trata como "posponer tarea" (no como fallo).
3. En `autonomy_digest.py`: línea diaria "coste LLM vs PnL del día" y acumulado mensual.

**Verificación:** `tests/test_llm_router.py` ampliado: presupuesto agotado degrada a local; total agotado pospone; el contador se reinicia por día.
**Aceptación:** el gasto LLM diario está acotado y es visible junto al PnL.
**Rollback:** budgets a 0 = sin límite (default explícito en `.env.example` con advertencia).

### T5.10 — Huecos operativos: earnings en holds, splits y dividendos

**Objetivo:** cerrar las fuentes de pérdidas raras-pero-grandes que el hit rate no detecta.

**Contexto actual:** `pre_earnings.py` analiza entradas pre-earnings; nada vigila posiciones ABIERTAS que atraviesan resultados; la maduración de outcomes no ajusta por splits/dividendos.

**Cambios:**

1. Guard de holds: en `scheduler.py` (junto a `_run_open_position_news_guard`), nuevo check diario `_earnings_hold_guard`: si una posición abierta tiene earnings en ≤ `EARNINGS_HOLD_MAX_DAYS` (default 2) días, decisión determinista por defecto = reducir 50% o cerrar si el PnL no-realizado < 0 (`EARNINGS_HOLD_POLICY=reduce|exit|hold`, default reduce). El LLM puede argumentar mantener, pero solo con la excepción objetiva de `_is_exceptional_llm_exit` invertida (evidencia positiva concreta).
2. Ajuste corporativo: en `signal_learning.py::update_signal_outcomes`, detectar splits comparando saltos de precio >40% con factor entero/medio del proveedor (yfinance/FMP entregan `splits`); ajustar entry/stop/take retroactivamente y marcar `corporate_action_adjusted=1`. Dividendos: sumar al PnL del outcome si el proveedor da `dividends` en la ventana.
3. Halts/datos congelados: si un símbolo en cartera no imprime barra nueva en 2 sesiones de mercado, evento `possible_halt` + excluirlo de señales nuevas hasta normalizar.

**Verificación:** tests con series sintéticas: split 2:1 no se contabiliza como -50% de pérdida; posición con earnings mañana genera plan de reducción; símbolo sin barras dispara `possible_halt`.
**Aceptación:** ningún outcome histórico queda distorsionado por acciones corporativas y ninguna posición atraviesa earnings sin decisión explícita.
**Rollback:** `EARNINGS_HOLD_POLICY=hold` y flags de ajuste desactivables.

### T5.11 — Diversidad real del comité

**Objetivo:** que el comité de agentes no sea un solo modelo con doce sombreros.

**Contexto actual:** todos los agentes LLM comparten modelo base (local o Gemini según entorno); el README ya advierte que la unanimidad no es independencia.

**Cambios:**

1. Asignación de modelos heterogéneos por rol vía los settings `LLM_ROLE_*` existentes (T0.4): al menos 2 proveedores distintos entre `decision` y `deep` cuando haya claves disponibles; documentar la matriz recomendada en `.env.example`.
2. En las votaciones del comité (`DecisionCommitteeAgent`): registrar qué modelo emitió cada dictamen (`model_id` en el payload) y calcular un índice de correlación de votos por par de modelos en `autonomy_digest`. Si dos "expertos" coinciden >95% en 50 dictámenes, son redundantes: el digest lo señala.
3. Regla de peso: las señales deterministas (score técnico, gates, backtest) deciden; el consenso LLM solo puede VETAR o reducir tamaño, nunca originar una compra sin candidato determinista (verificar que `deterministic_trade_fallback_recommendations` y los gates ya lo garantizan; añadir test de invariante).

**Verificación:** test de invariante: ninguna recomendación BUY sin candidato en `technical_context`; correlación de votos calculada correctamente con dictámenes sintéticos.
**Aceptación:** una compra requiere evidencia determinista siempre; la diversidad del comité se mide en vez de asumirse.
**Rollback:** configuración de modelos reversible por settings.

## ETAPA 6 — Correcciones guiadas por los resultados reales (análisis 2026-06-10)

Propósito: la primera lectura de datos reales del sistema (abril-junio 2026) revela exactamente por qué no acierta más. Esta etapa convierte ese diagnóstico en cambios concretos. Es la etapa MÁS importante para "acertar más": ataca el edge, no la infraestructura.

### Diagnóstico con datos (fuentes: `learning_digest` 2026-06-05, `activity_funnel_analysis` 2026-05-27)

**El embudo está casi cerrado.** De 66.969 candidatos long fuertes (abr-may): 1.127 considerados por el LLM (1,68%), 31 aprobados, 14 ejecutados. El cuello NO son los gates de riesgo (41 bloqueos de calidad, 5 de backtest): es el ranking pre-LLM, que descarta el 98,3% antes de que nadie los mire, y la fase aprobada→ejecutada que pierde más de la mitad. Consecuencia mortal: con ~3 ejecuciones en el dataset de aprendizaje, el ciclo de mejora gira en vacío — no hay resultados de los que aprender.

**El universo de señales tiene expectancy negativa a 1 día.** Win rate ~26%, retorno medio -0,16% en casi todos los buckets. El setup dominante (`confirmed_pattern`, 18.700 señales) pierde dinero de media. PERO hay bolsillos de edge claros a 3 días: `score≥15` (41% win, +0,88%), `sma20_dist>12%` (51% win, +2,72%), `orderly_breakout` (56% win, +0,95%, solo 25 señales). El sistema genera mayoritariamente ruido y NO concentra sus pocas balas en los bolsillos donde sus propios datos muestran edge.

**El 90% de las observaciones son duplicados** (`duplicate_ratio=0.9014`): la misma señal re-contada ciclo tras ciclo infla los stats y contamina los priors.

**Qué hubiera estado bien tener desde el principio** (y las etapas 0-5 ya construyen): la serie `performance_daily` para ver el PnL real día a día, outcomes shadow por estrategia para aprender sin ejecutar, el edge report con t-stat, y throughput suficiente para acumular muestra. La lección general: se construyó el optimizador antes que el caudal de datos que lo alimenta.

### T6.1 — Reorientar la selección al edge observado

**Objetivo:** que el ranking pre-LLM (el cuello de botella real) puntúe con la evidencia de outcomes, no solo con el score técnico teórico.

**Cambios:**

1. En la selección determinista de candidatos (`_select_deterministic_candidates` y `_annotate_technical_context_with_learning` en `trade_decision.py`): el orden de prioridad pasa a ser `expected_edge` del prior de perfil (`setup_priors` del learning digest) cuando exista con `confidence_weight≥0.5`, y si no, el score técnico. Los buckets con expectancy negativa demostrada (p. ej. `score:lt12`) se penalizan explícitamente.
2. Cuota de concentración: al menos el 60% del cupo de candidatos al LLM debe ir a señales en bolsillos de edge observado (`score≥15`, `sma20_dist>12%`, setups con win rate ≥50% y n≥20). Setting `SELECTION_EDGE_POCKET_QUOTA` (default 0.6).
3. `confirmed_pattern` deja de ser setup por defecto puntuable positivo: su peso se liga al scorecard de patrones (T3.3), que con los datos actuales lo deja a ~0.

**Medición:** expectancy media de los candidatos que llegan al prompt (debe pasar de negativa a positiva); win rate de ejecutadas.
**Verificación:** test con digest sintético: candidato de bolsillo con edge desplaza a candidato de score alto sin edge.

### T6.2 — Alinear el horizonte de gestión con el edge (3 días)

**Objetivo:** el edge medido vive en el horizonte de 3 días; los outcomes a 1 día son ruido negativo. Stops, takes y maduración deben reflejarlo.

**Cambios:**

1. La maduración principal de `signal_learning` y los priors inyectados al LLM usan el horizonte 3d (hoy mezclan 1d/3d/5d con dominancia de 1d en buckets).
2. Time-stop por defecto a 3 sesiones (`EXIT_TIME_STOP_SESSIONS`, revisar el `exit_policy_v2` existente) salvo que el take/stop se toque antes; ATR-stop calibrado para sobrevivir el ruido de 1d (≥1.5×ATR).
3. El backtest gate y la fábrica evalúan con holding de 3 sesiones como caso base.

**Medición:** expectancy de ejecutadas a 3d; % de salidas por time-stop vs stop-loss.

### T6.3 — Abrir el caudal con presupuesto (de 2 a 5-8 decisiones/día)

**Objetivo:** sin muestra no hay aprendizaje ni convergencia: subir el throughput de forma controlada por el presupuesto de riesgo, y eliminar la pérdida aprobada→ejecutada (31→14).

**Cambios:**

1. Subir `trade_selection_top_n` y el límite de compras diarias hasta que el sistema tome 5-8 decisiones reales/día, con sizing reducido proporcionalmente (mismo riesgo total diario vía `risk_budget`): más muestras, no más riesgo.
2. Instrumentar la fase aprobada→ejecutada: cada plan aprobado no ejecutado debe registrar el motivo exacto (`order_plans.status` + razón) y `autonomy_digest` los lista. Arreglar las causas dominantes (timing de sesión, órdenes pendientes, flags).
3. Mantener TODOS los gates de calidad: el caudal sube por la cuota de bolsillos de edge (T6.1), no relajando calidad.

**Medición:** ejecutadas/día; outcomes maduradas/semana (objetivo: >25); ratio aprobada→ejecutada (objetivo: >90%).

### T6.4 — Deduplicación de señales

**Objetivo:** que el 90% de duplicados deje de contaminar stats y priors.

**Cambios:**

1. Fingerprint de señal en `signal_learning.record_signal_candidates`: `symbol + setup + nivel de entrada redondeado + fecha de la señal original`; re-detecciones del mismo nivel en ciclos posteriores actualizan la señal existente en vez de crear otra.
2. Migración suave: los stats (`learning_digest`, buckets, priors) cuentan señales únicas; añadir el campo `duplicate_of` para trazabilidad.

**Medición:** `duplicate_ratio` del digest (objetivo: <0.2).

### T6.5 — Primer challenger nacido de los datos: `edge_pocket_v1`

**Objetivo:** estrenar el ciclo completo champion/challenger con la estrategia que los propios datos del sistema señalan.

**Cambios:**

1. Crear `strategies/edge_pocket_v1.py`: long solo si `score≥15` Y (`sma20_dist` entre 6% y 20% O setup `orderly_breakout` confirmado) Y volumen confirmando (`volume_z>0`), horizonte 3 sesiones, stop 1.5×ATR, take 2.5×ATR.
2. Registrarla en SHADOW vía `PromotionManager.start_shadow("edge_pocket_v1")` y dejar que el ciclo (T1.3 + T5.2) decida con evidencia si destrona a `builtin_breakout`.
3. Si la promoción la confirma, será la primera mejora real del sistema cerrando el círculo: datos → diagnóstico → estrategia → shadow → promoción por métricas.

**Medición:** la propia ventana de promoción.

### Orden de la Etapa 6

T6.4 (limpia los datos) → T6.1 y T6.2 (redirigen la selección y el horizonte) → T6.3 (abre el caudal) → T6.5 (challenger formal). Todo en paper, con el watchdog vigilando cada paso.

## ETAPA 7 — Flujo del laboratorio: terminar trabajo, no acumularlo (IMPLEMENTADA 2026-06-10)

Diagnóstico: las iniciativas del laboratorio llevaban 7-8 días abiertas sin terminar. Tres causas en el código: (1) el ciclo de vida no tenía estados finales automáticos — nada pasaba de MONITORING/VALIDATING a CLOSED, y las iniciativas recurrentes (p. ej. `trading:market_regime`) se re-abrían en CADA evento; (2) las tareas con dependencias fallidas o nunca ejecutadas quedaban en WAITING_DEPENDENCY para siempre, sin TTL; (3) sin límite de WIP, el orquestador abría trabajo nuevo cada ciclo más rápido de lo que cerraba el viejo. Resultado: backlog creciente que parecía actividad pero no convergía en mejoras.

Implementación (hecha directamente, módulo `continuous_improvement/lifecycle.py` + ganchos):

- **TTL de tareas** (`sweep_stale_tasks`): tarea no terminal más vieja que `CI_TASK_TTL_HOURS` (48) → CANCELLED con motivo; sus dependientes en espera también (el trabajo previo no ocurrió).
- **Cierre con rendición de cuentas** (`resolve_initiatives`): iniciativa MONITORING sin tareas vivas e inactiva `CI_MONITORING_CLOSE_DAYS` (5) → CLOSED con `outcome` que compara `current_value` vs `baseline_value` de su `target_metric` (¿mejoró de verdad?).
- **Expiración de estancadas**: abierta > `CI_INITIATIVE_TTL_DAYS` (5) y sin avance `CI_INITIATIVE_STALL_DAYS` (3) y sin tareas vivas → REJECTED/EXPIRED. Puede reabrirse, pero solo con evidencia nueva.
- **Límite de WIP y cooldown** (en `orchestration._build_tasks`): máximo `CI_MAX_OPEN_INITIATIVES` (6) iniciativas activas — el resto de specs se descartan hasta que se cierre algo; una iniciativa activa con movimiento en las últimas `CI_RECURRING_COOLDOWN_HOURS` (24) no recibe un grupo nuevo de tareas, solo el enlace del evento como evidencia.
- **Gancho**: `run_lifecycle` corre al inicio de cada `run_once` del runtime (antes de planificar trabajo nuevo) y nunca bloquea el ciclo.
- **Visibilidad**: `collect_autonomy_state` expone `lab_flow` (WIP, edad de la iniciativa más vieja, tareas abiertas, resueltas en 7 días). La métrica de salud es simple: `oldest_open_days` debe dejar de crecer y `resolved_last_7d` debe ser > 0 cada semana.

Verificación: `tests/test_ci_lifecycle.py` (TTL y dependientes muertos; expiración por estancamiento; protección si hay tareas vivas; cierre MONITORING con outcome; flow report; idempotencia).

## 5. Orden de ejecución y dependencias

```
ETAPA 0:  T0.1 → T0.2 → T0.3 → T0.4 → T0.5     (secuencial, todo lo demás depende de ella)
ETAPA 1:  T1.1 → T1.2 → T1.3 → T1.4            (secuencial)
ETAPA 2:  T2.1 → T2.2                            (T2.3 y T2.4 tras T2.1; requieren T0.4)
ETAPA 3:  T3.1, T3.2, T3.3                       (paralelas entre sí; T3.2 requiere T1.2)
ETAPA 4:  T4.1 (tras Etapa 1) → T4.2 → T4.3 (tras 60 sesiones de todo lo anterior)
ETAPA 5:  T5.8 y T5.1 INMEDIATAS tras implementar 0-4 → T5.2, T5.3, T5.5 → resto en orden
```

Regla de ritmo: no empezar una etapa hasta que la anterior lleve ≥5 sesiones de mercado funcionando sin rollbacks del watchdog. La autonomía se gana con historial, igual que dentro del sistema (T1.1).

Nota sobre la Etapa 5 (estado: etapas 0-4 ya implementadas): el orden operativo recomendado es —

1. **T5.8 ya** (endurecer auto-escritura): el incidente de truncamiento demostró que es prerequisito de cualquier autonomía de código.
2. **T5.1 ya** (freeze + edge report): activar `SYSTEM_FREEZE_MODE=true` y empezar a acumular las 60 sesiones de medición del edge base. Esto corre en paralelo con todo lo demás porque es tiempo de calendario, no de desarrollo.
3. **T5.2, T5.3, T5.5** durante el período de freeze: disciplina estadística, iq_score honesto y realismo de ejecución estarán listos cuando el freeze se levante.
4. **T5.4, T5.6, T5.9, T5.10, T5.11** después, en ese orden.
5. **T5.7** (regímenes y cash) cuando haya veredicto del edge report: si el veredicto es `NO_EDGE`, T5.7 pasa a ser la prioridad absoluta porque el problema es la estrategia semilla.

## 6. Cómo se verifica "cada día más listo y rentable"

- **Rentable:** `alpha_vs_spy` acumulado y Sharpe 60 sesiones en `performance_daily` (T0.2), visibles en `performance --days 90`.
- **Más listo:** `iq_score` con tendencia positiva; embudo de aprendizaje sano (T2.3: hipótesis→estrategias ACTIVE); lecciones ACTIVE con lift confirmado (T2.4); % de promociones no revertidas creciente (T1.3 + T0.5).
- **Autónomo:** días consecutivos sin intervención humana (medirlo: evento `human_intervention` cada vez que se use un comando manual de override; contador en el digest).

Si tras 30 sesiones el `iq_score` no mejora, el plan tiene un mecanismo honesto de diagnóstico: el embudo de T2.3/T3.2 dice exactamente en qué fase mueren las mejoras (¿no se generan hipótesis? ¿no pasan backtest? ¿pasan backtest pero fallan en shadow? = sobreajuste). Atacar la fase con peor conversión antes de añadir nada nuevo.

Con la Etapa 5, la vara de medir definitiva es el `edge-report` (T5.1): alpha con t-stat frente a SPY y frente a momentum ingenuo, sobre costes realistas (T5.5), sin sesgo de supervivencia (T5.6) y con un iq_score que solo puede subir mejorando resultados (T5.3). "Cada día más listo y rentable" se traduce operativamente en: veredicto del edge report estable o mejorando trimestre a trimestre, drawdowns dentro del presupuesto, y un embudo de aprendizaje cuya tasa de conversión hipótesis→ACTIVE no se degrada.
