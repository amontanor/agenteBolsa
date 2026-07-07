# Informe Codex P-L4 - learning scoreboard - 2026-07-07

## Objetivo

Crear un scoreboard semanal honesto del cohorte `learning_experiment`, con criterio pre-registrado literal y sin inventar aprendizaje donde aun no hay fills reales.

## Entrega

- Nuevo modulo: `src/agente_bolsa/tools/learning_scoreboard.py`
- Nuevo comando:
  - `.\.venv\Scripts\python.exe -m agente_bolsa.main learning-scoreboard --json`
- Criterio pre-registrado embebido literalmente en codigo y artefacto:

`el sistema aprende si la expectancy neta media de las semanas 5-8 supera a la de las semanas 1-4 Y la pendiente semanal es positiva Y el resultado no lo explica solo el mercado (control: cohorte contrafactual de candidatos rechazados y/o selección aleatoria del universo con las herramientas counterfactual existentes — el aprendizaje debe batir a SU contrafactual, no solo al azar de un mes verde).`

## Metricas del scoreboard

Por semana de vida del experimento:

- `expectancy_net_10bps`
- `expectancy_net_20bps`
- `hit_rate`
- `profit_factor`
- `alpha_vs_spy`
- `max_drawdown`
- `n`
- `control_expectancy_net_10bps`

Tambien publica la tendencia explicita:

- `weekly_expectancy_net_10bps`
- `weekly_slope_expectancy_net_10bps`

## Evidencia real de hoy

Comando:

- `.\.venv\Scripts\python.exe -m agente_bolsa.main learning-scoreboard --json`

Resultado real:

- `cohort=learning_experiment`
- `weekly_rows=[]`
- `evaluation.status=pending_no_executed_cohort`
- `evaluation.learns=false`

Interpretacion:

- Hoy el scoreboard no maquilla nada: el cohorte ya existe, pero todavia no hay operaciones ejecutadas del experimento para evaluar aprendizaje real.
- Eso es coherente con G1 y G2: hubo shadow y observaciones, pero no fills.

## Tests sintéticos

Se añadieron tests para dos casos:

- `pending_no_executed_cohort`
- cohorte sintético de 8 semanas que SI cumple el criterio pre-registrado, incluyendo mejora semanas 5-8, pendiente positiva y batir al contrafactual

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests/test_learning_scoreboard.py -q`
  - `2 passed`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main learning-scoreboard --json`
  - estado real `pending_no_executed_cohort`

## Version

- `src/agente_bolsa/__init__.py`
- `0.4.117 -> 0.4.118`
