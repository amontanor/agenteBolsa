# P-L40B-T — caracterización de `performance_daily`

Fecha: 14-jul-2026
Base: `0.4.171`, commit `6640ed91ed4d83f598950517e4997a82a2043e9a`
Rama: `codex/pl40b-tests`
Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl40b_tests`

Este documento pertenece únicamente al worktree de pruebas. No implementa
P-L40B ni modifica el productor productivo.

## Flujo actual observado

```text
BrokerClientFactory.alpaca_portfolio_snapshot()
  → scheduler._persist_daily_performance()
  → tools.performance_baseline.build_daily_performance()
  → Store.upsert_performance_daily()
  → Store.performance_daily()
  → digest / watchdog / dashboard / CLI / scoreboard
```

`post_market_review_job` llama a `_persist_daily_performance` después de la
reconciliación y del pipeline de medición. El digest del pipeline de medición
se genera antes de esa llamada; por tanto, el digest de esa misma ejecución no
puede consumir todavía la fila recién persistida.

## Comportamiento actual caracterizado

### Pérdida de alpha

`build_daily_performance` devuelve `alpha_vs_spy`. El método de persistencia
lee `item["alpha"]`; la columna `performance_daily.alpha` queda `NULL` aunque
el valor exista en memoria.

### Pérdida de payload

El productor coloca métricas en el nivel superior del diccionario. El UPSERT
persiste `item.get("payload", {})`, por lo que `payload_json` queda `{}`.
Se pierden de la tabla, aunque permanecen en el evento de auditoría:

- `avg_exposure`;
- `result_metrics`;
- `process_metrics`;
- `benchmarks`;
- `regime`.

### SPY MultiIndex

El lector actual espera una columna plana `Close`. La caché generada por
yfinance para un símbolo tiene columnas como `("SPY", "Close")`; la función
degrada a `None`. Las pruebas usan únicamente DataFrames y ficheros pickle
sintéticos; nunca llaman a yfinance, red o broker.

### Sobrescritura

`session_date` es la clave primaria y el UPSERT evita filas duplicadas. Sin
embargo, un contenido distinto para el mismo día sustituye el contenido
anterior sin hash, revisión o conflicto auditable. `created_at` conserva el
valor de la inserción inicial, por lo que no identifica la última observación.

### Exposición

El campo llamado `avg_exposure` se calcula con un único snapshot:

```text
sum(abs(position.market_value)) / equity
```

Es una exposición bruta de snapshot EOD, no una media temporal de la sesión.
No debe promoverse automáticamente a `session_average_gross_exposure`.

## Contrato futuro esperado: `p-l40b.performance-benchmark.v1`

El contrato futuro debe conservar, como mínimo:

- `schema_version`, `session_date`, `xnys_session_status`;
- equity y equity previa;
- cash, buying power, posiciones long/short;
- exposición bruta y neta en USD y porcentaje;
- position count y P&L no realizado cuando estén disponibles;
- SPY anterior, cierre, `price_basis`, fuente, `as_of` y calidad;
- retornos total y ajustado por exposición;
- `content_hash`, `revision` y advertencias.

`captured_at` queda fuera del hash. Los campos ausentes permanecen `null` o
`unavailable`; nunca se convierten en cero.

La exposición del benchmark queda pre-registrada como media temporal de
exposición bruta durante la sesión. Requiere cobertura suficiente de snapshots
de inicio/cambios/cierre. Un único snapshot EOD produce `partial`, no una
media artificial.

## Fórmulas fijadas

```text
account_daily_return = equity_t / equity_previous_session - 1
spy_daily_return = spy_close_t / spy_close_previous_session - 1
gross_exposure_pct = gross_exposure_usd / equity_t
exposure_matched_spy_return = spy_daily_return * session_average_gross_exposure
excess_return_total = account_daily_return - spy_daily_return
excess_return_exposure_matched = account_daily_return - exposure_matched_spy_return
```

División por cero o dato ausente produce `null`. Los cálculos internos no se
redondean; el redondeo es solo de presentación.

## Separación de métricas

Las pruebas mantienen separadas:

1. retorno total de cuenta;
2. retorno sobre capital desplegado;
3. retorno SPY ajustado por exposición;
4. P&L y notional comprado;
5. drawdown;
6. cash drag.

`P&L / notional comprado` nunca puede etiquetarse como retorno total de cuenta.

## Matriz de pruebas

| Grupo | Cobertura |
|---|---|
| `current_behavior` | alpha perdido, payload vacío, SPY MultiIndex, UPSERT last-writer-wins, exposición EOD mal nombrada |
| Cuenta | long, short, long+short, sin posiciones, equity inválida, cash ausente, side ausente |
| Calendario | sesión cerrada, viernes-lunes, festivo, sesión ausente, sesión abierta, barra futura |
| Fórmulas | retornos de cuenta/SPY, exposición, excess, división por cero y missing |
| Exposición temporal | snapshots completos, gaps, un único EOD, estado `partial/unavailable` |
| Precio | `close_unadjusted`, `adjusted_close`, base desconocida y metadatos obligatorios |
| Idempotencia futura | hash estable, timestamp fuera del hash, no-op, conflicto y revisión |
| P-L40A | reproducción aproximada de −0,0401%, +0,1953% y −0,2354 pp |
| Separación | total account, deployed capital y exposure-matched no se mezclan |

Las expectativas futuras se implementan exclusivamente con helpers y fixtures
de test; no usan `skip` ni `xfail` para ocultar defectos actuales.

## Pendiente para P-L40B

P-L40B deberá corregir únicamente la observabilidad:

- conservar el payload completo en la estructura existente;
- normalizar SPY plano/MultiIndex usando caché local cerrada;
- propagar cash y exposición del `PortfolioSnapshot` ya disponible;
- añadir hash, revisión y conflictos auditables;
- publicar el benchmark antes del digest final de la sesión;
- añadir CLI/health sin nuevas llamadas al broker.

No debe cambiar trading, ranking, gates, órdenes, exposición ni crear un
scheduler o tabla paralelos.

## P-L40B-W: candidato implementado en el worktree aislado

El worktree `codex/pl40b-tests` añade una fuente única en
`src/agente_bolsa/tools/performance_benchmark.py`. Consume el
`PortfolioSnapshot` ya obtenido por `_persist_daily_performance` y lee la caché
local directamente; no llama al broker, a yfinance ni a la red.

El contrato persistido es `p-l40b.performance-benchmark.v1` dentro de
`performance_daily.payload_json`. Las observaciones nuevas incluyen
`content_hash`, `revision=1`, `price_basis`, `data_quality`,
`exposure_observation_type=eod_snapshot` y
`temporal_exposure_status=unavailable`.

La persistencia nueva es idempotente: mismo `session_date` y hash producen
`idempotent`; contenido distinto produce `conflict` sin sobrescritura. Una fila
legacy existente para esa sesión también se conserva. La ruta legacy de
`upsert_performance_daily` se mantiene para no reescribir las filas históricas.

La lectura de SPY resuelve `Close` y las orientaciones MultiIndex
`(SPY, Close)`/`(Close, SPY)`, selecciona fechas XNYS exactas y rechaza sesiones
abiertas, barras futuras o sesiones ausentes. Si no puede probar la base de
precios, publica `price_basis=unknown` y mantiene calidad `partial`.

Se corrigen los defectos del camino nuevo: `alpha_vs_spy` se copia a la columna
legacy `alpha` y el payload completo se persiste junto al bloque benchmark.
`session_average_gross_exposure`, retorno SPY ajustado por exposición y cash drag
permanecen `null` porque solo existe una observación EOD.

El digest de laboratorio, health y el comando read-only `performance-benchmark`
exponen el estado y los campos disponibles sin convertir valores ausentes en
cero. El fallo de observabilidad se mantiene fail-open respecto al pipeline.

### Integración nocturna pendiente

Durante XNYS abierto solo se validan pruebas focales y fixtures temporales. La
integración de producción queda pendiente de revisión nocturna: ejecutar la
suite completa fuera de mercado, comprobar el orden final del digest, validar
paridad exacta de decisiones/órdenes y confirmar que no se realiza backfill ni
se altera el comportamiento legacy.
