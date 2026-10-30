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


## 9. 0.4.406 ? arreglo del lock de outcomes desplegado (2026-10-29 23:06 Madrid)

Con la traza real del postmarket (21:20:48Z) se identific? el frame exacto:

```text
post_market_review.py:855 update_signal_outcomes(...)
-> signal_learning.py:1640 store.update_signal_outcomes_bulk(...)
-> storage.py:4563 conn.executemany(...)
-> sqlite3.OperationalError: database is locked
```

Lote P-L163b (N2), portado sobre 0.4.402 para no arrastrar el cambio de crews:

- `storage.update_signal_outcomes_bulk` escribe en trozos de 500 filas con
  reintento acotado (3, backoff 0,2-1,5 s) solo para `locked`/`busy`.
- `post_market_review._build_learning_pipeline` degrada el outcome update ante
  lock: registra `outcome_update:failed` y sigue con el informe
  (`deferred=True`, `warnings=["outcome_update_locked"]`). Los outcomes se
  recalculan de forma idempotente en la pasada siguiente.
- Pruebas: base `3 failed` -> candidato `5 passed`; regresiones 26 passed.

Despliegue: `agente-bolsa:0.4.406-arm64`
`sha256:88ef7ae7391b6ecaf5938f564cc46289bf78cc0809b0f06c19afc8ff6b4d208b`,
`FROM 0.4.402-arm64`, 223/223 ficheros verificados, commit `e37da517`, tree
`d32a24cc`, tag `prod-jetson-0.4.406`, recibo 2026-10-29T22:06:43Z. Doble salud
verde, kernel ok.

El postmarket reintent? a las 22:05:15Z (recuper? el lease hu?rfano), complet?
reconciliaci?n y arranc? `outcome_update` a las 22:06:09Z. A las 22:38Z segu?a en
esa etapa con el host a?n degradado por I/O. Sin terminal todav?a; el veredicto
de P-L163 queda pendiente de esa ejecuci?n.


### Resultado real de 0.4.406

El reintento de las 22:05:15Z recuper? el lease hu?rfano y complet?
reconciliaci?n, pero qued? en `outcome_update` desde las 22:06:09Z. A las 22:38Z
segu?a ah?, con el scheduler sin emitir eventos desde 22:18:29Z (79 minutos).
El troceado de escritura no basta: el coste dominante es recalcular 128.441
outcomes y mantener el proceso bloqueado; adem?s cada trozo a?ade su propio
commit sobre un NVMe degradado.

Se reinici? el scheduler a las 22:39Z para recuperar servicio (healthy,
0.4.406, HTTP 200). Dictamen del arreglo: `partially_verified` ? elimina el
aborto por lock, pero no acota el trabajo. Siguiente lote **P-L163c**: procesar
outcomes solo para se?ales cuyo resultado puede cambiar, por s?mbolo y en
streaming, sin cargar 128.441 filas; medir tiempo y memoria antes de desplegar.


## 10. 0.4.407 ? ventana acotada y learning diario fail-open (2026-10-30 08:03)

Con 0.4.406 el PMR ya super? el lock de outcomes (degrad?) y muri? m?s adelante:

```text
daily_learning.py:1871 build_learning_daily_run
-> _materialize_observations_spooled
-> storage.upsert_learning_observations_batch (BEGIN IMMEDIATE)
-> LearningObservationBatchError: database is locked   (23:10:55Z)
```

Lote P-L163c:

- outcomes: ventana de 45 d?as desde `session_date` (los horizontes m?ximos son
  10 sesiones) en lugar de recalcular 128.441 filas desde abril;
- `upsert_learning_observations_batch`: reintento acotado por chunk (3 intentos,
  backoff 0,2-1,5 s) solo para `locked`/`busy`;
- `_build_learning_pipeline`: si la materializaci?n sigue bloqueada, degrada con
  `daily_learning_deferred` (declarado, sin inventar datos) y el informe cierra.

Imagen `agente-bolsa:0.4.407-arm64`
`sha256:ea6e9e1a1b5b4ceeb23f7d837943fba12f8774bed97f7b3a81f1da6ea11349d0`,
`FROM 0.4.406`, 223/223 ficheros byte a byte, commit `311ab5a8`, tree `780e8265`,
tag `prod-jetson-0.4.407`, recibo 2026-10-30T07:03:26Z. Doble salud verde
(07:01:11Z y 07:02:52Z), kernel ok, runtime 0.4.407, smoke aislado exit 0.

Validaci?n pendiente: el PMR de la sesi?n 2026-10-30, tras el cierre.
