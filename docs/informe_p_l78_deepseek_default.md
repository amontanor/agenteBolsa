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
