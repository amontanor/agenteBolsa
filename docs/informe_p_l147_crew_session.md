# P-L147 — cabeceras de sesión en CrewAI LLM (candidato 0.4.249)

Dictamen: `ready_for_review`. XNYS abierto (18-sep-2026, sesión en
curso); trabajo aislado en worktree, sin broker/red/LLM en pruebas,
sin despliegue.

## Causa

El dashboard 0.4.306 mostró 30 `MissingSessionID` (Console Go) y 3/3
compras `Fallback determinista... no usada por el LLM`. P-L142 cubrió
`llm_router.build_openai_client` y `llm_client`, pero `crew.py:54`
construía CrewAI `LLM(model, base_url, api_key)` sin cabeceras: los
crews nunca se autenticaban en Go/Zen y `crew_failed` degradaba cada
ciclo a fallback. Trading intacto por fail-open P-L141.

## Cambio

- `build_crew` pasa `additional_params={"extra_headers":
  provider_client_headers(endpoint.provider, scope="crew")}` al LLM
  compartido (también `planning_llm`, mismo objeto). CrewAI 1.14.7
  fusiona `additional_params` en params litellm (`crewai/llm.py:701`),
  que reenvía `extra_headers` al cliente OpenAI.
- Vacío `{}` para proveedores sin sesión (sin cambio de conducta).
  Alcance `crew` = sesión diaria propia, separada de `decision`.
- Sin tocar scheduler, riesgo, kernel, config ni `.env`.

## QA

- Nuevos: `tests/test_p147_crew_session_headers.py` (2 tests: Go
  reenvía sesión exacta; openai no añade nada).
- `test_version_policy` verde tras bump `0.4.248` → `0.4.249`.
- Ruff, `check_no_nulls.py` (514 archivos), `git diff --check` verdes.
- Omitidos (sesión abierta): suite, smoke, config/kernel, despliegue.

## Límites y siguiente

- No verificado contra proveedor real (sin red en tests); la prueba
  afirma el reenvío hasta `additional_params`, no el handshake.
- Siguiente: merge `--no-ff` tras el cierre + suite + splice Jetson
  0.4.307 y corte post-postmarket. P-L144/P-L145 siguen en cola.
