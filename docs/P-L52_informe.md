# P-L52B-T — caracterización del snapshot EOD contable y benchmark comparable

Fecha: 21-jul-2026. Lote exclusivamente de tests y documentación en worktree
aislado. No implementa Store, agent_events, performance_daily, CLI, health ni
UI.

## Dictamen

`ready_for_p52b_implementation`.

La causa de los gaps de P-L52A queda caracterizada en un contrato mínimo y
determinista: faltan un ledger exacto de flujos externos, cobertura completa de
costes/P-L realizado y un snapshot SPY con ventana, timestamps, `price_basis` y
calidad comparables. El contrato permite publicar la pérdida absoluta de equity
cuando existe, pero deja `flow_adjusted_return`, neto atribuible y residual en
`null`/`unavailable` si falta cualquiera de sus entradas.

## Referencias y aislamiento

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52b_eod_snapshot_tests`.
- Rama: `codex/pl52b-eod-snapshot-tests`.
- Base exacta: `7638149610060153dfe8a8edf2037ad9dab028a3`.
- Producción permanece en `24537e813ff0905696cda0b3925a212045ee7b09`, tree
  `4747f27f3d5dc152410203bf089baee500440897`, versión `0.4.185`, con su
  suciedad conocida intacta.
- El candidato P-L51C no fue modificado: antes de crear este worktree estaba en
  `7638149610060153dfe8a8edf2037ad9dab028a3`, tree
  `85791739016915c1985d347583e747c1663ab797`, versión `0.4.189`.
- XNYS estaba cerrado; siguiente apertura `2026-07-22T15:30:00+02:00`.
  Scheduler lock vivo y coherente; el PMR posterior estaba en
  `session_already_completed`; reconciliación completada con `changes=0`.
- No se accedió a SQLite productiva ni se ejecutaron jobs, servicios, broker,
  red, yfinance, LLM, postmarket, reconciliación real, suite completa, smoke ni
  despliegue.

## Contrato `p-l52b.canonical-eod-account-snapshot.v1`

La unidad es `(session_date, account_id, currency, window_start_at,
window_end_at)`. El `event_id` determinista es:

```text
canonical_eod_account_snapshot:<session_date>:<account_id>:<currency>:<window_start_at>:<window_end_at>
```

Todos los timestamps de identidad y fuente se normalizan a UTC y deben ser
timezone-aware. `captured_at` queda fuera de `content_hash`; mismo contenido
con distinta captura es idempotente. Mismo ID con contenido distinto conserva
el original y devuelve conflicto separado.

El payload probado contiene:

- `schema_version`, `event_id`, `session_date`, `calendar=XNYS`, `account_id`,
  `currency`, ventana exacta, `generated_at`, `as_of`, `source_timestamps` y
  `age_seconds` a añadir en la implementación productiva desde timestamps
  autorizados;
- `equity_start`, `equity_end`, `delta_equity`, `cash_start`, `cash_end` y
  `cash_ratio_end`;
- `gross_exposure_start/end/average`, `net_exposure_start/end/average` y
  `position_market_value_start/end`; el promedio solo es exacto con al menos
  dos muestras válidas;
- `open_pl_start`, `open_pl_end`, `delta_open_pl`;
- `gross_realized_pl`, comisiones, tasas regulatorias, spread, slippage,
  otros costes y `net_realized_pl` únicamente con cobertura completa;
- ledger exacto de `external_cash_flow_ledger`, `external_cash_flows` y
  `flow_adjusted_return`;
- `contributions[]` con `broker_order_id` y `lot_identity` exactos;
- benchmark SPY con precios, timestamps, `price_basis`, calidad, retorno y
  estado de comparabilidad;
- `residual_amount`, `residual_status`, `warnings`, `reason_codes` y
  `coverage`;
- resultado serializable con `received`, `valid`, `unavailable`, `conflict`,
  denominadores de sesiones y coberturas.

Missing, stale, partial, ambiguous o sin identidad permanecen `null`/
`unavailable`; nunca se convierten en cero.

## Ecuación contable

Los signos y unidades son moneda de la cuenta:

```text
delta_equity = external_cash_flows
             + net_realized_pl
             + delta_open_pl
             + residual_amount
```

Los depósitos son flujos positivos y las retiradas negativos. Los costes
explícitos son salidas positivas y:

```text
net_realized_pl = gross_realized_pl
                - commissions - regulatory_fees - spread_cost
                - slippage_cost - other_costs
```

Si falta `external_cash_flows`, `net_realized_pl` o `delta_open_pl`, el
`residual_amount` es `null`. La rentabilidad neutral a flujos solo se calcula
como `(delta_equity - external_cash_flows) / equity_start` con ledger exacto y
equity inicial no nulo. `trade_history.total_pl`, fragments, señales,
recomendaciones y planes no entran en esta ecuación.

## Benchmark y exposición

SPY solo es `comparable` si coincide la sesión y ventana, los timestamps de
precio son exactamente los extremos autorizados, `price_basis` es conocido y
consistente y la calidad es `exact`/`verified`. `partial`, `unknown`, `stale`,
ventana distinta o precio ajustado/no ajustado mezclado producen comparación
`degraded`/`unavailable`, nunca alpha.

La exposición EOD y el promedio de exposición son denominadores distintos.
`SPY × exposición` puede registrarse como métrica descriptiva de oportunidad
perdida; no demuestra que cash cause una pérdida absoluta ni constituye alpha o
beta ajustada.

## Matriz productor → campo → gap

| Fuente actual | Campos que puede aportar | Gap caracterizado |
|---|---|---|
| Snapshot de cuenta/equity | equity inicial/final, cash, timestamps | No garantiza ledger de flujos ni separación completa de P/L |
| `performance_daily` | equity final, `pnl_pct`, `spy_pct` | Es resumen de cierre; no basta para reconstruir flujos, exposición o residual |
| órdenes/fills y P-L51C | `broker_order_id`, fills, costes y lotes futuros exactos | Históricos sin carrier BUY→SELL siguen unavailable |
| posiciones | valor de mercado, lado, open P/L | Puede dar EOD; promedio requiere snapshots intraventana |
| ledger de flujos externos | depósitos/retiros exactos | No existe cobertura productiva verificada en P-L52A |
| benchmark persistido | SPY, precios y retorno | P-L52A tenía `partial`/`price_basis unknown`; no comparable |
| UI | presenta series de equity ya cargadas | No es autoridad de identidad, ventana ni contabilidad |

No se propuso modificar ninguna de estas fronteras en este lote.

## Fixtures y denominadores

Las 21 pruebas finales cubren:

1. cierre reconciliado con flujo cero, costes completos y ecuación;
2. depósito y retirada con ledger exacto;
3. ledger de flujos ausente;
4. costes parciales;
5. realized canónico + cambio de open P/L;
6. residual no cero con warning;
7. benchmark SPY comparable;
8. `price_basis` desconocido;
9. benchmark stale, fuera de ventana o con ventana distinta;
10. exposición solo EOD frente a promedio verificable;
11. long/short y neto firmado;
12. `position_side_invalid`;
13. órdenes abiertas separadas;
14. contribución sin `broker_order_id`;
15. multi-currency sin FX exacto;
16. hash estable fuera de `captured_at`;
17. repetición idempotente y conflicto sin overwrite;
18. reordenación, NaN, Inf y timestamps ingenuos;
19. caso P-L52A sanitizado;
20. ventanas de 3 y 5 sesiones con denominadores diferentes;
21. no causalidad de una sesión/outcomes inmaduros y no mutación de objetos
    activos.

El resultado serializable separa `received=1`, `valid`, el número de coberturas
`unavailable` y `conflict=0`, además de `session_count`,
`comparable_session_count`, cobertura de equity, flows, realized bruto/neto,
costes, open P/L, exposición, contribuciones, benchmark y residual.

El caso P-L52A reproduce exactamente:

```text
delta_equity       = -9.87
delta_open_pl      = -18.97
descriptive_realized_pl = +9.12  # no canónico, no entra en la ecuación
cash_ratio_end     = 0.8915
SPY return         = +0.007092, quality=partial, price_basis=unknown
net_realized_pl    = null
residual_amount    = null
flow_adjusted_return = null
```

Conclusión permitida: pérdida absoluta de equity verificada; cash como
oportunidad descriptiva; atribución neta y residual unavailable; causalidad de
una sesión unavailable.

## Validación y límites

- Nuevas pruebas P-L52B-T: `21 passed` en `0.49 s` en la ejecución final.
- Focales UI P-L46, P-L48/P-L51, performance/reporting/digest/health y
  postmarket: `248 passed` en `55.43 s`, 1 warning deprecación de
  `websockets.legacy`.
- Ruff completo: `All checks passed!`.
- `check_no_nulls.py`: `OK (413 archivos)`.
- `git diff --check`: OK.
- `validate-agent-config --json` temporal: `ok=true`, sin errores ni warnings.
- `kernel-status` temporal: `unsealed`, sin violaciones, esperado por ausencia
  de manifiesto temporal; no describe producción.

Durante la primera ejecución se detectó y corrigió únicamente un defecto del
fixture auxiliar: faltaban identificadores por defecto y faltaba proteger la
ecuación cuando `delta_equity` era unavailable. Tras la corrección, las 21
pruebas quedaron verdes. No hubo cambios en `src`.

No se ejecutaron suite completa, smoke, benchmark largo, jobs, servicios,
SQLite productiva, broker, red, yfinance, LLM, postmarket, reconciliación real,
despliegue ni push. No se añadieron skips/xfails.

## Siguiente lote mínimo

Implementar únicamente el productor/lector shadow del snapshot en la frontera
de postmarket ya existente, reutilizando objetos de equity, posiciones, P-L51C,
benchmark y un ledger de flujos exacto si dirección confirma su autoridad.
Debe quedar fail-open, append-only, sin tabla ni migración, y demostrar paridad
de trading antes de consumirlo en `performance_daily` o UI. No cambiar
thresholds, sizing, ranking, gates, stops, política ni producción.

## P-L52B-W — implementación shadow (candidato 0.4.190)

### Dictamen

`ready_for_integration_rehearsal`.

La implementación productiva queda limitada a observabilidad: recibe la foto
de cartera, el objeto P-L48 y el objeto P-L51 ya construidos por el PMR; no
consulta broker, SPY, cartera, outcomes, reconciliación ni red. El evento
canónico productivo es exactamente
`canonical_eod_account_snapshot:<session_date>`. La cuenta, ventana, costes,
flujos, benchmark y contribuciones conservan `null`/`unavailable` cuando no
existe una fuente autorizada; no se reconstruyen por símbolo, fecha,
`trade_history.total_pl` ni fragments.

### Frontera y secuencia

```text
coordination → reconciliation → outcome_update → daily_learning
→ postmarket_report → canonical_operation_telemetry (P-L48)
→ canonical_trade_attribution (P-L51)
→ canonical_eod_account_snapshot (P-L52)
→ performance → measurement_pipeline → thesis → terminal
```

P-L52 construye y persiste una vez por PMR efectivo, reutiliza el mismo objeto
en `performance_daily` y no aparece en `cycle_runner`, trade decision, gates,
risk, broker, execution, kernel ni config. El lector de CLI, digest y health
solo lee `agent_events`; `runtime_state` no es historia.

Persistencia: `agent_events` append-only, transacción corta, hash determinista
con `captured_at` fuera del hash, repetición idéntica `idempotent`, contenido
distinto `conflict` con original intacto. No se añadieron tablas, migraciones,
backfill ni `INSERT OR REPLACE`.

### Cobertura y límites observados

| Campo | Fixture completa | PMR real sin fuente adicional |
|---|---:|---:|
| equity/delta | exact | EOD disponible; apertura unavailable |
| flujos y retorno neutral | exact con ledger | unavailable |
| realized bruto/neto | exact con costes completos | unavailable si P-L51 no aporta cobertura |
| open P/L delta | exact con ambos extremos | unavailable sin apertura |
| exposición EOD/promedio | exact con posiciones/muestras | parcial/unavailable sin extremos intraventana |
| contribuciones | exact con IDs de lote | unavailable sin carrier P-L51C |
| benchmark SPY | comparable solo con ventana/timestamps/basis/calidad exactos | unavailable si no viene persistido |
| residual | balanced/nonzero con todos los términos | unavailable |
| freshness | edades en segundos por fuente autorizada | explícita; no actúa como gate |

El caso P-L52A conserva `delta_equity=-9,87`, `delta_open_pl=-18,97`,
`descriptive_realized_pl=+9,12`, cash `89,15%`, neto/residual null y benchmark
degradado; no convierte el valor descriptivo en beneficio neto.

### Commits y validación

- `57ec7b7f` — `feat: add canonical EOD account snapshot shadow`.
- `eb17d582` — `test: verify canonical EOD snapshot wiring`.
- `4e868109` — `fix: include canonical EOD freshness ages`.
- Validación focal P-L52B-W + contrato T: `32 passed`.
- Ruff completo `src tests`: `All checks passed`; `git diff --check`: OK.
- Se mantuvieron las 21 fixtures T y se añadieron persistencia temporal,
  idempotencia/conflicto, concurrencia sin `database is locked`, consumidores
  collecting, stage order, reutilización, fail-open y protección de rutas.
- Suite completa, benchmark P-L45 de 33.336 filas, smoke y despliegue no se
  ejecutan en este lote de implementación; quedan para XNYS cerrado y
  preflight terminal, sin skips/xfails añadidos.

No se modificó producción, SQLite productiva, servicios, broker, red, LLM,
archivos protegidos ni candidatos originales; no hubo merge, despliegue ni
push.
