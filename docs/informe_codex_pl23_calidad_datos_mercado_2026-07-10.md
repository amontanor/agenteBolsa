# P-L23 - Diagnostico accionable de calidad de datos de mercado

Version: 0.4.146

## Entrega

`market-data-quality` sigue siendo solo lectura respecto a las barras. Ahora
publica `anomalies` con: `symbol`, `date`, `invalid_fields`,
`invalidity_class`, `severity`, `provider`, `cache` y
`affects_operational_scan`. La deduplicacion estable usa simbolo, fecha, campos,
clase, proveedor y cache key.

Reglas explicitas y conservadoras:

- `bloqueante`: OHLC invalido en la ultima fecha observada del simbolo; se
  declara que afecta al escaneo, pero no modifica gates ni la politica de
  bloqueo.
- `advertencia`: OHLC invalido historico o volumen negativo/no finito; no se
  declara impacto en el escaneo.
- `informativa`: gap extremo observado.
- `unavailable`: alerta legacy sin barra verificable; no se infiere fecha,
  campo ni causa.

El digest diario muestra cobertura, bloqueos diagnosticos reales, anomalias
unicas y la accion requerida.

## Evidencia actual

Se inspecciono la cache existente `market_data_600f58bc83572a79` sin cambiar
barras ni proveedor. Origen: yfinance, `cache_hit=false`, ventana 2026-06-10 a
2026-07-11. Resultado: cobertura 500/500, bloqueos de cobertura 0, 25 anomalias
unicas y 25 bloqueantes diagnosticas de OHLC en 2026-07-10.

Campos detectados: `high` en AIG, CPAY, HUM, ORCL; `low` en AEE, ATO, BLDR, CL,
DG, DHI, DTE, ES, FTV, GPC, IEX, KIM, LEN, LYV, MOS, NEM, NUE, PHM, PKG, SWK y
URI. Accion: revisar la evidencia antes del siguiente escaneo; no se corrige,
elimina ni sustituye ninguna barra y no se cambia ningun gate, ranking u orden.

## Verificacion

Pruebas nuevas: barra valida, OHLC invalido, volumen invalido, repeticion de
barra cacheada, alerta legacy sin detalle y caso bloqueante; tambien se verifica
el renderizado del digest. Se ejecutan suite completa, Ruff, NUL check y gates
operativos en la entrega.
