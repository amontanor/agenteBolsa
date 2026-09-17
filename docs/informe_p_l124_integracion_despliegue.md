# P-L124 — integracion y despliegue del bucle de mejora continua (0.4.230)

## Dictamen

## Dictamen

`deployed`.

## Alcance

Integra P-L120 (contrato determinista), P-L121 (SPY EOD), P-L122 (bucle de
promocion) y P-L123 (dedupe y cuadro). No cambia trading, riesgo, sizing,
broker, ejecucion, configuracion ni auto-apply. Sin backfill ni reescritura.

## Advertencia preexistente (no bloqueante, no re-sellada)

`kernel-status` productivo: `violation` solo en `.env` (editado por el
operador el 16-sep, fuera de este lote). `kernel.py`, `broker.py` y
`execution.py` coinciden con el sello; postura verificada paper/live-false/
auto-apply-false. No se ejecuta `kernel-seal`: requiere confirmacion humana
del cambio intencional del `.env`.

## Evidencia

- Suite rehearsal: 2531 passed, 1 skip preexistente, 1 expectativa stale
  corregida (patron P-L89B-QA).
- Suite post-merge: pendiente al redactar (ver cierre).
- Ruff, NUL, diff-check, config `ok=true`, smoke aislado: verdes.
- Paridad de protegidos objeto-a-objeto contra la base.

## Cierre productivo P-L124 (17-sep-2026, 12:19-12:22 Europe/Madrid)

- Merge 83e366d9, v0.4.230. Suite post-merge 2531 passed, 2 preexistentes clasificados.
- Salud 1 (12:19:47) y salud 2 (12:21:25, +98 s): scheduler unico (61240, lock 62356 ok), web unica (7404, 8501 HTTP True), 0 criticas + 3 warnings preexistentes, lease vacio, 138 ordenes sin cambios, 0 ordenes hoy.
- Supervisores auxiliares: catch-up con exit 0 al arrancar; PARADO en reposo es su estado normal; flags lock_orphan por PID reutilizado (falso positivo conocido).
- Kernel: violacion preexistente solo en .env, sin re-sellar. Postura paper/live-false/auto-apply-false.


## Re-sellado de kernel (17-sep-2026, 12:28 Europe/Madrid)

- Operador confirma: el cambio del .env es el paso a DeepSeek V4.1 Flash (verificado en .env: IMPROVEMENT_LLM_MODEL=deepseek-v4.1-flash, roles decision/sentiment iguales, postura paper/live-false intacta).
- kernel-seal ejecutado con autorizacion explicita: ok=true, iolations=[], sello 2026-09-17T10:28:48Z sobre kernel/broker/execution + .env actual.


## Split-brain Windows/Jetson (17-sep-2026, 12:58 Europe/Madrid)

- El despliegue Windows 0.4.230 creo doble instancia activa: Jetson corre
  `agente-bolsa:0.4.297-arm64` (healthy, 28h) y Windows 0.4.230 arranco 12:19.
- 0 ordenes ejecutadas en Windows (mercado cerrado); 4 eventos de ciclo sin
  trading. Sin dano.
- Decision: Jetson es la linea autoritativa (mas nueva, sana, instruccion
  permanente del operador). Stack Windows detenido (`stack_down`,
  PARADO verificado 12:58). Codigo 0.4.230 preservado en repo/ramas.
- Pendiente operador (elevado): `Disable-ScheduledTask AgenteBolsaScheduler,
  AgenteBolsaWeb` para evitar rearranque de Windows antes de la apertura
  15:30. Futuros despliegues van al pipeline Jetson, nunca downgrade a 0.4.230.
