# P-L20 - Operacion autonoma y agenda de investigacion

Fecha: 2026-07-10. Version: 0.4.143.

## Entrega

- Cadena postcierre auditable: reconciliacion, outcomes forward/observaciones,
  linaje, scoreboard, investigacion y digest.
- Revision idempotente cada viernes a las 23:15 Europe/Madrid.
- Digest orientado a decision: resultados, cobertura, bloqueos, hipotesis y un
  unico objeto `decision_requested`.
- `production-health`: TTL de 26 horas para market-data-quality, coherencia del
  scheduler, ratio real/fallback de 7 dias, duracion y solapes postmercado.
- Informe diario observacional por estrategia, origen de decision, subcohorte
  low-sample, gates, excursiones/salidas y setup/regimen.
- Agenda persistente ampliada con breakout, LLM vs fallback, low-sample, efecto
  de gates y MFE/MAE/salidas/setup/regimen.

## Gobierno del experimento

El informe declara `policy_frozen=true` y no contiene acciones de mutacion. El
gate de pullback exige simultaneamente ventana hasta 20-jul, expectancy 5d y 10d
neta positiva, excess SPY positivo, n>=30 y concentracion temporal/sectorial
evaluable y aceptable. Si falta un criterio, la accion es `keep_shadow`. Los
limites de tres ordenes/dia, 1.000 USD por operacion, exposicion y low-sample no
se amplian durante la ventana. El scoreboard ya emite `learning_confirmed` o
`learning_not_confirmed` al completar las ocho semanas sin alterar el criterio.

## Seguridad

No se han tocado kernel, broker, execution, risk, config.py ni .env. Paper y
auto-apply off siguen sellados. La investigacion y los jobs nuevos son de solo
lectura respecto a la politica de trading.

## Primera ejecucion real de aceptacion

La cadena se ejecuto sobre la base actual en 8,27 s: scoreboard 1,02 s,
investigacion 0,20 s y digest 7,05 s. Resultado honesto: `pending_maturity`,
6 ejecuciones legacy con cobertura de linaje verificado 0%, control comparable
0%, 2.984 observaciones investigadas y `n=0` a 5d. No se solicito decision humana.

`production-health` encontro scheduler coherente (PID/lock/heartbeat),
market-data-quality rancio (ultimo 29-jun; TTL 26h) y fallback determinista del
58,66% en 254 decisiones de siete dias. El ultimo estado del job postmarket era
`skipped` por mercado abierto: su solape queda `unavailable`, no se presenta como
un falso positivo; las duraciones internas de la ultima ejecucion real si quedan
persistidas. Estas cifras son lineas base operativas y no alteran la politica.

## Verificacion

- Pruebas de madurez, gate pullback, secuencia postcierre, idempotencia semanal,
  decision unica, TTL, coherencia, fallback y solapes.
- Suite completa, Ruff, no-NUL, gates operativos y smoke aislado.
