# P-L78B — default global DeepSeek V4 Flash

## Dictamen

`ready_for_pl78b_closed_market_deployment` para el candidato aislado. El lote
queda preparado para un ensayo de integración y despliegue cerrado posterior;
no se ha integrado ni desplegado en producción.

## Alcance y causa

Fecha de validación: 2026-08-01, Europe/Madrid. XNYS estaba cerrado y la
próxima apertura persistida era 2026-08-03 15:30 CEST. La auditoría P-L78A
identificó que el runtime seleccionaba DeepSeek Flash en parte de la
configuración productiva, pero mantenía defaults de código Kimi y
`IMPROVEMENT_LLM_MODEL=glm-5.2`. Además, snapshots y `llm_usage` podían
reconstruir el modelo desde `settings.openai_model` en vez del endpoint usado.

La reproducción contra la base exacta falló en tres casos: Settings sin env,
la cadena de roles y codegen resolvían Kimi; tres pruebas de overrides
explícitos/fallback Qwen ya pasaban. Después del cambio, todas las pruebas de
contrato pasan.

## Referencias y Git

- Base: `ba7d488de5ddb2f0b1174b22ff676e5abba1ac1d`, tree
  `6938d15799c39d760035e1afc8294f614ece0b04`, versión 0.4.211.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl78b_deepseek_default`.
- Rama: `codex/pl78b-deepseek-default`.
- Commits funcionales y de QA: `5625b3b1` (caracterización), `c31e7079`
  (implementación y 0.4.212), `8ab06717` (alineación de version policy).
- El commit documental de este informe deja el candidato limpio en su HEAD
  final, que debe ser la única referencia a integrar mediante `merge --no-ff`.

La producción no se usó como área de trabajo y conserva HEAD/tree/versión
verificados por P-L78A. Sus untracked del operador (`.agents/skills/*`,
`.codex-remote-attachments/`, `.opencode/`, `opencode.json` y
`skills-lock.json`) no se copiaron ni tocaron.

## Contrato efectivo

La precedencia implementada es:

1. override explícito autorizado de operador/entorno;
2. override explícito de rol;
3. default global `opencode-go/deepseek-v4-flash`;
4. fallback técnico local Qwen ya existente;
5. fallback determinista/no-LLM de cada ruta.

GLM-5.2, Kimi y MiMo no son defaults ni fallbacks silenciosos. Siguen siendo
valores aceptables solo cuando una prueba, una opción de compatibilidad o un
override explícito los solicita. El historial de eventos que los contiene no
se reescribe. `MIMO_MODEL` conserva su valor específico cuando se selecciona
explícitamente el proveedor MiMo.

La identidad canónica por defecto es `opencode-go/deepseek-v4-flash`, con el
endpoint lógico ya existente `https://opencode.ai/zen/go/v1`. No se cambiaron
credenciales ni endpoints productivos.

## Rutas auditadas

| Ruta | Default/fuente tras el cambio | Fallback | Estado |
|---|---|---|---|
| primary, decision, sentiment y deep | selector `opencode-go`, DeepSeek Flash; role override explícito | Qwen local y luego fallback determinista | activo |
| CrewAI y agentes de decisión | endpoint/resolución central; identidad del endpoint real | fallback de decisión existente | activo |
| mejora continua, nightly, retrospective y strategy builder | `IMPROVEMENT_LLM_MODEL`/orchestrator DeepSeek Flash | Qwen/determinista según ruta | activo |
| lesson distiller, telegram radar, prompt replay y codegen | heredan la resolución de mejora/orquestador | fallback local/determinista existente | activo |
| health check y `.env.example` | DeepSeek Flash para el default OpenCode | no añade GLM | activo/documental |
| Kimi, MiMo y GLM en tests/UI | parámetros explícitos, compatibilidad o fixtures históricas | no son selección implícita | no-default |

La matriz no convierte al LLM en autoridad de gates, sizing, RiskManager,
planes, órdenes, exposición, límites, readiness, promoción o auto-apply.

## Identidad y telemetría

`LLMEndpoint` conserva provider, endpoint y modelo solicitado. El carrier
`llm_identity` publica `requested_model`, `effective_model`, `response_model`,
`fallback_used`, estado y razón sin secretos. `llm_usage`, snapshots de
decisión, `cycle_runner`, `main`, scheduler y eventos CrewAI consumen esa
identidad; ya no etiquetan una llamada de rol con `settings.openai_model`.

Cuando no existe endpoint efectivo, la identidad es `unavailable`, no una
etiqueta inventada. Los eventos y respuestas históricas no se reescriben.

Con la misma respuesta estructurada del LLM, la frontera económica permanece
igual: candidatos, scores/ranks, gates, sizing, microexperimentos, planes,
cantidades, precios, stops/takes, requests, exposición y límites no cambian.
Un error 403, timeout, JSON inválido o límite de tokens solo activa los
fallbacks existentes y no crea órdenes ni modifica control flow de trading.

## Validación

- Focales config/router/roles/decision/sentiment/CI/codegen/cycle/telemetría y
  regresiones: `317 passed`.
- Suite completa aislada con `DATA_DIR` temporal: `2370 passed, 1 skipped,
  1 warning` en `812.37 s`. El skip es preexistente; la warning es la
  deprecación externa de `websockets.legacy`.
- Ruff completo: OK.
- `scripts/check_no_nulls.py`: OK.
- Compilación aislada de `src` y `tests`: OK.
- `git diff --check`: OK.
- `validate-agent-config --json` temporal: `ok=true`, sin warnings.
- `kernel-status --json` temporal: `unsealed` sin manifiesto temporal y cero
  violaciones; no se ejecutó `kernel-seal`. El estado productivo/base del
  kernel fue contrastado separadamente y permanece sellado/OK.
- Smoke real aislado `run-once --skip-crew`: OK, con `DATA_DIR` temporal,
  `TRADING_MODE=paper`, live y auto-apply desactivados, LLM externo desactivado
  y sin proveedores reales. Devolvió ciclo temporal `20260801-115550`,
  `used_crew=false` y `market_state_quality=PARTIAL` por mercado cerrado.

La caracterización histórica lenta de 33.336 observaciones no se ejecutó como
batería separada: no es necesaria para este contrato y no se añadió carga
externa.

## Protección y límites

`config.py` fue modificado con la autorización explícita del operador solo
para los defaults de modelo. `kernel.py`, `tools/broker.py`,
`tools/execution.py`, `tools/risk.py` y `.env` son idénticos a la base por
objeto Git. `.env.example` sí se actualizó; el `.env` productivo no se
modificó en este lote. No hubo red, llamadas LLM reales, broker, yfinance,
Telegram, SQLite productiva, jobs, reinicio, despliegue ni push.

Siguiente paso único: en un turno separado y con mercado cerrado, integrar el
HEAD final de este candidato mediante `merge --no-ff`, repetir los gates de
despliegue, cambiar únicamente las claves de modelo/proveedor productivas
autorizadas y verificar doble salud. Este informe no autoriza por sí mismo esa
integración.

## P-L78C — `schedule-status` genuinamente read-only (0.4.213)

### Dictamen del candidato

`ready_for_pl78c_closed_market_integration`, pendiente de integrar en un
turno separado. La causa era que `main.command_schedule_status` llamaba a
`scheduler_status`, que a su vez ejecutaba `Store.ensure_schema()` y lecturas
mediante la conexión escribible. En una `DATA_DIR` inexistente la consulta
creaba directorios, SQLite y el esquema; con una base WAL, una conexión SQLite
URI read-only puede crear o modificar el sidecar `-shm` en Windows.

### Contrato implementado

- `scheduler_status` ya no llama `ensure_schema`, `connect`, migraciones ni
  escritores de `Store`.
- La lectura usa `Store.read_runtime_values`, `mode=ro` y
  `PRAGMA query_only=ON`, con la conexión cerrada en `finally`.
- Antes de abrir SQLite se comprueba existencia, cabecera WAL y sidecars. Si
  hay WAL o `-wal`/`-shm`, el estado runtime queda explícitamente
  `available=false, reason=wal_mode_or_sidecar_present`; no se arriesga una
  mutación para aparentar frescura. La base productiva usa precisamente este
  modo, por lo que su `job_runtime` será unavailable mediante esta interfaz
  hasta existir una lectura segura compatible.
- Base ausente devuelve `database_missing`; tabla/columnas incompatibles,
  payload inválido, acceso denegado y errores SQLite tienen razones estables.
  Calendario, horarios y lista estática de jobs se siguen publicando aunque el
  runtime no esté disponible; los valores de jobs son `null` en ese caso.
- Se acepta `schedule-status --json`; la salida existente continúa siendo JSON
  y no cambia calendario, cadencias, enablement ni scheduling efectivo.

### Evidencia y límites

La caracterización contra la base exacta reprodujo la creación de artefactos
en `DATA_DIR` inexistente y falló en siete casos de no-mutation. El candidato
prueba DB ausente, rollback-journal existente, WAL, esquema legacy/parcial,
errores de apertura, cierre de conexión, JSON estable y preservación de
calendario/jobs. Runtime unavailable por WAL es una decisión fail-closed, no
una afirmación de que los jobs estén detenidos.

La deriva productiva de `.env` que deja `kernel-status` en violation y el
despliegue pendiente de P-L78B no se tocaron ni se resuelven con este lote.
No se ejecuta `kernel-seal` ni se copia un manifiesto. El siguiente y único
paso de integración debe resolver primero la procedencia autorizada de `.env`
según P-L78C-AUDIT; después podrá ensayarse P-L78B junto con este cambio.

### Referencias y validación P-L78C

- Base: `95cfdc04ea7f5e6ccf4a6985dc55d6310b633fc9`, tree
  `0861b2fbef1e9a4627f21e5377dff60081c7904a`, versión 0.4.212.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl78c_schedule_status_readonly`.
- Rama: `codex/pl78c-schedule-status-readonly`.
- Commits: `cb664ae6` (caracterización), `d2c31225` (implementación y bump),
  `cb6aac67` (version policy), `36aed9b5` (CLI sin efectos laterales) y
  `227140c0` (settings CLI sin bootstrap de directorios).
- El candidato conserva como cambios funcionales únicamente la frontera
  read-only de runtime, el soporte CLI `--json` y el bump 0.4.213; las
  adaptaciones de tests solo reflejan que una base WAL no puede leerse sin
  riesgo de sidecar.
- Regresiones focales: `61 passed` en la batería ampliada; el focal P-L78C final
  quedó en `10 passed`.
- Suite completa aislada: `2380 passed, 1 skipped preexistente, 1 warning`
  externo en `807.81 s`. El skip es
  `tests/test_pre_earnings.py::test_score_study_regression_current_sqlite`,
  condicionado a disponer de la SQLite histórica local; no fue creado por
  este lote. La warning es la deprecación externa de `websockets.legacy`.
- Ruff completo, `scripts/check_no_nulls.py`, compilación y `git diff --check`:
  verdes. `validate-agent-config --json` aislado: `ok=true`, sin warnings.
  `kernel-status --json` aislado: `unsealed` esperado por falta de manifiesto
  temporal, con cero violaciones; no se ejecutó `kernel-seal`.
- Smoke `run-once --skip-crew` ejecutado mediante la misma frontera CLI con
  `DATA_DIR` temporal, `use_crew=false`, snapshot/estado de mercado fake y un
  proveedor broker que falla si es alcanzado: OK, ciclo temporal completado,
  `market_state_quality=PARTIAL`, sin red, broker ni LLM.
- Invocación real `schedule-status --json` sobre `DATA_DIR` inexistente:
  `database_missing`, `available=false` y el directorio no fue creado.
- `kernel.py`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py`,
  `config.py` y `.env` no son parte de este lote; producción, stack, SQLite
  productiva, jobs, broker, red, LLM, Telegram, locks, leases y untracked del
  operador permanecen intactos.
