# Informe Codex - P3 pullback vs breakout

Fecha de ejecucion: 2026-07-05  
Ventana solicitada: desde 2026-06-25  
Estado: read-only, sin promocion ni cambios de trading

## Veredicto

**SE POSPONE el veredicto de promocion de `builtin_pullback`.**

Motivo: con los outcomes disponibles tras el cierre del 3-jul, `builtin_pullback`
no tiene horizonte 10d maduro (`n=0`). El 5d ya supera el minimo bruto (`n=53`),
pero procede de un unico `signal_date` maduro, 2026-06-25. Por tanto no se puede
evaluar el criterio pre-registrado "5d y 10d positivos, excess vs SPY positivo,
n>=30 y sin dependencia de un solo dia/sector".

No se promueve nada en esta tarea.

## Comandos ejecutados

```powershell
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 10 --benchmark SPY
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 20 --benchmark SPY
.\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel --shadow-scoreboard --history 20 --json
```

## Cobertura de maduracion

Filas deduplicadas estrategia-simbolo-dia: 3.359.

| estrategia | filas | 1d maduro | 3d maduro | 5d maduro | 10d maduro |
|---|---:|---:|---:|---:|---:|
| builtin_pullback | 373 | 295 | 168 | 53 | 0 |
| builtin_breakout | 2.986 | 2.488 | 1.493 | 497 | 0 |

Detalle relevante:

| estrategia | horizonte | fecha madura dominante |
|---|---:|---|
| builtin_pullback | 5d | 2026-06-25: 53/53 muestras |
| builtin_breakout | 5d | 2026-06-25: 497/497 muestras |
| ambas | 10d | sin muestras maduras |

## Resultados con coste 10 bps

### Retorno crudo neto

| estrategia | 1d | 3d | 5d | 10d |
|---|---:|---:|---:|---:|
| builtin_pullback | -0.61% | -1.78% | -3.07% | n/d |
| builtin_breakout | -0.08% | +0.19% | +0.95% | n/d |
| delta pullback-breakout | -0.53% | -1.97% | -4.02% | n/d |

### Excess vs SPY neto

| estrategia | 1d | 3d | 5d | 10d |
|---|---:|---:|---:|---:|
| builtin_pullback | -0.89% | -3.28% | -4.50% | n/d |
| builtin_breakout | -0.37% | -1.32% | -0.48% | n/d |
| delta pullback-breakout | -0.52% | -1.96% | -4.02% | n/d |

## Resultados con coste 20 bps

### Retorno crudo neto

| estrategia | 1d | 3d | 5d | 10d |
|---|---:|---:|---:|---:|
| builtin_pullback | -0.71% | -1.88% | -3.17% | n/d |
| builtin_breakout | -0.18% | +0.09% | +0.85% | n/d |
| delta pullback-breakout | -0.53% | -1.97% | -4.02% | n/d |

### Excess vs SPY neto

| estrategia | 1d | 3d | 5d | 10d |
|---|---:|---:|---:|---:|
| builtin_pullback | -0.99% | -3.38% | -4.60% | n/d |
| builtin_breakout | -0.47% | -1.42% | -0.58% | n/d |
| delta pullback-breakout | -0.52% | -1.96% | -4.02% | n/d |

## Regimen, semana y dependencia

El 5d maduro no es robusto porque solo cubre senales del 2026-06-25.

| estrategia | semana | n 5d | media 5d |
|---|---:|---:|---:|
| builtin_pullback | 2026-W26 | 53 | -2.97% |
| builtin_breakout | 2026-W26 | 497 | +1.05% |

Por regimen en 5d:

| estrategia | regimen | n | media 5d |
|---|---|---:|---:|
| builtin_pullback | bullish | 48 | -3.12% |
| builtin_pullback | neutral | 5 | -1.51% |
| builtin_breakout | bullish | 497 | +1.05% |

Sector: no hay `sector` persistido en los features de estas filas; queda `unknown`.
Por tanto no se puede descartar ni confirmar dependencia sectorial con esta muestra.

Top contribuidores 5d de `builtin_pullback`:

| lado | simbolo | contribucion | retorno |
|---|---|---:|---:|
| peor | CRWD | -71.32% | -71.32% |
| peor | STX | -22.21% | -22.21% |
| peor | MRVL | -14.34% | -14.34% |
| mejor | TROW | +10.96% | +10.96% |
| mejor | IFF | +9.85% | +9.85% |
| mejor | GD | +7.44% | +7.44% |

La media negativa 5d de pullback esta muy afectada por CRWD, pero incluso sin
forzar esa lectura el problema principal sigue siendo de madurez: 10d no existe y
5d es un solo dia.

## Calidad de candidatos

Scoreboard reciente (`cycle-funnel --shadow-scoreboard --history 20`) para
`builtin_pullback`:

| fecha/run reciente | shadow candidates | distance_sma20 mediana | rsi_14 mediana |
|---|---:|---:|---:|
| 2026-07-05 / opp_c0d04d228ff6 | 49 | +0.52% | 54.39 |
| 2026-07-03 / opp_21e17b55882b | 49 | +0.52% | 54.39 |
| 2026-07-02 / closed_f95e32e34510 | 52 | +0.16% | 53.56 |

Distribucion deduplicada desde 2026-06-25:

| estrategia | metrica | n | min | q1 | mediana | q3 | max |
|---|---|---:|---:|---:|---:|---:|---:|
| builtin_pullback | distance_sma20 | 373 | -4.83% | -0.67% | +0.53% | +1.57% | +7.93% |
| builtin_pullback | rsi_14 | 373 | 40.00 | 49.88 | 54.04 | 56.65 | 59.99 |
| builtin_breakout | distance_sma20 | 2.986 | -24.48% | -2.41% | +2.03% | +5.15% | +143.34% |
| builtin_breakout | rsi_14 | 2.986 | 2.88 | 44.04 | 56.50 | 66.72 | 97.30 |

Replay read-only del gate real de entrada sobre los 373 pullbacks persistidos:

| conjunto | total | aprobados | rechazados |
|---|---:|---:|---:|
| todos los pullbacks | 373 | 0 | 373 |
| pullbacks con 5d maduro | 53 | 0 | 53 |

Motivos principales de rechazo: score por debajo del minimo 12 y
`entry_score_v2` bajo por sentimiento/reward-risk no disponible. Este replay se
hizo contra features persistidos, no contra el escaneo vivo actual.

## Criterios pre-registrados

Pullback -> ACTIVE solo si:

| criterio | resultado | cumple |
|---|---|---|
| expectancy 5d neta 10 bps positiva | -3.07% | NO |
| expectancy 10d neta 10 bps positiva | n=0 | NO EVALUABLE |
| excess vs SPY 5d positivo | -4.50% neto | NO |
| excess vs SPY 10d positivo | n=0 | NO EVALUABLE |
| n>=30 maduro | 5d si, 10d no | NO |
| sin dependencia de un solo dia/sector | 5d depende de 2026-06-25; sector no disponible | NO |

Veredicto binario: **NO PROMOVER / VEREDICTO POSPUESTO POR INMADUREZ 10D**.

## Limitaciones

- El cierre del 3-jul aun no da horizonte 10d para senales desde 2026-06-25.
- El 5d maduro solo cubre un dia de senales; no representa regimenes ni semanas.
- No hay sector persistido en las filas usadas; no se puede medir concentracion
  sectorial real.
- La lectura de gate de entrada es replay read-only sobre features guardados; no
  modifica decisiones ni ordenes.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests/ -x -q`: `975 passed, 1 warning`.
- `.\.venv\Scripts\python.exe -m ruff check src tests scripts`: limpio.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: `trading_mode=paper`, `allow_live_trading=false`.
- Diff de bloqueados: vacio.
- No hay bump de `__version__`: esta entrega solo ejecuta el estudio y anade el
  informe, sin cambios de codigo ni conducta.
