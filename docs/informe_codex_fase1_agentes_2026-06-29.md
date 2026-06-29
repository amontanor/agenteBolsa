# Informe Codex Fase 1 - Agentes de mejora continua

Fecha: 2026-06-29  
Repositorio: `C:\Antonio\Bref\agenteBolsa`  
Objetivo: ejecutar experimentos shadow desde el runtime residente y permitir que propuestas con evidencia lleguen a `READY_TO_APPLY`, sin aplicar codigo ni tocar trading real.

## Resultado ejecutivo

Fase 1 queda desbloqueada en el lab:

| Indicador | Antes Fase 1 | Despues Fase 1 |
|---|---:|---:|
| `continuous_improvement_experiments` | 0 | 4 |
| Propuestas `READY_TO_APPLY` | 0 | 1 |
| `continuous_improvement_applied_changes` | 0 | 0 |

La propuesta de prueba con evidencia quedo en cola humana:

- `proposal_id`: `ci_prop_8ec6df9615bd`
- Tipo: `PARAMETER_CHANGE`
- Componente: `entry_quality_filter`
- Target: `shadow_entry_quality_threshold_review`
- Estado final: `READY_TO_APPLY`
- Cambio aplicado: ninguno (`applied_changes=[]`)

## Que se cableo

1. `ExperimentRunner` se integra en el runtime residente de mejora continua.
   - El runtime llama a `ExperimentRunner.run_for_proposal(...)` antes de validar.
   - Los artefactos se persisten en `continuous_improvement_experiments`.
   - Cada experimento guarda `status`, `metrics`, `result` y `result.verdict`.

2. Se anadio experimento shadow `strategy_edge_compare`.
   - Reutiliza el motor existente de medicion `scripts.study_strategy_edge_compare`.
   - Cubre propuestas `PARAMETER_CHANGE` y `STRATEGY_RULE_CHANGE` con validaciones `in_sample`, `out_of_sample`, `walk_forward` o `strategy_edge_compare`.
   - Tambien se activa para componentes relacionados con `entry_quality` o `strategy`.
   - No toca trading, ordenes, broker, runtime de ejecucion ni codigo productivo aplicado.

3. La evidencia del experimento alimenta al `ValidationAgent`.
   - El runtime convierte cada experimento persistido en payload de reporte mediante `_experiment_report_payload`.
   - `strategy_edge_compare` se inyecta en `context["reports"]`.
   - La validacion acepta evidencia shadow solo cuando `robust_improvement=true`.

4. `READY_TO_APPLY` queda como final de Fase 1.
   - En dry-run, `AutoApplyCodeAgent.try_apply(...)` solo se invoca si `proposal_type == CODE_CHANGE`, `validation == READY_TO_APPLY`, `improvement_dry_run == false` y `allow_auto_apply_improvements == true`.
   - Con el lab actual, la propuesta queda en cola humana y no se escribe ningun `applied_change`.

5. Se anadio observabilidad CLI.
   - Nuevo comando: `continuous-improvement-lab phase1-status --limit N`.
   - Resume runtime, experimentos recientes, cola `READY_TO_APPLY` y cambios aplicados.

## Evidencia en base de datos

Consulta posterior al reinicio:

```json
{
  "experiments_count": 4,
  "ready_to_apply_count": 1,
  "applied_changes_count": 0
}
```

Experimento principal:

- `experiment_id`: `ci_exp_5c2161eef1e0`
- `proposal_id`: `ci_prop_8ec6df9615bd`
- `experiment_type`: `strategy_edge_compare`
- `status`: `PASSED`
- `result.verdict`: `PASSED`
- `robust_improvement`: `true`
- `deduped_rows`: 1661

Metricas relevantes:

| Estrategia | Horizonte | n | coverage | hit_rate | mean_net |
|---|---:|---:|---:|---:|---:|
| `builtin_breakout` | 1d | 995 | 0.6664 | 0.5347 | 0.00256 |
| `builtin_pullback` | 1d | 110 | 0.6548 | 0.5636 | 0.00094 |

Validacion que promovio:

- `validation_id`: `ci_val_2d237a5bbb25`
- `proposal_id`: `ci_prop_8ec6df9615bd`
- `status`: `READY_TO_APPLY`
- `objective_status`: `READY_TO_APPLY`

Checks:

| Check | Resultado |
|---|---|
| `safety_flags` | passed |
| `rollback_plan_present` | passed |
| `blocked_entry_quality_detected` | passed |
| `strategy_edge_experiment_present` | passed (`deduped_rows=1661`, `robust_improvement=true`) |

## Por que se desbloqueo la validacion

Fase 0 dejo dos bloqueos confirmados:

1. El runner existia, pero no estaba cableado al runtime residente.
2. El comite/validacion no recibia evidencia objetiva suficiente para pasar a `READY_TO_APPLY`; las iniciativas acababan en revision humana o expiraban.

Fase 1 corrige el camino minimo:

- `ExperimentDesignerAgent`/propuesta declara validaciones.
- Runtime ejecuta experimentos shadow antes de validar.
- `ExperimentRunner` persiste el resultado.
- `ValidationAgent` ve `strategy_edge_compare`.
- Si el experimento es robusto y las safety flags estan cerradas, la propuesta pasa a `READY_TO_APPLY`.
- El apply queda bloqueado por dry-run y flags de auto-apply.

Ademas, se ajusto una discrepancia estrecha del comite: si la decision determinista aprueba y la respuesta LLM discrepa sin justificar, se conserva el `APPROVE` determinista. Las discrepancias justificadas siguen pudiendo escalar.

## No aplicado / no tocado

No se tocaron los ficheros prohibidos:

- `src/agente_bolsa/risk.py`
- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/config.py`
- `.env`

Confirmaciones operativas:

- `TRADING_MODE=paper`
- `ALLOW_LIVE_TRADING=false`
- Broker Alpaca paper activo
- Posiciones: `[]`
- Ordenes abiertas: `[]`
- `kernel-status --json`: `ok=true`, `violations=[]`

## Validacion tecnica

Comandos ejecutados:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -x -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status
.\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health --json
.\.venv\Scripts\python.exe -m agente_bolsa.main production-health --json
.\.venv\Scripts\python.exe -m agente_bolsa.main market-data-quality --json
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab phase1-status --limit 3
```

Resultado:

- `pytest`: `782 passed, 1 warning`
- `ruff`: `All checks passed`
- `status`: paper/false confirmado
- `kernel-status`: ok, sin violaciones
- `broker-status`: paper activo
- `portfolio-status`: sin posiciones ni ordenes abiertas
- `production-health`: scheduler heartbeat fresco y CI heartbeat fresco
- `market-data-quality`: `ok=true`, coverage 1.0, blockers 0

El comando `validate-agent-config --json` no existe en el CLI de esta rama; argparse lo rechaza como comando invalido.

## Reinicio

Se uso el helper del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_services.ps1
```

Resultado:

- Un unico scheduler del `.venv`
- Panel HTTP 200 en `http://127.0.0.1:8501`
- `portfolio_watch` fresco tras el arranque
- `continuous_improvement` heartbeat fresco

Alertas operativas tras el reinicio:

- 0 criticas
- Warnings existentes: `job_slow` de `market_cycle`, deterioro de setups y backlog CI por encima del limite WIP.
- `market-data-quality` reporto 16 alertas de barras/anomalias puntuales y 0 blockers.

## Cambios de codigo

Archivos modificados:

- `src/agente_bolsa/continuous_improvement/experiments.py`
- `src/agente_bolsa/continuous_improvement/runtime.py`
- `src/agente_bolsa/continuous_improvement/agents.py`
- `src/agente_bolsa/main.py`
- `src/agente_bolsa/__init__.py`
- `tests/test_continuous_improvement.py`

Version:

- `0.4.64` -> `0.4.65`

Tests nuevos o ajustados:

- Promocion de experimento shadow a `READY_TO_APPLY` sin auto-apply.
- Garantia de que `CODE_CHANGE` en dry-run queda en cola y no aplica.
- Conservacion del `APPROVE` determinista cuando el LLM discrepa sin razon.
- Persistencia de experimentos generados por el runner.

## Riesgos y limites

1. El experimento robusto actual se apoya en horizonte 1d porque horizontes 3d/5d/10d siguen pendientes para la ventana reciente. Es suficiente para probar el cableado de Fase 1, no para activar Fase 2 sin revision humana.

2. La metrica `robust_improvement` acepta una estrategia con muestra suficiente, `mean_net>0`, `hit_rate>=0.50` y `coverage>=0.25`, aunque el delta pullback-vs-breakout de 1d sea negativo. Esto evita bloquear propuestas cuando una alternativa absoluta tiene edge positivo, pero Fase 2 deberia revisar si la decision final debe exigir delta positivo contra baseline.

3. Sigue existiendo backlog CI alto (`active_initiatives=13`, `validating_initiatives=12`). Fase 1 demuestra que ya no todo expira por falta de experimento, pero no limpia automaticamente todo el backlog historico.

## Recomendacion priorizada

1. Fase 2 debe empezar por la cola humana `READY_TO_APPLY`, no por auto-apply.
   - Revisar `ci_prop_8ec6df9615bd`.
   - Exigir confirmacion humana del criterio estadistico.
   - Decidir si el criterio de robustez debe usar delta positivo frente a baseline como requisito duro.

2. Despues, endurecer el modelo de experimento.
   - Separar `absolute_edge_positive` de `baseline_delta_positive`.
   - Guardar ambos en `result`.
   - Promocionar a `READY_TO_APPLY` solo si el tipo de propuesta pide exactamente ese criterio.

3. Solo cuando la cola humana sea estable, abordar codigo/apply.
   - Mantener `applied_changes=0` hasta Fase 2.
   - No habilitar auto-apply mientras `improvement_dry_run=true` o falte aprobacion explicita.
