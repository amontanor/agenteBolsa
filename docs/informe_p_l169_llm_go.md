# P-L169 — LLM real en OpenCode Go: cabecera de sesión y presupuesto de probe

Fecha: 2026-10-29. XNYS abierto durante el corte (autorización operativa explícita
del operador: «olvídate del horario, doy el ok»).

Nivel: **N2** (diagnóstico y credencial operativa; sin autoridad de trading).

## Dictamen

`deployed`. Imagen `agente-bolsa:0.4.399-arm64`
`sha256:81e970415d242c13598c3bed461e1a3da5fed1317ff9dcd4c91d7f42598880bc`,
commit `764c8b5f`, tree `ff443e06`, tag `prod-jetson-0.4.399`, recibo
2026-10-29T13:25:28Z. **Los cinco roles LLM responden HTTP 200** con
`deepseek-v4.1-flash` sobre `https://opencode.ai/zen/go/v1`.

## Causa raíz (hechos verificados)

1. OpenCode Go exige la cabecera `x-opencode-session`. Sin ella devuelve
   `400 MissingSessionID`. La ruta real de la app ya la enviaba
   (`build_openai_client` construye `x-opencode-session` + `User-Agent`), pero
   `scripts/llm_health_check.py` usaba `urllib` sin cabecera: daba falso
   negativo en los cinco roles.
2. La clave anterior estaba caducada para Zen (`401 api_key_expired`) y Zen
   devolvía además `402 Insufficient account funds`; el modelo free ya no existe
   (`400 Model is unavailable`).
3. `IMPROVEMENT_LLM_API_KEY` y `IMPROVEMENT_LLM_ORCHESTRATOR_API_KEY` seguían con
   la clave vieja: `deep`, `improvement` y `codegen` daban 401 aunque el resto
   funcionase.
4. Con el modelo de razonamiento, el probe de `improvement` gastaba 1.311 tokens
   de reasoning con `max_tokens=1024` y truncaba el JSON (`json_incompleto:role`).

## Cambio

| Fichero | Cambio |
|---|---|
| `scripts/llm_health_check.py` | `_provider_session_header()`: cabecera `x-opencode-session` para Go/Zen, id estable por día y ámbito; `improvement.max_tokens` 1024 → 4096 |
| `tests/test_p169_llm_health_session_header.py` | Go/Zen con cabecera, estabilidad diaria y no-op en otros proveedores |
| `src/agente_bolsa/__init__.py` | `0.4.398` y `0.4.399` |

Configuración de producción (fuera de la imagen): clave nueva de OpenCode en
`OPENCODE_API_KEY`, `OPENAI_API_KEY`, `IMPROVEMENT_LLM_API_KEY` y
`IMPROVEMENT_LLM_ORCHESTRATOR_API_KEY`; selector `opencode-go`, base
`.../zen/go/v1`, modelo `deepseek-v4.1-flash` en primario y roles. Cada corte de
`application.env` recalculó hash, alineó `runtime.env` y `jetson-ops`, y reselló
el manifiesto (root, contenedor temporal: el secreto es `root:600`).

## Evidencia

```
[OK] decision    deepseek-v4.1-flash 2068.7ms HTTP=200
[OK] sentiment   deepseek-v4.1-flash 5129.1ms HTTP=200
[OK] deep        deepseek-v4.1-flash 3084.3ms HTTP=200
[OK] improvement deepseek-v4.1-flash 4735.3ms HTTP=200
[OK] codegen     deepseek-v4.1-flash 7957.8ms HTTP=200
RESULTADO: todos los roles LLM tienen respuesta valida.
```

Focales: `3 passed`; Ruff de los ficheros del lote: limpio. Salud: 3 contenedores
`healthy`, `RestartCount=0`, `OOMKilled=false`, HTTP 200, `kernel-status ok` con
0 violaciones.

## Límites

- El corte se hizo con el mercado abierto por autorización expresa; el stack se
  recreó dos veces. No se ejecutaron `run-once`, postmarket ni reconciliación.
- El probe de `codegen` tarda ~8 s y gasta ~2.459 tokens de razonamiento: es
  diagnóstico, no una ruta de producción.
- `improvement` real usa su propio presupuesto (`IMPROVEMENT_LLM_MAX_TOKENS`);
  que el probe pase no garantiza que cada propuesta larga no se trunque.
- Sin `push` y sin cambios en ficheros protegidos (`kernel.py`, broker,
  execution, risk, `config.py`, `.env`).
