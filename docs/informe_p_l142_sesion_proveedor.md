# P-L142 — cabeceras de sesion del proveedor Go/Zen (candidato Windows 0.4.246)

Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
push ni escritura productiva.

## Causa

Auditoria Jetson 17-sep: el LLM de mejora falla con 400
`MissingSessionID` en primario y `Connection error` en fallback. La
documentacion oficial del proveedor exige `x-opencode-session` estable
por conversacion y User-Agent propio (no generico de SDK). Nuestros
clientes no enviaban ninguno: el ruteo rechaza la peticion.

## Cambio (transporte LLM, sin trading ni protegidos)

- `llm_router.provider_session_id`: UUID5 determinista por
  proveedor+ambito+dia (estable intradia para cacheo, rota a diario).
  Solo Go/Zen; otros proveedores → None.
- `provider_client_headers`: sesion + `User-Agent: agente-bolsa/<ver>`.
- `build_openai_client(..., scope)`: `default_headers` en SDK;
  `chat_for_role` propaga el rol como ambito. Preflight sin ambito.
- `llm_client` (mejora): mismas cabeceras en `_request_headers`
  (urllib) y `_sdk_chat_completion_content` (merge con api-key mimo).
- 4 fakes de `test_llm_router` adaptados a la firma nueva.
- Bump `0.4.245` → `0.4.246`; pin `test_p59c` actualizado.

Sin cambiar proveedor, modelo, reintentos, prompts, decisiones,
trading, riesgo ni configuracion. Si el 400 persiste en produccion,
sera causa de credencial/limite, ya no de cabeceras: el diagnostico
queda acotado.

## Commits (rama `codex/pl142-provider-session`, base `0796d003`)

- `b82ad1ae` test: 4 tests de cabeceras (rojo por coleccion).
- `6edb351f` feat + bump 0.4.246 + pin + adaptacion de 4 fakes.

## QA (XNYS cerrado)

- Focales: 6 passed (+2 wiring CI/mimo).
- Regresiones: 68 passed con llm_router + p59c; 82 passed
  `test_continuous_improvement.py`.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (511 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa: en la integracion final. Sin red/LLM en tests.

## Siguiente paso

Merge P-L139+P-L142 → suite → port Jetson → corte con verificacion
del 400 en logs. Sin push.
