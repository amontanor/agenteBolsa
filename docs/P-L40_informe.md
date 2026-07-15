# Informe final P-L40 — benchmark diario de cartera frente a SPY

## Dictamen de P-L40A

La ventana pre-registrada 7–13 jul obtuvo cuenta `-0,0401%`, SPY `+0,1953%` y
exceso `-0,2354 pp`; la exposición EOD media aproximada fue 5,17%. El resultado
se clasifica como `insufficient_sample`, `lower_return_with_lower_risk` y
`data_quality_blocked`: todavía no demuestra edge frente a SPY ni justifica
cambiar la política. El retorno ajustado por exposición permanece
`unavailable` por falta de exposición temporal verificable.

## Contrato implementado

`p-l40b.performance-benchmark.v1` se persiste dentro de la fila existente de
`performance_daily`. Consume el único `PortfolioSnapshot` que ya obtiene el
postmarket, deriva equity, cash, posiciones y exposición EOD, y lee SPY solo de
la caché local. El lector acepta columnas planas y MultiIndex, exige la sesión
XNYS exacta cerrada y rechaza barras futuras o sesiones ausentes.

Se persisten el payload completo, `alpha_vs_spy`, `price_basis`, calidad de
datos, warnings, revisión y `content_hash`. `captured_at` queda fuera del hash.
La misma sesión y hash son no-op; contenido diferente produce conflicto
auditable sin sobrescritura. Las filas legacy no se reescriben ni se rellenan.

La exposición EOD se etiqueta `eod_snapshot`; no se presenta como media
temporal. Por ello `session_average_gross_exposure`,
`exposure_matched_spy_return`, `excess_return_exposure_matched` y `cash_drag`
permanecen `null` hasta disponer de observaciones temporales suficientes.
Valores ausentes no se convierten en cero y el fallo de observabilidad es
fail-open respecto al postmarket y trading.

## QA y ensayo de integración

La caracterización reproducía la pérdida de alpha, payload vacío, SPY
MultiIndex, UPSERT silencioso y exposición EOD mal nombrada. La implementación
focal de P-L40B fue validada con 51 pruebas; el ensayo P-L41R cubrió además una
captura de cartera única, ausencia de red/broker, paridad de pipeline, legacy,
conflicto e idempotencia. El benchmark no modifica señales, recomendaciones,
ranking, gates, planes, cantidades, stops, takes, exposición real, frecuencia
del scheduler ni órdenes.

La métrica de cuenta usa `equity_t / equity_previous_session - 1`; SPY usa el
cierre de la sesión anterior XNYS; el exceso total es la diferencia entre ambos.
No se anualiza Sharpe con muestra insuficiente y no se confunde P&L/notional con
retorno de cuenta.

## Integración nocturna y limitaciones

P-L40B se integró después de P-L37B en
`codex/nightly-integration-rehearsal`. El conflicto de `storage.py` conserva las
dos políticas: historial append-only de señales y persistencia de benchmark con
conflictos. La captura única del portfolio evita consultas adicionales al
broker; la caché SPY evita red.

Las observaciones prospectivas empiezan con el despliegue. Las 21 filas legacy
conservan sus campos faltantes; no hay backfill. `exposure-matched` y `cash_drag`
son `unavailable` hasta contar con una media temporal verificable. No se afirma
ninguna mejora de rentabilidad.
