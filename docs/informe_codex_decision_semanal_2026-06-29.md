# Informe Codex ? decisi?n semanal por pol?tica (?ltimo mes, 2026-06-29)

## Resumen ejecutivo

- Este estudio estima distribuciones hist?ricas condicionales a 5 sesiones para el ?ltimo mes disponible. No es una predicci?n de la pr?xima semana.
- Ventana usada: 2026-05-29?2026-06-29, ?ltimos 30 d?as naturales. Muestra madura muy peque?a: 3 semanas con forward 5d completo.
- R?gimen observado en la ventana: solo `bull_above_sma200`; no hay semanas bear maduras en el ?ltimo mes, as? que no se puede estimar riesgo de giro con esta submuestra.
- Universo point-in-time S&P 500 (`survivorship_biased=False`), top-N=15, coste plano=10.0 bps.
- Muestra t?cnica: 4 fechas muestreadas, 545 candidatos elegibles, 60 top-picks del selector; semanas maduras por pol?tica: {'P0_cash': 3, 'P1_spy': 3, 'P2_top_pass_extension_gate': 3, 'P3_top_no_extension_gate': 3, 'P4_all_eligible_equal_weight': 3}.
- En este ?ltimo mes, P0 caja domina por preservaci?n de capital. Entre pol?ticas activas, P2 cae menos que P3/P4 y SPY en media, pero tiene una semana <-5%.

## Tabla de decisi?n ? ?ltimo mes, r?gimen bull

| Opci?n | semanas | retorno semanal esperado | mediana | Sharpe semanal | max DD | peor semana | % semanas neg | cola <-5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 ? Caja | 3 | 0.00% | 0.00% | n/d | 0.00% | 0.00% | 0.00% | 0.00% |
| P1 ? Comprar y mantener SPY | 3 | -0.54% | 0.47% | -0.302 | -2.60% | -2.60% | 33.33% | 0.00% |
| P2 ? Top-N que pasan gate ?12% | 3 | -0.07% | -0.85% | -0.012 | -5.88% | -5.88% | 66.67% | 33.33% |
| P3 ? Top-N sin gate extensi?n | 3 | -0.21% | -0.72% | -0.032 | -6.37% | -6.37% | 66.67% | 33.33% |
| P4 ? Todos elegibles equal-weight | 3 | -0.25% | -0.89% | -0.147 | -1.58% | -1.58% | 66.67% | 0.00% |

## Lectura

- P0 caja: 0% retorno y 0% drawdown; en una muestra mensual negativa/mixta es la referencia m?s estable.
- P1 SPY: media semanal -0.54%, peor semana -2.60%, sin cola <-5%.
- P2 top-N que pasan gate: media -0.07%, mejor que SPY/P3/P4 en esta ventana, pero peor semana -5.88% y cola <-5% en 1 de 3 semanas.
- P3 top-N sin gate: media -0.21%, peor semana -6.37%; en el ?ltimo mes no compensa abrir el gate.
- P4 todos elegibles: media -0.25%, drawdown menor (-1.58%) y sin cola <-5%, pero diluye el selector y no equivale a la operativa real.

## Veredicto para decisi?n

Con solo el ?ltimo mes, no hay evidencia para aumentar riesgo ni abrir el gate de extensi?n. La muestra favorece mantener disciplina/caja: P2 es la opci?n activa menos mala en media, pero a?n presenta cola semanal <-5%. P3, que antes ganaba en ventana larga bull, no mejora en esta submuestra reciente.

## Caveats

- Muestra extremadamente peque?a: 3 semanas maduras; no usar como prueba estad?stica.
- No hay r?gimen bear en esta ventana; el riesgo de giro debe leerse del informe largo 2022?2026, no de este corte mensual.
- Selector aproximado: no incluye LLM, learning-prior hist?rico exacto, gates completos ni ejecuci?n real.
- Equal-weight: el sistema real topa a 4 ?rdenes/ciclo y m?nimo $100, as? que el despliegue real ser?a menor y m?s concentrado.
- Costes planos de 10 bps; no modela slippage variable ni gaps.

## Comando ejecutado

```powershell
.\.venv\Scripts\python.exe scripts\study_weekly_policy_decision.py --since 2026-05-29 --to 2026-06-29 --sample-every 5 --progress-every 50 --json > tmp_weekly_policy_last_month_20260629.json
```
