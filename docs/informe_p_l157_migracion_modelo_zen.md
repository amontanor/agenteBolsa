# P-L157 — migración exacta del ID de modelo OpenCode Zen

## Dictamen

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
