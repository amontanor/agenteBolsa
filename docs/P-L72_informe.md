# P-L72 — rendimiento apertura XNYS a apertura XNYS

## Dictamen

`ready_for_closed_market_deployment`

La causa raíz era una mezcla de ventanas. La cabecera utilizaba una diferencia
de snapshots/cierres, la tabla consumía `performance_daily` y SPY podía proceder
de otra captura. Además, el timestamp UTC de una barra diaria de Alpaca podía
convertirse en la fecha civil siguiente en Madrid.

P-L72 define una sola semántica:

- sesión final: apertura XNYS de T → apertura XNYS de la siguiente sesión;
- sesión vigente: última apertura XNYS → observación más reciente;
- cuenta: equity exacta de Alpaca a las 09:30 America/New_York;
- SP500: `Open` ajustado de SPY para las aperturas y último precio local con
  `as_of` verificable para el intervalo en curso;
- sin ledger de flujos se publica “variación de equity”, no rentabilidad
  neutral a flujos.

## Contrato y seguridad

- Evento append-only `session_open_snapshot:<session_date>`, schema
  `p-l72.session-open-snapshot.v1`.
- Identidad por sesión XNYS y timestamp exacto, nunca por fecha UTC de una barra
  diaria.
- Solo se forman intervalos entre sesiones XNYS consecutivas. Si falta una
  apertura, la sesión se omite; no se publica cero, `pending` ni aproximación.
- La tabla se muestra de más reciente a más antigua. Gráfica, contadores y tabla
  usan exactamente el mismo rowset visible.
- La cabecera usa el mismo denominador de apertura que el panel.
- Telegram usa `p-l72.telegram-daily-summary.v3` cuando existe la apertura
  exacta y conserva fallback compatible P-L70/P-L71 cuando no existe.
- La captura del scheduler es observacional y fail-open. No cambia candidatos,
  ranking, gates, riesgo, sizing, planes, órdenes ni ejecución.
- No se modificaron `kernel.py`, `broker.py`, `execution.py`, `risk.py`,
  `config.py` ni `.env`.

## Evidencia real read-only

Valores de Alpaca y caché local ajustada de SPY:

| Intervalo | Cuenta | SPY |
|---|---:|---:|
| 24-jul apertura → 27-jul apertura | +0,198504% | +0,866605% |
| 27-jul apertura → 28-jul apertura | +0,156870% | -0,767874% |
| 28-jul apertura → preapertura 29-jul | aproximadamente -0,043% | +0,225921% |

El antiguo +0,14% de la captura no era el retorno 28-jul apertura → ahora. Era
una comparación de otra pareja de snapshots. El +0,2259% de SPY sí reproduce
la subida aproximada de +0,21/+0,23% observada externamente, usando SPY ajustado.

La consulta Alpaca `2W/15Min` entregó diez aperturas exactas y permite mostrar
siete filas completas en el selector de siete días.

## Validación

- Focales UI/Telegram/P-L63/P-L65/P-L68/P-L70/P-L71/P-L72/scheduler:
  `179 passed`.
- Suite completa: `2283 passed, 1 skipped, 1 warning` preexistentes.
- Ruff completo: verde.
- `check_no_nulls.py`: verde, 451 archivos.
- `git diff --check`: verde.
- `validate-agent-config --json` con `DATA_DIR` temporal: `ok=true`.

No hubo escritura SQLite productiva, órdenes, reconciliación, postmarket,
reinicio, despliegue ni push durante la construcción y QA del candidato.

## Despliegue productivo — 29-jul-2026

`deployed`

- Merge `--no-ff`: `50d959d76de113da40067dfbb3a03973d5635d2f`.
- Árbol funcional: `b7eb971fc7fa8733706a6eef826ba5750e1aa267`.
- Versión productiva: `0.4.206`.
- Suite sobre el merge con el stack detenido: `2284 passed`, sin fallos; un
  warning de deprecación preexistente.
- Ruff, `check_no_nulls.py` (451 archivos), `git diff --check`,
  configuración, kernel y smoke aislado: verdes.
- Stack arrancado con helpers gestionados. Dos comprobaciones separadas
  confirmaron HTTP raíz y `/health` 200, una cadena lógica de scheduler,
  PID/token de lock coherentes, kernel sellado, lease postmarket vacío, cero
  órdenes nuevas y cero eventos `database is locked`.
- Validación visual productiva: siete filas con valores, seis finales y una en
  curso, orden descendente en la tabla y el mismo rowset en gráfica,
  contadores y tabla.
- En la preapertura del 29-jul, el intervalo vigente 28-jul apertura → ahora
  mostró cuenta `-0,05%` (`-$38,05`) y SPY ajustado `+0,23%`.
- No hubo push ni cambio de política de trading.
