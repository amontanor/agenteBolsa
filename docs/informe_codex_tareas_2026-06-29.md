# Informe Codex — tareas 2026-06-29

Contexto operativo: todas las comprobaciones se hicieron sobre `agenteBolsa` en modo paper. No se modificaron `risk.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py`, `config.py` ni `.env`.

## 1. Caracterización de conflictos T6 en `signal_outcomes`

### Qué hice

- Leí `docs/signal_outcomes_migration_conflicts_2026-06-25.json`.
- Verifiqué el esquema real de `signal_outcomes` en `src/agente_bolsa/storage.py`: `signal_id`, `source_run_id`, `source`, `symbol`, `signal_date`, `decision`, `features_json`, `gate_json`, `outcome_json`, `created_at`, `updated_at`.
- Abrí la BD en modo read-only (`file:...agente_bolsa.sqlite3?mode=ro`).
- Para cada grupo `(signal_date, symbol, strategy)` del JSON de conflictos, comparé los valores forward presentes en `outcome_json`: `return_1d`, `return_3d`, `return_5d`, `return_10d`.
- Separé conflictos reales de returns frente a diferencias de metadatos (`as_of`, `bars_seen`, `exit_policy_v2`, etc.).

### Números

| Métrica | Valor |
|---|---:|
| Grupos en JSON de conflictos | 10.969 |
| Grupos cargados desde BD live | 10.969 |
| Conflictos con diferencias reales en `return_*` | 10.966 |
| Conflictos solo de metadatos con mismos `return_*` | 3 |

Distribución de tamaño de grupos duplicados más frecuente:

| Filas por grupo | Grupos |
|---:|---:|
| 30 | 1.479 |
| 28 | 1.006 |
| 27 | 1.003 |
| 21 | 999 |
| 31 | 994 |
| 34 | 988 |
| 26 | 671 |
| 12 | 499 |
| 18 | 488 |
| 36 | 485 |

Subtipos observados:

- `return_diff_entry_or_close_diff`: 10.966 grupos. Cambia el precio base de entrada/cierre usado para calcular el forward return.
- `metadata_exit_policy_v2_diff`: 2 grupos. Mismos returns, diferencia de metadatos de política de salida.
- `metadata_maturity_asof_bars_diff`: 1 grupo. Mismos returns, diferencia de maduración/metadatos.

### Causa probable de los conflictos reales

La causa dominante no parece ser una diferencia de maduración tardía sobre el mismo punto de entrada, sino varios snapshots intradía del mismo símbolo-día antes de T6. Cada snapshot tiene `source_run_id` distinto (`mkt_*`, `closed_*`, `scan_*`) y distinto `entry_price`/`close`; al madurar, los retornos forward se calculan contra bases distintas. Por eso los `return_*` cambian aunque el `(signal_date, symbol, strategy)` sea el mismo.

Ejemplos:

1. `(2026-05-11, A, unknown)`: 26 filas, 15 mapas de returns distintos, 15 valores distintos de `entry_price/close`, fuentes `closed`, `mkt`, `scan`.
   - `mkt_f48d16b34934:A`: entrada 112,225; `return_1d=0,006`, `return_3d=0,0092`, `return_5d=-0,001`, `return_10d=0,0254`.
   - `mkt_10f2cd812f78:A`: entrada 113,14; `return_1d=-0,0021`, `return_3d=0,0011`, `return_5d=-0,0091`, `return_10d=0,0171`.
   - `mkt_6ba6eef5431c:A`: entrada 114,14; `return_1d=-0,0109`, `return_3d=-0,0077`, `return_5d=-0,0178`, `return_10d=0,0082`.

2. `(2026-05-11, AAPL, unknown)`: 26 filas, 14 mapas de returns, 15 entradas/cierres.
   - `mkt_6c0968ea0d54:AAPL`: entrada 293,455; `return_1d=0,0046`, `return_3d=0,0162`, `return_5d=0,0149`, `return_10d=0,0507`.
   - `mkt_f48d16b34934:AAPL`: entrada 293,125; `return_1d=0,0057`, `return_3d=0,0173`, `return_5d=0,0161`, `return_10d=0,0519`.
   - `mkt_10f2cd812f78:AAPL`: entrada 292,49; `return_1d=0,0079`, `return_3d=0,0196`, `return_5d=0,0183`, `return_10d=0,0542`.

3. `(2026-05-11, ABBV, unknown)`: 26 filas, 15 mapas de returns, 15 entradas/cierres.
   - `mkt_6c0968ea0d54:ABBV`: entrada 203,325; `return_1d=0,0223`, `return_3d=0,0366`, `return_5d=0,0299`, `return_10d=0,0482`.
   - `mkt_f48d16b34934:ABBV`: entrada 203,84; `return_1d=0,0197`, `return_3d=0,034`, `return_5d=0,0273`, `return_10d=0,0455`.

4. `(2026-05-11, ABNB, unknown)`: 26 filas, 15 mapas de returns, 15 entradas/cierres, fuentes `closed`, `mkt`, `scan`.

5. `(2026-05-11, ABT, unknown)`: 26 filas, 15 mapas de returns, 15 entradas/cierres, fuentes `closed`, `mkt`, `scan`.

### Regla de fusión propuesta, no ejecutada

No recomiendo compactar destructivamente los 10.966 grupos con `return_*` distinto usando solo `(signal_date, symbol, strategy)`: no son duplicados puros, son observaciones con bases de entrada distintas.

Regla humana por subtipo:

1. Solo metadatos, mismos `return_*` — 3 grupos:
   - Fusión segura.
   - Conservar fila más reciente por `updated_at/created_at/signal_id`.
   - Preservar el `outcome_json` más completo/maduro.

2. `return_*` distinto por `entry_price/close` distinto — 10.966 grupos:
   - No borrar como si fueran duplicados lossless.
   - Opción segura: excluir de migración destructiva y crear una vista/tabla derivada para estudios diarios con una regla canónica explícita.
   - Si se fuerza una sola fila diaria para análisis, escoger una regla canónica auditable, por ejemplo: preferir snapshot oficial de cierre (`closed_*`) sobre intradía; si no existe, primera observación tras apertura o último snapshot, pero documentando que se descartan otras bases de entrada.
   - Alternativa más fiel: cambiar la clave histórica a `(signal_date, symbol, strategy, entry_price redondeado, source_run_id/time_bucket)` para no mezclar entradas intradía distintas.

3. Misma entrada, diferente madurez (`as_of`, `bars_seen`) — no dominante en la muestra:
   - Conservar el outcome con más horizontes presentes y mayor `bars_seen`.
   - Si empata, conservar `updated_at` más reciente.

4. Irreconciliables:
   - Mantener fuera de migración destructiva y exportar para revisión humana.

## 2. Jobs nocturnos y cierre de app

### Qué hice

- Revisé `src/agente_bolsa/scheduler.py`, `src/agente_bolsa/market_calendar.py` y el estado existente en SQLite.
- No lancé ciclos pesados adicionales.
- Consulté eventos existentes y `runtime_state` para las últimas sesiones.

### Dónde se disparan

| Job | Definición | Disparo | Persistencia/catch-up observado |
|---|---|---|---|
| `daily_study_job` | `src/agente_bolsa/scheduler.py:1860-1909` | `CronTrigger` diario en `src/agente_bolsa/scheduler.py:2761-2771` | No vi clave persistente `daily_study_last_session` ni llamada de bootstrap. Si la app está cerrada a la hora exacta, el job se pierde. |
| `post_market_review_job` | `src/agente_bolsa/scheduler.py:2130-2187` | `IntervalTrigger` cada `closed_market_study_interval_minutes` en `src/agente_bolsa/scheduler.py:2772-2782` | Usa `post_market_review_last_session`; además se invoca en bootstrap de `run_scheduler_forever`. Tiene catch-up parcial si el calendario aún apunta a la última sesión cerrada. |
| `overnight_learning_heartbeat_job` | `src/agente_bolsa/scheduler.py:2360-2425` | `CronTrigger` diario en `src/agente_bolsa/scheduler.py:2805-2816` | Usa `overnight_learning_heartbeat_last_session` vía `tools/overnight_learning.py`; también se invoca en bootstrap. Tiene catch-up parcial, no equivalente a cron persistente por día histórico. |

La condición de elegibilidad temporal común usa `MarketCalendar.should_run_daily_study()` en `src/agente_bolsa/market_calendar.py`.

### Respuesta explícita

Si la app está cerrada a la hora programada:

- `daily_study`: se pierde. Es cron puro; no hay catch-up por sesión cerrada en el arranque.
- `post_market_review`: no depende solo de una hora exacta; el checker cada 15m y el bootstrap pueden recuperarlo si el calendario sigue considerando pendiente esa sesión.
- `overnight_learning_heartbeat`: tiene dedupe por sesión y bootstrap, pero si pasan varias sesiones sin app abierta no vi un barrido histórico de todas las sesiones pendientes.

### Evidencia en datos existentes

Eventos recientes:

- Último `daily_study_completed`: `daily_bd8737e11cdc`, iniciado `2026-06-24T21:00:00Z`, terminado `2026-06-24T21:05:21Z`.
- Último `post_market_review_completed`: `pmr_64d138a71a66`, sesión `2026-06-25`, creado `2026-06-25T20:18:18Z`.
- Último `overnight_learning_completed`: `night_06cb4c7e7e29`, creado `2026-06-24T22:10:23Z`.
- `runtime_state` relevante:
  - `post_market_review_last_session = 2026-06-25`.
  - `overnight_learning_heartbeat_last_session = 2026-06-24`.
  - `scheduler_job_status:daily_study` sigue apuntando a `2026-06-24`.

Cobertura reciente aproximada de sesiones cerradas:

| Sesión | `daily_study` | `post_market_review` | `overnight_learning` |
|---|---|---|---|
| 2026-06-22 | presente | presente | no concluyente en payload |
| 2026-06-23 | presente | presente | presente por evento de esa noche |
| 2026-06-24 | presente | presente | presente |
| 2026-06-25 | ausente | presente | ausente |
| 2026-06-26 | ausente | ausente | ausente |

La sesión 2026-06-29 estaba abierta durante la auditoría, por lo que no se evalúa como sesión nocturna cerrada.

### Recomendación, no implementada

Agregar un checker idempotente de sesiones pendientes, no un cambio de cadencia:

- Guardar `daily_study_last_session` en `runtime_state`.
- En arranque y cada 15m fuera de mercado, calcular la última sesión cerrada esperada.
- Si falta `daily_study`, `post_market_review` u `overnight_learning` para esa sesión, ejecutar una sola vez con dedupe por `session_date`.
- No intentar backfill masivo automático sin límite; como mínimo, solo última sesión cerrada o una ventana pequeña configurable.

## 3. WIP del laboratorio CI

### Qué hice

Primero investigué en modo read-only cómo se cuenta WIP:

- Estados activos definidos en `src/agente_bolsa/continuous_improvement/lifecycle.py:56-63`: `OPEN`, `ANALYZING`, `EXPERIMENTING`, `VALIDATING`, `WAITING_REVIEW`, `READY_TO_APPLY`.
- `production-health` alerta en `src/agente_bolsa/tools/operational_health.py:491-555` si `active_initiatives` supera el límite operativo.
- El límite viene de `CI_MAX_OPEN_INITIATIVES`, definido como 4 en `src/agente_bolsa/config.py:814` (solo leído; archivo bloqueado no modificado).
- La acción recomendada por salud operacional es `run_ci_lifecycle_and_reduce_wip` en `src/agente_bolsa/tools/operational_health.py:627-635`.
- El lifecycle oficial está en `src/agente_bolsa/continuous_improvement/lifecycle.py:529-539`; expira/cierra sin borrar histórico.

Después hice backup antes de cualquier mutación:

- Comando: `python -m agente_bolsa.main backup-db`.
- Backup creado: `data\backups\agente_bolsa_db_backup_e776472088db.sqlite3`.
- Tamaño: 2.031.816.704 bytes.

Luego ejecuté únicamente el lifecycle oficial:

```powershell
from agente_bolsa.continuous_improvement.lifecycle import run_lifecycle, flow_report
before = flow_report(store)
result = run_lifecycle(store, settings)
after = flow_report(store)
```

No ejecuté cierres manuales ni updates directos sobre iniciativas.

### Hallazgo importante

El contexto decía WIP=15, pero el estado real al auditar era WIP=19:

- `OPEN`: 14.
- `VALIDATING`: 5.
- `REJECTED`: 563.
- Tareas abiertas: 0.
- `production-health` antes del lifecycle: `ci_backlog_over_wip_limit`, detalle `WIP CI=19 supera el limite operativo 4`.

Además, el lab estaba vivo y emitiendo ciclos en cooldown durante la auditoría. Por eso todos los timestamps recientes deben leerse como una foto de un sistema concurrente.

### Iniciativas activas encontradas

| Iniciativa | Estado | Edad aprox. | Actividad | Clasificación |
|---|---|---:|---|---|
| `ci_init_1424d6201ee8` `trading:duplicate_reduction` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_63c7201d9f6f` `software:duplicate_reduction` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_a15b26c2b363` `trading:p4` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_c92849b039f0` `trading:risk_manager` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_7b30572baa04` `trading:strategy_parameters` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_d4f3f750efe2` `software:observation_executor` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_a0288162685a` `software:p001` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_edc29daf9222` `trading:confidence_calibration_monitor` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_76936f582aed` `trading:short_term_monitoring` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_a3bf75facdc3` `software:pre_earnings_risk_veto` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_46018ab98a9c` `software:p002` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_2cfb57bc214a` `software:p003` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_7205d6cfad26` `software:enhance_analyst_estimation_coverage` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_d784c448cadc` `software:setup_priority_adjustment` | OPEN | 13,7d | 0 tareas abiertas, 0 propuestas activas | Estancada/ambigua |
| `ci_init_a534842771da` `software:gradual_observation_execution` | VALIDATING | 0,04d | 1 propuesta activa | Activa |
| `ci_init_5d4818fc1a09` `software:cycle_end_observation_retry` | VALIDATING | 0,02d | 1 propuesta activa | Activa |
| `ci_init_7e02b03f7f60` `software:initiative_stuck_alert` | VALIDATING | 0,02d | 1 propuesta activa | Activa |
| `ci_init_6125e1ae9e87` `software:proposal_validation_details` | VALIDATING | 0,02d | 1 propuesta activa | Activa |
| `ci_init_b71b3d810952` `software:observation_execution_bypass` | VALIDATING | 0,01d | 1 propuesta activa | Activa |

Las 14 `OPEN` antiguas tenían `latest_decision={"decision":"REJECTED","source":"autonomy_normalizer"}`, pero seguían contando como WIP porque su `status` real es `OPEN`. También tenían `updated_at` refrescado el 2026-06-29 por el normalizador, lo que impide que la regla de inactividad del lifecycle las expire por `idle_days > stall_days`.

### Resultado del lifecycle oficial

Antes:

```json
{
  "initiatives_by_status": {"REJECTED": 563, "OPEN": 14, "VALIDATING": 5},
  "wip": 19,
  "open_task_count": 0,
  "oldest_open_days": 13.7
}
```

Lifecycle:

```json
{
  "tasks": {"expired": [], "cancelled_dependents": []},
  "initiatives": {"closed": [], "expired": [], "advanced": []}
}
```

Después:

```json
{
  "initiatives_by_status": {"REJECTED": 563, "OPEN": 14, "VALIDATING": 5},
  "wip": 19,
  "open_task_count": 0,
  "oldest_open_days": 13.7
}
```

`production-health` posterior siguió en warning:

- `ci_backlog_over_wip_limit`: `WIP CI=19 supera el limite operativo 4`.
- `ci_validation_backlog`: 5 iniciativas en `VALIDATING`.

### Decisión

Me paré aquí. No reduje WIP a mano porque la regla segura no está codificada:

- Hay 14 iniciativas `OPEN` que parecen semánticamente rechazadas por `latest_decision`, pero el lifecycle oficial no las cierra.
- Cambiar `status=REJECTED` manualmente sería plausible, pero no sería “por cauces oficiales” y podría ocultar un bug del normalizador/lifecycle.
- Las 5 `VALIDATING` son recientes y tienen propuestas activas, así que cerrarlas para cumplir WIP≤4 no está justificado sin una decisión humana o una regla adicional.

Recomendación concreta, no implementada:

1. Añadir al lifecycle una regla explícita y testeada: si `status` activo, `latest_decision.decision=REJECTED`, sin tareas abiertas y sin propuestas activas, cerrar como `REJECTED` con `source=lifecycle`.
2. Alternativamente, corregir `AutonomyNormalizer` para que no deje `status=OPEN` cuando normaliza una propuesta ya rechazada.
3. Ejecutar de nuevo `run_lifecycle` tras esa regla. Con los datos actuales, esa regla sacaría 14 iniciativas del WIP y dejaría WIP=5. Para bajar a ≤4 haría falta además resolver al menos una `VALIDATING` reciente con evidencia de validación, no por antigüedad.

## Cierre operativo

- No hubo cambios de código fuente; no aplica bump de versión ni suite completa.
- No hubo restart.
- Se creó backup antes de tocar el lifecycle: `data\backups\agente_bolsa_db_backup_e776472088db.sqlite3`.
- No se tocó conducta de trading.
- El intento de lifecycle oficial no cambió iniciativas, tareas ni propuestas; solo confirmó que el cauce actual no reduce este WIP.
- Verificación final:
  - `python -m agente_bolsa.main status`: `trading_mode=paper`, `allow_live_trading=false`, broker Alpaca paper.
  - `python -m agente_bolsa.main kernel-status --json`: `status=ok`, sin violaciones; `kernel.py`, `tools/broker.py`, `tools/execution.py` y `.env` coinciden con el sello.
  - `validate-agent-config` no existe como subcomando en esta versión de `main.py`; no se ejecutó una alternativa para evitar inventar un flujo fuera del CLI real.
