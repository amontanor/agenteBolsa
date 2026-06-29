# Informe Codex ? gate de extensi?n con riesgo y ventana bear (2026-06-29)

## Resumen ejecutivo

- Estudio read-only ampliado a 2022-01-01?2026-06-29 para incluir selloffs reales y m?s r?gimen bajista. Universo S&P 500 point-in-time; `survivorship_biased=False`; muestreo semanal; top-N=15; coste round-trip=10.0 bps.
- Top-picks analizados: 3,346; pasan el gate ?12%: 2,749; rechazados >12%: 597; sin distancia: 0.
- Resultado agregado: los rechazados siguen teniendo mayor media neta y mayor Sharpe simple que los que pasan en 5/10/20d, incluso beta-ajustado.
- Pero al contar riesgo, la cola rechazada es claramente m?s peligrosa: peor max drawdown, mayor downside deviation y m?s eventos <-10% en todos los horizontes.
- Veredicto: el gate sigue ?costando? edge medio/Sharpe, sobre todo en r?gimen alcista, pero s? protege contra convexidad negativa/drawdown. En r?gimen bajista el beneficio del rechazo casi desaparece en beta-ajustado y el riesgo empeora. No conviene relajar globalmente el gate; si se act?a, deber?a ser con una excepci?n muy acotada y medida en SHADOW/guarded.

## Cambios al motor

- Reutilic? `strategy_edge_backtest.py`; no se reimplement? descarga, universo, features ni forward returns.
- A?ad? m?tricas de riesgo al agregador del selector:
  - `sharpe_simple = mean_net / std` sobre retornos por se?al, no anualizado.
  - `max_drawdown` sobre una curva de retornos medios por fecha de se?al y cohorte, neta de costes.
  - `downside_deviation` sobre retornos netos negativos.
  - `tail_loss_rate_lt_10pct`: porcentaje de se?ales netas < -10%.
- A?ad? deltas de riesgo rechazado ? pasa: `sharpe_simple_delta`, `max_drawdown_delta`, `downside_deviation_delta`, `tail_loss_rate_lt_10pct_delta`.
- El CLI `scripts/study_extension_gate_edge.py` queda con default `--since 2022-01-01` para este estudio ampliado.

## Metodolog?a

1. Para cada fecha semanal y s?mbolo point-in-time, el motor calcula features causales vectorizadas.
2. Se rankean candidatos con el score determinista aproximado del selector y se toman los top-N por fecha.
3. Se separan por el gate real de extensi?n: `distance_sma20 <= 0.12` vs `distance_sma20 > 0.12`.
4. Se calculan forward returns 5/10/20d raw, excess vs SPY y beta-ajustado, netos de 10 bps.
5. Se reportan media y m?tricas de riesgo por cohorte/r?gimen, m?s delta rechazado ? pasa.

Comando principal:

```powershell
.\.venv\Scripts\python.exe scripts\study_extension_gate_edge.py --since 2022-01-01 --to 2026-06-29 --sample-every 5 --progress-every 50 --json > tmp_gate_risk_20260629.json
```

Run completo: 506 s?mbolos, 1124 sesiones, 225 fechas muestreadas, 29.47s de ejecuci?n interna.

## Distribuci?n de extensi?n

| Cohorte | n | min distance_sma20 | mediana | max |
|---|---:|---:|---:|---:|
| extension_pass | 2,749 | -8.77% | 6.26% | 11.99% |
| extension_rejected | 597 | 12.00% | 15.43% | 91.48% |

## M?tricas agregadas por cohorte

### Beta-ajustado vs SPY, neto de costes

| Cohorte | Horizonte | n | mean net | std | Sharpe simple | max DD | downside dev | cola <-10% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| extension_pass | return_5d | 2,737 | -0.09% | 4.64% | -0.019 | -32.72% | 3.25% | 2.12% |
| extension_pass | return_10d | 2,728 | -0.08% | 6.48% | -0.012 | -47.01% | 4.40% | 4.80% |
| extension_pass | return_20d | 2,711 | 0.14% | 9.81% | 0.014 | -56.76% | 6.03% | 8.89% |
| extension_rejected | return_5d | 594 | 0.63% | 7.95% | 0.080 | -43.31% | 4.75% | 5.72% |
| extension_rejected | return_10d | 588 | 1.22% | 10.63% | 0.114 | -71.92% | 6.07% | 10.37% |
| extension_rejected | return_20d | 575 | 2.44% | 16.23% | 0.151 | -84.19% | 8.07% | 15.13% |

### Raw y excess: resumen de media neta y Sharpe

| Cohorte | Horizonte | raw mean net | raw Sharpe | excess mean net | excess Sharpe |
|---|---:|---:|---:|---:|---:|
| extension_pass | return_5d | 0.21% | 0.040 | 0.00% | 0.001 |
| extension_pass | return_10d | 0.50% | 0.069 | 0.04% | 0.006 |
| extension_pass | return_20d | 1.24% | 0.114 | 0.26% | 0.025 |
| extension_rejected | return_5d | 1.25% | 0.145 | 0.94% | 0.115 |
| extension_rejected | return_10d | 2.61% | 0.223 | 1.87% | 0.170 |
| extension_rejected | return_20d | 4.94% | 0.277 | 3.53% | 0.209 |

## Delta rechazado ? pasa

### Beta-ajustado

| Horizonte | mean net delta | Sharpe delta | max DD delta | downside delta | cola <-10% delta |
|---|---:|---:|---:|---:|---:|
| return_5d | 0.72% | 0.098 | -10.58% | 1.49% | 3.60% |
| return_10d | 1.29% | 0.127 | -24.91% | 1.67% | 5.57% |
| return_20d | 2.30% | 0.136 | -27.44% | 2.04% | 6.24% |

Lectura: el delta de Sharpe sigue positivo, pero el delta de max drawdown es negativo porque los rechazados sufren drawdowns mucho peores. La mejora de media viene con cola m?s pesada.

### Raw/excess: media y Sharpe

| Horizonte | raw mean delta | raw Sharpe delta | excess mean delta | excess Sharpe delta |
|---|---:|---:|---:|---:|
| return_5d | 1.05% | 0.105 | 0.94% | 0.115 |
| return_10d | 2.11% | 0.154 | 1.82% | 0.164 |
| return_20d | 3.69% | 0.163 | 3.27% | 0.184 |

## Por r?gimen SPY

### Beta-ajustado por cohorte y r?gimen

| R?gimen | Cohorte | Horizonte | n | mean net | Sharpe | max DD | downside dev | cola <-10% |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| bull_above_sma200 | extension_pass | return_5d | 2,042 | -0.00% | -0.001 | -25.04% | 3.09% | 1.67% |
| bull_above_sma200 | extension_pass | return_10d | 2,033 | 0.07% | 0.010 | -32.22% | 4.20% | 4.23% |
| bull_above_sma200 | extension_pass | return_20d | 2,016 | 0.44% | 0.044 | -34.84% | 5.75% | 8.04% |
| bull_above_sma200 | extension_rejected | return_5d | 508 | 0.74% | 0.089 | -36.05% | 4.84% | 6.10% |
| bull_above_sma200 | extension_rejected | return_10d | 502 | 1.50% | 0.137 | -47.49% | 6.04% | 10.16% |
| bull_above_sma200 | extension_rejected | return_20d | 489 | 3.03% | 0.179 | -73.40% | 7.93% | 14.93% |
| bear_below_sma200 | extension_pass | return_5d | 695 | -0.33% | -0.068 | -18.07% | 3.69% | 3.45% |
| bear_below_sma200 | extension_pass | return_10d | 695 | -0.50% | -0.077 | -27.67% | 4.94% | 6.47% |
| bear_below_sma200 | extension_pass | return_20d | 695 | -0.73% | -0.077 | -50.36% | 6.75% | 11.37% |
| bear_below_sma200 | extension_rejected | return_5d | 86 | 0.03% | 0.005 | -47.96% | 4.12% | 3.49% |
| bear_below_sma200 | extension_rejected | return_10d | 86 | -0.43% | -0.053 | -67.33% | 6.23% | 11.63% |
| bear_below_sma200 | extension_rejected | return_20d | 86 | -0.87% | -0.076 | -76.69% | 8.83% | 16.28% |

### Delta beta-ajustado por r?gimen ? rechazado ? pasa

| R?gimen | Horizonte | mean net delta | Sharpe delta | max DD delta | downside delta | cola <-10% delta | n rechazado | n pasa |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bear_below_sma200 | return_5d | 0.35% | 0.073 | -29.89% | 0.43% | 0.04% | 86 | 695 |
| bear_below_sma200 | return_10d | 0.06% | 0.024 | -39.67% | 1.30% | 5.16% | 86 | 695 |
| bear_below_sma200 | return_20d | -0.13% | 0.001 | -26.34% | 2.07% | 4.91% | 86 | 695 |
| bull_above_sma200 | return_5d | 0.74% | 0.090 | -11.01% | 1.76% | 4.43% | 508 | 2,042 |
| bull_above_sma200 | return_10d | 1.43% | 0.127 | -15.27% | 1.84% | 5.93% | 502 | 2,033 |
| bull_above_sma200 | return_20d | 2.59% | 0.135 | -38.56% | 2.17% | 6.89% | 489 | 2,016 |

Lectura por r?gimen:

- En r?gimen alcista, los rechazados mantienen mayor mean net y mayor Sharpe beta-ajustado, pero con m?s colas y peor drawdown. El gate cuesta edge medio, pero reduce riesgo de cola.
- En r?gimen bajista, la ventaja de los rechazados se reduce mucho: beta-aj 5d/10d apenas mejora y 20d empeora en media; el drawdown y la cola empeoran claramente. Aqu? el gate s? parece m?s protector.

## Rigor y caveats

- Read-only: no se escribi? en la BD ni se cambi? runtime de trading.
- No look-ahead: features por s?mbolo con rolling causal; forward returns se calculan aparte para outcome.
- Universo: point-in-time seg?n `universe_as_of`; no se detect? fallback survivorship-biased.
- Riesgo: max drawdown se calcula sobre una serie equal-weight de retornos medios por fecha de se?al y cohorte. Es una m?trica comparable de path risk, no una simulaci?n de cartera ejecutada con sizing, liquidez ni solape real de posiciones.
- Selector: sigue siendo replay determinista aproximado; no incluye LLM, gates completos, learning-prior hist?rico exacto ni excepciones runtime.

## Veredicto

Con ventana 2022?2026, el gate de extensi?n sigue costando edge medio y Sharpe agregados en los top-picks del selector, especialmente en r?gimen alcista y a 10/20d. Pero una vez se cuentan selloffs y riesgo, el gate tambi?n protege: los rechazados tienen drawdowns, downside deviation y colas <-10% sustancialmente peores. En r?gimen bajista, la mejora media desaparece o se vuelve negativa a 20d beta-ajustado mientras el riesgo empeora. Conclusi?n operativa: no relajar el gate global. Si se quiere capturar el edge, la v?a defendible es una excepci?n separada, medida y limitada para top-picks extendidos con confirmaci?n de fuerza/r?gimen, primero en SHADOW/guarded y con l?mites de cola/drawdown expl?citos.

## Verificaci?n

- `python -m py_compile src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_extension_gate_edge.py` ? ok.
- `pytest tests/test_strategy_edge_backtest.py -q -p no:warnings` ? 6 passed.
- `ruff check src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_extension_gate_edge.py tests/test_strategy_edge_backtest.py src/agente_bolsa/__init__.py` ? limpio.
- `ruff check src tests` -> limpio.
- `pytest -q -p no:warnings` -> 778 passed.
