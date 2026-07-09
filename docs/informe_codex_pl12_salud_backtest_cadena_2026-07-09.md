# Informe Codex P-L12 - salud operativa, error `backtest` y cadena de aprendizaje

Fecha: 2026-07-09
Version entregada: `0.4.135`

## A. Regeneracion periodica de salud operativa

Problema:
- `latest_operational_health.json` podia quedarse rancio durante horas.
- P-L8 habia dejado el kill switch en fail-open ante informe stale, pero sin
  regeneracion automatica el monitoreo quedaba ciego.

Cambio aplicado:
- Nuevo job residente `operational_health_refresh` en `src/agente_bolsa/scheduler.py`.
- Se ejecuta al arrancar el scheduler y cada 45 minutos.
- Queda visible en `schedule-status` con runtime propio.
- Si la regeneracion falla, solo se registra el fallo; no se revive ningun
  bloqueo por stale report. El kill switch por informe rancio sigue fail-open.

Evidencia real:
- `python -m agente_bolsa.main operational-health --json` regenero un informe nuevo.
- `python -m agente_bolsa.main schedule-status` ya lista `operational_health_refresh`.
- Ejecucion real directa del job: `status=completed`, `detail="operational health refrescado"`.

Tests:
- `tests/test_scheduler_observability.py`

## B. Diagnostico real del error `cannot access local variable 'backtest'`

Hallazgo:
- El texto no era alucinacion. Hay evidencia real en:
  - `data/logs/system.log`
  - `data/logs/agents/orchestrator.jsonl`
- La traza real apunta a:
  - `scheduler.py -> cycle_runner.py -> tools/signal_learning.py`
- Causa raiz:
  - `backtest` se inicializaba solo en la rama `recommendation.action == "buy"`.
  - Luego se reutilizaba al persistir features tambien para rutas `hold/no-buy`.

Fix:
- Inicializacion de `backtest` antes del bloque condicional en
  `src/agente_bolsa/tools/signal_learning.py`.
- No se anadieron `try/except` silenciosos ni overrides del gate.

Tests:
- Regresion en `tests/test_signal_learning.py`

## C. Cadena de aprendizaje de AIZ / CRWD / ALL

Diagnostico eslabon a eslabon:
- `broker_orders`: los 3 fills reales existen y quedaron reconciliados.
- `signal_outcomes`: las senales de origen existen con `features.cohort=learning_experiment`.
- `post_market_review`: existe y ya contenia AIZ, CRWD y ALL con P&L abierto.
- `lecciones`: `latest_operational_learning.json` si contenia la linea util, pero sin `session_date`.
- Corte real:
  - El digest enlazaba ejecuciones solo por `recommendation.source=learning_experiment`.
  - Las ordenes reales de ayer guardaron `recommendation.source=deterministic_*`,
    aunque si conservaron `plan.payload.cohort=learning_experiment`.

Cambio aplicado:
- El digest y la reconstruccion de cohortes aceptan ahora:
  - `recommendation.source`
  - `recommendation.cohort`
  - `plan.payload.cohort`
- `learning_experiment_yesterday` incorpora `execution_snapshot` por simbolo con:
  - estado de bracket (`open/closed`)
  - `open_pl`
  - `realized_pl`
  - `verdict`
  - `issue`
- Las lecciones reutilizan el journal operativo relevante por simbolo aunque el
  reporte legacy no traiga `session_date`.

Evidencia real tras regenerar el digest:
- `trades=3`
- `pnl.open=5.99`
- `execution_snapshot`:
  - `AIZ`: `open`, `open_pl=-10.29`, `verdict=debil_de_momento`
  - `CRWD`: `open`, `open_pl=15.89`, `verdict=bien_de_momento`
  - `ALL`: `open`, `open_pl=0.39`, `verdict=neutro_de_momento`
- `lessons` ya incluye:
  - `Ultimas decisiones revisadas: ALL buy winner_open (3 orden(es)), CRWD buy winner_open (3 orden(es)), AIZ buy loser_open (2 orden(es)).`

Conclusion de cohorte:
- No hizo falta re-etiquetar retroactivamente las 3 senales.
- La etiqueta de cohorte ya sobrevivia en `cohort=learning_experiment`; el bug
  era de lectura/enlace del digest, no de ausencia total de marca.

## Verificacion ejecutada

Focal:
- `python -m pytest tests/test_learning_loop.py tests/test_signal_learning.py tests/test_scheduler_observability.py -q`
- `python -m agente_bolsa.main learning-digest --json`
- `python -m agente_bolsa.main operational-health --json`

Completa:
- `python -m pytest tests/ -x -q`
- `ruff check src tests`
- `python -m agente_bolsa.main status`
- `python -m agente_bolsa.main validate-agent-config --json`
- `python -m agente_bolsa.main run-once --skip-crew`
