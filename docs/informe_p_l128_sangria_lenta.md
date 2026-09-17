# P-L128 — regla de retire por sangria lenta 10d (Jetson 0.4.303 / Windows rama)

## Hallazgo (Jetson en vivo)

Los setups ejecutados sangran a 10d sin disparar el retire de 5d:
`confirmed_pattern` alfa_10d -2,15% (73 maduras), `rsi:60_75` y
`volume_z:lt0` tambien negativos. El umbral 5d (alfa <= -2% y pf <= 0,60)
solo caza desastres, no sangrias.

## Cambio

- `RETIRE_MIN_MATURED_10D=20`, `RETIRE_MAX_ALPHA_10D=-0,015`,
  `RETIRE_MAX_EXPECTANCY_10D=0,0` (estricto < 0). Solo claves accionables
  existentes. Veredicto `RETIRE_CANDIDATE` -> `propose_active_to_shadow`.
- Sync: RETIRE sin politica coincidente va a `human_review` (antes se
  perdia en silencio). Degradar sigue exigiendo politica humana coincidente.
- Correccion propia: la llamada a `evaluate` quedo como codigo muerto tras
  un `return` (el sync devolvia vacio); test de regresion anadido.
- Direccion siempre segura: jamas activa nada; solo degrada a shadow o avisa.

## Despliegue Jetson 0.4.303

- Primera prueba en vivo: `human_review` = setup:confirmed_pattern,
  tag:rsi:60_75, tag:volume_z:lt0. 0 auto-degradaciones (sin politicas
  humanas coincidentes: correcto y conservador).
- Salud 1+2, 0 reinicios/OOM. Siguiente: el humano decide si penalizar o
  retirar `confirmed_pattern` (alfa_10d -2,15% con 73 maduras).
