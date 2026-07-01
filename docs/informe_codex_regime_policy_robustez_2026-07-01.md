# Informe Codex - Regimen, beta y robustez - 2026-07-01

## Pregunta

Estudio historico read-only: al aislar beta y sensibilidad, la politica de
top-selecciones en regimen alcista sigue batiendo a caja, SPY buy&hold y
controles pasivos?

## Metodologia

Se extendio `scripts/study_regime_policy.py` reutilizando
`src/agente_bolsa/tools/strategy_edge_backtest.py`.

Ventana y supuestos:

- `2022-01-01` -> `2026-07-01`, incluyendo bear market 2022.
- Horizonte semanal: 5 sesiones; muestreo cada 5 sesiones.
- Universo: S&P 500 point-in-time aproximado del proyecto.
- Top picks: `top_n=15` del selector determinista vectorial.
- Robustez de regimen: `SPY close > SMA150/200/250` => participar; si no, caja.
- Sensibilidad de coste: 10/20/30 bps por periodo invertido.
- Control random: 15 simbolos, seed fija `17`, misma cadencia y costes que top picks.
- Etiqueta causal: cada SMA[t] se calcula con rolling historico usando datos `<= t`.

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe scripts\study_regime_policy.py --since 2022-01-01 --to 2026-07-01 --top-n 15 --sample-every 5 --progress-every 150 --sma-windows 150,200,250 --cost-sensitivity-bps 10,20,30 --json > tmp_regime_policy_robust_20260701.json
```

Scan por ventana:

| SMA | Sesiones | Semanas muestreadas | Simbolos | Candidatos selector | Top picks | Registros universo |
|---:|---:|---:|---:|---:|---:|---:|
| 150 | 1126 | 226 | 506 | 28047 | 3361 | 111181 |
| 200 | 1126 | 226 | 506 | 28047 | 3361 | 111181 |
| 250 | 1126 | 226 | 506 | 28047 | 3361 | 111181 |

## Politicas comparadas

| Politica | Descripcion |
|---|---|
| `cash` | Caja permanente |
| `spy_buy_hold` | SPY comprado siempre |
| `spy_bull_cash_bear` | SPY solo en bull; caja en bear |
| `universe_equal_weight_bull_cash_bear` | Todo el universo equal-weight solo en bull; caja en bear |
| `random15_bull_cash_bear` | 15 simbolos aleatorios con seed fija solo en bull; caja en bear |
| `top_bull_cash_bear` | Top picks solo en bull; caja en bear |
| `top_bull_cash_bear_beta_adjusted` | Retorno neto top picks - beta media cartera * retorno SPY |

## Resultado base: 10 bps

| SMA | Politica | Semanas | Retorno acum. | Sharpe anual. | Max DD | Peor semana |
|---:|---|---:|---:|---:|---:|---:|
| 150 | SPY buy&hold | 225 | 32.71% | 0.488 | -27.41% | -5.84% |
| 150 | SPY bull/caja | 225 | 24.54% | 0.510 | -18.91% | -4.92% |
| 150 | Universo EW bull/caja | 225 | 19.56% | 0.413 | -17.89% | -4.89% |
| 150 | Random15 bull/caja | 225 | 18.49% | 0.377 | -19.34% | -5.07% |
| 150 | Top bull/caja | 225 | 134.62% | 1.119 | -18.32% | -9.81% |
| 150 | Top beta-ajustado | 225 | 27.75% | 0.487 | -14.98% | -7.00% |
| 200 | SPY buy&hold | 225 | 32.71% | 0.488 | -27.41% | -5.84% |
| 200 | SPY bull/caja | 225 | 12.21% | 0.285 | -24.17% | -5.51% |
| 200 | Universo EW bull/caja | 225 | 11.23% | 0.265 | -22.47% | -4.89% |
| 200 | Random15 bull/caja | 225 | 9.63% | 0.229 | -22.45% | -5.07% |
| 200 | Top bull/caja | 225 | 112.57% | 0.991 | -24.83% | -9.81% |
| 200 | Top beta-ajustado | 225 | 24.20% | 0.437 | -17.28% | -7.00% |
| 250 | SPY buy&hold | 225 | 32.71% | 0.488 | -27.41% | -5.84% |
| 250 | SPY bull/caja | 225 | 22.50% | 0.441 | -19.89% | -5.51% |
| 250 | Universo EW bull/caja | 225 | 19.40% | 0.394 | -19.38% | -4.97% |
| 250 | Random15 bull/caja | 225 | 8.79% | 0.212 | -22.68% | -7.10% |
| 250 | Top bull/caja | 225 | 175.66% | 1.280 | -16.75% | -9.81% |
| 250 | Top beta-ajustado | 225 | 39.10% | 0.628 | -13.14% | -7.00% |

Lectura: el filtro de regimen por si solo no bate siempre a buy&hold SPY en
retorno acumulado, pero reduce drawdown en SMA150/250. La seleccion top-picks
supera a los controles de universo y random15 en las tres ventanas. El residual
beta-ajustado sigue positivo a 10 bps, lo que sugiere que no todo es beta de
mercado, aunque la ventaja se estrecha frente a la serie bruta.

## Sensibilidad a costes

Retorno acumulado / Sharpe anualizado:

| SMA | Coste | SPY bull/caja | Universo EW | Random15 | Top picks | Top beta-ajustado |
|---:|---:|---:|---:|---:|---:|---:|
| 150 | 10 bps | 24.54% / 0.510 | 19.56% / 0.413 | 18.49% / 0.377 | 134.62% / 1.119 | 27.75% / 0.487 |
| 150 | 20 bps | 5.29% / 0.163 | 1.07% / 0.079 | 0.17% / 0.065 | 98.47% / 0.919 | 8.01% / 0.199 |
| 150 | 30 bps | -10.99% / -0.185 | -14.57% / -0.255 | -15.33% / -0.247 | 67.87% / 0.718 | -8.70% / -0.089 |
| 200 | 10 bps | 12.21% / 0.285 | 11.23% / 0.265 | 9.63% / 0.229 | 112.57% / 0.991 | 24.20% / 0.437 |
| 200 | 20 bps | -5.43% / -0.050 | -6.25% / -0.064 | -7.61% / -0.078 | 79.26% / 0.790 | 4.69% / 0.146 |
| 200 | 30 bps | -20.31% / -0.386 | -21.00% / -0.392 | -22.15% / -0.385 | 51.15% / 0.587 | -11.77% / -0.146 |
| 250 | 10 bps | 22.50% / 0.441 | 19.40% / 0.394 | 8.79% / 0.212 | 175.66% / 1.280 | 39.10% / 0.628 |
| 250 | 20 bps | 2.94% / 0.116 | 0.33% / 0.068 | -8.59% / -0.087 | 131.83% / 1.079 | 16.91% / 0.333 |
| 250 | 30 bps | -13.50% / -0.209 | -15.70% / -0.259 | -23.21% / -0.385 | 94.94% / 0.878 | -1.76% / 0.038 |

Lectura: la politica top-picks bruta aguanta 30 bps en las tres ventanas. El
residual beta-ajustado es positivo a 10 bps, mixto a 20 bps y se vuelve fragil a
30 bps; ese es el limite practico de la evidencia de alpha residual.

## Desglose por regimen a 10 bps

En bear, las politicas gobernadas por regimen quedan en caja por construccion:
retorno 0, drawdown 0. SPY buy&hold no queda en caja y tuvo rebotes positivos en
tramos etiquetados bear:

| SMA | Bear weeks | SPY buy&hold retorno bear | Bull weeks | Top retorno bull | Top beta-ajustado bull |
|---:|---:|---:|---:|---:|---:|
| 150 | 57 | 6.56% | 168 | 134.62% | 27.75% |
| 200 | 54 | 18.27% | 171 | 112.57% | 24.20% |
| 250 | 51 | 8.33% | 174 | 175.66% | 39.10% |

Esto confirma que el filtro de regimen sacrifica rebotes bear. La mejora de
top-picks aparece dentro del tramo bull, no por operar en bear.

## Turnover semanal

| SMA | Politica | Transiciones | Turnover medio | Mediana | Max |
|---:|---|---:|---:|---:|---:|
| 150 | SPY buy&hold | 224 | 0.00% | 0.00% | 0.00% |
| 150 | SPY bull/caja | 224 | 8.04% | 0.00% | 100.00% |
| 150 | Universo EW bull/caja | 224 | 8.05% | 0.00% | 100.00% |
| 150 | Random15 bull/caja | 224 | 76.22% | 100.00% | 100.00% |
| 150 | Top bull/caja | 224 | 66.90% | 80.00% | 100.00% |
| 200 | SPY bull/caja | 224 | 8.04% | 0.00% | 100.00% |
| 200 | Universo EW bull/caja | 224 | 8.05% | 0.00% | 100.00% |
| 200 | Random15 bull/caja | 224 | 77.44% | 100.00% | 100.00% |
| 200 | Top bull/caja | 224 | 68.04% | 80.00% | 100.00% |
| 250 | SPY bull/caja | 224 | 6.25% | 0.00% | 100.00% |
| 250 | Universo EW bull/caja | 224 | 6.26% | 0.00% | 100.00% |
| 250 | Random15 bull/caja | 224 | 77.95% | 100.00% | 100.00% |
| 250 | Top bull/caja | 224 | 67.92% | 80.00% | 100.00% |

El turnover de top-picks es alto, por lo que la conclusion depende de costes y
capacidad. La sensibilidad 10/20/30 bps es obligatoria antes de cualquier lectura
operativa.

## Cambios implementados

- `build_regime_map` acepta `sma_window` y conserva etiquetas causales
  `bull_above_smaN` / `bear_below_smaN`.
- `run_selector_edge_backtest` puede emitir registros del universo completo
  (`universe_member_records`) sin cambiar estado.
- `regime_policy_weekly_details` agrega controles `universe_equal_weight` y
  `random15`, residual beta-ajustado y turnover.
- `run_regime_policy_robustness_study` ejecuta SMA150/200/250 una vez por ventana
  y recalcula costes 10/20/30 sin repetir descargas innecesarias.
- `scripts/study_regime_policy.py` expone `--sma-windows`,
  `--cost-sensitivity-bps`, `--random-seed` y `--random-n`.

## Limitaciones

- El selector sigue siendo una aproximacion vectorial causal del selector real:
  omite learning-prior exacto, chart-pattern counts, bonus same-session y capas
  LLM.
- Retornos forward close[t+5]/close[t]-1; no simula intradia ni capacidad.
- Coste modelado como bps por periodo invertido; no modela slippage variable ni
  impacto por turnover real de cada posicion.
- El estudio es read-only y no promueve ninguna regla a produccion.

## Verificacion

- Test focal: `.\.venv\Scripts\python.exe -m pytest tests\test_strategy_edge_backtest.py -q -p no:warnings` -> 9 passed.
- Ruff: `.\.venv\Scripts\ruff.exe check src tests scripts\study_regime_policy.py` -> OK.
- Suite completa: `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 826 passed, 1 warning externa de `websockets.legacy`.
- Estado read-only: `.\.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`.
- `validate-agent-config --json` no existe en la CLI actual; no se conto como verificacion pasada.
- Estudio robusto completo: comando anterior -> OK.
