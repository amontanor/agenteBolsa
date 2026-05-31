# Checklist de Promocion de Reglas y Cambios

Objetivo: evitar activar thresholds, prompts, setups o reglas adaptativas sin evidencia suficiente.

## Requisitos minimos antes de promocionar

- El cambio tiene un identificador y una motivacion escrita.
- Hay tests unitarios o de integracion que cubren la logica nueva o el bug corregido.
- Hay backtest reproducible con costes y slippage.
- Hay validacion cronologica `walk-forward` o retrospectiva equivalente sin fuga temporal.
- Hay evidencia en `paper trading` si el cambio afecta decision, riesgo o ejecucion.
- El cambio no degrada trazabilidad, `kill switch`, gates de entrada ni validaciones de riesgo.

## Evidencia obligatoria por tipo de cambio

- `thresholds` o gates:
  debe incluir impacto en `blocked_entry_quality`, `blocked_backtest`, ganadores bloqueados y perdedores evitados.
- prompts LLM:
  debe incluir comparacion A/B o sesion-retrospective; no basta una explicacion subjetiva.
- setup tecnico:
  debe incluir muestra minima, estabilidad por setup y comparacion contra `SPY` o baseline actual.
- regla adaptive o shadow:
  debe incluir estado `shadow`, estabilidad por ventanas y criterio explicito de rollback.

## Bloqueos automaticos

- No promover si la muestra es pequena o concentrada en pocas sesiones.
- No promover si mejora retorno pero empeora drawdown materialmente.
- No promover si rompe compatibilidad con `paper` o reduce trazabilidad en SQLite/reportes.
- No promover si depende de datos no auditados o de un provider no controlado.

## Salida esperada de cada propuesta

- `cambio`: que se activa exactamente.
- `evidencia`: tests, backtest, walk-forward, paper.
- `riesgo`: impacto esperado en drawdown, turnover y bloqueos.
- `rollback`: como desactivar o revertir.
- `decision`: `shadow`, `guarded_active`, `active` o `rejected`.
