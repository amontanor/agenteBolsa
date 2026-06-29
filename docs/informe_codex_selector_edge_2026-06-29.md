# Informe Codex ? selector edge hist?rico (2026-06-29)

## Resumen ejecutivo

- Estudio read-only completado sobre 2024-01-01?2026-06-29, muestreo semanal (`sample_every=5`), universo S&P 500 point-in-time seg?n `universe_as_of`, coste round-trip 10 bps, horizontes 5/10/20 sesiones.
- Muestra: 17,010 candidatos de poblaci?n, 1,875 candidatos top-N; observaciones maduras: 5d=16,870, 10d=16,688, 20d=16,437.
- Resultado: el top-N por score determinista concentra retorno forward frente a la poblaci?n en los tres horizontes. El delta beta-ajustado neto top-N ? poblaci?n es +0.23 pp a 5d, +0.29 pp a 10d y +0.42 pp a 20d.
- El test de deciles muestra se?al predictiva m?s clara en excess vs SPY que en raw: D10?D1 neto es +0.95 pp a 5d, +1.31 pp a 10d y +2.50 pp a 20d; no es monot?nico perfecto, pero los deciles altos dominan a los bajos.
- Caveat cr?tico: esto mide selecci?n determinista vectorizada/aproximada. No rejuega LLM, gates completos, prior de aprendizaje hist?rico exacto, patrones textuales ni sizing. Debe interpretarse como evidencia de que el ranking concentra candidatos mejores, no como PnL ejecutable.

## Paso 0 ? winner-coverage-report y fallback-blocker-report

Intent? ejecutar los CLI `winner-coverage-report --json` y `fallback-blocker-report --json`; ambos recalculan/leen reportes conservados y excedieron 124s, as? que los procesos se cortaron para no dejar trabajo pesado colgado. Para enmarcar la muestra us? los artefactos conservados m?s recientes en `data/reports/` (retenci?n corta, ~30 d?as).

- Winner coverage usado: `data\reports\winner_coverage_winner_coverage_ea5fb56d067a.json`; `as_of=2026-06-05T17:24:26.929019`, periodo 2026-05-26?2026-05-27, `top_n=3`.
- Winners considerados: 3; selected_any=2; selected_all=1; fallback_buy_any=1; buckets=`captured_partial=1`, `captured_all=1`, `near_miss=1`.
- Lectura: el selector/reporting captur? parcialmente HPE, captur? DELL y dej? SMCI como near-miss por `rank_outside_selection_limit`. La muestra es demasiado peque?a para inferir edge hist?rico.
- Fallback blockers usado: `data\reports\fallback_blockers_fallback_blockers_034a23ec3ca4.json`; `as_of=2026-06-05T17:15:47.350226`, periodo 2026-05-04?2026-06-03.
  - `sma20_extension_no_exception`: sessions=5.112, matured=1.911, avg_return_5d=1.20%, negative=835.
  - `entry_score_v2 bajo`: sessions=536, matured=314, avg_return_5d=1.42%, negative=120.
  - `score_below_fallback_min`: sessions=292, matured=150, avg_return_5d=0.25%, negative=111.
  - `MACD no confirma momentum alcista`: sessions=224, matured=62, avg_return_5d=-0.38%, negative=36.
  - `entrada extendida sin fuerza relativa 20d disponible`: sessions=157, matured=156, avg_return_5d=3.44%, negative=46.
- Limitaci?n: ambos reportes dependen de snapshots conservados recientes; sirven para contexto operativo, no para potencia estad?stica.

## Paso 1 ? scoring localizado

- `src/agente_bolsa/tools/technical_study.py:29` construye el estudio t?cnico cerrado; `src/agente_bolsa/tools/technical_study.py:97` genera `top_longs` ordenando candidatos long por `item["score"]`.
- `src/agente_bolsa/tools/trade_decision.py:1801` define elegibilidad de selecci?n; exige long, `setup_quality=strong`, `return_20d>0` y plan de riesgo v?lido.
- `src/agente_bolsa/tools/trade_decision.py:1853` define `_selection_score_for_candidate`: combina prior de learning, score t?cnico, fuerza relativa, volumen, patrones/continuaci?n, bonuses de leader/emerging/parabolic/constructive y penalizaciones de riesgo.
- `src/agente_bolsa/tools/trade_decision.py:2123` define `_select_deterministic_candidates`; `src/agente_bolsa/tools/trade_decision.py:2166` ordena por `selection_score` y luego `score`.
- Para vectorizar, implement? `add_vector_selector_columns` en `src/agente_bolsa/tools/strategy_edge_backtest.py:390`: usa features causales ya calculadas (`return_*`, SMA/RSI/volumen, flags vectoriales de breakout/failure) y reproduce los componentes deterministas computables. Omite expl?citamente learning-prior hist?rico exacto, `chart_patterns`, bonus same-session y capa LLM.

## Paso 2 ? backtest hist?rico del selector

Comando principal:

```powershell
.\.venv\Scripts\python.exe scripts\study_selector_edge_backtest.py --since 2024-01-01 --to 2026-06-29 --sample-every 5 --progress-every 50 --json > tmp_selector_edge_20260629.json
```

Smoke previo: 10 s?mbolos, 2026-03-01?2026-06-29, completado en ~3s. Run completo: 505 s?mbolos, 623 sesiones, 125 fechas muestreadas, 26.6s wall-time.

### Overall ? poblaci?n vs top-N

| Cohort | Horizonte | M?trica | n | mean net | mediana bruta | hit-rate |
|---|---:|---|---:|---:|---:|---:|
| population | return_5d | raw | 16,870 | 0.29% | 0.29% | 53.60% |
| population | return_5d | excess | 16,870 | 0.01% | -0.06% | 49.28% |
| population | return_5d | beta-aj | 16,870 | -0.02% | -0.02% | 49.65% |
| population | return_10d | raw | 16,688 | 0.65% | 0.52% | 54.18% |
| population | return_10d | excess | 16,688 | 0.07% | -0.20% | 48.31% |
| population | return_10d | beta-aj | 16,688 | 0.00% | -0.13% | 48.87% |
| population | return_20d | raw | 16,437 | 1.38% | 0.88% | 54.85% |
| population | return_20d | excess | 16,437 | 0.31% | -0.36% | 47.96% |
| population | return_20d | beta-aj | 16,437 | 0.17% | -0.31% | 48.18% |
| top_n | return_5d | raw | 1,860 | 0.70% | 0.52% | 54.95% |
| top_n | return_5d | excess | 1,860 | 0.30% | 0.08% | 50.97% |
| top_n | return_5d | beta-aj | 1,860 | 0.20% | 0.07% | 50.70% |
| top_n | return_10d | raw | 1,845 | 1.31% | 0.71% | 55.12% |
| top_n | return_10d | excess | 1,845 | 0.49% | -0.05% | 49.81% |
| top_n | return_10d | beta-aj | 1,845 | 0.29% | -0.03% | 49.92% |
| top_n | return_20d | raw | 1,815 | 2.51% | 1.40% | 57.30% |
| top_n | return_20d | excess | 1,815 | 0.84% | -0.08% | 49.48% |
| top_n | return_20d | beta-aj | 1,815 | 0.59% | -0.20% | 49.04% |

### Delta top-N ? poblaci?n

| Horizonte | raw net delta | excess net delta | beta-aj net delta |
|---|---:|---:|---:|
| return_5d | 0.41% | 0.28% | 0.23% |
| return_10d | 0.66% | 0.42% | 0.29% |
| return_20d | 1.13% | 0.53% | 0.42% |

### Por r?gimen SPY

| R?gimen | Cohort | Horizonte | raw mean net | excess mean net | beta-aj mean net | n raw |
|---|---|---:|---:|---:|---:|---:|
| bear_below_sma200 | population | return_5d | 0.51% | -0.59% | -0.45% | 481 |
| bear_below_sma200 | population | return_10d | 0.87% | -1.41% | -1.21% | 481 |
| bear_below_sma200 | population | return_20d | 1.97% | -2.66% | -1.40% | 481 |
| bear_below_sma200 | top_n | return_5d | 1.11% | 0.15% | 0.24% | 165 |
| bear_below_sma200 | top_n | return_10d | 1.27% | -1.28% | -0.88% | 165 |
| bear_below_sma200 | top_n | return_20d | 1.89% | -4.11% | -1.77% | 165 |
| bull_above_sma200 | population | return_5d | 0.28% | 0.03% | -0.01% | 16,389 |
| bull_above_sma200 | population | return_10d | 0.64% | 0.12% | 0.04% | 16,207 |
| bull_above_sma200 | population | return_20d | 1.36% | 0.40% | 0.22% | 15,956 |
| bull_above_sma200 | top_n | return_5d | 0.66% | 0.31% | 0.20% | 1,695 |
| bull_above_sma200 | top_n | return_10d | 1.31% | 0.66% | 0.41% | 1,680 |
| bull_above_sma200 | top_n | return_20d | 2.57% | 1.34% | 0.82% | 1,650 |

Lectura por r?gimen: la mayor potencia est? en `bull_above_sma200`; ah? top-N mejora frente a poblaci?n y queda positivo en excess/beta-aj. En `bear_below_sma200` hay pocas observaciones; raw es positivo pero excess/beta-aj es d?bil o negativo, especialmente a 20d.

## Paso 3 ? deciles de score y monoton?a

| Decil | 5d raw net | 5d excess net | 5d beta-aj net | 10d raw net | 10d excess net | 10d beta-aj net | 20d raw net | 20d excess net | 20d beta-aj net |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | -0.05% | -0.51% | -0.35% | 0.32% | -0.59% | -0.26% | 0.71% | -0.98% | -0.46% |
| 2 | 0.23% | -0.14% | -0.08% | 0.46% | -0.33% | -0.19% | 0.88% | -0.55% | -0.28% |
| 3 | 0.15% | -0.12% | -0.10% | 0.23% | -0.36% | -0.31% | 0.79% | -0.41% | -0.27% |
| 4 | 0.24% | -0.03% | -0.01% | 0.46% | -0.10% | -0.13% | 0.81% | -0.35% | -0.32% |
| 5 | 0.20% | -0.10% | -0.08% | 0.36% | -0.21% | -0.25% | 0.78% | -0.38% | -0.41% |
| 6 | 0.32% | 0.00% | -0.07% | 0.65% | 0.03% | -0.05% | 1.81% | 0.61% | 0.45% |
| 7 | 0.62% | 0.23% | 0.16% | 1.23% | 0.47% | 0.33% | 1.88% | 0.80% | 0.49% |
| 8 | 0.40% | 0.10% | -0.02% | 0.75% | 0.12% | -0.05% | 2.03% | 0.96% | 0.51% |
| 9 | 0.35% | 0.27% | 0.07% | 1.33% | 1.01% | 0.68% | 2.50% | 1.97% | 1.35% |
| 10 | 0.41% | 0.44% | 0.24% | 0.71% | 0.72% | 0.28% | 1.68% | 1.52% | 0.70% |

| Horizonte | M?trica | Pasos crecientes | D10?D1 neto |
|---|---|---:|---:|
| return_5d | raw | 5/9 | 0.45% |
| return_5d | excess | 7/9 | 0.95% |
| return_5d | beta-aj | 6/9 | 0.59% |
| return_10d | raw | 5/9 | 0.39% |
| return_10d | excess | 5/9 | 1.31% |
| return_10d | beta-aj | 5/9 | 0.54% |
| return_20d | raw | 6/9 | 0.97% |
| return_20d | excess | 7/9 | 2.50% |
| return_20d | beta-aj | 6/9 | 1.17% |

Lectura: el score no ordena retornos de forma estrictamente mon?tona decil a decil, pero s? separa consistentemente la cola alta de la baja, sobre todo en excess vs SPY. El patr?n es compatible con alpha de ranking, aunque ruidoso.

## Rigor y caveats

- Read-only: el script solo descarga/lee precios y usa cache temporal bajo `%TEMP%`; no escribe en la BD.
- Universo: `universe_as_of` report? `survivorship_biased=False`, modo `point_in_time`, tama?o diario 503?504.
- No look-ahead: las features se calculan por s?mbolo con `add_basic_technical_features` sobre el hist?rico completo; los rolling de pandas son causales y cada fila usa datos ? t. Los forward returns se calculan aparte con `close[t+N]/close[t]-1`.
- Muestreo semanal: reduce solape de ventanas forward y pseudo-replicaci?n frente a se?ales diarias.
- Beta/excess: se usa SPY como benchmark; beta rolling 120 sesiones. La beta-aj es una aproximaci?n lineal y no sustituye a un modelo multifactorial.
- Aproximaci?n del selector: no incluye LLM, gates finales, aprendizaje hist?rico exacto, patrones textuales ni ejecuci?n. Esto mide el ranking determinista computable, no el sistema completo.

## Veredicto

S? hay evidencia hist?rica de que la selecci?n determinista concentra mejores forward returns: top-N supera a la poblaci?n en raw, excess y beta-aj en 5/10/20d, y los deciles altos del score superan a los bajos. La se?al es m?s robusta en r?gimen alcista y en excess vs SPY a 20d. No basta por s? sola para promover una estrategia ni para inferir PnL ejecutable, pero s? cambia el diagn?stico: el filtro bruto puede no tener edge agregado mientras el ranking s? concentra parte del edge.

## Comandos ejecutados

- `python -m py_compile src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_selector_edge_backtest.py`
- `pytest tests/test_strategy_edge_backtest.py -q -p no:warnings`
- `ruff check src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_selector_edge_backtest.py tests/test_strategy_edge_backtest.py src/agente_bolsa/__init__.py`
- `python scripts/study_selector_edge_backtest.py --since 2026-03-01 --to 2026-06-29 --max-symbols 10 --sample-every 5 --progress-every 2`
- `python scripts/study_selector_edge_backtest.py --since 2024-01-01 --to 2026-06-29 --sample-every 5 --progress-every 50 --json`
- `ruff check src tests` → limpio.
- `pytest -q -p no:warnings` → 776 passed.

