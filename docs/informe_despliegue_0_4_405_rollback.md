# Despliegue 0.4.405 y rollback — 2026-10-29

## 1. Dictamen

`precondition_not_met` para mantener 0.4.405 en producción. El candidato es
correcto en su contrato (P-L178 elimina el fallback de crews), pero el crew real
tarda ~20 minutos y excede la cadencia de 15 minutos del ciclo, con dos ciclos
solapados y watches de riesgo saltados. Se revirtió a 0.4.402 con mercado
abierto.

## 2. Desviación autorizada

La precondición del plan («postmarket de hoy terminal») era imposible antes de
las 21:00. El operador autorizó expresamente el corte con mercado abierto y esta
sustitución, que se declara aquí con sus palabras: sesión previa terminal
(2026-10-28, `skipped`), cero leases globales, cero postmarket/reconciliación en
curso, kernel `ok` y flags `paper/true/false/false`.

## 3. Despliegue

- Imagen `agente-bolsa:0.4.405-arm64`
  `sha256:a971e906700d5e2bacc9b5ec274200c48724cda49a3bebcff78322ed00a15c0b`,
  `FROM agente-bolsa:0.4.402-arm64`, delta `src` de `e9bcb657`/tree `3028901a`.
- Verificación byte a byte: **223/223 ficheros OK** en contenedor temporal
  `--entrypoint sh` (sin arrancar el entrypoint del sistema).
- Selector con backup `runtime.env.bak-pl405-20261029T165226Z`.
- Compose completo vía `jetson-ops deploy-agente-bolsa` (base + override +
  `runtime.env`). Sin tocar `application.env`, claves, `mem_limit` ni presupuesto
  web; sin resello.
- Salud 1 y salud 2 (100 s): 3× `healthy`, `RestartCount=0`, `OOMKilled=false`,
  HTTP 200 en `/`, `/health`, `/_stcore/health`, `/kindle`, kernel `ok` 0
  violaciones, flags intactos.
- Recibo emitido 2026-10-29T16:55:04Z.

## 4. Qué funcionó (P-L178)

Primer ciclo tras el corte: `crew_started` 16:57:37Z, **12 tareas**
`agent_task_execution` `succeeded` y **cero** `agent_run_fallback_started`.
Antes del lote: 45 `crew_failed` al día, fallback en 3,6 s y `llm_calls=0`.

## 5. Qué falló

Duración real del crew: 16:57:46Z → 17:17:48Z = **~20 min** (tareas de 40 a
110 s, 12–13 en secuencia), frente a la cadencia de 15 min del ciclo.

Consecuencias verificadas:

- `mkt_7fc5a87df089` (16:57:32Z) y `mkt_cd874763e1ad` (17:13:54Z): dos
  `cycle_started` sin terminal, solapados.
- `portfolio_watch` y `trade_fill_watch` con `maximum number of running
  instances reached` repetido entre 17:08Z y 17:12Z.
- `database is locked` en `signal_learning._persist_signal_prediction_captures`
  (`h_capture.py:664` → `storage.py:1518`), fail-open y preexistente, agravado
  por la contención.
- Cero órdenes, cero planes y cero recomendaciones en la ventana: sin efecto de
  trading.

## 6. Rollback

17:19Z: selector a `agente-bolsa:0.4.402-arm64`, `jetson-ops
deploy-agente-bolsa`, salud 2 a 17:21:19Z: 3× healthy, restart 0, OOM false, HTTP
200 ×3, kernel `ok`, runtime 0.4.402. El recibo de 0.4.405 queda superado por el
rollback y el tag `prod-jetson-0.4.405` se eliminó por inexacto (no se publicó).

## 7. Estado de Git

- `main` = `e9bcb657` (candidato 0.4.405), árbol limpio salvo untracked ajenos.
- `codex/oct29-integration` y las ramas de lote se conservan.
- Producción = 0.4.402. La brecha `main`/producción se cerrará con el lote
  correctivo.

## 8. Siguiente lote

**P-L178b (N2)**: desacoplar el crew de la cadencia de 15 min — ejecución
asíncrona/shadow con cadencia propia, o conjunto de tareas reducido — y garantía
demostrable de no solape entre ciclos. Criterio: un ciclo con crew real no puede
producir dos `cycle_started` sin terminal ni saltar `portfolio_watch`.
