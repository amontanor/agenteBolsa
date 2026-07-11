# P-L27D - Cohorte prospectiva observacional reward/risk

Fecha de entrega: 2026-07-11
Version: 0.4.155
Estado inicial: `collecting`; no hay resultado de rendimiento que interpretar.

## Contrato pre-registrado

- Hipotesis: `pl27d_rr_1_1_5_vs_1_5_2`.
- Clase: `observability`; solo lectura analitica de la fabrica de senales.
- Inicio efectivo: 2026-07-13, primer dia XNYS completo tras el despliegue.
- Horizonte: 10 sesiones XNYS; la primera fecha posible de madurez es
  2026-07-24 tras el cierre.
- Brazo A: `1.0 <= reward_risk_ratio < 1.5`.
- Brazo B: `1.5 <= reward_risk_ratio < 2.0`.
- Resultado primario, siempre A menos B: media, mediana y tasa positiva de
  `return_10d`.
- Minimos por brazo y ventana: 300 observaciones maduras y 100 clusters
  `symbol x signal_date`; concentracion top-1 de simbolo y fecha inferior a
  20%.
- Exito: las tres diferencias positivas en dos ventanas cronologicas maduras
  consecutivas, con muestra, concentracion, linaje y control comparables
  validos.
- Invalidacion: cambio de signo en dos ventanas maduras, muestra insuficiente,
  concentracion, falta de control comparable o contaminacion/falta de linaje.
- Limite: 40 sesiones XNYS; al agotarse se conserva la evidencia y se declara
  que no hay ampliacion automatica.

## Diseno y datos

Cada tarjeta se conserva bajo `features.rr_cohort_p_l27d` del ledger ya
existente `learning_observations`; no se crea tabla ni se modifica
`signal_outcomes`. Conserva id de senal y linaje, ciclo, fecha/timestamp,
simbolo, direccion, entrada/stop/take, distancias y R/R, brazo, estrategia,
origen de decision, rango, calidad, ejecucion, control, madurez, retorno 10d,
procedencia y advertencias.

Solo entra una senal long con geometria valida, `signal_id`, linaje verificado,
ciclo, simbolo y fecha. Los motivos de exclusion son auditables; no hay
imputacion. Los controles son candidatos no ejecutados del mismo ciclo y fecha,
con geometria y gates iguales, aprobados pero retenidos por capacidad; se
guardan como maximo tres. Las senales bloqueadas por gate o de otro ciclo no
son controles.

Los historicos anteriores al inicio no se reinterpretan. El flag opcional de
contexto legacy es explicito y nunca alimenta el resultado primario.

## Operacion y validacion

`rr-cohort-report --json` es de solo lectura y acepta `--from`, `--to`,
`--window first|second|all` y `--include-legacy-context`. El digest diario
presenta solamente estado, sesiones XNYS, madurez por brazo, cobertura de
linaje/control, criterios pendientes y proxima fecha evaluable. Tras el
post-market se genera el informe JSON; un error suyo no interrumpe el pipeline.

Las pruebas deterministas cubren contrato y fronteras, exclusiones, no
reescritura de pre-inicio, idempotencia, control mismo ciclo/geometria, madurez,
ventanas por fecha, hash estable, fin de semana/festivo XNYS y CLI JSON. No
usan red, LLM, codegen, apply ni ordenes.

## Limites y riesgos

No se modifica estrategia, stop, take, time-stop, ranking, gates, ordenes,
exposicion ni ejecucion. Tampoco se infiere causalidad, profits, costes, alpha,
SPY o P&L ejecutado: permanecen `unavailable`. Hasta que existan dos ventanas
maduras con todos los criterios no puede afirmarse soporte descriptivo ni
proponerse un cambio de trading.
