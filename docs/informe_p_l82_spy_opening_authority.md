# P-L82 - resolucion autoritativa de apertura SPY y sesiones omitidas

## Dictamen final

`deployed`. P-L82 esta integrado en produccion con version `0.4.218`.
El resolver observacional de apertura SPY usa autoridad a nivel de grupo y la
UI hace visibles las sesiones omitidas. Trading, riesgo, ejecucion, seleccion,
gates, sizing, ordenes, exposicion, limites y la captura prospectiva P-L80 no
cambian.

## Referencias

- Produccion antes del lote: `2875b01263ecf0bb93513cd12a296cdcdbe66fb5`,
  tree `49c8e0224aa15f30e70fd795afb7536ea6d0dab3`, version `0.4.217`.
- Candidato validado: `f1bc5a5b461b53cd274ce6c03567728b625b239f`, tree
  `93d8a756a8e96ec5c9c5d55baaed2955546c537d`, version `0.4.218`.
- Commits funcionales y QA: `e1538614`, `87919ee2`, `d5228ac4`,
  `7b26d259`, `b938eaa9`.
- Documentacion candidata: `f1bc5a5b`.
- XNYS cerrado; siguiente apertura verificada:
  `2026-08-04T15:30:00+02:00`.
- Cutoff P-L80 preservado:
  `2026-08-02T15:51:41.5484478Z`.

## Causa reproducida

`load_cached_spy_open_observations()` agrupaba por
`(price, price_basis)` pero inspeccionaba solo `group[0]` para detectar
`explicit_benchmark_open`. Un cache generico del mismo precio antes del
cache dedicado ocultaba la autoridad y producia `conflict`; el orden inverso
producía `available`. La caracterizacion contra la base fue
`1 failed, 1 passed` y demostro dependencia del orden de lectura.

## Contrato implementado

El resolver:

1. agrupa por valor canonico y base de precio;
2. busca autoridad en todos los elementos del grupo, nunca solo en el primero;
3. acepta un unico grupo con autoridad inequivoca y elige de forma
   determinista;
4. conserva `conflict` para autoridades discordantes o varios valores sin
   autoridad;
5. conserva missing/unavailable y no usa latest-wins, intuicion o texto libre;
6. no realiza llamadas de red ni escrituras de cache.

La UI expone `omitted_sessions` con fecha de sesion, estado, razon y cobertura
de cuenta/SPY. Muestra omisiones aun sin filas comparables; no fabrica puntos
ni conecta sobre huecos. Los motivos incluyen
`account_open_unavailable`, `spy_open_conflict`,
`spy_open_unavailable`, `price_basis_mismatch` y `not_comparable`.

## Casos y validacion del candidato

Se cubrieron: generico antes de autoridad dedicada, orden inverso, dos
autoridades discordantes, ausencia de autoridad, basis incompatible, timestamp
futuro, repeticion, no mutacion y renderer de omisiones.

- Suite fresca candidata: `2430 passed, 1 skipped preexistente, 1 warning`
  en `716.88s`.
- Focales P-L65/P-L68/P-L71/P-L72/P-L74/P-L81/web/Telegram/P-L82:
  `193 passed, 1 warning`.
- Ruff completo: verde.
- NUL: `OK (471 archivos)`.
- Compilacion temporal de `src/tests/scripts`: verde.
- `git diff --check`: verde.
- Version policy: verde.
- `validate-agent-config --json`: `ok=true`, 23 agentes, 6 tareas,
  6 habilitadas, sin warnings.
- Kernel temporal: `unsealed`, sin violaciones, esperado sin manifest.
- Smoke: harness fake aislado `ok=true`; no se ejecuto el ciclo real porque
  la CLI no ofrece un proveedor fake y un ciclo real contactaria broker o
  mercado.

La primera suite candidata fue `1555 passed, 1 failed, 1 warning`; el unico
fallo era una expectativa stale de version policy, corregida exclusivamente
en `b938eaa9`.

## Integracion y recuperacion auditable

Una primera operacion accidental integro `098283bf` sobre el checkout
productivo. Se revirtio inmediatamente con `31b7367b`, restaurando el estado
funcional seguro `49c8e022` / version `0.4.217`. La tentativa y su
rollback permanecen en la historia y se documentan aqui.

Despues del `stack_down` gestionado se creo el candidato de recuperacion
`a0ac5eed9c103b062c02796c6e3c2146d02345d0` mediante revert auditable del
rollback. Su tree `93d8a756` coincide objeto a objeto con el candidato
validado `f1bc5a5b`.

La integracion final fue:

- merge `--no-ff df80dee8dd1f8f8409906eb511a6e42c97a251cc`;
- primer padre `31b7367b6393260d1c1a04f2d539ccc0a2dac79e`;
- segundo padre `a0ac5eed9c103b062c02796c6e3c2146d02345d0`;
- HEAD productivo `df80dee8dd1f8f8409906eb511a6e42c97a251cc`;
- tree funcional `93d8a756a8e96ec5c9c5d55baaed2955546c537d`;
- version `0.4.218`.

Con el stack detenido se repitieron los gates: suite post-merge
`2431 passed, 1 warning` en `846.40s`; focales `193 passed, 1 warning`;
Ruff, NUL, compilacion, diff-check, version policy,
`validate-agent-config`, kernel productivo y paridad de protegidos verdes.
El kernel productivo quedo `ok` sin violaciones. Los hashes protegidos no
cambiaron.

## Salud post-arranque

- Salud 1: `2026-08-04T09:59:51.761896+02:00`, HTTP raiz/health
  `200/200`.
- Salud 2: `2026-08-04T10:02:08.649277+02:00`, HTTP `200/200`,
  separacion `136.89s`.
- En ambas: XNYS cerrado, scheduler unico con owner vivo y token coincidente,
  listener unico, wrapper/launcher/runtime coherentes, paper activo,
  live=false y auto-apply=false.
- Kernel: `ok`, 0 violaciones.
- Salud operativa durable: 0 criticos, 3 warnings preexistentes
  (setup edge, atribucion postmarket y governance adaptativa), sin
  `database is locked`.
- `schedule-status` informa runtime unavailable por
  `wal_mode_or_sidecar_present` bajo el contrato read-only; no se repararon
  WAL/sidecars. La etiqueta `lock_orphan` de `stack_status` es el falso
  positivo conocido del arbol wrapper/launcher y no se clasifico como segundo
  scheduler.

El smoke real no se ejecuto por seguridad. No se uso broker, red, LLM real,
yfinance, Telegram, jobs manuales, postmarket/reconciliacion forzada,
backfill, kernel-seal, edicion de manifest, nueva probe DeepSeek ni push.

## Estado siguiente

El cutoff P-L80 permanece vigente y la observacion prospectiva no se reescribe.
No iniciar P-L83 en este cierre.

## P-L82R - continuidad y comparabilidad temporal

### Dictamen del candidato

`ready_for_closed_market_deployment`. P-L82R corrige únicamente la frontera
observacional Sistema vs SPY. El candidato parte de la producción exacta
`d73a8971b40075830dc40824c2308cd2057e4a6c`, tree
`f966a7250beb4d4236ef27926e3c7aa956bb007a`, version `0.4.218`, y queda en el
worktree `pl82r_spy_temporal_continuity`, rama
`codex/pl82r-spy-temporal-continuity`, HEAD
`1fab7813814d9bd3e68eaf867f9e6644dbbc5127`, tree
`32506e65c69c8c0fe1093f13447ac698755be550`, version `0.4.219`.

El candidato no está integrado ni desplegado en este estado del informe.
Producción, stack, SQLite productiva, `.env`, sello y la captura prospectiva
P-L80 permanecen intactos. No se inicia P-L83.

### Causa reproducida y contrato

La caracterización contra la base produjo `1 passed, 4 failed`: la gráfica
formaba un único dataset de línea para filas finales separadas por omisiones,
y una observación SPY anterior al `system_end_at` se clasificaba como una fila
vigente comparable. La base no publicaba estado temporal para la fila vigente.

El fix implementa lo mínimo siguiente:

- una línea histórica solo agrupa intervalos contiguos cuando
  `previous.end_session_date == next.session_date`; cada intervalo omitido,
  conflicto o missing rompe el segmento y no se conecta visualmente;
- la comparación vigente exige `system_end_at == spy_end_at` en UTC, además de
  la misma base de precio y valores válidos. No se inventa un umbral de
  frescura;
- cuando los as-of no están alineados, Sistema y SPY permanecen visibles como
  observaciones separadas, pero la fila publica
  `comparison_status=unavailable`, `comparison_reason`,
  `comparison_lag_seconds` y `comparison_coverage.aligned=false`; no produce
  ganador ni conector de comparación;
- los contadores y conectores de ganadores solo consumen filas finales con
  `comparison_status=comparable` y ambos valores presentes;
- las cuatro omisiones `spy_open_conflict` y los conflictos genuinos de P-L82
  permanecen sin resolver, sin backfill ni llamada adicional.

El caso equivalente observado por dirección, sistema `2026-08-04T08:11:00Z`
frente a SPY `2026-08-03T20:12:55Z`, queda
`current_observation_not_aligned`, sin ganador. La fecha visible puede seguir
siendo la fecha local del as-of, mientras el intervalo conserva su
`session_date`/cobertura canónicos.

### Commits y QA

- `3668369f`: caracterización roja y focales iniciales.
- `914c715b`: cobertura explícita de exclusión de ganador vigente.
- `0fce01a1`: implementación, ajuste de tooltip y bump `0.4.219`.
- `1fab7813`: QA/version policy y formato de tests.

Resultados en el worktree, con `PYTHONPATH` del worktree, `DATA_DIR` temporal,
sin `.env` local, red, broker, LLM, yfinance ni SQLite productiva:

- focales P-L82R: `6 passed`;
- regresiones P-L65/P-L68/P-L71/P-L72/P-L74/P-L81/P-L82/web/Telegram:
  `200 passed, 1 warning`;
- suite completa fresca: `2436 passed, 1 skipped preexistente, 1 warning` en
  `786.12s`;
- Ruff completo, `check_no_nulls` (`472 archivos`), compilación temporal,
  `git diff --check` y version policy: verdes;
- `validate-agent-config --json`: `ok=true`, 23 agentes, 6 tareas, 6
  habilitadas, sin warnings;
- `kernel-status --json` temporal: `unsealed`, `violations=[]`, esperado por
  ausencia de manifest temporal;
- smoke fake aislado de la frontera `run_observable_cycle` con
  `use_crew=false`: `ok=true`, ciclo `smoke-p82r`, persistencia solo en DB
  temporal. No se ejecutó ciclo productivo ni hubo llamadas externas;
- protegidos `kernel.py`, `broker.py`, `execution.py`, `risk.py` y `config.py`
  objeto-a-objeto iguales a `d73a8971`; `.env` no existe en el worktree.

El preflight productivo read-only previo permaneció verde: XNYS cerrado,
próxima apertura `2026-08-04T15:30:00+02:00`, PMR `2026-08-03` terminal,
lease vacío, paper activo, live/auto-apply off, kernel productivo `ok`,
scheduler con owner/token coherentes y cero jobs de validación competidores.

### Límites y siguiente paso

La validación no modifica trading, riesgo, ejecución, selección, gates,
sizing, exits, órdenes, exposición, límites, broker.py, kernel.py, execution.py,
risk.py, config.py, `.env`, datos históricos ni cutoff P-L80
`2026-08-02T15:51:41.5484478Z`. El único siguiente paso es un ensayo
`merge --no-ff` desde `d73a8971` y, solo si las precondiciones/margen siguen
verdes, cierre productivo secuenciado con gates y dos health checks; no iniciar
P-L83 ni reparar deudas ajenas.

### P-L82R - cierre productivo

Dictamen: `deployed`. Tras el ensayo exacto (`67183356`, primer padre
`d73a8971`, segundo padre `06152971`, tree `cd75d3de`) se integró el candidato
con `merge --no-ff` en producción mediante `b0a88b984b51d862d4d9eb960d82061e6f258db3`.
El tree productivo final es `cd75d3de6b384ba2a67b97fe21e422d03ad954fa`,
version `0.4.219`, y el checkout quedó limpio. No hubo conflicto ni delta
funcional fuera del candidato.

Con stack detenido se repitieron suite y gates: `2436 passed, 1 skipped
preexistente, 1 warning` en `763.44s`; Ruff, NUL (`472 archivos`), compile,
diff-check, version policy, configuración aislada, kernel temporal sin
violaciones y smoke fake aislado verdes. Kernel productivo quedó `ok` con 0
violaciones y los cinco protegidos permanecen objeto-a-objeto iguales; `.env`
conserva el hash redacted `86a8420fc308...9ccedfc35afb`.

Salud 1: `2026-08-04T11:07:20 CEST`, HTTP raíz/health `200/200`, scheduler
owner vivo/token coincidente, wrapper/launcher/runtime coherentes, listener
único, version `0.4.219`, paper activo, live=false, auto-apply=false y kernel
ok. Salud 2: `2026-08-04T11:09:34 CEST`, mismos checks, separación `134.33s`.
El runtime de `schedule-status` sigue `unavailable` por
`wal_mode_or_sidecar_present`, sin reparación; el artefacto operativo vigente
reporta 0 críticos y se conservan los warnings observacionales preexistentes.
PMR `2026-08-03` quedó terminal y las claves de coordinación activa vacías;
no se crearon órdenes desde el merge.

El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` y su cohorte no cambian. No
hubo backfill, jobs manuales, broker/red/LLM real, P-L83, kernel-seal,
modificación de manifest, cambio de `.env` ni push.
