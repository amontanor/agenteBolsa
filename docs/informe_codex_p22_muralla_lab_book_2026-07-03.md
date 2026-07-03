# Informe P22 - Muralla lab book sobre `signal_outcomes`

Fecha: 2026-07-03

## Veredicto

**SEGURO habilitar lab book log-only**, condicionado a mantener
`data/config/lab_book.json` con `enabled=false` hasta decision explicita del
responsable.

La muralla queda implementada: las lecturas normales de `signal_outcomes` excluyen
`source='lab_book'` por defecto. La unica excepcion intencional es la maduracion de
outcomes, que usa `include_lab_book=True` para que el libro laboratorio aprenda sin
contaminar estudios ni decisiones del libro real.

No se habilito el lab book.

## Inventario de consumidores

| Consumidor | Tipo | Filtro tras P22 | Riesgo residual |
|---|---|---|---|
| `Store.signal_outcomes` | helper central | `include_lab_book=False` por defecto | Bajo; todos los consumidores normales heredan exclusion |
| `signal_learning.update_signal_outcomes` | maduracion | `include_lab_book=True` explicito | Bajo; solo calcula forward returns, no decide ni promueve |
| `signal_learning.build_learning_status` | learning/status | helper central excluye | Bajo |
| `edge_analysis.veto_forward_cohorts` | edge/backtest veto | helper central excluye | Bajo |
| `execution_linking.match_signal_row_for_buy_order` | enlace orden-senal | SQL `coalesce(source,'') != 'lab_book'` | Bajo; evita enlazar fills reales a lab |
| `profitability_scoreboard` | scoreboard paper | depende de `linked_executed_buy_signals` filtrado | Bajo |
| `exit_horizon_shadow` | horizonte salida | recibe linked rows filtradas | Bajo |
| `promotion_readiness` | readiness/promocion | matching filtrado + scoreboard filtrado | Bajo |
| `continuous_improvement.promotion` | promociones CI | helper central excluye | Bajo |
| `lesson_distiller` | memorias/lecciones | helper central excluye | Bajo |
| `continuous_improvement.agents` | contexto CI | helper central excluye | Bajo |
| `counterfactual_analysis` | estudios contrafactuales | helper central excluye | Bajo |
| `nightly_retrospective` | retrospectiva | helper central excluye | Bajo |
| `ops_reports` | reportes operativos | helper central excluye | Bajo |
| `pattern_scorecard` | scorecard patrones | helper central excluye | Bajo |
| `performance_baseline` | baseline performance | helper central excluye | Bajo |
| `prompt_replay` | replay prompts | helper central excluye | Bajo |
| `setup_edge.compute_setup_edge_table_from_connection` | setup edge SQL directo | SQL excluye lab cuando existe columna `source` | Bajo |
| `c2_shadow_reporting` | reporte C2 semanal | SQL excluye lab | Bajo |
| `opportunities` / `web_app` contexto LLM | fallback UI/decision context | SQL excluye lab | Bajo |
| `web_app._company_study_signal_rows` | estudio company | excluye lab salvo `sources=['lab_book']` explicito | Bajo |
| `operational_learning._signal_context` | memoria operacional | SQL excluye lab | Bajo |
| `scripts/study_strategy_edge_compare.py` | comparador estrategias | SQL excluye lab | Bajo |
| `scripts/study_setup_edge.py` | estudio setup edge | SQL excluye lab | Bajo |
| `scripts/study_edge_by_score.py` | estudio score/edge | SQL excluye lab | Bajo |
| `scripts/shadow_setup_edge_reweight.py` | reweight shadow | SQL excluye lab | Bajo |
| `scripts/study_near_miss_shadow.py` | near-miss shadow | SQL excluye lab | Bajo |
| `scripts/trading_block_metrics.py` | metricas bloqueo | SQL excluye lab | Bajo |
| `scripts/study_signal_duplication.py` | duplicacion real | SQL excluye lab | Bajo |
| `scripts/migrate_signal_outcomes_dryrun.py` | mantenimiento tabla | sin filtro por diseno | No contamina decisiones; opera sobre tabla fisica completa |
| `scripts/migrate_signal_outcomes_compact.py` | compactacion tabla | sin filtro por diseno | No contamina decisiones; opera sobre tabla fisica completa |

## Cambios aplicados

- `Store.signal_outcomes(..., include_lab_book=False)` excluye lab book por
  defecto.
- `update_signal_outcomes` pasa `include_lab_book=True` para madurar tambien las
  filas del laboratorio.
- Filtros SQL directos en matching de ejecucion, setup edge, C2 shadow, contexto
  de oportunidades/UI, operational learning y scripts de estudios.
- Test candado global: `tests/test_lab_book_wall.py`.
- Ajuste de tests propios de lab book para pedir `include_lab_book=True` cuando
  validan sus filas.
- Version: `0.4.103`.

## Validacion focal

Comando:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_lab_book_wall.py tests\test_lab_book.py tests\test_signal_learning.py tests\test_setup_edge.py tests\test_strategy_edge_compare.py tests\test_profitability_scoreboard.py tests\test_promotion_readiness.py tests\test_edge_analysis.py tests\test_operational_learning.py -q
```

Resultado: `60 passed`.

## Seguridad operativa

- No se tocaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py` ni `.env`.
- No se habilito `lab_book`.
- No cambia conducta de trading ni sizing.

## Verificacion estandar

- `pytest tests\ -x -q`: `913 passed, 1 warning`.
- `ruff check src tests scripts`: limpio.
- `python -m agente_bolsa.main status`: OK, `trading_mode=paper`,
  `allow_live_trading=false`.
- `python -m agente_bolsa.main validate-agent-config --json`: `ok=true`, sin
  errores ni warnings.
- `python -m agente_bolsa.main run-once --skip-crew`: OK, ciclo
  `20260703-061501`, sin LLM ni ordenes automaticas.
- Flags confirmados: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`,
  `core_sleeve_dry_run=true`, `lab_book_enabled=false`.
