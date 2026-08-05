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

## P-L85R - caracterización corregida y migración preparada

### Dictamen

`ready_for_closed_market_deployment`. La incertidumbre de la primera batería
quedó aislada y no se relajó el contrato: `finish_reason=length`, contenido
final ausente, identidad incorrecta, respuesta malformada o error HTTP siguen
siendo fallos. La probe se alineó con los límites de los consumidores y
conserva `reasoning_content` solo como metadato; nunca sustituye el contenido
final requerido.

### Evidencia real adicional (presupuesto agotado)

No se repitieron las cinco llamadas históricas. Se consumieron exactamente las
cinco llamadas restantes autorizadas: una health Zen, dos Zen concurrentes,
una Zen combinada JSON estructurado + multi-turn/reasoning y una health directa
Go. Todas fueron una sola tentativa, sin retry ni fallback dentro de la probe.

| Llamada | Ruta | Captured_at UTC | HTTP | Resultado | Finish | Latencia |
|---:|---|---|---:|---|---|---:|
| 6 | Zen health corregida | 2026-08-05T21:52:31.544973Z | 200 | válido; content y reasoning presentes | stop | 1.953 s |
| 7 | Zen concurrente A | 2026-08-05T21:52:43Z | 200 | válido; content y reasoning presentes | stop | 1.546 s |
| 8 | Zen concurrente B | 2026-08-05T21:52:43Z | 200 | válido; content y reasoning presentes | stop | 2.026 s |
| 9 | Zen JSON + multi-turn/reasoning | 2026-08-05T21:52:54.568496Z | 200 | válido; content y reasoning presentes | stop | 2.558 s |
| 10 | Go health directo | 2026-08-05T21:53:00.535859Z | 200 | válido; content y reasoning presentes | stop | 1.565 s |

En las cuatro llamadas Zen corregidas: `provider=opencode-zen`,
`model=deepseek-v4-flash-free`, endpoint `/zen/v1/chat/completions`,
`fallback_used=false` y `requests_made=1`. En Go: `provider=opencode-go`,
`model=deepseek-v4-flash`, endpoint `/zen/go/v1/chat/completions`,
`fallback_used=false` y `requests_made=1`. No se observaron 401/403/404/408,
409/429/5xx, `Retry-After`, `request-id` ni cabeceras de rate-limit. No se
observaron límites numéricos oficiales en la documentación consultada.

Las latencias Zen válidas de las diez llamadas (excluyendo la respuesta
histórica inválida) tienen p50 aproximado de 1.983 s y p95 lineal aproximado
de 2.426 s. El antiguo `length` se conserva como hecho; su causa interna
exacta es `unavailable` porque el cuerpo no se almacenó. La hipótesis de cap
artificial bajo queda caracterizada, no afirmada como causalidad demostrada.

### Contrato implementado

El candidato configura Zen Free como primario (`opencode-zen`,
`https://opencode.ai/zen/v1`, `deepseek-v4-flash-free`) y Go como fallback
inmediato (`opencode-go`, `https://opencode.ai/zen/go/v1`,
`deepseek-v4-flash`). Zen y Go tienen cero reintentos propios; ante un fallo
del primario se hace una única petición Go y después se conservan los fallbacks
locales existentes. Los eventos/identidades distinguen requested/effective,
`fallback_used` y `fallback_reason`; los motivos de proveedor publicados son
clases/HTTP acotados y no cuerpos de respuesta. No cambian prompts,
thresholds, gates, selección, sizing, trading, riesgo, ejecución ni autoridad.

El cambio de telemetría adicional en `b69b7d38` elimina mensajes crudos del
proveedor de `fallback_reason`, previews de fallback y el evento de fallo de
mejora continua. Los estados válidos de respuesta siguen siendo solo
`stop`, `tool_calls` o `function_call` con contenido final no vacío.

### QA del candidato

- Focales router/continuous-improvement/probe tras el fix de telemetría:
  `106 passed`.
- Suite completa fresca en el candidato: `2456 passed, 1 skipped
  preexistente, 1 warning` en `752.91 s`. El warning es el
  `DeprecationWarning` externo de `websockets.legacy`.
- `ruff check src tests` y los scripts modificados: verde.
- `scripts/check_no_nulls.py`: `OK (475 archivos)`.
- Compilación temporal de `src`, `tests` y probe: verde.
- `validate-agent-config --json`: `ok=true`, sin errores ni warnings.
- `kernel-status --json` aislado: `unsealed`, `violations=[]`, esperado al
  usar `DATA_DIR` temporal sin manifiesto productivo.
- Smoke del ciclo observable con `--skip-crew`, snapshots fake y
  `DATA_DIR` temporal: verde; sin broker, red, LLM real ni SQLite productiva.
- `git diff --check`: verde.
- No se ejecutó otra probe real: el presupuesto total autorizado quedó en
  `10/10`.

### Estado y siguiente paso

Producción permaneció intacta en v0.4.220, HEAD
`94a5cf7fe3695d5c3935d16a3bb1428b8e554e62`, tree
`400d178466c85f31dc2f804024429351577ce3bd`, con `.env` sin editar, stack sin
reinicio y sin push. El candidato contiene los commits funcionales de
caracterización, probe corregida, migración/fallback, version policy y
telemetría segura, y mantiene los archivos protegidos sin delta.

La migración queda autorizada para el cierre productivo solo después de
renovar preflight, revisar el delta no secreto de `.env`, ejecutar gates con
stack detenido, sellar una sola vez el kernel si el delta exige sello,
arrancar con helpers y completar dos health checks separados al menos 75 s.
El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` permanece inmutable; la
activación Zen requerirá su propio `activation_at` UTC y cohortes separadas,
sin backfill.
