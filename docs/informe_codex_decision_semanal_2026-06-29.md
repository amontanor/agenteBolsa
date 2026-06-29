# Informe Codex ? decisi?n semanal por pol?tica (2026-06-29)

## Resumen ejecutivo

- Este estudio estima distribuciones hist?ricas condicionales a 5 sesiones. No es una predicci?n de la pr?xima semana.
- R?gimen actual asumido para la decisi?n: `bull_above_sma200` (SPY > SMA200). El r?gimen bear se muestra como riesgo de giro.
- Ventana: 2022-01-01?2026-06-29; muestreo semanal; horizonte 5 sesiones; coste plano 10.0 bps; universo point-in-time S&P 500 (`survivorship_biased=False`).
- Muestra: 225 semanas muestreadas, 27,905 candidatos elegibles, 3,346 top-picks del selector.
- En r?gimen bull, P3 (Top-N sin gate de extensi?n) tiene el mejor retorno semanal hist?rico y Sharpe simple: +0.46% semanal neto, Sharpe 0.150. El coste es m?s cola: peor semana -9.81% y 3.53% de semanas <-5%.
- P2 (Top-N que pasan gate) tiene menor retorno: +0.21% semanal neto, Sharpe 0.077, pero cola <-5% m?s baja (1.76%).
- P4 (todos elegibles) diversifica: +0.22% semanal neto, Sharpe 0.110, menor max DD en bull (-18.39%) y cola <-5% 0.59%, pero diluye el edge del selector.
- En bear, P1 SPY fue el mejor promedio de esta muestra (+0.36% semanal), pero con cola; P2/P3 no mejoran claramente y sufren peores semanas (~-15%). Riesgo expl?cito: si el r?gimen gira, el edge del selector/top momentum se degrada.

## Metodolog?a

- Reutilic? `strategy_edge_backtest.py`: mismo universo point-in-time, features causales, top-N del selector, gate de extensi?n, r?gimen SPY y costes.
- Cada opci?n se construye como cartera equal-weight semanal y se mide con retorno forward a 5 sesiones neto de 10 bps.
- P0 no opera: retorno 0. P1 usa SPY 5d neto de coste. P2/P3/P4 usan retornos medios equal-weight de las se?ales disponibles esa semana.
- M?tricas: media, mediana, Sharpe simple semanal (mean/std), max drawdown de la curva semanal, peor semana, % semanas negativas y % semanas <-5%.

Comando principal:

```powershell
.\.venv\Scripts\python.exe scripts\study_weekly_policy_decision.py --since 2022-01-01 --to 2026-06-29 --sample-every 5 --progress-every 50 --json > tmp_weekly_policy_20260629.json
```

Run completo: 506 s?mbolos, 1124 sesiones, 225 fechas muestreadas, 55.58s de ejecuci?n interna.

## Tabla de decisi?n ? r?gimen bull actual

| Opci?n | semanas | retorno semanal esperado | mediana | Sharpe semanal | max DD | peor semana | % semanas neg | cola <-5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 ? Caja | 170 | 0.00% | 0.00% | n/d | 0.00% | 0.00% | 0.00% | 0.00% |
| P1 ? Comprar y mantener SPY | 170 | 0.08% | 0.29% | 0.040 | -24.17% | -5.51% | 41.18% | 0.59% |
| P2 ? Top-N que pasan gate ?12% | 170 | 0.21% | 0.10% | 0.077 | -24.58% | -7.76% | 47.06% | 1.76% |
| P3 ? Top-N sin gate extensi?n | 170 | 0.46% | 0.34% | 0.150 | -24.99% | -9.81% | 44.12% | 3.53% |
| P4 ? Todos elegibles equal-weight | 170 | 0.22% | 0.34% | 0.110 | -18.39% | -7.49% | 42.35% | 0.59% |

Lectura bull:

- P3 maximiza retorno esperado hist?rico y Sharpe, pero duplica aproximadamente la cola <-5% frente a P2.
- P2 es m?s conservadora que P3: menor peor semana y menor cola, pero tambi?n menor retorno.
- P4 ofrece una alternativa diversificada: retorno parecido a P2, mejor drawdown y menor cola, aunque no representa el sistema real top-N.
- P0 elimina riesgo de mercado pero renuncia al edge hist?rico; P1 tiene retorno bajo en bull neto de costes y drawdown similar a P2/P3.

## Riesgo de giro ? r?gimen bear

| Opci?n | semanas | retorno semanal esperado | mediana | Sharpe semanal | max DD | peor semana | % semanas neg | cola <-5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 ? Caja | 54 | 0.00% | 0.00% | n/d | 0.00% | 0.00% | 0.00% | 0.00% |
| P1 ? Comprar y mantener SPY | 54 | 0.36% | 0.59% | 0.116 | -17.87% | -5.84% | 44.44% | 9.26% |
| P2 ? Top-N que pasan gate ?12% | 54 | 0.27% | 0.44% | 0.080 | -23.68% | -15.14% | 40.74% | 3.70% |
| P3 ? Top-N sin gate extensi?n | 54 | 0.26% | 0.75% | 0.075 | -23.59% | -15.13% | 40.74% | 5.56% |
| P4 ? Todos elegibles equal-weight | 54 | 0.04% | 0.54% | 0.013 | -24.24% | -15.35% | 42.59% | 5.56% |

Lectura bear:

- En esta muestra, SPY mantiene mejor media que P2/P3/P4, probablemente por semanas de rebote dentro de r?gimen bajo SMA200.
- P2 y P3 tienen peor semana cercana a -15% y max DD alrededor de -23.6%; P3 no compensa claramente el riesgo bear frente a P2.
- El riesgo de giro de r?gimen es material: la ventaja de P3 observada en bull no debe extrapolarse si SPY pierde SMA200.

## Comparaci?n global

| Opci?n | semanas | media | Sharpe | max DD | peor semana | cola <-5% |
|---|---:|---:|---:|---:|---:|---:|
| P0 ? Caja | 224 | 0.00% | n/d | 0.00% | 0.00% | 0.00% |
| P1 ? Comprar y mantener SPY | 224 | 0.14% | 0.064 | -27.41% | -5.84% | 2.68% |
| P2 ? Top-N que pasan gate ?12% | 224 | 0.22% | 0.077 | -29.59% | -15.14% | 2.23% |
| P3 ? Top-N sin gate extensi?n | 224 | 0.41% | 0.131 | -28.07% | -15.13% | 4.02% |
| P4 ? Todos elegibles equal-weight | 224 | 0.18% | 0.075 | -26.92% | -15.35% | 1.79% |

## Veredicto para decisi?n

- Si el objetivo primario es retorno esperado condicionado a bull: P3 domina hist?ricamente, pero acepta m?s cola.
- Si el objetivo es retorno/riesgo m?s equilibrado sin tocar el gate: P2 es defendible, aunque su edge es modesto.
- Si el objetivo es menor path risk hist?rico: P4 aparece atractivo por diversificaci?n, pero no es una pol?tica operativa equivalente al sistema real porque el sistema limita ?rdenes y selecciona top-picks.
- Para una decisi?n prudente esta semana: la evidencia no justifica cambiar runtime ni abrir el gate global. Sirve para elegir entre esperar (P0), mantener disciplina (P2) o dise?ar una excepci?n medida (P3-like) bajo control de r?gimen/riesgo.

## Caveats obligatorios

- No es predicci?n: son distribuciones hist?ricas condicionales.
- Selector aproximado: no incluye LLM, learning-prior hist?rico exacto, gates completos ni ejecuci?n real.
- Equal-weight: el sistema real topa a 4 ?rdenes/ciclo y m?nimo $100, por lo que el despliegue real ser?a menor y m?s concentrado.
- Costes planos de 10 bps; no modela slippage variable, liquidez, gaps ni solape operativo real.
- R?gimen definido solo por SPY vs SMA200; no captura cambios intrar?gimen ni volatilidad macro.

## Verificaci?n

- `python -m py_compile src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_weekly_policy_decision.py` ? ok.
- `pytest tests/test_strategy_edge_backtest.py -q -p no:warnings` ? 7 passed.
- `ruff check src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_weekly_policy_decision.py tests/test_strategy_edge_backtest.py src/agente_bolsa/__init__.py` ? limpio.
- `ruff check src tests` -> limpio.
- `pytest -q -p no:warnings` -> 779 passed.
