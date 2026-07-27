# P-L46BR3 - resultado de cartera por periodo

## Diagnostico

La grafica `Valor de cartera` representa la evolucion del equity de la cuenta.
La tarjeta `P/L desde abril` mostraba en cambio `trade_history.total_pl`, suma
operativa de resultados realizados y abiertos. Al comparar magnitudes con
origen y denominador distintos, la interfaz podia afirmar que la cuenta ganaba
aunque el equity visible hubiese bajado.

## Contrato visual corregido

- `Resultado del periodo = ultimo equity visible - primer equity visible`.
- El porcentaje usa el primer equity visible como denominador.
- La tarjeta publica las fechas inicial y final del filtro.
- `Desde inicio` conserva todos los puntos disponibles desde el corte
  configurado del 28-abr-2026.
- `P/L abierto` suma el P/L no realizado de las posiciones del snapshot actual.
- `P/L hoy` se elimina del bloque porque ya se publica en la cabecera.
- Cuando falta autoridad suficiente se muestra `-`; no se inventa cero.

La cifra es variacion de equity, no rentabilidad ajustada por flujos. Si en el
futuro hubiera depositos o retiradas, deberan persistirse para calcular una
rentabilidad neutral a flujos sin reinterpretar retrospectivamente esta serie.

## Seguridad

El cambio no escribe datos ni realiza una llamada adicional al broker. No toca
senales, ranking, gates, sizing, planes, ordenes, stops, takes, exposicion,
SQLite, scheduler ni politicas P-L43/P-L44/P-L48/P-L49.

## P-L46BR4 - filtro calendario del grafico de cartera (candidato 0.4.195)

La reproduccion contra `a0ab7ce4` mostro que el selector aplicaba `tail(days)`:
interpretaba dias como numero de filas. Con snapshots de sesiones XNYS, 30
filas podian abarcar mas de 30 dias naturales y hacer que el filtro pareciera
ignorado.

La correccion centraliza las ventanas 7, 15, 30, 90 y `Desde inicio`. Filtra
por limites de fecha del ultimo snapshot disponible, ordena y deduplica fechas
sin mutar la serie original. La misma serie visible alimenta la grafica y
`Resultado del periodo`; `P/L abierto` continua usando las posiciones ya
cargadas.

QA del worktree aislado:

- reproduccion negativa: el tail de 30 filas empezaba el 07-may para una
  ventana calendario cuyo limite era 19-may;
- `tests/test_web_app.py`: 75 passed;
- cubiertos 7/15/30/90/Desde inicio, historico corto, duplicados, orden,
  ventanas consecutivas y no mutacion;
- suite completa, smoke y validacion cerrada quedan pendientes por XNYS abierto.

El cambio es exclusivamente UI/lectura: no anade llamadas broker, escrituras,
SQLite ni autoridad sobre trading. Commit funcional: `9ad9775c`.
