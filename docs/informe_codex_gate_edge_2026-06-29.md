# Informe Codex ? gate de extensi?n sobre top-picks del selector (2026-06-29)

## Resumen ejecutivo

- Estudio read-only sobre 2024-01-01?2026-06-29, muestreo semanal, universo S&P 500 point-in-time, top-N=15, coste round-trip=10.0 bps.
- Gate evaluado: `distance_sma20 > entry_quality_max_sma20_distance`; el threshold real viene de `settings.entry_quality_max_sma20_distance=12.00%`.
- Top-picks analizados: 1,875; pasan ?12%: 1,468; rechazados >12%: 407; sin distancia: 0.
- Resultado central: en este replay hist?rico, los top-picks rechazados por extensi?n rinden mejor que los que pasan. El delta rechazado ? pasa es positivo en raw, excess vs SPY y beta-ajustado en 5/10/20d.
- Veredicto: para el top del selector, el gate de extensi?n habr?a destruido edge hist?rico m?s que protegerlo. Esto no autoriza cambiar el gate: falta replay completo de LLM/gates/excepciones y validaci?n forward paper.

## Evidencia de c?digo

- Threshold real: `src/agente_bolsa/config.py:162` (`ENTRY_QUALITY_MAX_SMA20_DISTANCE`, default 0.12).
- Gate runtime: `src/agente_bolsa/tools/trade_decision.py:4318` rechaza si `sma20_distance > settings.entry_quality_max_sma20_distance` y no hay excepci?n de extensi?n.
- Estudio a?adido: `src/agente_bolsa/tools/strategy_edge_backtest.py:1252` (`run_extension_gate_edge_backtest`) reutiliza el runner del selector; `src/agente_bolsa/tools/strategy_edge_backtest.py:1533` imprime el resumen CLI.
- Wrapper CLI: `scripts/study_extension_gate_edge.py`.

## Metodolog?a

1. Reutilic? el motor `strategy_edge_backtest.py` del estudio del selector: descarga por s?mbolo, features causales vectorizadas, universo point-in-time y forward returns `close[t+N]/close[t]-1`.
2. Para cada fecha muestreada semanalmente, tom? los top-N por score determinista aproximado del selector.
3. Part? esos top-picks en dos cohortes usando el gate real de extensi?n:
   - `extension_pass`: `distance_sma20 <= 0.12`.
   - `extension_rejected`: `distance_sma20 > 0.12`.
4. Agregu? forward 5/10/20d raw, excess vs SPY y beta-ajustado, netos de 10 bps, con desglose por r?gimen SPY.

Comando principal:

```powershell
.\.venv\Scripts\python.exe scripts\study_extension_gate_edge.py --since 2024-01-01 --to 2026-06-29 --sample-every 5 --progress-every 50 --json > tmp_gate_edge_20260629.json
```

Run completo: 505 s?mbolos, 623 sesiones, 125 fechas muestreadas, ~27s wall-time.

## Distribuci?n de extensi?n

| Cohorte | n | min distance_sma20 | mediana | max |
|---|---:|---:|---:|---:|
| extension_pass | 1,468 | -12.34% | 6.41% | 12.00% |
| extension_rejected | 407 | 12.00% | 15.47% | 78.49% |

## Overall ? PASA vs RECHAZADO

| Cohorte | Horizonte | M?trica | n | mean net | mediana bruta | hit-rate |
|---|---:|---|---:|---:|---:|---:|
| extension_pass | return_5d | raw | 1,456 | 0.49% | 0.44% | 54.53% |
| extension_pass | return_5d | excess | 1,456 | 0.11% | 0.05% | 50.34% |
| extension_pass | return_5d | beta-aj | 1,456 | 0.07% | 0.09% | 50.82% |
| extension_pass | return_10d | raw | 1,447 | 0.92% | 0.60% | 54.53% |
| extension_pass | return_10d | excess | 1,447 | 0.13% | -0.17% | 49.14% |
| extension_pass | return_10d | beta-aj | 1,447 | 0.03% | -0.07% | 49.55% |
| extension_pass | return_20d | raw | 1,428 | 1.84% | 1.39% | 57.63% |
| extension_pass | return_20d | excess | 1,428 | 0.17% | -0.13% | 49.16% |
| extension_pass | return_20d | beta-aj | 1,428 | 0.11% | -0.19% | 49.16% |
| extension_rejected | return_5d | raw | 404 | 1.45% | 0.83% | 56.44% |
| extension_rejected | return_5d | excess | 404 | 0.98% | 0.21% | 53.22% |
| extension_rejected | return_5d | beta-aj | 404 | 0.68% | 0.04% | 50.25% |
| extension_rejected | return_10d | raw | 398 | 2.71% | 1.39% | 57.29% |
| extension_rejected | return_10d | excess | 398 | 1.81% | 0.44% | 52.26% |
| extension_rejected | return_10d | beta-aj | 398 | 1.26% | 0.30% | 51.26% |
| extension_rejected | return_20d | raw | 387 | 4.98% | 1.75% | 56.07% |
| extension_rejected | return_20d | excess | 387 | 3.31% | 0.06% | 50.65% |
| extension_rejected | return_20d | beta-aj | 387 | 2.36% | -0.21% | 48.58% |

## Delta rechazado ? pasa

| Horizonte | raw net delta | excess net delta | beta-aj net delta | n rechazado raw | n pasa raw |
|---|---:|---:|---:|---:|---:|
| return_5d | 0.96% | 0.87% | 0.61% | 404 | 1,456 |
| return_10d | 1.79% | 1.69% | 1.23% | 398 | 1,447 |
| return_20d | 3.14% | 3.14% | 2.25% | 387 | 1,428 |

Lectura: el rechazo por extensi?n no filtra perdedores en el top del selector; en media, filtra ganadores m?s fuertes. El efecto aumenta con el horizonte: +0.61 pp beta-aj a 5d, +1.23 pp a 10d y +2.25 pp a 20d.

## Desglose por r?gimen SPY

| R?gimen | Cohorte | Horizonte | raw mean net | excess mean net | beta-aj mean net | n raw |
|---|---|---:|---:|---:|---:|---:|
| bull_above_sma200 | extension_pass | return_5d | 0.47% | 0.14% | 0.06% | 1,310 |
| bull_above_sma200 | extension_pass | return_10d | 0.97% | 0.32% | 0.13% | 1,301 |
| bull_above_sma200 | extension_pass | return_20d | 1.94% | 0.73% | 0.34% | 1,282 |
| bull_above_sma200 | extension_rejected | return_5d | 1.29% | 0.90% | 0.66% | 385 |
| bull_above_sma200 | extension_rejected | return_10d | 2.50% | 1.84% | 1.36% | 379 |
| bull_above_sma200 | extension_rejected | return_20d | 4.78% | 3.44% | 2.52% | 368 |
| bear_below_sma200 | extension_pass | return_5d | 0.65% | -0.17% | 0.14% | 146 |
| bear_below_sma200 | extension_pass | return_10d | 0.53% | -1.61% | -0.90% | 146 |
| bear_below_sma200 | extension_pass | return_20d | 0.98% | -4.74% | -1.90% | 146 |
| bear_below_sma200 | extension_rejected | return_5d | 4.70% | 2.60% | 0.98% | 19 |
| bear_below_sma200 | extension_rejected | return_10d | 6.91% | 1.27% | -0.78% | 19 |
| bear_below_sma200 | extension_rejected | return_20d | 8.85% | 0.69% | -0.79% | 19 |

### Delta por r?gimen ? rechazado ? pasa

| R?gimen | Horizonte | raw net delta | excess net delta | beta-aj net delta | n rechazado | n pasa |
|---|---:|---:|---:|---:|---:|---:|
| bear_below_sma200 | return_5d | 4.06% | 2.77% | 0.84% | 19 | 146 |
| bear_below_sma200 | return_10d | 6.37% | 2.88% | 0.12% | 19 | 146 |
| bear_below_sma200 | return_20d | 7.87% | 5.43% | 1.11% | 19 | 146 |
| bull_above_sma200 | return_5d | 0.82% | 0.76% | 0.60% | 385 | 1,310 |
| bull_above_sma200 | return_10d | 1.53% | 1.52% | 1.23% | 379 | 1,301 |
| bull_above_sma200 | return_20d | 2.84% | 2.71% | 2.19% | 368 | 1,282 |

Lectura por r?gimen:

- R?gimen alcista (`bull_above_sma200`): el rechazo por extensi?n destruye edge de forma consistente en raw/excess/beta-aj para 5/10/20d. Es la muestra dominante.
- R?gimen bajista (`bear_below_sma200`): muestra peque?a de rechazados (n=19). Raw y excess mejoran, pero beta-aj a 10/20d sigue negativo; no conviene extrapolar.

## Rigor y caveats

- Read-only: no se escribi? en BD ni se toc? runtime; el ?nico output persistente es este informe y el script/test/versionado del estudio.
- Causalidad: features rolling por s?mbolo calculadas con pandas; cada fila t usa datos ?t. Forward returns se calculan aparte con cierres futuros solo para outcome.
- Universo: el motor report? `survivorship_biased=False` y modo point-in-time.
- Costes: 10 bps round-trip restados en `mean_net`.
- Caveat del selector: score determinista aproximado; no incluye LLM, gates finales, learning-prior hist?rico exacto, patrones textuales ni excepciones completas. El resultado mide el gate simple de extensi?n sobre top-picks del replay, no una propuesta directa de ejecuci?n.
- La cola rechazada tiene mayor volatilidad: a 20d `std` raw 18.03% vs 10.36% en los que pasan. El edge medio podr?a venir con m?s dispersi?n/drawdown.

## Veredicto

En esta ventana hist?rica, para los top-picks del selector, el gate de extensi?n (>12% sobre SMA20) destruye m?s edge del que protege. Los rechazados superan a los que pasan en raw, excess vs SPY y beta-ajustado en todos los horizontes agregados. El hallazgo es m?s s?lido en r?gimen alcista y a 10/20d. No recomiendo tocar el gate todav?a: la acci?n segura siguiente ser?a dise?ar una excepci?n SHADOW/guarded para ?top selector + extensi?n con fuerza relativa? y medir forward paper/OOS, no relajar globalmente el gate.

## Verificaci?n

- `python -m py_compile src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_extension_gate_edge.py` ? ok.
- `pytest tests/test_strategy_edge_backtest.py -q -p no:warnings` ? 5 passed.
- `ruff check src/agente_bolsa/tools/strategy_edge_backtest.py scripts/study_extension_gate_edge.py tests/test_strategy_edge_backtest.py src/agente_bolsa/__init__.py` ? limpio.
- `ruff check src tests` ? limpio.
- `pytest -q -p no:warnings` ? 777 passed.
