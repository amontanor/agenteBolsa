# P-L85 — Caracterización de OpenCode Zen y fallback Go

## Dictamen

`needs_fix`. La primera prueba de OpenCode Zen fue correcta, pero la batería
secuencial posterior no fue completamente estable: una respuesta HTTP 200
terminó con `finish_reason=length` y sin contenido utilizable según el contrato
de la probe. No se autoriza la migración a Zen, ningún cambio de configuración
ni el despliegue.

## Alcance y referencias

- Producción: `94a5cf7fe3695d5c3935d16a3bb1428b8e554e62`, árbol
  `400d178466c85f31dc2f804024429351577ce3bd`, v0.4.220, limpia.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl85_zen_primary_failover`.
- Rama: `codex/pl85-zen-primary-failover`.
- Base exacta: `94a5cf7fe3695d5c3935d16a3bb1428b8e554e62`.
- XNYS cerrado; la preapertura y el stack productivo no se modificaron.
- El slot 0.4.221 estaba libre al comenzar; no se reservó porque no hubo
  migración funcional.

## Contrato y evidencia real

La fuente oficial lista `deepseek-v4-flash-free` en OpenCode Zen con el endpoint
OpenAI-compatible `/zen/v1/chat/completions`, y documenta que el modelo Free es
temporal y puede usar datos para mejorar el modelo:
<https://opencode.ai/docs/zen>.

Se ejecutaron cinco llamadas reales, todas sin retry ni fallback, con prompt
benigno sintético, `requests_made=1` por llamada y sin SQLite, broker, cartera,
servicios ni prompts operativos:

| Nº | Ruta | HTTP | Resultado | finish_reason | Latencia |
|---:|---|---:|---|---|---:|
| 1 | Zen health | 200 | válido | stop | 2.181 s |
| 2 | Zen health secuencial | 200 | inválido | length | 2.003 s |
| 3 | Zen health secuencial | 200 | válido | stop | 1.688 s |
| 4 | Zen health secuencial | 200 | válido | stop | 2.012 s |
| 5 | Zen health secuencial | 200 | válido | stop | 1.710 s |

En la llamada 2 la respuesta no tenía contenido utilizable para el contrato de
la probe. El cuerpo no se conserva ni se publica; por tanto no se puede afirmar
si la causa fue `reasoning_content` sin exponer datos. Queda como incompatibilidad
o estabilidad no resuelta, no como autorización para ignorar `length`.

No se observaron HTTP 401/403/404/408/409/429/5xx, ni headers de request-id,
Retry-After o rate-limit en estas respuestas. No se ejecutó la llamada Go: la
regla del lote solo la permite como fallback del primer Zen fallido, y esa
primera probe fue verde. El presupuesto real consumido fue 5/10; no se lanzaron
las pruebas concurrentes, estructurada ni multi-turn porque la batería ya dejó
de cumplir el gate de estabilidad.

## Caracterización offline

Se añadió una probe independiente, sin imports del runtime de trading, con:

- una sola tentativa por proveedor;
- fallback Go únicamente cuando el primer proveedor falla;
- clasificación de 401/403/404/408/409/429/5xx, timeout y respuesta inválida;
- comprobación de identidad provider/model/endpoint;
- captura segura de uso y presencia de headers, sin valores de credenciales;
- modos health, JSON estructurado y multi-turn/reasoning para pruebas sin red.

Resultado: 6 tests offline pasados, Ruff limpio y `git diff --check` limpio.

## Decisión y siguiente precondición

No se modificó `llm_router.py`, `config.py`, `.env`, `broker.py`, `kernel.py`,
riesgo, ejecución, selección, gates, sizing, exits ni fallback local. No se
ejecutó Go real, no se cambió el proveedor primario, no se hizo `kernel-seal`,
no se detuvo/arrancó el stack y no se hizo merge ni push.

El siguiente lote debe resolver y probar explícitamente el contrato de
`reasoning_content`/`finish_reason=length` o demostrar que la respuesta es
válida bajo el contrato actual, con tests offline y una nueva autorización de
caracterización real antes de migrar. No debe reinterpretarse el fallo como
éxito ni activar Zen por defecto mientras exista esta incertidumbre.
