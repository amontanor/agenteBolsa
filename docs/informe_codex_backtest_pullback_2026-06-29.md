# Informe Codex: backtest historico pullback vs breakout (2026-06-29)

## Resumen ejecutivo

Se implemento y ejecuto un estudio historico read-only para comparar `builtin_pullback` contra `builtin_breakout` en una ventana larga: 2024-01-01 a 2026-06-29, con horizontes forward 5/10/20 sesiones, costes round-trip de 10 bps, exceso vs SPY y retorno beta-ajustado.

Veredicto: con esta metodologia, `builtin_pullback` no muestra edge robusto superior a `builtin_breakout`. En crudo queda muy cerca a 5d, peor a 10d/20d; en excess vs SPY queda peor en todos los horizontes; en beta-ajustado queda levemente mejor a 5d, practicamente igual a 20d y peor a 10d. En regimen bajista la muestra pullback es pequena (n=360 por horizonte) y tambien queda peor que breakout en beta-ajustado.

No promuevo nada. Esto es evidencia para decidir el 6-jul, no un cambio de runtime.

## Cambios implementados

Nuevo script:

- `scripts/study_pullback_breakout_backtest.py`

Nuevo modulo testeable:

- `src/agente_bolsa/tools/strategy_edge_backtest.py`

Nuevo test:

- `tests/test_strategy_edge_backtest.py`

Version:

- `src/agente_bolsa/__init__.py`: `0.4.59` -> `0.4.60`

El script no escribe en la BD ni modifica datos operativos. Para no tocar `data/cache`, usa el fetcher existente `download_daily_prices_with_metadata` con `cache_dir` temporal del sistema: `C:\Users\utopi\AppData\Local\Temp\agente_bolsa_strategy_edge_backtest_cache`.

## Metodologia

### Reutilizacion del sistema existente

Se reviso `src/agente_bolsa/tools/backtest.py` y los CLI `backtest` / `backtest-baseline`. Ese motor simula trades single-symbol con stop/take, no un estudio cross-sectional de senales forward por simbolo-dia. Por eso se reutilizaron sus piezas base, pero no su bucle de trades:

- descarga de precios: `download_daily_prices_with_metadata`
- features causales: `add_basic_technical_features`
- universo: `resolve_study_universe` y `universe_as_of`
- convencion de forward return: `close[t+N] / close[t] - 1`, equivalente a `signal_learning._outcome_for_signal`

### Vectorizacion

La primera version llamaba al validador completo por simbolo-dia y era inviable: tras 53 minutos no habia producido JSON. Se paro el proceso, se elimino el `tmp_*.json` vacio y se reescribio el estudio.

La version final:

- descarga cada simbolo una vez;
- calcula `add_basic_technical_features(frame)` una sola vez por simbolo;
- calcula forward returns vectorizados con `shift(-N)`;
- evalua senales solo cada 5 sesiones para reducir solape de ventanas forward;
- imprime progreso con ETA por stderr.

Smoke previo:

- comando: `python scripts/study_pullback_breakout_backtest.py --since 2025-10-01 --to 2025-12-31 --max-symbols 10 --horizons 5,10,20 --sample-every 5 --progress-every 2 --json`
- duracion: 2.75s total
- escaneo interno: 0.4s para 10 simbolos
- estimacion antes de completo: minutos bajos, dominado por descarga/cache

Run completo:

- comando: `python scripts/study_pullback_breakout_backtest.py --since 2024-01-01 --to 2026-06-29 --horizons 5,10,20 --sample-every 5 --progress-every 50 --json`
- duracion: 23.43s
- progreso final: 505/505 simbolos, 7707 senales pullback, 41550 senales breakout durante el scan

### Look-ahead

No hay fuga temporal en las features usadas:

- `add_basic_technical_features` usa rolling/pct_change/shift sobre la serie historica completa;
- en pandas, la fila `t` de `rolling()` y `pct_change()` solo usa datos `<= t`;
- los forward returns se calculan despues, separados de los predicados de entrada, con `close.shift(-N)`.

### Survivorship

El estudio uso `universe_as_of(date)` con `data/universe/sp500_changes.csv`.

Resultado:

- `mode`: `point_in_time`
- `survivorship_biased`: `false`
- universo actual detectado: 503 simbolos
- universo diario historico: 503 a 504 simbolos

Caveat: el fichero de cambios existe, pero es pequeno. Aunque el modo reportado no cae al fallback, la calidad point-in-time depende de que `data/universe/sp500_changes.csv` este completo para todo 2024-2026. Si ese fichero no recoge todos los cambios reales del indice, queda sesgo residual.

### Breakout y pullback

Pullback:

- replica de forma vectorizada los umbrales de `builtin_pullback`: tendencia mayor intacta, `distance_sma20` entre -5% y +8%, RSI 40-60, `return_5d <= 2%`, `return_20d >= -8%`, `return_60d > 0`, y exclusion de flags de momentum/breakout.

Breakout:

- `builtin_breakout` real llama a `validate_symbol_technical_state`.
- Para hacerlo viable, el estudio usa una aproximacion vectorizada del validador tecnico: scores long/short, velas y flags `event_momentum_long`, `range_expansion_breakout_long`, `orderly_breakout_long`, `breakout_continuation_long`, `breakout_failure_risk`, `momentum_shakeout_hold_long`.
- Limitacion: se omite `chart_patterns` porque no es vectorizable barato. Esto puede mover algunas senales marginales de breakout. El informe trata la comparacion como "aproximacion historica vectorizada del filtro real", no como reproduccion bit-a-bit del runtime.

## Muestra

Ventana:

- desde: 2024-01-01
- hasta: 2026-06-29
- sesiones de mercado: 623
- fechas de senal muestreadas: 125
- simbolos escaneados: 504
- simbolos con features: 504

Senales:

| estrategia | senales detectadas | n 5d maduro | n 10d maduro | n 20d maduro |
|---|---:|---:|---:|---:|
| builtin_pullback | 7,716 | 7,652 | 7,571 | 7,462 |
| builtin_breakout | 41,595 | 41,267 | 40,910 | 40,278 |

La diferencia entre senales detectadas y n maduro viene del final de ventana: faltan cierres futuros para algunos horizontes.

## Resultados overall

Mean net resta 10 bps round-trip.

| estrategia | horizonte | raw mean | raw mean net | excess vs SPY mean net | beta-aj mean net | hit raw |
|---|---:|---:|---:|---:|---:|---:|
| breakout | 5d | 0.311% | 0.211% | -0.120% | -0.092% | 53.16% |
| pullback | 5d | 0.302% | 0.202% | -0.138% | -0.064% | 53.27% |
| breakout | 10d | 0.667% | 0.567% | -0.130% | -0.067% | 54.25% |
| pullback | 10d | 0.553% | 0.453% | -0.222% | -0.090% | 54.23% |
| breakout | 20d | 1.417% | 1.317% | -0.100% | 0.044% | 55.59% |
| pullback | 20d | 1.314% | 1.214% | -0.305% | 0.038% | 55.03% |

Delta pullback - breakout:

| horizonte | raw delta | excess delta | beta-aj delta |
|---|---:|---:|---:|
| 5d | -0.009% | -0.017% | +0.028% |
| 10d | -0.114% | -0.092% | -0.023% |
| 20d | -0.103% | -0.205% | -0.006% |

Lectura:

- No hay superioridad robusta de pullback.
- En beta-ajustado, el 5d mejora ligeramente frente a breakout, pero el efecto es pequeno.
- A 10d y 20d, pullback no bate.

## Resultados por regimen

Regimen definido por SPY:

- `bull_above_sma200`: SPY > SMA200
- `bear_below_sma200`: SPY < SMA200

### Regimen bull_above_sma200

| estrategia | horizonte | n | raw mean net | excess mean net | beta-aj mean net |
|---|---:|---:|---:|---:|---:|
| breakout | 5d | 39,216 | 0.203% | -0.116% | -0.092% |
| pullback | 5d | 7,292 | 0.212% | -0.106% | -0.057% |
| breakout | 10d | 38,859 | 0.532% | -0.088% | -0.051% |
| pullback | 10d | 7,211 | 0.464% | -0.183% | -0.075% |
| breakout | 20d | 38,227 | 1.262% | 0.030% | 0.089% |
| pullback | 20d | 7,102 | 1.228% | -0.163% | 0.075% |

Lectura:

- Pullback compite a 5d en bull, incluso algo mejor beta-ajustado.
- A 10d/20d no bate de forma clara.

### Regimen bear_below_sma200

| estrategia | horizonte | n | raw mean net | excess mean net | beta-aj mean net |
|---|---:|---:|---:|---:|---:|
| breakout | 5d | 2,051 | 0.366% | -0.196% | -0.100% |
| pullback | 5d | 360 | -0.004% | -0.781% | -0.209% |
| breakout | 10d | 2,051 | 1.232% | -0.925% | -0.353% |
| pullback | 10d | 360 | 0.231% | -1.004% | -0.382% |
| breakout | 20d | 2,051 | 2.355% | -2.532% | -0.799% |
| pullback | 20d | 360 | 0.947% | -3.096% | -0.691% |

Lectura:

- La muestra pullback bajista es mucho menor.
- Pullback no gana en raw/excess.
- En beta-aj 20d es algo menos malo que breakout, pero con n=360 y sin consistencia en 5d/10d no es una base fuerte.

## Caveats

1. `builtin_breakout` es aproximacion vectorizada, no reproduccion exacta bit-a-bit.
   - Se replican scores tecnicos, velas y flags relevantes.
   - Se omiten `chart_patterns`.

2. Aunque el universo se reconstruye con `universe_as_of`, la calidad point-in-time depende del fichero local `data/universe/sp500_changes.csv`.

3. El muestreo semanal reduce pseudo-replicacion, pero no la elimina por completo:
   - una senal de 20d sigue solapando con la siguiente senal semanal;
   - aun asi es bastante mas limpio que evaluar todos los dias.

4. Beta-ajustado usa beta rolling de 120 sesiones contra SPY:
   - es util para separar nivel de mercado, pero no sustituye un modelo multifactorial.

5. Los costes son 10 bps round-trip fijos:
   - no modelan spread variable, liquidez por simbolo, gaps ni slippage intradia.

## Veredicto para el 6-jul

Con este backtest, `builtin_pullback` no tiene evidencia suficiente para pasar a ACTIVE por superioridad historica frente a `builtin_breakout`.

Lo que si sugiere:

- pullback puede ser competitivo a 5d en regimen alcista y beta-ajustado;
- no hay edge consistente a 10d/20d;
- en regimen bajista no hay robustez suficiente.

Decision recomendada:

- mantener `builtin_pullback` en SHADOW;
- usar outcomes paper reales y el comparador `study_strategy_edge_compare.py` como confirmacion OOS;
- si el 6-jul se evalua promocion, exigir que la evidencia paper confirme al menos el bolsillo 5d alcista beta-ajustado, no una media global debil.

## Verificacion

Comandos ejecutados:

- `python -m pytest tests/test_strategy_edge_backtest.py -q`
- `python -m ruff check src/agente_bolsa/tools/strategy_edge_backtest.py tests/test_strategy_edge_backtest.py scripts/study_pullback_breakout_backtest.py`
- `python -m ruff check src tests`
- `python -m pytest -q -p no:warnings`
- smoke 10 simbolos / 3 meses
- run completo 2024-01-01 a 2026-06-29

Resultado:

- ruff completo limpio.
- suite completa verde: 775 passed en 148.60s.
