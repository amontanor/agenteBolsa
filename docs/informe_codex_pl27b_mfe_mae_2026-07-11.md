# Informe P-L27B - auditoria MFE/MAE y geometria stop/take

Fecha: 2026-07-11
Version: 0.4.154 (correccion P-L27BR)
Commit de partida P-L27BR: f531e4bb

## Resultado

`excursion-quality-report` es una lectura observacional y pura de
`signal_outcomes`: no crea experimentos, propuestas ni artefactos, y no altera
historicos. El schema final es `p-l27b.excursion-quality.v2`; incluye parametros
resueltos, fechas, calidad de datos y un `content_hash` estable que excluye solo
`generated_at`.

## Correccion dimensional P-L27BR

La causa raiz de P-L27B v1 fue mezclar unidades: entry, stop y take son precios
absolutos; MFE/MAE son fracciones decimales respecto a entry. V1 dividia una
fraccion por una distancia monetaria, asi que sus `mfe_r`, `mae_r`,
`stop_consumption` y `target_attainment` quedan invalidados y no son comparables.

Las formulas v2 para long son:

- `risk_distance_price = entry_price - stop_loss` (precio)
- `reward_distance_price = take_profit - entry_price` (precio)
- `stop_distance_pct = risk_distance_price / entry_price` (fraccion decimal)
- `take_distance_pct = reward_distance_price / entry_price` (fraccion decimal)
- `reward_risk_ratio = reward_distance_price / risk_distance_price` (multiplo R)
- `mae_r = abs(min(mae_decimal, 0)) / stop_distance_pct` (multiplo R)
- `mfe_r = max(mfe_decimal, 0) / stop_distance_pct` (multiplo R)
- `target_attainment = max(mfe_decimal, 0) / take_distance_pct = mfe_r / target_r`

Ejemplo obligatorio: entry=100, stop=90, take=130, MFE=0.20 y MAE=-0.05 da
stop_distance_pct=0.10, take_distance_pct=0.30, target_r=3, MFE=2R, MAE=0.5R
y target_attainment=0.666667. La misma geometria a entry=10, stop=9, take=13
produce los mismos multiplos R.

## Conteos y semantica temporal

El informe separa ahora filas fuente de observaciones fila×horizonte:
`selected_source_rows`, `valid_geometry_source_rows`,
`excluded_source_rows` y sus motivos son contadores de fuente. Por separado,
`selected_horizon_observations`, madurez, validas y excluidas son contadores de
fila×horizonte. `geometry_coverage` usa long fuente como denominador;
`matured_valid_coverage` usa observaciones maduras como denominador.

Toda excursion usa `excursion_horizon=10d`. Las vistas 1d/3d/5d llevan
`return_horizon` explicito y la advertencia `observational_mismatched_horizon`:
relacionan retorno temprano con MFE/MAE de 10d, por lo que son solo descriptivas
y no producen recomendaciones. Grupos y buckets se publican por horizonte para
evitar presentar una senal como cuatro senales.

## Lectura local corregida

Ejecucion: `excursion-quality-report --from 2026-06-01 --to 2026-07-10
--horizon 10d --min-sample 300 --json`.

- 228.760 filas fuente: 148.289 long y 80.471 short; direction ausente e
  invalida: 0. Short permanece excluida explicitamente porque el productor no
  ofrece excursion direccional short verificable.
- Vista 10d: 228.760 observaciones seleccionadas, 216.982 maduras, 139.680
  maduras-validas y 77.302 maduras excluidas por short.
- `matured_valid_coverage=0.643740`; cero imputaciones; 139.680 legacy sin
  linaje verificable y cero verificadas.
- Metricas 10d corregidas: retorno medio/mediano 0.9844%/1.59%; MFE medio
  1.135488R; MAE medio 0.818641R; alcance medio de target 0.756992; reward/risk
  medio y mediano 1.5R.

Son estadisticas descriptivas de senales, no P&L ejecutado, alpha, exceso SPY,
causalidad, significancia ni mejora de profits.

## Idempotencia, seguridad y pruebas

Sin `--to`, los datos locales resolvieron 2026-07-07. Repetir con
`--to 2026-07-07` produjo el mismo `content_hash`; cambiar la fecha resuelta
cambia los parametros y el hash como corresponde. La lectura no modifica Store.

Las pruebas cubren formulas dimensionales, invariancia, escala de precios,
bordes y cobertura de buckets, signos MFE/MAE, cada exclusion, direction short/
ausente/invalida, conteos fuente/horizonte, estados, linaje, semantica temporal,
hash, JSON, lectura pura y CLI con Store temporal. No se llama a red, LLM,
codegen, ordenes ni propuestas.

No se modificaron estrategias, senales, ranking, gates, stops, takes, ordenes,
exposicion, horarios, timeouts, archivos protegidos ni registros historicos.
P-L27B sigue pendiente de aceptacion de direccion tecnica tras revisar P-L27BR.
