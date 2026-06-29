# Informe Codex fixes 2026-06-29

Contexto operativo: cambios limitados a runtime no trading. No se tocaron `risk.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py`, `config.py` ni `.env`.

## 1. Catch-up de `daily_study`

### Hallazgo confirmado

`daily_study` estaba implementado como cron puro en `src/agente_bolsa/scheduler.py`. Si la app estaba cerrada a la hora programada, la sesion cerrada quedaba perdida. `post_market_review`, en cambio, ya seguia un patron robusto: comprobador periodico, estado `*_last_session` y bootstrap al arrancar.

### Cambio aplicado

Se alineo `daily_study` con el patron de `post_market_review`:

- `daily_study_job(...)` ahora deduplica por sesion con `daily_study_last_session`.
- El job se ejecuta como comprobador periodico cada `closed_market_study_interval_minutes`, no como cron puntual.
- En bootstrap del scheduler con mercado cerrado, `run_scheduler_forever(...)` invoca `daily_study_job(...)` una vez igual que ya hacia con `post_market_review`.
- El criterio temporal sigue siendo el mismo que `post_market_review`: `MarketCalendar.should_run_daily_study()`. No se abrio una ventana nueva ni se relajo el gate; solo se evita perder la sesion cerrada si la app estuvo apagada.

Archivos tocados:

- [src/agente_bolsa/scheduler.py](C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/scheduler.py)
- [tests/test_scheduler_observability.py](C:/Antonio/Bref/agenteBolsa/tests/test_scheduler_observability.py)

### Tests anadidos

- `test_daily_study_job_catches_up_once_per_closed_session`
  - simula sesion cerrada sin `daily_study` previo;
  - el checker ejecuta el estudio una vez;
  - una segunda llamada en la misma sesion queda en `skipped`.
- `test_daily_study_job_skips_when_session_already_processed`
  - si `daily_study_last_session` ya coincide, no vuelve a lanzar `run_observable_cycle`.

### Decision de diseno

No mantuve el cron anterior en paralelo. El job pasa a ser un checker idempotente por sesion, igual que `post_market_review`. Eso evita duplicidades y resuelve el problema exacto de sesiones perdidas con la app cerrada.

## 2. Fix de expiracion del lifecycle CI

### Investigacion read-only previa

Causa confirmada:

- El normalizador/autonomia refresca `updated_at` de la iniciativa via `Store.update_continuous_improvement_initiative(...)`.
- El lifecycle usaba `initiative.updated_at` como proxy de inactividad en `resolve_initiatives(...)`.
- Resultado: iniciativas viejas sin trabajo real seguian pareciendo "recientes" por puro bookkeeping.

Puntos concretos:

- `src/agente_bolsa/continuous_improvement/runtime.py`
  - `AutonomyNormalizer` actualiza iniciativas y por tanto toca `updated_at`.
  - tambien se refresca `updated_at` al append de links y otras transiciones internas.
- `src/agente_bolsa/storage.py`
  - `update_continuous_improvement_initiative(...)` siempre anade `updated_at = _utc_iso()`.
- `src/agente_bolsa/continuous_improvement/lifecycle.py`
  - antes del fix: `idle_days = age(updated_at)`.

### Cambio aplicado

Se sustituyo la nocion de inactividad por una marca de actividad real:

- Nueva helper en `Store`: `continuous_improvement_initiative_last_activity_at(...)`.
- La marca de actividad toma el maximo de:
  - `updated_at` de tareas ligadas;
  - `updated_at` de propuestas ligadas;
  - `created_at` de validaciones ligadas;
  - `created_at` de mensajes de iniciativa.
- Si no hay actividad ligada, el fallback es `created_at` de la propia iniciativa.
- `resolve_initiatives(...)` ya no usa `initiative.updated_at`; usa la helper anterior para calcular `idle_days`.

Archivos tocados:

- [src/agente_bolsa/storage.py](C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/storage.py)
- [src/agente_bolsa/continuous_improvement/lifecycle.py](C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/continuous_improvement/lifecycle.py)
- [tests/test_ci_lifecycle.py](C:/Antonio/Bref/agenteBolsa/tests/test_ci_lifecycle.py)

### Tests anadidos

- `test_stalled_initiative_uses_real_activity_not_initiative_updated_at`
  - una iniciativa vieja con `updated_at` reciente pero sin actividad real expira.
- `test_recent_real_activity_prevents_stalled_expiration_even_if_old_initiative`
  - una iniciativa vieja con mensaje real reciente no expira.

Ademas, siguio pasando el test previo:

- `test_churning_initiative_expires_even_when_normalizer_refreshes_updated_at`

### Backup antes de mutar estado

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main backup-db
```

Backup creado:

- `data\backups\agente_bolsa_db_backup_6339eba1a4f5.sqlite3`

### Ejecucion del lifecycle oficial

Comando/logica ejecutada:

```python
before = flow_report(store)
result = run_lifecycle(store, settings)
after = flow_report(store)
```

### Resultado real en la BD operativa

Foto antes del fix, medida con `production-health`:

- `active_initiatives = 21`
- `validating_initiatives = 5`
- warning presente: `ci_backlog_over_wip_limit`

Composicion observada antes:

- 14 iniciativas `OPEN` antiguas, creadas el `2026-06-15`, sin tareas abiertas ni propuestas activas, pero con `updated_at` refrescado el `2026-06-29` por el normalizador.
- 5 iniciativas `VALIDATING` recientes y activas.
- 2 iniciativas `OPEN` nuevas del mismo dia.

Despues del fix y del lifecycle oficial:

- `active_initiatives = 7`
- `validating_initiatives = 7`
- el warning `ci_backlog_over_wip_limit` desaparecio
- quedo solo `ci_validation_backlog`

Es decir:

- el bug de drenaje por `updated_at` falso quedo resuelto;
- se drenaron las iniciativas genuinamente inactivas;
- el WIP no bajo a `<=4` porque siguen 7 iniciativas recientes y activas, no porque el lifecycle siga roto.

### Iniciativas drenadas por el fix

Quedaron en `REJECTED` por `latest_decision.source = lifecycle` y razon `estancada 14.2 dias sin avance`:

- `trading:risk_manager`
- `trading:strategy_parameters`
- `trading:duplicate_reduction`
- `software:duplicate_reduction`
- `trading:p4`
- `software:observation_executor`
- `software:p001`
- `trading:confidence_calibration_monitor`
- `trading:short_term_monitoring`
- `software:pre_earnings_risk_veto`
- `software:p002`
- `software:p003`
- `software:enhance_analyst_estimation_coverage`
- `software:setup_priority_adjustment`

### Estado restante y por que no lo force

Las 7 iniciativas que siguen activas estan en `VALIDATING` y son recientes:

- `software:gradual_observation_execution`
- `software:cycle_end_observation_retry`
- `software:initiative_stuck_alert`
- `software:proposal_validation_details`
- `software:observation_execution_bypass`
- `software:observation_scheduler`
- `software:deterministic_gate`

Las dos ultimas quedaron en `VALIDATING` por el propio lifecycle con razon `all_tasks_terminal_with_active_proposals`. Forzarlas a cierre solo para cumplir `WIP <= 4` habria sido incorrecto: son backlog activo legitimo, no basura estancada.

### Concluson operativa de Tarea 2

El fix corrige la causa pedida:

- la expiracion ya no depende de `initiative.updated_at`;
- depende de actividad real de tarea/propuesta/validacion/mensaje;
- el WIP se drena automaticamente cuando la iniciativa esta vieja e inactiva de verdad.

No se alcanzo `<=4` porque el estado live ya tenia 7 iniciativas activas recientes. El warning de exceso de WIP desaparecio, pero permanece `ci_validation_backlog`, que es coherente con el estado actual.

Tras el restart final del runtime, el laboratorio reanudo actividad y `production-health` quedo en:

- `active_initiatives = 8`
- `validating_initiatives = 8`
- sigue sin `ci_backlog_over_wip_limit`
- sigue presente solo `ci_validation_backlog`

Ese `8` no indica regresion del fix: es trabajo nuevo/activo generado por el runtime tras reanudarse, no reapertura de las 14 iniciativas viejas drenadas por el lifecycle.

## Verificacion

Comandos ejecutados durante la entrega:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\agente_bolsa\scheduler.py src\agente_bolsa\storage.py src\agente_bolsa\continuous_improvement\lifecycle.py tests\test_scheduler_observability.py tests\test_ci_lifecycle.py
.\.venv\Scripts\python.exe -m pytest tests\test_ci_lifecycle.py tests\test_scheduler_observability.py -q
.\.venv\Scripts\python.exe -m agente_bolsa.main production-health --json
.\.venv\Scripts\python.exe -m agente_bolsa.main backup-db
```

Verificaciones finales exigidas por la tarea se ejecutan al cierre:

- `pytest` completo
- `ruff check src tests`
- restart de servicios/runtime
- `status`
- `kernel-status --json`

Resultados finales:

- `python -m pytest tests -q -p no:warnings`: `772 passed`
- `python -m ruff check src tests`: `All checks passed!`
- restart ejecutado con `scripts/restart_services.ps1`
- `python -m agente_bolsa.main status`: `trading_mode=paper`, `allow_live_trading=false`
- `python -m agente_bolsa.main kernel-status --json`: `status=ok`, sin violaciones
- `python -m agente_bolsa.main schedule-status`: `daily_study` ya figura como checker cada 15 minutos por sesion cerrada
