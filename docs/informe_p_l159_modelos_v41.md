## P-L159 - unificacion de modelos a DeepSeek V4.1 Flash via opencode Go (29-oct-2026)

Dictamen: `ready_for_integration_rehearsal`. Candidato aislado en
`.worktrees/models-v41` (rama `codex/models-v41`), base exacta
`b3a1c57731fe0e6ad8a3b799cf639d87243b1367`, tree
`dea237b9e81a0d686bbd476705b9700263003db9`, version `0.4.394`.

### Motivo

El operador pidio verificar que todos los modelos del proyecto fueran
`deepseek-v4.1-flash` servido por `opencode-go`. La verificacion read-only
encontro que la linea `main` ya normaliza el ID y usa v4.1 en router, cliente
de mejora, scripts y `.env.example`, pero quedaban cuatro huecos:

1. `config.py` mantenia `opencode-zen` como selector por defecto, base Zen y
   proveedor de mejora/orquestador Zen. Un entorno sin overrides arrancaba en
   Zen.
2. `LLM_LOCAL_FALLBACK_ENABLED` y `IMPROVEMENT_LLM_LOCAL_FALLBACK_ENABLED`
   venian activos por defecto (`qwen3.6-27b`). `role_endpoints` anexa
   `configured_llm_endpoints`, de modo que qwen podia servir decision y
   sentimiento reales como respaldo.
3. El catalogo de la UI (`web_app.py`) ofrecia `glm-5.2/5.1`, `kimi-k2.7/2.6`,
   `deepseek-v4-pro`, `deepseek-v4-flash` y `mimo-v2.5*`, y la pantalla de
   configuracion escribe `.env` con el modelo elegido. Un clic podia dejar un
   modelo no v4.1 en el entorno activo.
4. `.env.example` seguia documentando Zen, base Zen, fallback local activo y
   roles con base Zen.

El `.env` local ya estaba en go/v4.1 para primario, mejora, orquestador y roles
decision/sentimiento, pero conservaba `OPENAI_MODEL_NAME=kimi-k2.6`,
`MIMO_MODEL=mimo-v2.5-pro` y ambos fallbacks locales activos.

### Cambios

- `config.py` (protegido, autorizado por el operador): selector por defecto
  `opencode-go`; `opencode_api_base` por defecto `https://opencode.ai/zen/go/v1`;
  proveedor, base y modelo de mejora y de orquestador por defecto en Go/v4.1;
  `llm_local_fallback_enabled` y `improvement_llm_local_fallback_enabled` por
  defecto en `False`.
- `web_app.py`: catalogo reducido a `deepseek-v4.1-flash`; `mimo` retirado del
  catalogo y del selector; proveedores seleccionables limitados a
  `opencode-go`; tabla informativa de modelos con una sola fila Go/v4.1.
- `.env.example`: selector, base, roles y mejora alineados a Go/v4.1; fallback
  local documentado como `false`; MiMo marcado como legacy retirado.
- `.env` local (protegido, autorizado): `LLM_LOCAL_FALLBACK_ENABLED=false`,
  `IMPROVEMENT_LLM_LOCAL_FALLBACK_ENABLED=false`, `OPENAI_MODEL_NAME` a
  `deepseek-v4.1-flash` y `MIMO_MODEL` retirado. Copia previa en
  `.env.bak-p159-<timestamp>`.
- `tests/test_p159_models_v41_only.py` (nuevo): fija que los defaults son
  Go/v4.1, que la cadena primaria y los roles decision/sentimiento/deep tienen
  un unico modelo v4.1, que el cliente de mejora tambien, que qwen solo aparece
  con opt-in explicito y que el catalogo de UI no expone otro modelo.
- `tests/test_p78b_deepseek_default.py` y `tests/test_llm_router.py`: las
  aserciones del default pasan de Zen a Go/v4.1.

Sin cambios en `kernel.py`, `tools/broker.py`, `tools/execution.py`,
`tools/risk.py`, `llm_router.py`, `continuous_improvement/llm_client.py` ni
`llm_model_ids.py`: en `main` ya usan `DEEPSEEK_V4_1_FLASH_MODEL_ID`. No hay
cambio de politica de trading, sizing, gates ni persistencia.

### Verificacion

- `tests/test_p159_models_v41_only.py` + `test_p78b` + `test_llm_router` +
  `test_check_opencode_go_deepseek` + `test_check_opencode_zen_failover` +
  `test_p142_provider_session` + `test_dashboard_llm_helpers` +
  `test_ci402_account_funds` + `test_ci_context_compaction` +
  `test_continuous_improvement`: `116 passed, 48 failed` en el candidato frente
  a `106 passed, 49 failed` en la base. Comparacion por conjuntos: cero fallos
  nuevos y un fallo preexistente menos (la asercion del default Zen).
- Los 48 fallos restantes son preexistentes y ajenos: aislamiento SQLite en este
  entorno Windows (`no such table: llm_usage`,
  `no such table: main.continuous_improvement_cycles`) al crear el esquema en
  directorios temporales. Reproducidos identicos sobre la base `b3a1c577`.
- Focales de UI: `tests/test_web_app.py` + `test_ci_codegen.py` +
  `test_llm_budget.py` dan `15 failed, 82 passed` en candidato y en base, mismo
  conjunto de fallos SQLite.
- `.env` real cargado con el codigo del candidato: selector `opencode-go`, base
  Go, modelo `deepseek-v4.1-flash`, fallback local `False`; cadena primaria y
  roles decision/sentimiento/deep resuelven a un unico endpoint
  `('opencode-go', 'deepseek-v4.1-flash')`.
- Ruff `src tests`: 3 errores preexistentes (`dashboard_warmup.py`,
  `retention.py`, `web_app.py:10`), 0 nuevos. `check_no_nulls` OK (598
  archivos). `git diff --check` sin salida.

### Limites y pendientes

- Produccion Jetson: `unavailable` en esta ventana. `ssh antonio@192.168.1.186`
  devuelve `Permission denied (publickey,password)`, asi que no se ha podido
  verificar ni cambiar el `.env` ni `runtime.env` del contenedor. Los docs
  declaran `0.4.393`; no se afirma como verificado.
- `llm_usage` local no registra ningun uso de `deepseek-v4.1-flash`: la ultima
  fila es de 2026-08-14. La evidencia de uso real v4.1 en produccion sigue
  `unavailable`.
- Suite completa, smoke aislado, `validate-agent-config` y `kernel-status`
  omitidos: XNYS abre a las 15:30 Europe/Madrid y AGENTS prohibe suites largas
  con mercado abierto. Deben ejecutarse antes de integrar.
- Rotacion pendiente de `OPENCODE_API_KEY`: su valor se imprimio por error
  durante la auditoria. No se repite aqui.
- El fallback local qwen sigue disponible por opt-in explicito; si el operador
  quiere eliminarlo del codigo, es un lote aparte.
