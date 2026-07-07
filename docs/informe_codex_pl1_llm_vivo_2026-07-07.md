# Informe P-L1 - LLM vivo

Fecha: 2026-07-07

## Resumen

Se corrigio el diagnostico LLM para que deje de dar falsos positivos/falsos negativos por probes irreales y para que el digest matinal publique siempre la linea `LLM: ...` con horas desde la ultima respuesta real registrada. Tambien se dejo una llamada real del rol `decision` persistida en `llm_usage`.

No se confirmo la hipotesis de presupuesto agotado. A fecha del cierre, el gasto real del dia era `0.006947 USD / 5.0 USD` y el subpresupuesto `deep` seguia en `0.0 USD / 3.0 USD`.

## Diagnostico con evidencia

Diagnostico crudo previo al fix del healthcheck, con llamada real por rol:

| Rol | Evidencia cruda | Causa |
|---|---|---|
| `decision` | `HTTP 200`, `finish_reason=length`, `content_chars=0`, `reasoning_chars=126` con probe corta; con `max_tokens=512` devolvio `OK-DECISION` | El proveedor estaba vivo. El fallo era del chequeo: probe demasiado corta y criterio `200 + choices = OK` aunque el contenido viniera vacio. |
| `sentiment` | `HTTP 200`, `finish_reason=length`, `content_chars=0`, `reasoning_chars=4225` con probe corta/JSON; con probe parecida al uso real y `max_tokens=2048` devolvio JSON valido | El proveedor estaba vivo. El chequeo anterior no representaba el contrato real del rol de sentimiento. |
| `deep` | `HTTP 200`, JSON valido via `glm-5.2`, con formas variables como `{"status":"ready","ack":true}`; intermitentemente timeout con timeout corto | El rol estaba vivo, pero el chequeo era demasiado estricto con el shape y demasiado corto de timeout. |
| `improvement` | `HTTP 200`, `finish_reason=stop`, `content_chars>0`, JSON valido | OK. Sin incidencia funcional. |
| `codegen` | `HTTP 200`, a veces `finish_reason=length` con probe insuficiente; con probe JSON mas realista devolvio JSON valido | El proveedor estaba vivo. El chequeo anterior confundia una sonda artificial con la salud real del rol. |

Estado adicional observado antes del fix:

- `agents_healthcheck` marcaba degradado por `decision` sin uso reciente: ultima llamada real registrada el `2026-07-02T19:42:19+00:00`.
- `pip check` en el Python global del sistema salia roto por paquetes fuera del entorno del proyecto; en `.venv` sale limpio (`No broken requirements found.`).
- Cuota del proveedor no es visible desde este stack; no hubo evidencia de `429` ni de corte por presupuesto interno.

## Cambios aplicados

- `scripts/llm_health_check.py`
  - ahora diagnostica `decision`, `sentiment`, `deep`, `improvement` y `codegen`;
  - captura `status`, `finish_reason`, `content_chars`, `reasoning_chars`, error literal y estado del presupuesto;
  - usa probes cercanas al contrato real de cada rol en vez de probes triviales;
  - deja de marcar `OK` cuando hay `content` vacio;
  - reporta tambien `pip check` del entorno que ejecuta el script.
- `src/agente_bolsa/tools/llm_degraded_watchdog.py`
  - expone `roles` y la linea `status_line`:
    - `LLM: decision=OK/CAIDO (...) sentiment=OK/CAIDO (...)`
- `src/agente_bolsa/tools/daily_learning.py`
  - inyecta `llm_status` y `llm_status_line` en el digest diario.
- `src/agente_bolsa/main.py`
  - imprime la linea `LLM: ...` en `learning-digest`.
- `src/agente_bolsa/__init__.py`
  - version subida a `0.4.114`.

## Evidencia de cierre

### Healthcheck LLM

`.\.venv\Scripts\python.exe scripts/llm_health_check.py --json`

Resultado final:

- `overall_ok=true`
- `decision_ok=true`
- `sentiment_ok=true`
- `deep_ok=true`
- `improvement_ok=true`
- `codegen_ok=true`

### Digest matinal

`.\.venv\Scripts\python.exe -m agente_bolsa.main learning-digest --from 2026-04-01 --to 2026-07-07 --json`

Linea publicada:

`LLM: decision=OK (0.1h sin respuesta real) sentiment=OK (17.3h sin respuesta real)`

### Llamada real del rol decision registrada en llm_usage

Smoke ejecutado:

- `chat_for_role("decision", max_tokens=512)` devolvio `OK-DECISION-SMOKE`
- endpoint usado: `role:decision`
- modelo usado: `deepseek-v4-flash`

Registro persistido:

- `source=trade_decision`
- `role=decision`
- `created_at=2026-07-07T13:37:58.378535+00:00`
- `total_tokens=213`

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_llm_degraded_watchdog.py tests\test_daily_learning.py tests\test_llm_health_check_script.py -q` -> `16 passed`
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts` -> OK
- `.\.venv\Scripts\python.exe scripts\llm_health_check.py --json` -> `overall_ok=true`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json` -> OK, sin warnings
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew` -> OK, ciclo `20260707-133755`

Bloqueo residual ajeno a P-L1:

- `.\.venv\Scripts\python.exe -m pytest tests -x -q` sigue fallando en `tests/test_lab_book_wall.py::test_lab_book_source_is_excluded_from_real_book_consumers`
- El fallo esta en `profitability_scoreboard/edge_analysis` (`linked_executed_buys == 0` esperado `1`) y no toca ninguno de los modulos cambiados en esta tarea.
