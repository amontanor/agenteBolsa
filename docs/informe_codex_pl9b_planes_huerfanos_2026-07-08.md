# Informe Codex P-L9B - Expiracion de planes pendientes huerfanos

Fecha: 2026-07-08

## Objetivo

Evitar que `execute-approved --confirm-paper` pueda enviar planes viejos o huerfanos acumulados en `order_plans`.

## Cambios aplicados

- [src/agente_bolsa/storage.py](/C:/Antonio/Bref/agenteBolsa/src/agente_bolsa/storage.py):
  - nuevos estados `PENDING`, `SUBMITTED`, `EXPIRED`,
  - columnas `status`, `status_reason`, `status_updated_at`,
  - expiracion TTL por cierre de la sesion de mercado del dia de creacion,
  - `pending_order_plans()` expira primero lo caducado y solo devuelve `PENDING`,
  - `save_broker_order()` marca el plan como `SUBMITTED`,
  - helper de expiracion auditable para purgas masivas.
- Nuevo test [tests/test_order_plan_expiration.py](/C:/Antonio/Bref/agenteBolsa/tests/test_order_plan_expiration.py).

## Politica TTL

Valor aplicado: un plan `PENDING` caduca al cierre de la sesion NYSE del mismo dia de mercado en que se creo. Si llega una lectura posterior de pendientes y ese cierre ya paso, el plan pasa a `EXPIRED` con motivo auditable.

## Purga inicial ejecutada

Motivo aplicado:

`huerfanos pre-P-L9, incluye planes de proceso intruso fuera de presupuesto`

Resultado real:

- filas afectadas: 25
- `pending_order_plans(limit=500)`: 0
- `order_plans` en `EXPIRED`: 25

## Lista completa expirada

| plan_id | cycle_id | symbol | side | notional | created_at |
| --- | --- | --- | --- | ---: | --- |
| `plan_ce6e51e75385` | `20260612-133312` | `FRT` | `buy` | 1746.08 | `2026-06-12T13:33:44.094248+00:00` |
| `plan_b81cb5a2a63f` | `20260605-155400` | `CRWD` | `buy` | 1380.03 | `2026-06-05T15:55:11.434901+00:00` |
| `plan_fa32f001e36e` | `20260604-140742` | `PSX` | `buy` | 1649.30 | `2026-06-04T14:10:46.435607+00:00` |
| `plan_ae630cee205c` | `20260513-195621` | `HPE` | `buy` | 3512.53 | `2026-05-13T19:59:58.311484+00:00` |
| `plan_4285a038f4c7` | `decide_482511801f81` | `HPE` | `buy` | 3158.05 | `2026-05-13T19:49:26.601997+00:00` |
| `plan_282ec64baac9` | `decide_1b216c4c6a08` | `HPE` | `buy` | 3512.53 | `2026-05-13T19:41:27.197180+00:00` |
| `plan_10d1b0fd9890` | `20260430-192355` | `WELL` | `buy` | 3483.60 | `2026-04-30T19:26:45.775210+00:00` |
| `plan_38c1f20091e9` | `20260429-134151` | `SBUX` | `buy` | 3498.60 | `2026-04-29T13:45:23.001671+00:00` |
| `plan_8013757c903b` | `20260428-183347` | `PWR` | `sell` | 3565.78 | `2026-04-28T18:36:39.555894+00:00` |
| `plan_ca5de25abfed` | `20260428-173349` | `FDX` | `buy` | 3483.32 | `2026-04-28T17:36:50.487224+00:00` |
| `plan_8709b7df14cf` | `20260428-171848` | `STX` | `sell` | 3433.99 | `2026-04-28T17:21:44.336211+00:00` |
| `plan_0ce6915010cf` | `20260428-164848` | `SNDK` | `sell` | 3355.41 | `2026-04-28T16:51:47.711679+00:00` |
| `plan_3d8019aa4f65` | `20260428-151833` | `NVDA` | `sell` | 3476.99 | `2026-04-28T15:21:26.600415+00:00` |
| `plan_30859026c9ae` | `20260428-150333` | `CVS` | `buy` | 3480.85 | `2026-04-28T15:06:25.981459+00:00` |
| `plan_df9f04f78d69` | `20260428-140346` | `VRT` | `sell` | 3364.97 | `2026-04-28T14:06:48.432122+00:00` |
| `plan_0291d47891d9` | `20260427-181300` | `VRT` | `buy` | 3571.86 | `2026-04-27T18:15:44.687030+00:00` |
| `plan_b5055ac214ef` | `20260427-181300` | `NVDA` | `buy` | 3571.86 | `2026-04-27T18:15:44.682016+00:00` |
| `plan_feaae2b5be24` | `20260427-171715` | `AMZN` | `sell` | 3569.07 | `2026-04-27T17:19:46.700112+00:00` |
| `plan_fc89519892cc` | `20260427-171715` | `PWR` | `buy` | 1.47 | `2026-04-27T17:19:46.694105+00:00` |
| `plan_6b6f8b81cad5` | `20260427-170216` | `AMZN` | `buy` | 3573.97 | `2026-04-27T17:05:03.866704+00:00` |
| `plan_26bdb5fd6f4a` | `20260427-170216` | `PWR` | `buy` | 3573.97 | `2026-04-27T17:05:03.861702+00:00` |
| `plan_e9e0fb7c695a` | `20260427-165528` | `STX` | `buy` | 3573.97 | `2026-04-27T16:58:20.129776+00:00` |
| `plan_14b06ee15418` | `20260427-164744` | `SNDK` | `buy` | 3573.97 | `2026-04-27T16:50:30.304207+00:00` |
| `plan_8ca572bb1ea4` | `decide_d9408262c132` | `GEV` | `buy` | 3573.97 | `2026-04-27T09:58:47.707298+00:00` |
| `plan_345ebd072fb5` | `decide_d9408262c132` | `AMD` | `buy` | 3573.97 | `2026-04-27T09:58:47.702298+00:00` |

Todos quedaron con:

- `status = EXPIRED`
- `status_reason = huerfanos pre-P-L9, incluye planes de proceso intruso fuera de presupuesto`

## Verificacion

- `pytest tests/test_order_plan_expiration.py tests/test_web_launch.py tests/test_web_app.py -q` -> verde.
- `ruff check src tests` -> limpio.
- Purga real ejecutada sobre la base local -> `changed=25`, `pending=0`, `expired=25`.
