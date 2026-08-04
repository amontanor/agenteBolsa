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
