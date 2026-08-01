# P-L77B1 — autoridad fail-closed de overrides adaptativos

## Dictamen

`deployed`. La validación cerrada y el despliegue productivo terminaron verdes.
El merge exacto se verificó en producción y el stack superó dos comprobaciones
post-arranque separadas por más de 75 segundos.

## Base, aislamiento y evidencia de producción

- Producción/base: `ba9d60d43fe2ae3e2775e1eab5c4a74f3ce9a6d8`, árbol
  `7ea8ea9adb774b3c97e642e67f44bae2791538cd`, versión `0.4.210`.
- Candidato: `C:\Antonio\Bref\agenteBolsa_worktrees\pl77b1_adaptive_override_authority`,
  rama `codex/pl77b1-adaptive-override-authority`.
- Commits del candidato: `132c369a` (reproducción), `0046f58f` y `06886090`
  (contrato/tests), `678165b1` (QA de imports), `7a73a093` (loader y versión),
  `f536394f` (resolución de sesión XNYS).
- HEAD final antes del commit documental: `a636be2540130ae7e2a60c47b119c9c2a14fc2be`,
  versión `0.4.211`; el árbol final se registra tras cerrar este informe.
- Producción tracked permanece limpia; se preservan sus untracked del
  operador. No se tocó `.env`, `adaptive_config.json` productivo ni SQLite.
- `data/state/adaptive_config.json` productivo fue leído sin escritura:
  SHA-256 antes/después de la auditoría `60833b60f83edb1b5ecbe0785bdacd68f58af6d5dfb307649749a8dbf6c7f4d0`.

## Causa y contrato

La escritura ya era fail-closed en `save_adaptive_config`, pero
`active_adaptive_overrides` aceptaba cualquier registro `status=active` con un
valor acotable. Por eso los seis registros legacy con `auto_apply=true` podían
entrar en `Settings` aunque `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`; el caso
observable era `MAX_ORDERS_PER_CYCLE` base 4 frente a efectivo 2.

El loader ahora exige, en este orden:

1. autorización global literal `bool True`;
2. `status=active`, nombre conocido y valor validado por los bounds existentes;
3. `requested_auto_apply is True` y `authorized_auto_apply is True` como
   autorización individual canónica. `auto_apply` legacy nunca autoriza por sí
   solo y, si aparece contradictorio, invalida el registro;
4. `expires_after_sessions` entero positivo, `evidence.session_date` ISO y
   sesión actual XNYS evaluable mediante el calendario real. La expiración se
   cuenta por sesiones entre la sesión de evidencia y la sesión actual; fecha
   de fichero, `created_at` o días naturales no sustituyen esa autoridad.

Cuando la sesión actual no puede obtenerse, el lector devuelve `unavailable`
implícito (`{}`) y no altera Settings. El caller normal puede resolver la
sesión actual desde `MarketCalendar.status()` solo durante una sesión XNYS
abierta; las pruebas pueden aportar explícitamente el `session_date` canónico.
No se ha modificado `config.py`, por lo que la ruta productiva mantiene el
default/base cuando la autorización global es falsa.

La lectura no crea directorios, eventos, reportes ni transacciones. El inventario
existente `adaptive_governance_status` sigue marcando los registros legacy como
`preexisting_unauthorized` y no les concede autoridad.

## Evidencia y paridad

- Reproducción contra la base: una fila legacy `MAX_ORDERS_PER_CYCLE=2` con
  global falso produjo `{"max_orders_per_cycle": 2}` y la prueba nueva falló
  contra la base.
- Candidato: la misma fila produce `{}` y la salida efectiva conserva
  `MAX_ORDERS_PER_CYCLE=4`.
- Un registro canónico autorizado y vigente solo actualiza su
  `settings_attr`; una fila desconocida, ambigua, no evaluable o vencida no se
  aplica.
- No se reejecutan ranking, gates, sizing, planes ni órdenes. El cambio solo
  retira una influencia adaptativa no autorizada.
- Archivos protegidos `config.py`, `kernel.py`, `broker.py`, `execution.py`,
  `risk.py` y `.env` permanecen idénticos a la base.

## QA

Focales iniciales: `36 passed` en P-L77B1/adaptive tuning/governance y `49
passed` incluyendo version policy, config audit y validate-agent-config. La
primera suite se detuvo en `1540 passed` por una expectativa obsoleta de versión
`0.4.210`; el test se corrigió a `0.4.211` y la repetición final terminó con
`2361 passed`, `1 skipped` preexistente y `1 warning` de dependencia externa en
`816.14 s`.

Gates finales: Ruff completo OK; `check_no_nulls.py` OK (`462 archivos`);
compilación aislada OK (`412` archivos); `git diff --check` OK; validate-agent-
config aislado `ok=true` sin warnings; smoke `run-once --skip-crew` OK con
DATA_DIR temporal y `market_state_quality=PARTIAL` por mercado cerrado. El
`kernel-status` aislado devuelve `unsealed` sin manifiesto temporal y cero
violaciones; el kernel productivo/base se contrastó por objetos Git y no se
modificó. La caracterización histórica de 33.336 observaciones no forma parte
de este lote y queda omitida por no ser necesaria.

La caracterización histórica de 33.336 observaciones no forma parte de este
lote y queda omitida por no ser necesaria para el contrato de autoridad.

## Seguridad y siguiente paso

Al corte, XNYS estaba cerrado y la próxima apertura era 2026-08-03 15:30
CEST. El PMR del 2026-07-31 tenía terminal durable `completed` con reason
`pipeline_completed`, sin lease activo; las comprobaciones SQLite forenses se
hicieron solo con URI `mode=ro` y `PRAGMA query_only=ON`. Las rutas operativas
usadas para el preflight y los checks fueron las canónicas autorizadas; no se
ejecutaron postmarket, reconciliación, run-once ni jobs productivos manuales.

El siguiente paso único es mantener la observación natural de la primera sesión
XNYS posterior; no se abre P-L78 en este lote.

## Cierre productivo P-L77B1

- Merge productivo `7682901ab2e66f82f5b2838b55d8d29d45c822ac`, padres exactos
  `ba9d60d4` y `9701e2f1`; producción queda en versión `0.4.211`, árbol
  funcional `ea93a5124ecf8c9c7a212d6c1abd9cb75dc3851f`.
- Suite completa en el candidato exacto tras el merge: `2361 passed`, `1
  skipped` preexistente y `1 warning` de dependencia; focales post-merge
  `73 passed`. Ruff, NUL, compilación temporal (`446` archivos), diff,
  validate-agent-config y smoke aislado quedaron verdes.
- Check post-arranque 1: 2026-08-01 12:04:21 CEST, HTTP raíz/health `200/200`,
  kernel `sealed/ok`, paper activo, live false, `MAX_ORDERS_PER_CYCLE=4`,
  cero órdenes abiertas, cero críticos y token del scheduler válido.
- Check post-arranque 2: 2026-08-01 12:07:29 CEST, HTTP `200/200`, kernel
  `sealed/ok`, scheduler `owner_alive`/token válido, un listener web,
  `MAX_ORDERS_PER_CYCLE=4`, cero órdenes abiertas y cero críticos. Los cinco
  warnings observacionales permanecen sin autoridad de trading.
- SHA-256 de `.env` y `data/state/adaptive_config.json` permaneció idéntico al
  preflight (`99907aa6…aa58` y `60833b60…f4d0`, respectivamente); no se
  activó ni modificó ningún override legacy.
- El watcher conserva `enabled=true`, límites `30/25/5/30/300` y estado
  natural `collecting` sin ejecución por mercado cerrado. PMR terminal y lease
  vacío se conservaron; no se ejecutaron jobs manuales ni se enviaron fills.

No quedan acciones funcionales autorizadas en este lote. La primera sesión
XNYS posterior debe observarse por su ruta natural; no se abre P-L78.
