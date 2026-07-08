# Informe Codex P-L10 - excepcion low-sample

Fecha: 2026-07-08
Version: 0.4.133
Rama: `codex/mejora_continua`

## Objetivo

Permitir en `learning_mode` la excepcion low-sample autorizada por Antonio para
senales cuyo unico bloqueo de backtest sea `trades < minimo`, con cuota
persistente maxima de 1 orden por dia y trazabilidad completa en aprendizaje,
embudo y digest.

## Cambios aplicados

- `src/agente_bolsa/cycle_runner.py`
  - Nueva ruta `learning_low_sample_exception` dentro del gate de backtest.
  - Rechazo explicito si la muestra corta tambien falla hit-rate, PF, alpha o
    regimens fuera de near-miss.
  - Cuota persistente por dia en `runtime_state` y bloqueo claro cuando la quota
    esta agotada o desactivada.
  - Etiquetado de recomendaciones/ordenes con `low_sample_exploration`.
- `src/agente_bolsa/tools/learning_mode.py`
  - Nuevo campo gobernado `low_sample_daily_quota` con clamp entero `>= 0`.
- `src/agente_bolsa/tools/signal_learning.py`
  - Propagacion de `low_sample_exploration` y `tags` a `signal_outcomes.features`.
- `src/agente_bolsa/tools/cycle_funnel.py`
  - Linea visible `low_sample: usado/quota hoy`.
- `src/agente_bolsa/continuous_improvement/digest.py`
  - Linea visible de uso diario en el digest del lab.
- `data/config/learning_mode.json`
  - `low_sample_daily_quota: 1`
  - `authorized_by: Antonio 2026-07-08`
  - nota explicita de autorizacion.

## Verificacion

- Tests especificos nuevos:
  - pasa cuando el unico fallo es muestra insuficiente y hay cupo.
  - no pasa si hit-rate cae fuera de near-miss.
  - no pasa la segunda del dia con quota agotada.
  - `low_sample_daily_quota=0` lo apaga.
  - la feature llega a `signal_outcomes`.
  - embudo y digest muestran el uso diario.
- Resultado focal:
  - `python -m pytest tests/test_learning_mode.py tests/test_signal_learning.py tests/test_cycle_funnel.py tests/test_ci_phase3_digest.py -q`
  - `54 passed`
- Suite completa:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\ -x -q`
  - `1027 passed, 1 warning`
- Lint:
  - `.\.venv\Scripts\ruff.exe check src tests`
  - `All checks passed!`
- Config y runtime:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json` -> `ok=true`
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main status` -> paper, broker Alpaca paper configurado, gates activos.

## Ejecucion real / evidencia operativa

- Run real sin crew:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`
  - Resultado: ciclo `20260708-173507` completado sin traceback; `market_state_quality=PARTIAL`; sin ordenes nuevas porque el ciclo fue solo de analisis.
- Embudo vivo:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel --json`
  - Resultado: `trade_execution_summary`, `completed_without_orders`, `low_sample_usage={}` en el evento actual (ninguna excepcion usada hoy en esta evidencia).
- Digest vivo:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days 1 --json`
  - Resultado: `learning_mode.enabled=true`, `authorized_by=Antonio 2026-07-08`, `low_sample_usage={"quota":1,"used":0}`.

Como hoy no se ha consumido una excepcion low-sample en produccion, la prueba de
visibilidad `1/1 usado hoy` queda cubierta por los tests de integracion verdes y
por el hecho de que el digest real ya expone `quota=1, used=0` en estado vivo.
