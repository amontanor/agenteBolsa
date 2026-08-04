# P-L83D - normalizacion temporal de datos diarios del dashboard

## Dictamen

`ready_for_closed_market_deployment` para el candidato aislado. El despliegue
productivo queda condicionado al ensayo `merge --no-ff`, a un preflight cerrado
renovado y a margen suficiente para rollback, arranque y dos comprobaciones de
salud antes de la apertura XNYS. Este lote es exclusivamente de presentacion
del dashboard; no inicia P-L82 ni otros lotes y congela nuevos cambios despues
de su cierre hasta la revision del 08/08.

## Base, candidato y alcance

- Produccion antes del lote: `5d53e24c16b0cda33993b7dbc294aa484f5e8e55`,
  tree `b29645b0570b557e49069cf67f9e1d795cd46791`, version `0.4.219`, limpia.
- Base del worktree: el mismo commit productivo exacto.
- Worktree: `C:/Antonio/Bref/agenteBolsa_worktrees/pl83d_dashboard_temporal_dates`.
- Rama: `codex/pl83d-dashboard-temporal-dates`.
- Commits: `b42f7edf` caracterizacion, `dd287e84` implementacion y bump,
  `d15eb37e` correccion de la expectativa de version.
- Candidato actual: `d15eb37e173fa9ed8d4f686e8e61cbba5fcc15d6`, tree
  `306a3daebf91e8145567d375c54337382550ed00`, version `0.4.220`, limpio.
- Version `0.4.220` estaba libre al iniciar el lote.

Produccion, SQLite productiva, stack, `.env`, manifiesto, P-L80 y los archivos
protegidos permanecieron intactos durante desarrollo y validacion.

## Causa reproducida

La frontera `_parse_utc_timestamp` pasaba un entero de epoch directamente a
`pd.Timestamp`, que lo interpretaba como nanosegundos. El valor
`1785801600`, que representa `2026-08-04T00:00:00Z`, terminaba como una fecha
de 1970 y emitia un warning. Ademas, la serie diaria convertia los buckets
UTC a fecha civil local antes de asignarles identidad XNYS: el bucket de
`2026-08-01T00:00Z` es el cierre de la sesion del 31/07, no un punto del
01/08. Finalmente, un diccionario por fecha permitia que el current
provisional sobrescribiera el cierre diario de la misma etiqueta civil.

## Contrato aplicado

- Los epoch numericos se interpretan explicitamente como segundos o
  milisegundos por magnitud; ISO aware/naive se normaliza a UTC; valores
  invalidos, booleanos y fechas fuera de rango quedan `unavailable`.
- Cada bucket 1D se asigna a la ultima sesion XNYS cuyo `market_close` UTC es
  menor o igual al instante del bucket. No se resta un dia ni se usa un
  fallback de dia laborable. Festivos, early close, fin de semana y DST usan
  el calendario XNYS existente.
- Los cierres conservan `session_date` canonica. El current se agrega aparte,
  con fecha visual local/as_of, `es_provisional=true` y sin sobreescribir un
  cierre. El filtro de siete dias opera sobre `session_date` ya normalizada.
- El detalle muestra el intervalo correcto, por ejemplo `03/08/2026 ->
  04/08/2026`, y nunca `01/01/1970`. No cambia importes, fuente ni autoridad
  de la metrica diaria de P-L81.
- `page_dashboard` reutiliza el `account_read_at` ya capturado; no añade
  llamadas al broker. La UI sigue siendo observacional y no adquiere
  autoridad sobre trading.

## Reconciliacion aislada

Con fixtures equivalentes a la evidencia contrastada, sin red ni broker:

- cierre 31/07 `70547.06` -> cierre 03/08 `70633.59`: `+86.53`;
- cierre 03/08 -> current 04/08 `70635.28`: `+1.69`;
- cierre 31/07 -> current 04/08: `+88.22`;
- ventana inclusiva 29/07 -> current 04/08: `70644.33` -> `70635.28`,
  `-9.05` y aproximadamente `-0.01%`.

Los importes son datos de fixture de validacion y no se hardcodean. La
ventana de P-L80 y su cutoff `2026-08-02T15:51:41.5484478Z` no se modifica.
P-L82R queda preservado: omisiones, continuidad, comparabilidad SPY y estado
`unavailable` no se alteran.

## Cambios

Funcionalmente solo se modifican `web_app.py`, las pruebas de contrato UI y la
version. Se añade `tests/test_p83d_dashboard_temporal_dates.py`. Los objetos
de `kernel.py`, `broker.py`, `execution.py`, `risk.py`, `config.py` y `.env`
son iguales a la base; `.env` no esta presente como archivo versionado en el
worktree y no fue creado.

## Validacion

- Caracterizacion contra la base: `8 failed, 2 warnings`, todos los fallos
  esperados de la regresion temporal.
- Suite completa fresca sobre el tree final: `2444 passed, 1 skipped,
  1 warning` en `1139.57s`.
- Focales P-L83D/P-L63/P-L65/P-L81/P-L82/P-L82R/web: `133 passed, 1 warning`.
- Regresiones P-L68/P-L71/P-L72/P-L74/Telegram/web: `102 passed`.
- Version policy: `1 passed`.
- Ruff: verde.
- `scripts/check_no_nulls.py`: `OK (473 archivos)`.
- Compilacion temporal de `src`, `tests` y `scripts`: verde.
- `git diff --check`: verde.
- `validate-agent-config --json` aislado: `ok=true`, 23 agentes, 6 tareas,
  6 habilitadas, sin warnings.
- `kernel-status` temporal: `unsealed`, sin violaciones; es el resultado
  esperado al no existir manifiesto temporal. El kernel productivo debe
  comprobarse desde produccion antes del despliegue.
- Smoke UI aislado: `ok=true`, 3 filas, rango `2026-07-31` -> `2026-08-04`,
  `pl=88.22`, 1 fila provisional, sin red, broker ni SQLite productiva.
  Los avisos de Streamlit sobre MemoryCacheStorageManager son del entorno de
  prueba, no un fallo funcional.

No se ejecutaron broker, LLM, yfinance, jobs operativos, postmarket,
reconciliacion, backfill ni SQLite productiva. No se hizo push.

## Preflight operativo conocido

Durante la caracterizacion XNYS estaba cerrado y la proxima apertura era
`2026-08-04T15:30:00+02:00`. `schedule-status` read-only informo mercado
cerrado y runtime `unavailable` por WAL/sidecars; no se hizo checkpoint,
borrado ni reparacion. El scheduler tenia owner/token coherentes y no se
detectaron pytest, deploy ni jobs competidores. La comprobacion final debe
repetir estas condiciones y verificar PMR terminal, lease vacio, paper activo,
live/auto-apply desactivados, kernel productivo valido y margen.

## Siguiente paso y congelacion

Crear un ensayo aislado desde la produccion exacta y fusionar este candidato
con `merge --no-ff`. Solo si el tree es identico, los gates breves son verdes y
queda margen operativo, detener/arrancar con helpers canonicos y desplegar.
Tras dos saludos separadas al menos 75 segundos, marcar el estado real. Si no
queda margen, conservar produccion en `0.4.219` y devolver
`ready_for_next_closed_market_deployment`.

Despues del cierre de P-L83D no se inician cambios funcionales nuevos hasta la
revision de cohorte del 08/08. El cutoff, la captura P-L80 y la politica activa
permanecen sin cambios.

## Cierre productivo P-L83D

Dictamen: `deployed`.

El candidato final `c3a5e6714213a1996eac100aa943b1a638ec14bc` se integro sobre
produccion mediante `merge --no-ff` `613aab8718ed2b1b652010e90019bc43ef5e0735`.
El primer padre es `5d53e24c16b0cda33993b7dbc294aa484f5e8e55` y el segundo
padre es el candidato exacto. El tree funcional y documental resultante es
`57780f1d35d2742d4cb1d9a5aa2f0b281fe935a5`, version `0.4.220`; produccion y
el candidato quedan limpios.

El ensayo aislado equivalente fue `cd73e8c3`, con los mismos padres logicos y
tree exacto. En candidato y ensayo se conservaron los archivos protegidos y
la paridad de trading/riesgo/ejecucion. La suite completa fresca del tree
final fue `2444 passed, 1 skipped preexistente, 1 warning` en `1139.57s` y se
reutilizo post-merge por identidad exacta del tree. Los focales post-merge
fueron `227 passed, 1 warning`; Ruff, NUL (`473 archivos`), compilacion,
`git diff --check`, version policy, configuracion aislada y kernel productivo
quedaron verdes. El smoke fake aislado del candidato fue verde y no se repitio
con produccion para evitar llamadas o efectos operativos adicionales.

Salud 1: `2026-08-04T12:36:06+02:00`, raiz y `/health` `200/200`.
Salud 2: `2026-08-04T12:37:58+02:00`, raiz y `/health` `200/200`, separacion
`111.83s`. Ambas confirmaron un scheduler logico, un listener, owner/token y
heartbeat coherentes, paper activo, live y auto-apply desactivados, kernel
`ok`, configuracion valida, 0 ordenes abiertas y 0 alertas criticas. Los 3
warnings observados son preexistentes: deterioro de setup, atribucion
degradada y governance adaptativa; no se mezclan ni reparan en P-L83D.

`schedule-status` mantuvo `runtime_state=unavailable` por WAL/sidecars bajo
el contrato read-only; no se hizo checkpoint, borrado ni reparacion. El PMR
del 03/08 quedo terminal `completed/pipeline_completed` y el lease vacio; el
estado `skipped/market_not_ready` de la sesion 04/08 es normal antes de
apertura. El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` y la cohorte no
cambian.

Desde este cierre quedan congelados los cambios funcionales del proyecto hasta
la revision de cohorte del 08/08. No se ejecutaron backfill, reconciliacion ni
jobs manuales, no se llamo a broker/LLM desde tests o smoke, no se tocaron
secretos ni `.env`, y no hubo push.
