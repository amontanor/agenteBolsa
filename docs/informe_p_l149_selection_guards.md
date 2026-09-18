# P-L149 — veto a tóxicos + cuota sin_patron en fallback (candidato 0.4.251)

Dictamen: `ready_for_review`. XNYS abierto (18-sep-2026); trabajo
aislado, sin broker/red/LLM en pruebas, sin despliegue.

## Causa

Cohorte comprado con edge neto negativo (`confirmed|strong -0.43%`,
`score≥18 -4.99%` 10d, estudio jun-2026 un régimen). Subir tamaño sin
arreglar cohorte multiplica pérdidas: selección primero (P-L148 en espera).

## Cambio (guarded_active, reversible por flags)

- Veto en fallback: `score≥TOXIC_SCORE_CAP (18.0)` o `return_20d≥
  TOXIC_RETURN_20D_CAP (0.20)` → excluido con razón
  `toxic_extreme_score/momentum`. Eximen las excepciones de extensión
  deliberadas (follow-through/pullback): el veto muerde extremos sin
  tesis, no paths con evidencia propia.
- Cuota `SIN_PATRON_QUOTA=1`: si el top-N no trae `sin_patron|strong`,
  el mejor por score entra por el último finalista. Etiqueta honesta en
  reason: `Cuota sin_patron|strong (guarded P-L149)`. Nunca amplía el
  límite ni inventa candidatos.
- Telemetría: `selection_report` opcional + metadatos en augment
  (`toxic_vetoed/count`, `sin_patron_quota`) para medir efecto en vivo.
- Settings nuevos con alias (`TOXIC_*`, `SIN_PATRON_*`). Selección LLM,
  scores, universo, riesgo y sizing intactos. `.env` intacto.

## QA

- Nuevos: `tests/test_p149_selection_guards.py` (8 tests: veto x2,
  límites, flag-off, cuota x3, metadatos).
- Regresiones: trade_decision, opportunity_ranker, setup_edge (146 tests).
  Total: 154 passed.
- Dos fixtures legacy `score=18`→`17` (comportamiento vetado ahora
  cubierto por tests propios). Tests de excepciones de extensión pasan
  SIN cambios: la exención funciona.
- `test_version_policy` verde tras bump `0.4.248` → `0.4.251`. Ruff,
  `check_no_nulls.py` (514), `git diff --check` verdes.
- Omitidos (sesión abierta): suite, smoke, config/kernel, despliegue.

## Promoción y siguiente

- Criterio active: 5+ sesiones con `toxic_veto_count>0` o quota fills,
  drawdown/MAE/tail sanos, sin aumento de `cycle_missed`. Rollback:
  flags a false (un commit).
- Siguiente: merge tras el cierre + suite + splice Jetson con P-L147
  (+P-L148 si se autoriza su Fase 1).
