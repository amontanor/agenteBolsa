# Informe Codex P26 - Auditoria de producto

Fecha: 2026-07-03

## 1. Configuracion efectiva

Valores cargados con `.env` real y defaults de codigo (`Settings(_env_file=None)`). `Plan` indica si aparece en `docs/plan_mejoras_y_tareas.md`.

| Parametro | Efectivo | Default | Plan | Nota |
|---|---:|---:|---|---|
| `trading_mode` | `paper` | `paper` | no | OK, pero el plan no lo lista como control principal. |
| `allow_live_trading` | `false` | `false` | si | OK. |
| `auto_paper_trading` | `true` | `false` | no | Diverge del default; necesita estar documentado. |
| `require_human_approval` | `false` | `true` | no | Diverge del default; aceptable solo por paper, pero poco visible. |
| `allow_auto_apply_improvements` | `false` | `true` | no | Incoherencia documental: el valor seguro es OFF, el default de codigo es ON. |
| `improvement_dry_run` | `false` | `false` | no | Seguro por `allow_auto_apply=false`, pero el nombre induce a pensar que el lab no aplica. |
| `continuous_improvement_enabled` | `true` | `true` | no | Activo. |
| `continuous_improvement_schedule_enabled` | `true` | `false` | no | Diverge; documentar cadencia real. |
| `continuous_improvement_max_proposals_per_cycle` | `5` | `5` | no | OK. |
| `continuous_improvement_runtime_interval_seconds` | `60` | `60` | no | OK. |
| `continuous_improvement_group_cooldown_seconds` | `300` | `300` | no | OK. |
| `ci_max_open_initiatives` | `4` | `4` | no | OK. |
| `ci_recurring_cooldown_hours` | `24` | `24` | no | OK. |
| `ci_task_ttl_hours` | `48` | `48` | no | OK. |
| `ci_validation_backlog_ttl_days` | `2` | `2` | no | OK. |
| `ci_build_strategy_enabled` | `false` | `false` | no | OFF correcto. |
| `ci_sandbox_enabled` | `true` | `true` | no | OK. |
| `code_autonomy_level` | `1` | `1` | si | OK. |
| `require_human_approval_for_code_changes` | `false` | `false` | no | Seguro por `allow_auto_apply=false`; documentar dependencia. |
| `require_human_approval_for_high_risk` | `true` | `true` | no | OK. |
| `improvement_llm_enabled` | `true` | `false` | no | Diverge; gasto relevante. |
| `improvement_llm_provider` | `opencode-go` | `opencode-go` | no | OK. |
| `improvement_llm_model` | `glm-5.2` | `kimi-k2.6` | no | Diverge; revisar por coste/calidad. |
| `improvement_llm_orchestrator_model` | `deepseek-v4-flash` | `kimi-k2.6` | no | Diverge; usado por overnight/codegen. |
| `improvement_llm_max_tokens` | `6000` | `6000` | no | OK. |
| `improvement_llm_context_target_tokens` | `12000` | `40000` | no | Diverge a favor de coste. |
| `llm_daily_budget_usd` | `5` | `5` | no | OK. |
| `llm_role_deep_daily_budget_usd` | `3` | `3` | no | OK. |
| `overnight_learning_enabled` | `true` | `true` | no | Activo. |
| `overnight_learning_use_llm` | `true` | `true` | no | Activo; ahora con fallback determinista. |
| `overnight_learning_time_local` | `00:10` | `00:10` | no | OK. |
| `overnight_learning_stale_llm_alert_hours` | `24` | `24` | no | OK. |
| `trade_aggressiveness_profile` | `opportunistic` | `opportunistic` | no | Sensible; deberia estar en plan. |
| `max_orders_per_cycle` | `4` | `4` | si | OK. |
| `max_daily_buy_orders` | `4` | `4` | si | OK. |
| `min_llm_confidence_to_trade` | `0.65` | `0.65` | no | Sensible; documentar. |
| `entry_quality_gate_enabled` | `true` | `true` | no | OK. |
| `backtest_gate_enabled` | `true` | `true` | no | OK. |
| `pre_earnings_enabled` | `true` | `true` | no | OK. |
| `data/config/core_sleeve.json` | `enabled=true, dry_run=true` | fichero | no | Config efectiva vive fuera de `Settings`; riesgo de flags muertos/duplicados. |
| `data/config/lab_book.json` | existe | fichero | no | Tambien file-based; no aparece como `Settings`. |
| `data/config/ci_research_mode.json` | `enabled=false` | fichero | no | Human-gated y OFF; correcto. |

Incoherencias principales:

- Defaults inseguros o confusos: `allow_auto_apply_improvements` default `true` aunque el operativo seguro es `false`.
- Config file-based (`core_sleeve`, `lab_book`, `ci_research_mode`) no esta reflejada en `Settings`, por eso aparece como `null` si se audita solo por `.env`.
- Muchos flags operativos clave no estan documentados en el plan maestro.

## 2. Utilizacion del cast de agentes

Ventana: ultimas 4 semanas de `continuous_improvement_proposals`.

| Agente | Propuestas | % CODE_CHANGE | % rechazadas | % gates/constitucion | % experimento/diff | Veredicto |
|---|---:|---:|---:|---:|---:|---|
| `OrchestratorAgent` | 969 | 4.23% | 98.14% | 1.03% | 3.20% | Mucho volumen, mucho ruido. Re-instruir y capar. |
| `SoftwareReliabilityAgent` | 96 | 17.71% | 100.00% | 0.00% | 0.00% | Produce algo de codigo pero no llega a diff. Re-instruir con contrato P25. |
| `StrategyEvaluatorAgent` | 82 | 6.10% | 100.00% | 0.00% | 0.00% | Retirar de generacion autonoma de propuestas; dejarlo como evaluador. |
| `DataQualityAgent` | 41 | 0.00% | 100.00% | 0.00% | 0.00% | Re-instruir; hoy no alimenta codegen. |
| `PreEarningsSpecialistAgent` | 8 | 12.50% | 100.00% | 0.00% | 0.00% | Mantener solo si aporta evidencia medida. |
| `UNKNOWN` | 5 | 100.00% | 40.00% | 0.00% | 100.00% | Rutas manuales/herramientas funcionan; etiquetar mejor. |
| `ExperimentDesignerAgent` | 5 | 0.00% | 100.00% | 0.00% | 20.00% | Util como validador, no como proponente. |
| `FindingsToProposals` | 3 | 100.00% | 0.00% | 0.00% | 0.00% | Potenciar: contrato determinista y elegible. |

Ranking aporte vs ruido:

1. Potenciar: `FindingsToProposals` y rutas manuales/UNKNOWN hasta etiquetarlas.
2. Re-instruir: `SoftwareReliabilityAgent`, `DataQualityAgent`.
3. Capar volumen: `OrchestratorAgent`.
4. Retirar como proponentes: `StrategyEvaluatorAgent`, `ExperimentDesignerAgent` salvo validacion/evaluacion.

## 3. Gasto LLM por rol

Ventana: ultimas 2 semanas, tabla `llm_usage`.

| Rol/fuente | Requests | Prompt | Completion | Total tokens | Lectura |
|---|---:|---:|---:|---:|---|
| `decision/trade_decision` | 196 | 6,024,365 | 1,069,955 | 7,094,320 | Principal gasto; auditar prompts y cache/contexto. |
| `continuous_improvement` | 347 | 2,458,667 | 96,415 | 2,555,082 | Alto volumen para bajo yield historico; P25 reduce ruido. |
| `sentiment/news_sentiment` | 266 | 584,546 | 494,542 | 1,079,088 | Completion muy alto; revisar formato de salida. |
| `operational_learning` | 9 | 424,901 | 69,680 | 494,581 | Pocos requests, prompts grandes. |
| `post_market_review` | 9 | 2,957 | 10,933 | 13,890 | Bajo. |
| `overnight_learning` | 4 | 2,655 | 0 | 2,655 | Barato pero fallaba producto por respuesta vacia/truncada. |

Despifarro principal: decision + mejora continua concentran ~9.65M tokens. Overnight no gasta mucho, pero generaba degradacion visible sin valor semantico.

Diagnostico overnight:

- Eventos recientes: `overnight_llm_response_invalid` el 2026-06-30, 2026-07-01 y 2026-07-02.
- Ultimo reporte previo: `primary_error=LLM response without text content`, uso registrado, `completion_tokens=0`.
- Ejecucion real tras el cambio: `job-once overnight-learning --force --quiet`.
- Resultado nuevo: proveedor repitio el patron como `llm_response_truncated: finish_reason=length content_chars=0 reasoning_chars=5234`, fallback local no disponible, pero el reporte quedo `status=ok`, `fallback_used=true`, warning `overnight_llm_response_invalid_fallback_used` y acciones deterministas.
- Conclusion: si, era la misma familia de problemas de contenido vacio/truncado ya tratada en otros roles; se corrigio el producto para degradar con fallback determinista en vez de marcar heartbeat inutil.

## 4. Recomendaciones priorizadas

1. Cambiar el default de `ALLOW_AUTO_APPLY_IMPROVEMENTS` a `false` en codigo cuando haya ventana humana; hoy el valor operativo seguro contradice el default.
2. Hacer que el `OrchestratorAgent` no pueda crear mas de N propuestas por semana sin evidencia medida y exigir contrato `CODE_CHANGE` cuando el destino sea codegen.
3. Consolidar configuracion file-based (`core_sleeve`, `lab_book`, `ci_research_mode`) en una auditoria oficial de config efectiva o reflejarla en `Settings` sin tocar los ficheros protegidos.
4. Reducir coste de `decision`: cachear contexto repetido y medir tokens por decision exitosa, no solo tokens totales.
5. Re-instruir `SoftwareReliabilityAgent` y `DataQualityAgent` con el contrato P25; retirar `StrategyEvaluatorAgent`/`ExperimentDesignerAgent` de la fase de propuesta.

## 5. Seguridad y verificacion

- `trading_mode=paper`
- `allow_live_trading=false`
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
- `data/config/core_sleeve.json`: `dry_run=true`
- No se tocaron los 6 ficheros del suelo de kernel.

Verificacion especifica:

- `job-once overnight-learning --force --quiet` ejecutado; reporte nuevo `night_a3b5992aee5d`, `status=ok`.
- `pytest tests/test_scheduler_observability.py::test_overnight_learning_heartbeat_records_llm_usage tests/test_scheduler_observability.py::test_overnight_learning_heartbeat_uses_deterministic_fallback_on_invalid_llm -q` -> `2 passed`.
- `ruff check src/agente_bolsa/tools/overnight_learning.py tests/test_scheduler_observability.py` -> limpio.
