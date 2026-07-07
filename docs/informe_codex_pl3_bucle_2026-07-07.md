# Informe Codex P-L3 - bucle de aprendizaje cerrado - 2026-07-07

## Objetivo

Cerrar el bucle del cohorte `learning_experiment` para que, cuando lleguen los primeros fills reales, quede trazado y medible de extremo a extremo: fill -> reconciliation -> `signal_outcomes`/`learning_observations` -> `post_market_review` -> memorias/lecciones -> puente a propuestas.

## Cambios entregados

- `learning-digest` incorpora la seccion `learning_experiment_yesterday`.
- El cohorte ya se reconstruye y materializa explicitamente desde `signal_outcomes` con `source=learning_experiment`.
- El digest publica:
  - senales del cohorte
  - observaciones canonicas
  - trades del cohorte
  - P&L
  - outcomes maduros
  - lecciones
  - estado de cada eslabon del pipeline
- `continuous-improvement-lab findings-to-proposals --json` expone `learning_experiment_bridge` y puede persistir propuestas no-code del cohorte cuando existan evidencias accionables.
- El bridge ya no degrada propuestas no-code a `CODE_CHANGE`.

## Evidencia real de hoy

### Digest real

Comando:

- `.\.venv\Scripts\python.exe -m agente_bolsa.main learning-digest --json`

Resultado principal del cohorte:

- `learning_experiment_yesterday.available=true`
- `session_date=2026-07-07`
- `signals=543`
- `observations=497`
- `trades=0`
- `matured_outcomes.3d=0`
- shadow real presente con:
  - `LYV`
  - `notional=924.15`
  - `entry=184.83`
  - `stop=174.6679`
  - `take=200.0732`

Leccion publicada hoy por el digest:

- `Shadow registrado sin fills reales todavia; quedan pendientes reconciliation y post-market del primer fill.`

### Puente a la firma

Comando:

- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab findings-to-proposals --json`

Resultado del bridge:

- `learning_experiment_bridge.available=true`
- `signal_outcomes.status=ok`
- `learning_observations.status=ok`
- `broker_reconciliation.status=pending_first_fill`
- `post_market_review.status=pending_first_fill`
- `memories_lessons.status=pending_first_fill`
- `findings_to_proposals.status=wired_no_actionable_evidence`

Interpretacion:

- El material del cohorte ya entra en el cauce normal.
- Hoy no genera propuesta accionable porque aun no hay fills reales ni outcomes maduros del cohorte, y eso es el comportamiento correcto.

## Eslabones verificados hoy con shadow

- `signal_outcomes` del cohorte: verificado.
- Materializacion a `learning_observations`: verificada.
- Digest matinal con seccion propia del cohorte: verificado.
- Puente findings -> proposals con lectura del cohorte: verificado.
- Honestidad del estado pendiente cuando no hay fills: verificada.

## Eslabones pendientes del primer fill real

- Fill real en `broker_orders`: pendiente.
- `broker_reconciliation` enlazando el fill del cohorte: pendiente.
- `executed_buy` del cohorte en `learning_observations`: pendiente.
- P&L real del cohorte en digest/post-market: pendiente.
- `post_market_review` del mismo trade como evidencia directa: pendiente.
- Memorias/lecciones destiladas especificamente del cohorte ejecutado: pendiente.
- Primera propuesta accionable derivada de ese cohorte con evidencia citada: pendiente.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests/test_learning_loop.py tests/test_findings_to_proposals.py -q`
  - `5 passed`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main learning-digest --json`
  - cohorte visible y pipeline instrumentado
- `.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab findings-to-proposals --json`
  - bridge visible y sin falsas propuestas

## Version

- `src/agente_bolsa/__init__.py`
- `0.4.116 -> 0.4.117`
