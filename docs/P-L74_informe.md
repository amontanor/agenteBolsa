# P-L74 — autoridad de apertura SPY y claridad de intervalo

## Dictamen provisional

`ready_for_integration_rehearsal` en candidato aislado. XNYS estaba abierto
durante la validación; por seguridad no se ejecutaron suite completa, smoke ni
benchmark largo, y no se hizo despliegue.

## Causa y contrato

La base elegía la última caché por `created_at`/nombre. Para 2026-07-29 eso
permitía seleccionar una apertura de la caché broad
`market_data_0bc493d6d987c1b1` (aprox. 739,1900) o de la caché estrecha
`market_data_fae973e5b2174803` (aprox. 739,9700) sin resolver autoridad. El
valor corriente se podía combinar así con una apertura no autorizada y
publicar un retorno apertura→ahora falso.

El contrato P-L74 queda así:

- una apertura inmutable se resuelve por `session_date`, `symbol`,
  `price_basis` y provenance explícitos; dos valores incompatibles son
  `conflict` y no se elige por recencia;
- un cache dedicado con `purpose=benchmark_open`,
  `observation_kind=spy_open`, `requested_symbols=["SPY"]`, `.pkl` legible y
  Open coherente es autoridad explícita;
- un valor corriente es mutable: se usa la observación válida más fresca, sin
  tratar dos `Close/current` distintos como conflicto. Puede proceder de otro
  artefacto solo si conserva la misma base y su apertura coincide con la
  apertura resuelta o esta tiene autoridad explícita;
- metadata huérfana, `.pkl` ilegible, base desconocida, fila ausente o valor no
  finito producen `unavailable` y permiten recuperar/reintentar;
- el productor dedicado usa el mismo ciclo natural de `market_cycle_job`,
  después de la ruta activa y en fail-open. No añade polling de
  `portfolio_watch`, no introduce un límite artificial de intentos y no toca
  `config.py`;
- la identidad del artefacto no incluye `created_at`. Igual contenido es
  `idempotent`; payload perdido se recupera con estado `recovered`; contenido
  distinto conserva el original y genera conflicto auditable.

Los estados terminales del guard son exactamente `inserted`, `available`,
`idempotent` y `recovered`. `unavailable`, `conflict` y errores no terminalizan
la sesión: el siguiente ciclo natural puede reintentar.

## Productor, consumidor y seguridad

`capture_authoritative_spy_open_cache` escribe el payload antes que la
metadata, en una identidad determinista por sesión/basis. La metadata solo se
considera disponible si el `.pkl` correspondiente se puede leer y contiene el
Open esperado. El lector UI permanece sin red y no adquiere el productor
network-capable; consume caches locales y devuelve `status`, `warnings` y
`conflicts`.

`market_cycle_job` llama al intento después de producir decisiones/órdenes y
de completar la ruta activa. Un fallo del productor se absorbe y no modifica
retornos, excepciones, gates, sizing, planes, órdenes, exposición o límites.
`portfolio_watch_job` no contiene este wiring. SPY sigue significando ETF SPY
ajustado, no SPX.

La UI muestra `Rendimiento desde apertura: Sistema vs SPY`, identifica la
`Sesión iniciada` y el `Intervalo`, y mantiene separados `Final` y `En curso`.
Gráfica, tabla, tarjeta y tooltip reciben el mismo retorno/ventana; una sesión
con apertura conflictiva no produce porcentaje. Los conflictos históricos no
contaminan el `status` global cuando la sesión vigente sí es válida.

## Pruebas y gates

La reproducción inicial contra la base falló con `KeyError: 'status'`, porque
la base no resolvía la contradicción ni publicaba estado auditable. El lote
añade cobertura para:

- dos aperturas incompatibles, autoridad dedicada y conflicto histórico fuera
  de la sesión vigente;
- current sucesivo distinto, seleccionando el más fresco sin falso conflicto;
- current/apertura con provenance incompatible y retorno negativo
  739,9699707 → 738,6500244;
- metadata explícita alcanzable mediante productor dedicado, idempotencia,
  conflicto con original intacto, `.pkl` huérfano recuperado y `.pkl` legible;
- tres fallos seguidos y cuarto éxito sin cap `attempts >= 3`;
- guard terminal para `inserted`, `available`, `idempotent` y `recovered`;
- captura únicamente en `market_cycle_job`, nunca en `portfolio_watch_job`;
- render de intervalos y consumidores Telegram sin heredar un SPY no
  autorizado.

Resultados focales:

- `tests/test_p74_spy_open_authority.py`: 17 passed;
- regresiones P-L74/P-L72/market-data/Telegram/web: 131 passed;
- Ruff completo: OK;
- `scripts/check_no_nulls.py`: OK, 452 archivos;
- `git diff --check`: OK.

Por XNYS abierto quedaron omitidos suite completa, smoke y benchmark largo.
No hubo red, broker, yfinance operativo, Telegram real, SQLite productiva,
servicios, jobs manuales, despliegue ni push.

## Siguiente paso

Ensayo `--no-ff` aislado de P-L74 sobre la cadena integrada, con XNYS cerrado,
precondiciones terminales, revisión de paridad de archivos protegidos y suite
completa/smoke temporal. No promover ni desplegar este candidato sin ese
ensayo.
