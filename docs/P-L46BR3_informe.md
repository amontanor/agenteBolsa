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
