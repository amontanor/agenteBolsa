# Informe Codex - robustez historica profunda overlay vol-target - 2026-07-02

## Veredicto

**Criterio pre-registrado: CUMPLE.**

Vol-target 12% fijo, neto de 20 bps, reduce max drawdown y peor mes frente a
buy&hold en **11/11 anos calendario** con drawdown anual de buy&hold >15%
(100%, umbral requerido >=80%) y mantiene Sortino full-period superior:
**0.765 vs 0.657**.

Esto no convierte la regla en palanca operativa automatica. El resultado favorable
viene con coste claro de CAGR, dependencia del feed `yfinance`, y no prueba
ejecucion real ni fiscalidad. Es una evidencia read-only para revision humana.

## Metodo

Estudio 100% read-only. No se tocaron `src/agente_bolsa/kernel.py`,
`src/agente_bolsa/tools/broker.py`, `src/agente_bolsa/tools/execution.py`,
`src/agente_bolsa/tools/risk.py`, `src/agente_bolsa/config.py`, `.env` ni el
scheduler. No se crearon ordenes.

Datos:

- Fuente: `yfinance`, descarga con `auto_adjust=True` mediante el helper local.
- Activo estudiado: solo SPY.
- Cesta equal-weight: no usada, para evitar sesgo de supervivencia en tramo largo.
- Ventana solicitada: 2000-01-01 a 2026-07-02.
- Primer dato real SPY: 2000-01-03.
- Ultimo dato real SPY: 2026-07-01. `yfinance` trata `end` como limite exclusivo.

Rejilla pre-registrada sin parametros nuevos:

- Buy&hold.
- SMA150/200/250.
- Vol-target 10%/12%/15%.
- Drawdown guard 10%/15%/20%.
- Combos regimen + vol-target.
- Costes 10/20/30 bps por turnover de exposicion.

Causalidad: cada exposicion objetivo usa informacion disponible hasta `t`; la
exposicion aplicada a retornos usa `shift(1)`.

Artefacto reproducible: `data/reports/drawdown_overlay_deep_2026-07-02.json`.

## Politica Fija OOS

Test sin seleccion: aplicar buy&hold, vol-target 10% y vol-target 12% fijos en
todos los bloques OOS anuales 2005-2026.

| Coste | Politica | CAGR | Max DD | Ulcer | Peor semana | Peor mes | Sortino |
|---:|---|---:|---:|---:|---:|---:|---:|
| 10 bps | Buy&hold | 10.87% | -55.19% | 12.38% | -19.79% | -16.52% | 0.781 |
| 10 bps | Vol-target 10% | 7.59% | -25.87% | 6.71% | -6.50% | -6.11% | 1.008 |
| 10 bps | Vol-target 12% | 8.73% | -29.81% | 7.66% | -7.77% | -6.75% | 1.039 |
| 20 bps | Buy&hold | 10.87% | -55.19% | 12.38% | -19.79% | -16.52% | 0.781 |
| 20 bps | Vol-target 10% | 7.13% | -26.51% | 7.03% | -6.54% | -6.17% | 0.952 |
| 20 bps | Vol-target 12% | 8.37% | -30.45% | 7.97% | -7.81% | -6.81% | 1.000 |
| 30 bps | Buy&hold | 10.87% | -55.19% | 12.38% | -19.79% | -16.52% | 0.781 |
| 30 bps | Vol-target 10% | 6.67% | -27.14% | 7.35% | -6.57% | -6.24% | 0.897 |
| 30 bps | Vol-target 12% | 8.00% | -31.07% | 8.29% | -7.85% | -6.86% | 0.961 |

Lectura: la politica fija 12% conserva gran parte de la proteccion frente a
buy&hold incluso a 30 bps. La penalizacion es retorno: a 20 bps, CAGR baja de
10.87% a 8.37% en el tramo OOS 2005-2026.

## Full Period

Periodo completo 2000-01-03 a 2026-07-01, coste 20 bps.

| Politica | CAGR | Max DD | Ulcer | Peor semana | Peor mes | Sortino | Exposicion media |
|---|---:|---:|---:|---:|---:|---:|---:|
| Buy&hold | 8.43% | -55.19% | 16.15% | -19.79% | -16.52% | 0.657 | 100.0% |
| Vol-target 10% | 5.21% | -36.26% | 12.30% | -6.54% | -6.52% | 0.731 | 72.0% |
| Vol-target 12% | 6.09% | -41.12% | 13.90% | -7.81% | -7.79% | 0.765 | 79.5% |
| Vol-target 15% | 6.83% | -46.94% | 15.98% | -9.48% | -9.19% | 0.759 | 87.2% |
| Regimen SMA200 | 5.97% | -24.09% | 9.16% | -10.96% | -10.98% | 0.634 | 71.5% |

Lectura: vol-target no maximiza CAGR, pero si mejora Sortino y reduce colas. Las
reglas SMA pueden reducir mas drawdown en este historico, pero sacrifican retorno,
mantienen peores semanas/meses grandes y no son el objeto del criterio operativo
pre-registrado.

## Walk-Forward Expansivo

Bloques anuales: entrena 2000-2004, aplica 2005; entrena 2000-2005, aplica
2006; y asi hasta 2026. Objetivo de seleccion heredado del estudio previo:
max Sortino de entrenamiento, desempate por menor max DD, menor Ulcer y mayor
CAGR.

| Coste | Pasos OOS | Cambios de politica | Tasa de cambio | Conteo de seleccion |
|---:|---:|---:|---:|---|
| 10 bps | 22 | 8 | 38.1% | combo_sma250_vol15pct: 12; vol_target_12pct: 5; regime_sma250: 4; combo_sma250_vol10pct: 1 |
| 20 bps | 22 | 4 | 19.0% | combo_sma250_vol15pct: 12; vol_target_12pct: 6; regime_sma250: 4 |
| 30 bps | 22 | 4 | 19.0% | combo_sma250_vol15pct: 11; vol_target_15pct: 7; regime_sma250: 4 |

Secuencia a 20 bps:

`regime_sma250 -> regime_sma250 -> regime_sma250 -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> regime_sma250 -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> combo_sma250_vol15pct -> vol_target_12pct -> vol_target_12pct -> vol_target_12pct -> vol_target_12pct -> vol_target_12pct -> vol_target_12pct`

Lectura: el selector no converge siempre a vol-target. Esto es una alerta contra
optimizar la politica a posteriori. Por eso el resultado decisivo es la politica
fija 12%, no la seleccion walk-forward.

## Episodios De Drawdown

Coste 20 bps. Recuperacion en dias de mercado desde el trough del episodio hasta
recuperar el pico previo; `n/d` si no recupera dentro del historico disponible.

| Episodio | Politica | Max DD | Peor semana | Peor mes | Ulcer | Recuperacion |
|---|---|---:|---:|---:|---:|---:|
| 2000-02 dot-com | Buy&hold | -47.52% | -11.27% | -10.49% | 22.83% | 1020 |
| 2000-02 dot-com | Vol-target 10% | -34.69% | -5.09% | -6.52% | 18.65% | 1094 |
| 2000-02 dot-com | Vol-target 12% | -39.85% | -6.09% | -7.79% | 21.58% | 1139 |
| 2008-09 crisis financiera | Buy&hold | -55.19% | -19.79% | -16.52% | 26.27% | 869 |
| 2008-09 crisis financiera | Vol-target 10% | -26.00% | -4.09% | -5.28% | 14.45% | 469 |
| 2008-09 crisis financiera | Vol-target 12% | -30.04% | -4.89% | -6.32% | 16.65% | 480 |
| 2011 crisis deuda/US downgrade | Buy&hold | -18.61% | -7.15% | -6.94% | 8.95% | 220 |
| 2011 crisis deuda/US downgrade | Vol-target 10% | -12.42% | -4.55% | -5.21% | 7.02% | 111 |
| 2011 crisis deuda/US downgrade | Vol-target 12% | -14.30% | -5.45% | -6.25% | 7.96% | 113 |
| 2015-16 China/energia | Buy&hold | -13.02% | -5.86% | -6.10% | 5.46% | 45 |
| 2015-16 China/energia | Vol-target 10% | -10.97% | -4.89% | -6.14% | 6.01% | 208 |
| 2015-16 China/energia | Vol-target 12% | -11.77% | -5.41% | -6.81% | 6.12% | 197 |
| 2018 Q4 tightening | Buy&hold | -19.35% | -7.05% | -14.49% | 7.72% | 75 |
| 2018 Q4 tightening | Vol-target 10% | -12.27% | -4.11% | -6.87% | 6.34% | 131 |
| 2018 Q4 tightening | Vol-target 12% | -13.69% | -4.23% | -8.20% | 6.75% | 81 |
| 2020 Covid shock | Buy&hold | -33.72% | -14.55% | -24.30% | 18.65% | 97 |
| 2020 Covid shock | Vol-target 10% | -11.37% | -6.54% | -7.20% | 7.89% | 107 |
| 2020 Covid shock | Vol-target 12% | -13.53% | -7.81% | -8.60% | 9.40% | 107 |
| 2022 inflacion/tipos | Buy&hold | -24.50% | -5.75% | -9.24% | 14.06% | 294 |
| 2022 inflacion/tipos | Vol-target 10% | -13.31% | -3.95% | -4.83% | 8.22% | 198 |
| 2022 inflacion/tipos | Vol-target 12% | -15.84% | -4.72% | -5.78% | 9.83% | 203 |

Matiz importante: en 2015-16, el episodio definido no llega a >15% con SPY
ajustado de yfinance; se mantiene en la tabla porque estaba pre-listado en el
prompt. Tambien hay episodios donde la recuperacion de vol-target tarda mas que
buy&hold aunque el drawdown sea menor, por menor exposicion durante la vuelta.

## Sanity-Check SPY Vs GSPC

Comparacion de retornos diarios SPY contra `^GSPC`:

- Dias solapados: 6662.
- Correlacion: 0.987806.
- Desviacion absoluta media: 0.0964%.
- Desviacion absoluta maxima: 3.0986%.
- Dias con desviacion >1%: 28.

Top desviaciones >1%:

| Fecha | SPY | ^GSPC | Desviacion abs |
|---|---:|---:|---:|
| 2000-01-07 | 5.81% | 2.71% | 3.10% |
| 2008-10-13 | 14.52% | 11.58% | 2.94% |
| 2000-12-11 | 3.48% | 0.75% | 2.72% |
| 2000-09-22 | 1.82% | -0.02% | 1.84% |
| 2000-12-08 | 0.23% | 1.96% | 1.73% |
| 2000-01-06 | -1.61% | 0.10% | 1.70% |
| 2008-10-24 | -5.07% | -3.45% | 1.62% |
| 2008-09-22 | -2.26% | -3.82% | 1.56% |
| 2000-02-24 | -2.01% | -0.53% | 1.48% |
| 2008-10-08 | -2.52% | -1.13% | 1.39% |

No hay evidencia de split roto obvio, pero las desviaciones de 2000 y 2008 son
suficientemente grandes para no tratar el feed como verdad perfecta. Parte puede
venir de SPY ajustado por dividendos frente a `^GSPC` indice de precio, timing de
ajustes o diferencias de proveedor.

## Criterios Pre-Registrados

Vol-target 12% fijo, neto 20 bps:

| Anno | Buy&hold max DD | VT12 max DD | Buy&hold peor mes | VT12 peor mes | Cumple |
|---:|---:|---:|---:|---:|---|
| 2000 | -17.13% | -12.05% | -7.47% | -5.31% | si |
| 2001 | -28.81% | -23.04% | -9.54% | -7.79% | si |
| 2002 | -32.97% | -21.89% | -10.49% | -5.10% | si |
| 2008 | -47.12% | -20.31% | -16.52% | -6.32% | si |
| 2009 | -27.13% | -10.65% | -10.74% | -3.61% | si |
| 2010 | -15.70% | -9.52% | -7.95% | -4.42% | si |
| 2011 | -18.61% | -14.30% | -6.94% | -6.25% | si |
| 2018 | -19.35% | -13.69% | -8.80% | -6.52% | si |
| 2020 | -33.72% | -13.53% | -12.49% | -4.58% | si |
| 2022 | -24.50% | -15.84% | -9.24% | -5.78% | si |
| 2025 | -18.76% | -12.90% | -5.57% | -4.63% | si |

Resultado:

- Reduccion max DD y peor mes: 11/11 = 100%, umbral requerido >=80%.
- Sortino periodo completo: vol-target 12% 0.765 >= buy&hold 0.657.
- Veredicto binario: **CUMPLE**.

## Por Que Podria Ser Falso O Exagerado

- `yfinance` no es un vendor institucional. El sanity-check detecta 28 dias con
  desviacion >1% frente a `^GSPC`; no invalida el estudio, pero exige cautela.
- SPY ajustado por dividendos no es exactamente comparable a `^GSPC` precio.
- El modelo de costes solo aplica bps por turnover de exposicion; no incluye
  impuestos, spreads intradia, tracking error, latencia ni restriccion de
  vehiculo real.
- Vol-target reduce drawdown comprando menos volatilidad, pero eso tambien puede
  retrasar recuperaciones tras caidas violentas.
- El selector walk-forward no es estable como politica unica; usarlo para elegir
  variantes a posteriori seria cherry-picking.
- El criterio pre-registrado valida control de caidas y Sortino, no maximiza CAGR.
  En periodo completo a 20 bps, CAGR baja de 8.43% a 6.09%.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_drawdown_overlay.py tests\test_drawdown_overlay_deep.py -q` -> 9 passed.
- `.\.venv\Scripts\ruff.exe check scripts\study_drawdown_overlay_deep.py tests\test_drawdown_overlay_deep.py` -> OK.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 851 passed, 1 warning externa de `websockets.legacy`.
- `.\.venv\Scripts\ruff.exe check src tests scripts` -> OK.
- Estudio real: `.\.venv\Scripts\python.exe scripts\study_drawdown_overlay_deep.py --since 2000-01-01 --to 2026-07-02 --out data\reports\drawdown_overlay_deep_2026-07-02.json` -> OK.
- Version actualizada: 0.4.82.
- Estado operativo: `.\.venv\Scripts\python.exe -m agente_bolsa.main status` -> `trading_mode=paper`, `allow_live_trading=false`.
- `.env`: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `TRADING_MODE=paper`, `ALLOW_LIVE_TRADING=false`.
- Nota: `validate-agent-config --json` no existe en el CLI actual; `status` se uso como verificacion disponible.
