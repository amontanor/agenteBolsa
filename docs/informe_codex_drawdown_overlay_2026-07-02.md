# Informe Codex - drawdown overlay de exposicion - 2026-07-02

## Objetivo

Estudio read-only de overlays de riesgo sobre exposicion de mercado, no sobre
seleccion de acciones. No se tocaron `kernel.py`, `tools/broker.py`,
`tools/execution.py`, `tools/risk.py`, `config.py`, `.env` ni el scheduler
operativo. No se crearon ordenes ni se reinicio el sistema.

## Metodo

Ventana: 2022-01-01 a 2026-07-02, incluyendo el bear market de 2022.

Mercados:

- SPY.
- Cesta equal-weight del universo resuelto: 503 simbolos con datos, fuente
  `yfinance`; 504 solicitados incluyendo SPY, 0 faltantes.

Politicas de exposicion 0..1:

- Buy&hold.
- Regimen on/off por SPY > SMA150/200/250.
- Volatility target 10%/12%/15% anualizado con vol realizada trailing.
- Drawdown guard 10%/15%/20%: reduce exposicion al 50% bajo umbral.
- Combo regimen + vol-target.

Costes: 10/20/30 bps aplicados a cambios de exposicion (`cost_bps * turnover`).

Causalidad: todas las senales usan datos hasta `t`; la exposicion objetivo se
aplica a retornos posteriores mediante `shift(1)`.

## Resultados base - SPY

Coste medio mostrado: 20 bps.

| Politica | CAGR | Max DD | Ulcer | Peor semana | Peor mes | Sortino | DD reducida / CAGR sacrificado |
|---|---:|---:|---:|---:|---:|---:|---:|
| Buy&hold | 12.13% | -24.50% | 8.90% | -9.07% | -9.24% | 1.02 | n/a |
| Vol-target 10% | 7.33% | -13.31% | 5.71% | -3.99% | -4.83% | 1.01 | 2.33 |
| Vol-target 12% | 8.85% | -15.84% | 6.62% | -4.78% | -5.78% | 1.09 | 2.64 |
| Vol-target 15% | 9.88% | -19.53% | 8.09% | -5.96% | -7.21% | 1.07 | 2.21 |
| Regimen SMA150 | 8.88% | -19.13% | 8.53% | -5.78% | -6.13% | 0.97 | 1.65 |
| Regimen SMA200 | 7.15% | -23.26% | 10.26% | -5.75% | -8.01% | 0.81 | 0.25 |
| Drawdown guard 10% | 9.78% | -22.65% | 10.47% | -6.34% | -7.29% | 1.02 | 0.79 |
| Combo SMA150 + vol 10% | 5.95% | -12.26% | 5.65% | -3.78% | -4.11% | 0.83 | 1.98 |
| Combo SMA150 + vol 12% | 7.24% | -14.57% | 6.52% | -4.52% | -4.92% | 0.92 | 2.03 |

Lectura: el overlay que mejor reduce las grandes caidas con sacrificio razonable
es vol-target. SMA150 ayuda, pero menos por unidad de retorno sacrificado. SMA200
sale tarde en esta ventana y apenas mejora drawdown. Drawdown-guard simple reduce
poco el drawdown y empeora Ulcer por quedarse expuesto durante caidas prolongadas.

## Resultados base - equal-weight universo

Coste medio mostrado: 20 bps.

| Politica | CAGR | Max DD | Ulcer | Peor semana | Peor mes | Sortino | DD reducida / CAGR sacrificado |
|---|---:|---:|---:|---:|---:|---:|---:|
| Buy&hold | 13.36% | -20.10% | 6.32% | -9.06% | -9.29% | 1.18 | n/a |
| Vol-target 10% | 7.22% | -12.91% | 5.10% | -4.21% | -6.22% | 1.07 | 1.17 |
| Vol-target 12% | 9.11% | -13.68% | 5.71% | -5.05% | -6.25% | 1.18 | 1.51 |
| Vol-target 15% | 10.49% | -15.88% | 6.41% | -6.30% | -6.14% | 1.18 | 1.48 |
| Regimen SMA150 | 8.01% | -18.58% | 8.11% | -5.64% | -6.14% | 0.96 | 0.28 |
| Regimen SMA200 | 6.95% | -22.37% | 9.37% | -5.69% | -7.04% | 0.87 | -0.35 |
| Drawdown guard 10% | 9.35% | -21.46% | 9.95% | -6.32% | -6.86% | 0.98 | -0.34 |
| Combo SMA150 + vol 10% | 4.78% | -12.96% | 6.33% | -4.19% | -6.22% | 0.74 | 0.83 |
| Combo SMA150 + vol 12% | 6.20% | -15.03% | 7.10% | -4.65% | -6.25% | 0.86 | 0.71 |

Lectura: la robustez con equal-weight tambien favorece vol-target. Las reglas
por SMA y drawdown guard no generalizan bien en este mercado sintetico de universo.

## Walk-forward OOS

Rejilla pre-registrada: SMA150/200/250, vol-target 10/12/15%, drawdown guard
10/15/20 y combos regimen+vol. Ventana expansiva:

- entrenar 2022, aplicar 2023;
- entrenar 2022-2023, aplicar 2024;
- entrenar 2022-2024, aplicar 2025-2026.

Objetivo de seleccion en entrenamiento: max Sortino, desempate por menor max DD,
menor Ulcer y mayor CAGR.

| Mercado | Coste | CAGR OOS | Max DD OOS | Ulcer OOS | Peor semana | Peor mes | Sortino | Secuencia seleccionada |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| SPY | 10 bps | 17.17% | -12.83% | 3.36% | -4.76% | -4.91% | 1.92 | buy_hold -> vol_target_10pct -> vol_target_12pct |
| SPY | 20 bps | 16.78% | -12.90% | 3.39% | -4.78% | -4.96% | 1.88 | buy_hold -> vol_target_10pct -> vol_target_12pct |
| SPY | 30 bps | 18.95% | -12.98% | 3.40% | -4.79% | -5.01% | 2.02 | buy_hold -> buy_hold -> vol_target_12pct |
| Equal-weight | 10 bps | 18.45% | -13.47% | 4.07% | -5.69% | -6.14% | 2.09 | buy_hold -> buy_hold -> vol_target_12pct |
| Equal-weight | 20 bps | 18.26% | -13.58% | 4.12% | -5.69% | -6.14% | 2.07 | buy_hold -> buy_hold -> vol_target_12pct |
| Equal-weight | 30 bps | 21.10% | -17.80% | 3.73% | -9.06% | -6.14% | 1.98 | buy_hold -> buy_hold -> buy_hold |

OOS reduce drawdowns respecto al buy&hold full-period, pero la seleccion no es
estable: SPY cambia en 1-2 de 2 transiciones y equal-weight cambia en 0-1. Ademas
el OOS aplica mayormente 2023-2026, un tramo favorable. No basta para activar una
regla operativa.

## Conclusion

La mejor candidata de control de caidas es **vol-target**, especialmente 10%-12%.
Reduce max drawdown y peores semanas de forma consistente en SPY y equal-weight.
El coste es una renuncia clara de CAGR frente a buy&hold full-period.

No recomendaria promover una regla aun. La version honesta es:

- vol-target 12% es el punto mas equilibrado en SPY a 20 bps;
- vol-target 10% reduce mas drawdown, pero sacrifica demasiado retorno;
- regimen SMA150 puede servir como comparador simple, pero no supera a vol-target;
- drawdown-guard simple llega tarde y no mejora suficiente;
- OOS no demuestra estabilidad de parametros.

## Limitaciones

- Datos de mercado via `yfinance`; no se contrasto con segundo vendor.
- Equal-weight usa el universo resuelto actual, no un S&P 500 point-in-time
  perfecto para cada fecha; por tanto puede tener sesgo de supervivencia.
- OOS empieza a aplicar en 2023, despues del bear 2022 usado como entrenamiento.
- No se modelan impuestos, spreads intradia ni ejecucion real de rebalanceos.
- Es un estudio de exposicion de mercado, no de seleccion de acciones ni sizing
  operativo.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_drawdown_overlay.py -q` -> 4 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_drawdown_overlay.py tests\test_strategy_edge_backtest.py -q` -> 15 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 846 passed, 1 warning externa de `websockets.legacy`.
- `.\.venv\Scripts\ruff.exe check src tests` -> OK.
- `.\.venv\Scripts\ruff.exe check scripts\study_drawdown_overlay.py` -> OK.
- Estudio real: `.\.venv\Scripts\python.exe scripts\study_drawdown_overlay.py --since 2022-01-01 --to 2026-07-02 --out data\reports\drawdown_overlay_2026-07-02.json` -> OK.
- Estado operativo: `trading_mode=paper`, `allow_live_trading=false`.
- Version final: `0.4.81`.
