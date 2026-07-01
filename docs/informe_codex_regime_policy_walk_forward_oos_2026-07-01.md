# Informe Codex - Walk-forward OOS honesto - 2026-07-01

## Pregunta

Extender `study_regime_policy.py` en modo read-only con un walk-forward OOS
honesto: elegir parametros solo con datos pasados y aplicar la eleccion sin tocar
al bloque siguiente. El resultado reportado es solo el alpha beta-ajustado OOS
cosido, no la mejor variante elegida a posteriori.

No se cambio trading, ejecucion, riesgo ni configuracion. No hubo restart.

## Rejilla pre-registrada

La rejilla se fijo antes de mirar el resultado OOS cosido:

- SMA de regimen: `150`, `200`, `250`.
- Cadencia de rebalanceo: `1`, `2`, `4` semanas.
- Min-hold: `0`, `2` semanas.
- Histeresis-delta: `0`, `0.02`.
- Total: 36 combinaciones.

Objetivo de seleccion en cada entrenamiento expansivo:

1. Maximizar Sharpe anualizado del alpha beta-ajustado en entrenamiento.
2. Empate: mayor alpha acumulado.
3. Empate: menor turnover.
4. Empate: id determinista.

Coste aplicado: `cost_bps * turnover semanal estimado`.

## Walk-forward

Bloques:

| Paso | Entrenamiento usado | Bloque OOS aplicado |
|---|---|---|
| 1 | 2022-01-01 -> 2022-12-31 | 2023-01-01 -> 2023-12-31 |
| 2 | 2022-01-01 -> 2023-12-31 | 2024-01-01 -> 2024-12-31 |
| 3 | 2022-01-01 -> 2024-12-31 | 2025-01-01 -> 2026-07-01 |

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe scripts\study_regime_policy.py --walk-forward --since 2022-01-01 --to 2026-07-01 --top-n 15 --sample-every 5 --progress-every 150 --sma-windows 150,200,250 --cost-sensitivity-bps 10,20,30 --cadence-weeks 1,2,4 --min-hold-values 0,2 --hysteresis-deltas 0,0.02 --json > tmp_regime_policy_walk_forward_20260701.json
```

Scan por SMA: 1126 sesiones, 226 fechas muestreadas, 506 simbolos escaneados,
28047 candidatos selector, 3361 top picks y 111181 registros de universo.

## Resultado OOS cosido

Metrica principal: alpha beta-ajustado OOS cosido.

| Coste | Semanas OOS | Alpha acum. | Sharpe anual. | Turnover medio | Peor semana | Cambios parametros |
|---:|---:|---:|---:|---:|---:|---:|
| 10 bps | 174 | -1.14% | 0.055 | 12.52% | -6.19% | 2 / 2 |
| 20 bps | 174 | -3.37% | 0.012 | 12.52% | -6.29% | 2 / 2 |
| 30 bps | 174 | -5.56% | -0.031 | 12.52% | -6.39% | 2 / 2 |

Lectura:

- El alpha beta-ajustado OOS cosido no confirma el edge. A 10 bps queda casi
  plano pero negativo en acumulado; a 20/30 bps empeora.
- El turnover baja mucho frente al semanal plain, pero no basta para hacer
  robusto el alpha OOS cosido.
- Esto invalida la lectura optimista de elegir variantes ex-post. La variante
  que parecia mejor en toda la muestra no es una regla OOS demostrada.

## Parametros elegidos por el procedimiento

Los tres costes eligieron la misma secuencia:

| Bloque OOS | Parametro elegido con entrenamiento pasado | Alpha OOS acum. 10 bps | Alpha OOS Sharpe 10 bps | Turnover OOS |
|---|---|---:|---:|---:|
| 2023 | `sma150_cadence1w_hold0_delta0.02` | -7.54% | -0.778 | 22.18% |
| 2024 | `sma150_cadence4w_hold2_delta0.02` | -12.49% | -0.808 | 2.59% |
| 2025-26 | `sma200_cadence4w_hold2_delta0.02` | 22.19% | 0.839 | 10.41% |

Estabilidad:

- 3 pasos de seleccion.
- 2 cambios de parametros en 2 transiciones.
- Change-rate: `100%`.
- Cada parametro se eligio una vez.

Lectura:

- La seleccion no es estable: cambia en todos los pasos.
- Los dos primeros bloques OOS son negativos; el tramo 2025-26 compensa parte
  de la perdida, pero no suficiente para cerrar positivo en acumulado.
- La mejora reciente no debe interpretarse como prueba de edge estructural.

## Cambios implementados

- `simulate_top_pick_turnover_policy`: simulacion parametrizada de top-picks con
  SMA/regimen, cadencia, min-hold, histeresis y coste por turnover.
- `build_regime_policy_walk_forward_report`: evaluacion pura walk-forward sobre
  reportes ya generados por SMA, con seleccion expansiva y cosido OOS.
- `run_regime_policy_walk_forward_study`: wrapper read-only que genera los
  reportes por SMA y llama al constructor walk-forward.
- `scripts/study_regime_policy.py`: nuevo flag `--walk-forward` y rejilla
  `--min-hold-values`, `--hysteresis-deltas`.
- Test sintetico que demuestra que el parametro se elige por entrenamiento y no
  por el mejor resultado futuro.

## Limitaciones

- Walk-forward por bloques anuales; no prueba estabilidad intrabloque mensual.
- El coste por turnover es aproximado y no modela liquidez ni impacto por
  simbolo.
- El selector sigue siendo la aproximacion vectorial causal del selector real.
- Estudio read-only: no promueve ninguna regla ni modifica estado operativo.

## Verificacion

- Test focal: `.\.venv\Scripts\python.exe -m pytest tests\test_strategy_edge_backtest.py -q -p no:warnings` -> 11 passed.
- Ruff parcial: `.\.venv\Scripts\ruff.exe check src tests scripts\study_regime_policy.py` -> OK.
- Smoke walk-forward limitado -> OK.
- Walk-forward completo 2022-2026 -> OK.
- Suite completa: `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 828 passed, 1 warning externa de `websockets.legacy`.
- Estado read-only: `.\.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`.
