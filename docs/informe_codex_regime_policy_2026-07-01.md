# Informe Codex - Politica simple por regimen - 2026-07-01

## Pregunta

Estudio historico read-only: una politica simple gobernada por regimen bate a
quedarse en caja y a comprar y mantener SPY?

Regimen:

- `bull_above_sma200`: SPY cierra por encima de SMA200 -> participar.
- `bear_below_sma200`: SPY cierra por debajo o igual a SMA200 -> caja/proteger.

## Metodologia

Se reutilizo `src/agente_bolsa/tools/strategy_edge_backtest.py`.

Ventana:

- `2022-01-01` -> `2026-07-01`
- incluye el bear market 2022 y el periodo posterior.
- horizonte semanal: 5 sesiones.
- muestreo: cada 5 sesiones.
- coste: 10 bps por periodo invertido.
- universo: S&P 500 point-in-time aproximado del proyecto.
- selector: aproximacion vectorial causal del selector determinista existente.
- top: `top_n=15` por fecha.

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe scripts\study_regime_policy.py --since 2022-01-01 --to 2026-07-01 --cost-bps 10 --top-n 15 --sample-every 5 --progress-every 100 --json > tmp_regime_policy_20260701.json
```

Scan:

- sesiones en ventana: 1126
- fechas semanales muestreadas: 226
- semanas validas de politica: 225
- simbolos escaneados: 506
- candidatos poblacion: 28.047
- top picks: 3.361

## Politicas comparadas

| Codigo | Politica |
|---|---|
| `cash` | Caja permanente |
| `spy_buy_hold` | Comprar y mantener SPY |
| `spy_bull_cash_bear` | SPY solo en `bull_above_sma200`; caja en `bear_below_sma200` |
| `top_bull_cash_bear` | Top-selecciones del selector solo en `bull_above_sma200`; caja en `bear_below_sma200` |

Todas las politicas se alinean por las mismas semanas. Si una politica no tiene
posicion, la semana cuenta como caja con retorno 0.

## Resultado overall

| Politica | Semanas | Retorno acum. | Media semanal | Sharpe anual. | Max drawdown | Peor semana |
|---|---:|---:|---:|---:|---:|---:|
| Caja | 225 | 0.00% | 0.00% | n/d | 0.00% | 0.00% |
| Buy&hold SPY | 225 | 32.71% | 0.15% | 0.488 | -27.41% | -5.84% |
| SPY bull/caja bear | 225 | 12.21% | 0.06% | 0.285 | -24.17% | -5.51% |
| Top bull/caja bear | 225 | 112.57% | 0.37% | 0.991 | -24.83% | -9.81% |

Lectura:

- Caja es el baseline sin riesgo: no gana, no pierde.
- Buy&hold SPY bate a caja en retorno, con drawdown alto.
- SPY filtrado por SMA200 bate a caja, pero no bate a buy&hold SPY en esta
  ventana. Reduce semanas invertidas, pero sacrifica bastante retorno.
- Top-selecciones solo en bull bate a caja y a buy&hold SPY por retorno
  acumulado y Sharpe. No domina por cola: la peor semana es peor que SPY.

## Desglose por regimen

### Bear: SPY <= SMA200

| Politica | Semanas | Retorno acum. | Media semanal | Sharpe anual. | Max drawdown | Peor semana |
|---|---:|---:|---:|---:|---:|---:|
| Caja | 54 | 0.00% | 0.00% | n/d | 0.00% | 0.00% |
| Buy&hold SPY | 54 | 18.27% | 0.36% | 0.834 | -17.87% | -5.84% |
| SPY bull/caja bear | 54 | 0.00% | 0.00% | n/d | 0.00% | 0.00% |
| Top bull/caja bear | 54 | 0.00% | 0.00% | n/d | 0.00% | 0.00% |

Comentario: el tramo `bear_below_sma200` no significa que cada semana posterior
sea negativa; en la muestra hubo rebotes semanales positivos mientras SPY seguia
por debajo de SMA200. La politica de regimen renuncia a esos rebotes a cambio de
estar en caja.

### Bull: SPY > SMA200

| Politica | Semanas | Retorno acum. | Media semanal | Sharpe anual. | Max drawdown | Peor semana |
|---|---:|---:|---:|---:|---:|---:|
| Caja | 171 | 0.00% | 0.00% | n/d | 0.00% | 0.00% |
| Buy&hold SPY | 171 | 12.21% | 0.09% | 0.327 | -24.17% | -5.51% |
| SPY bull/caja bear | 171 | 12.21% | 0.09% | 0.327 | -24.17% | -5.51% |
| Top bull/caja bear | 171 | 112.57% | 0.49% | 1.139 | -24.83% | -9.81% |

## Respuesta corta

Si la politica es solo `SPY > SMA200 -> SPY, si no caja`, no bate a buy&hold SPY
en esta ventana 2022-2026. Si la politica usa el mismo filtro de regimen para
permitir solo top-selecciones del selector en bull, si bate a caja y a SPY
buy&hold en retorno acumulado y Sharpe. La mejora no viene gratis: la peor semana
de top-selecciones es mas severa que la de SPY.

## Limitaciones

- El selector es una aproximacion vectorial causal: omite learning-prior exacto,
  patrones chartistas, bonus same-session y capas LLM.
- Los retornos son forward close[t+5]/close[t]-1, no una simulacion intradia.
- Coste aplicado como 10 bps por periodo invertido; no modela capacidad,
  impacto de mercado ni concentracion sectorial.
- El estudio es read-only y no promueve reglas a produccion.

## Verificacion

- Test de agregacion: `tests/test_strategy_edge_backtest.py`
- `python -m pytest tests/test_strategy_edge_backtest.py -q -p no:warnings` -> 8 passed
- `.\.venv\Scripts\ruff.exe check src tests scripts\study_regime_policy.py` -> OK
- `python -m pytest tests/ -x -q` -> 825 passed
