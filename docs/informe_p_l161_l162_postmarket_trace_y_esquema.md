# P-L161 + P-L162 — Traza durable del fallo postmarket y orden de índices del esquema

Fecha: 2026-10-29 (Europe/Madrid). XNYS cerrado en el corte; apertura
2026-10-29T14:30:00+01:00.

Nivel de riesgo: **N2** en ambos lotes (telemetría y esquema; sin autoridad de
trading, sin cambio de política y sin fronteras protegidas).

## 1. Dictamen

`deployed`. Imagen `agente-bolsa:0.4.397-arm64`
`sha256:1df7c5720c86e817bd312fb1ab4e2a296c9fe04408cb0314c47ec2b4a3a04621`,
commit `1ff8e4f9ed51ae95deef9265d052079107fe2c9f`, tree
`d129e2863871b12bebd3885f87fac8c389c17134`, tag `prod-jetson-0.4.397`, recibo
verificado 2026-10-29T12:27:29Z.

## 2. Causa raíz

### P-L162 — el esquema no creaba bases nuevas

`Store.ensure_schema` ejecuta un único `SCHEMA`. Ese script declaraba
`idx_ci_cycles_created` e `idx_trade_recommendations_cycle_created` **antes** de
sus `CREATE TABLE`, de modo que cualquier base nueva abortaba con:

```text
sqlite3.OperationalError: no such table: main.continuous_improvement_cycles
```

Arrastraba 858 identificadores de la suite completa (852 `FAILED` + 7 `ERROR`
menos solapes) en el candidato y en `main`, siempre en `storage.py:1400`. La base
productiva ya tenía las tablas, así que producción no se veía afectada: el daño
era de validación, no de operación.

### P-L161 — el fallo postmarket llegaba sin frame

`post_market_review_failed` se persistía solo con `repr(exc)`. Los intentos del
26 y 27-oct dejaron 19 eventos con:

```text
TypeError("<' not supported between instances of 'NoneType' and 'int'")
```

y ningún frame, así que no se pudo atribuir a productor ni a entrada. Los
`started` sin terminal de esos días (hasta 18 en un día) quedan como evidencia
parcialmente `unavailable`: el proceso se reinició o el evento no se escribió.
El arreglo previo `_metric_number` (P-L354, commit `b4ddf194`) ya está en la
imagen desplegada y cubre el camino P/L; no se ha reproducido el `TypeError` con
el código actual.

## 3. Cambio

| Fichero | Cambio |
|---|---|
| `src/agente_bolsa/storage.py` | cada índice se declara junto a su tabla: `idx_ci_cycles_created` tras `continuous_improvement_cycles`, `idx_trade_recommendations_cycle_created` tras `trade_recommendations` |
| `src/agente_bolsa/scheduler.py` | `_failure_traceback()` acotado a 6.000 caracteres; el evento `post_market_review_failed` publica la traza dentro del payload |
| `tests/test_p162_fresh_schema.py` | base nueva, idempotencia del esquema e índice presente |
| `tests/test_p161_postmarket_traceback.py` | la traza viaja en el evento, contiene el frame y el recorte es determinista |
| `src/agente_bolsa/__init__.py` | `0.4.396` y `0.4.397` |

Paridad: sin órdenes, sizing, riesgo, broker, red ni LLM; sin esquema nuevo ni
migración (solo se mueve la creación de dos índices ya existentes); sin diff en
`kernel.py`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py`,
`config.py` ni `.env`. `_failure_traceback` es evidencia, nunca señal de control:
no lee ni escribe estado operativo.

## 4. Validación

| Gate | Resultado |
|---|---|
| P-L162 focales | `2 passed in 1.89s` |
| P-L162 regresiones que antes fallaban | `43 passed in 18.49s` (`test_agent_run_telemetry`, `test_p47b1_coordination_recovery`, `test_p45b_postmarket_reliability`) |
| P-L161 focales y vecinos | `78 passed in 43.71s` (`test_p161_postmarket_traceback`, `test_p45b_postmarket_reliability`, `test_p48br1_adversarial_qa`) |
| Ruff de los ficheros del lote | `All checks passed!` |
| `check_no_nulls` | `OK (605 archivos)` |
| `git diff --check` | limpio |
| Verificación de imagen | 3/3 ficheros con sha256 idéntico al commit, en contenedor temporal con `--entrypoint python3` |

Suite completa: no se repitió por presupuesto. La evidencia de identidad es que
el delta es de dos ficheros fuente y el defecto de esquema está demostrado
corregido por focales que antes fallaban con la firma exacta.

## 5. Despliegue

Corte 12:26Z, mercado cerrado. `jetson-ops deploy-agente-bolsa` con Compose base
más override Raspberry y `--env-file /etc/agente-bolsa/runtime.env`, tras fijar
`AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.397-arm64` con copia
`runtime.env.bak-pl161-20261029T122xxx`.

Salud 1 y salud 2 (80 s): 3 contenedores `healthy`, `RestartCount=0`,
`OOMKilled=false`, HTTP 200 en `/`, `/health` y `/_stcore/health`, kernel `ok`
con 0 violaciones, flags `paper`/`true`/`false`/`false`, cero órdenes desde el
corte y cero `critical`/`traceback`/`database is locked`. Recibo releído
correctamente.

## 6. Límites

- El postmarket **sigue sin completar** desde 2026-10-19. Este lote no lo
  arregla: garantiza que, si vuelve a fallar, el evento traiga el frame. La
  prueba real es el postmarket de la sesión de hoy, a partir de las 22:00 Madrid.
- Los `started` sin terminal de 21-28 oct no se pueden reconstruir: no hubo
  evento de cierre y los logs se rotaron. Quedan como `unavailable`.
- La suite completa no se repitió; la deuda restante de 858 identificadores
  debería caer ahora, pero eso exige su propia ejecución y triaje.

## 7. Siguiente paso

1. Observar el postmarket de hoy: si completa, cerrado; si falla, leer la traza
   del evento y convertir el frame en lote mínimo.
2. Repetir la suite completa sobre `main` para cuantificar cuántos de los 858
   identificadores desaparecen con P-L162.
3. Unificar modelos en producción (N3): `application.env` sigue forzando
   `opencode-zen`, `zen/v1`, `deepseek-v4-flash-free` y mimo con `kimi-k2.6`.
4. Pasos 8–11 del plan de agentes: siguen N3 sin autorización.
