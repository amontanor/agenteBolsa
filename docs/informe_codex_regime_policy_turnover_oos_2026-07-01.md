# Informe Codex - Turnover, alpha beta-ajustado y OOS - 2026-07-01

## Pregunta

Extender el estudio read-only de `study_regime_policy.py` para comprobar si el
alpha residual de top-picks sobrevive al bajar turnover y si el edge aparece de
forma estable fuera de muestra por subperiodos.

No se cambio nada de trading, ejecucion, riesgo ni configuracion. No se hizo
restart.

## Metodologia

Base:

- Ventana: `2022-01-01` -> `2026-07-01`.
- Regimen: SPY sobre SMA150/200/250; foco principal en SMA200 para las tablas.
- Horizonte: 5 sesiones; muestreo semanal.
- Top picks: `top_n=15`.
- Costes: 10/20/30 bps.
- Alpha principal: `retorno neto cartera - beta_media_cartera * retorno SPY`.

Nueva sensibilidad de turnover:

- `top_rebalance_1w`: rebalanceo semanal.
- `top_rebalance_2w`: rebalanceo quincenal.
- `top_rebalance_4w`: rebalanceo mensual.
- Variante con histeresis para cada cadencia: minimo 2 semanas de tenencia y no
  se rota una posicion salvo que el candidato sustituto mejore el score al menos
  `0.02`.
- En esta seccion el coste se aplica como `cost_bps * turnover semanal estimado`.
  Esto aisla si reducir rotacion protege el alpha residual.

Subperiodos OOS:

- `2022`
- `2023`
- `2024`
- `2025-26`

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe scripts\study_regime_policy.py --since 2022-01-01 --to 2026-07-01 --top-n 15 --sample-every 5 --progress-every 150 --sma-windows 150,200,250 --cost-sensitivity-bps 10,20,30 --cadence-weeks 1,2,4 --min-hold-weeks 2 --hysteresis-score-delta 0.02 --json > tmp_regime_policy_turnover_oos_20260701.json
```

Scan por SMA: 1126 sesiones, 226 fechas muestreadas, 506 simbolos escaneados,
28047 candidatos selector, 3361 top picks y 111181 registros de universo.

## Resultado principal: SMA200

Metrica principal: alpha beta-ajustado acumulado / Sharpe anualizado. Se incluye
retorno bruto acumulado para contexto y turnover medio semanal.

| Coste | Variante | Retorno bruto acum. | Alpha acum. | Alpha Sharpe | Turnover medio |
|---:|---|---:|---:|---:|---:|
| 10 bps | semanal | 116.31% | 26.40% | 0.466 | 68.04% |
| 10 bps | semanal + histeresis | 117.03% | 37.37% | 0.631 | 14.05% |
| 10 bps | quincenal | 117.63% | 37.78% | 0.618 | 40.09% |
| 10 bps | quincenal + histeresis | 124.42% | 57.17% | 0.891 | 12.80% |
| 10 bps | mensual | 172.72% | 70.41% | 0.946 | 23.18% |
| 10 bps | mensual + histeresis | 131.40% | 63.81% | 0.931 | 10.98% |
| 20 bps | semanal | 85.65% | 8.43% | 0.205 | 68.04% |
| 20 bps | semanal + histeresis | 110.09% | 32.97% | 0.572 | 14.05% |
| 20 bps | quincenal | 98.79% | 25.83% | 0.462 | 40.09% |
| 20 bps | quincenal + histeresis | 117.83% | 52.55% | 0.834 | 12.80% |
| 20 bps | mensual | 158.67% | 61.64% | 0.859 | 23.18% |
| 20 bps | mensual + histeresis | 125.53% | 59.66% | 0.885 | 10.98% |
| 30 bps | semanal | 59.31% | -6.99% | -0.056 | 68.04% |
| 30 bps | semanal + histeresis | 103.36% | 28.71% | 0.513 | 14.05% |
| 30 bps | quincenal | 81.57% | 14.91% | 0.306 | 40.09% |
| 30 bps | quincenal + histeresis | 111.44% | 48.07% | 0.778 | 12.80% |
| 30 bps | mensual | 145.33% | 53.31% | 0.771 | 23.18% |
| 30 bps | mensual + histeresis | 119.81% | 55.60% | 0.838 | 10.98% |

Lectura:

- El alpha semanal plain no sobrevive a 30 bps: cae a `-6.99%`.
- Reducir turnover cambia la conclusion. Quincenal/mensual con histeresis sigue
  positivo incluso a 30 bps.
- La mejor combinacion por alpha acumulado a 10 bps fue mensual plain
  (`70.41%`), pero con turnover mayor que mensual+histeresis. La variante mensual
  con histeresis da casi el mismo alpha Sharpe y el turnover mas bajo.

## Robustez SMA a 10 bps

Alpha beta-ajustado acumulado / Sharpe / turnover:

| SMA | Semanal | Semanal+hyst | Quincenal | Quincenal+hyst | Mensual | Mensual+hyst |
|---:|---:|---:|---:|---:|---:|---:|
| 150 | 29.95% / 0.516 / 66.90% | 32.04% / 0.543 / 14.49% | 26.75% / 0.470 / 39.32% | 20.08% / 0.371 / 13.60% | 30.89% / 0.501 / 23.78% | 20.49% / 0.372 / 11.88% |
| 200 | 26.40% / 0.466 / 68.04% | 37.37% / 0.631 / 14.05% | 37.78% / 0.618 / 40.09% | 57.17% / 0.891 / 12.80% | 70.41% / 0.946 / 23.18% | 63.81% / 0.931 / 10.98% |
| 250 | 42.03% / 0.663 / 67.92% | 14.19% / 0.317 / 12.08% | 21.25% / 0.435 / 38.96% | 2.48% / 0.106 / 10.51% | 20.56% / 0.440 / 22.95% | 20.54% / 0.450 / 8.90% |

Lectura:

- El efecto de bajar turnover no es monotono para todas las ventanas SMA.
- SMA200 es donde histeresis y cadencia lenta mas ayudan.
- SMA250 mantiene alpha positivo, pero la histeresis sacrifica demasiado retorno
  en quincenal. Esto no es una regla lista para promover; es evidencia para
  investigar una politica de retencion.

## Estabilidad OOS: SMA200, 10 bps

Alpha beta-ajustado acumulado por subperiodo:

| Variante | 2022 | 2023 | 2024 | 2025-26 |
|---|---:|---:|---:|---:|
| Baseline top beta-ajustado | 6.99% | -11.82% | 1.84% | 29.26% |
| Semanal | 6.51% | -11.29% | 2.64% | 30.33% |
| Semanal + histeresis | 5.14% | -4.80% | 7.68% | 27.45% |
| Quincenal | 3.93% | -12.13% | 3.93% | 45.17% |
| Quincenal + histeresis | 5.33% | 1.03% | 19.72% | 23.37% |
| Mensual | 9.59% | -9.38% | 7.45% | 59.69% |
| Mensual + histeresis | 9.59% | 4.83% | 14.28% | 24.77% |

Lectura OOS:

- El edge no aparece igual en todos los anos. `2023` es el ano problematico:
  baseline, semanal, quincenal y mensual plain son negativos.
- Las variantes con histeresis quincenal/mensual convierten 2023 en positivo,
  pero eso puede ser seleccion de reglas sobre la muestra. No se debe promover
  sin validacion adicional.
- `2025-26` explica una parte grande del retorno. Hay edge residual, pero no es
  uniformemente estable por ano.

## Cambios implementados

- `top_pick_turnover_sensitivity`: simula top-picks con cadencias 1/2/4 semanas,
  coste por turnover, min-hold e histeresis.
- `summarize_policy_subperiods`: desglose OOS por periodos ISO.
- `run_regime_policy_robustness_study` ahora incluye `turnover_sensitivity` y
  `subperiod_summary` en el JSON.
- `scripts/study_regime_policy.py` anade `--cadence-weeks`,
  `--min-hold-weeks` y `--hysteresis-score-delta`.
- Test sintetico cubre que cadencia/histeresis bajan turnover y que el residual
  beta-ajustado se calcula sobre retornos netos.

## Limitaciones

- La histeresis se define por score determinista historico (`selector_score`),
  no por una decision LLM.
- El coste por turnover es una aproximacion de cartera equal-weight; no modela
  liquidez, spread real ni impacto por simbolo.
- Retornos forward close[t+5]/close[t]-1; no simula intradia.
- Estudio read-only: no cambia reglas, gates, configuracion, trading ni estado.

## Verificacion

- Test focal: `.\.venv\Scripts\python.exe -m pytest tests\test_strategy_edge_backtest.py -q -p no:warnings` -> 10 passed.
- Ruff: `.\.venv\Scripts\ruff.exe check src tests scripts\study_regime_policy.py` -> OK.
- Suite completa: `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 827 passed, 1 warning externa de `websockets.legacy`.
- Estado read-only: `.\.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`.
- Estudio completo 2022-2026: comando anterior -> OK.
