# P-L155 — Lector de recibos EOD de SPY y reloj del productor

Dictamen: `ready_for_integration_rehearsal`.

## Causa raiz

`load_spy_eod_receipt` en `src/agente_bolsa/tools/spy_eod_authority.py` elegia el
recibo EOD de una sesion por el **nombre del fichero**:

```python
stem = f"{RECEIPT_PREFIX}{session_date.replace('-','')}_"
candidates = sorted(root.glob(f"{stem}*.json"))
for path in reversed(candidates):
    ...
    return receipt
```

El sufijo del nombre lo escribe `capture_spy_eod_receipt` como
`receipt["content_hash"][:8]`. Es un identificador de contenido truncado, no un
reloj. Ordenar alfabeticamente y devolver el ultimo no es orden cronologico, y
la funcion no filtraba por `comparison_status`: devolvia el primer valido que
encontraba, tanto `comparable` como `unavailable`.

Consecuencia medida en produccion, sesion 2026-09-24, cuatro recibos validos en
`/var/lib/agente-bolsa/cache/market_data`:

| Fichero | `comparison_status` |
| --- | --- |
| `spy_eod_close_20260924_37277f9b.json` | `unavailable` |
| `spy_eod_close_20260924_8a09005c.json` | `comparable` |
| `spy_eod_close_20260924_a5284111.json` | `comparable` |
| `spy_eod_close_20260924_fdf426ce.json` | `unavailable` |

Orden alfabetico: `37277f9b` < `8a09005c` < `a5284111` < `fdf426ce`. `reversed`
empieza por `fdf426ce`, que es `unavailable`, y tapa los dos `comparable`. El
overlay de `performance_benchmark.py` solo acepta `comparison_status ==
"comparable"`, asi que descartaba el recibo bueno y caia a la cache same-day, que
falla con `same_day_cache_not_eod`. El mismo fallo occurred en 2026-09-21
(`f75e14ac` `unavailable` ganaba a `c2f95286` y `c6cfa128` `comparable`).
Acumulado en produccion: 18 recibos, 7 `comparable`, y el Telegram nocturno sale
con "SP500 n/d".

Defecto secundario, mismo fichero: `refresh_and_capture_spy_eod` fijaba
`captured = _now(now)` **antes** de llamar a
`download_daily_prices_with_metadata` y reutilizaba ese mismo reloj en
`capture_spy_eod_receipt`. La cache recien escrita lleva un `cache_created_at`
posterior a ese reloj, y el recibo nacia con `cache_created_at_future` en
`reason_codes`: 5 de los 18 recibos de produccion. El recibo posterior, ya
descargada la cache, si salia `comparable`; el primero quedaba inutil.

## Cambio 1 — lector

`load_spy_eod_receipt` elige por reloj de captura, no por nombre. La precedencia
esta en `_receipt_precedence` y declarada en su docstring:

1. `comparison_status == "comparable"` gana a `unavailable` de la misma sesion,
   sea cual sea su reloj. Un `unavailable` no puede enmascarar un `comparable`.
2. dentro de cada clase, `captured_at` mas reciente en UTC.
3. desempate determinista y explicito, sin reloj del sistema: `content_hash`
   completo mayor (identidad canonica del contenido del recibo) y, si tambien
   empata, `receipt_path` mayor. Un `captured_at` ausente o no parseable ordena
   por debajo de cualquier `captured_at` presente, pero se desempata con el
   mismo par. El hash truncado del nombre nunca decide.

Se mantiene sin cambios la validacion de `schema_version`, `session_date` y
`content_hash`: un recibo invalido se ignora como hoy. La funcion sigue siendo
estrictamente de lectura: no reescribe, no borra y no renombra ficheros
append-only. No se cambia la semantica de `comparison_status`, `eod_authority`,
`price_basis` ni el fail-closed de P-L71. El tipo de salida es el mismo dict del
recibo con `receipt_path` anadido.

## Cambio 2 — productor

`refresh_and_capture_spy_eod` mantiene `session_status(session_date, now=entry)`
con el reloj de entrada, antes de descargar, y no descarga si la sesion no esta
cerrada. El reloj que se pasa a `capture_spy_eod_receipt` se toma despues de la
descarga mediante `_capture_clock(entry, download_meta)`: se vuelve a leer el
reloj real (o se conserva el `now` explicito) y se avanza hasta el `created_at`
que declara la propia descarga. Con `now=None` el reloj real se lee ya
descargada la cache; con `now` explicito sigue siendo determinista
(maximo de la entrada y del `created_at` declarado). No hay parametro nuevo y la
firma publica no cambia. El fail-open se mantiene intacto: cualquier excepcion de
red, validacion o I/O devuelve resumen no persistado sin lanzar y nunca inventa
cierres.

Detalle de identidad observado al escribir la caracterizacion: `captured_at` no
entra en `_stable_hash`, asi que dos recibos que solo difieren en el reloj
comparten `content_hash` y nombre de fichero. Los cuatro recibos de produccion
tienen por tanto contenido genuinamente distinto, y la fixture de test replica
esa propiedad en vez de suponerla.

## Criterios de aceptacion

| Criterio | Resultado | Evidencia |
| --- | --- | --- |
| A1 comparable con los 4 ficheros de 2026-09-24 | pasa | `test_a1_unavailable_no_tapa_comparable_de_la_misma_sesion`; en rojo contra la base con `['eod_authority_unavailable', 'same_day_cache_not_eod']` |
| A2 dos comparables gana el mas reciente; comparable gana a unavailable posterior | pasa | `test_a2_dos_comparables_gana_el_captured_at_mas_reciente`, `test_a2_unavailable_posterior_no_tapa_al_comparable`, `test_a2_empate_de_reloj_es_estable_y_repetible` |
| A3 cache same-day sigue `unavailable` con `same_day_cache_not_eod` | pasa | `test_a3_cache_same_day_sigue_unavailable`, `test_a3_overlay_sin_comparable_no_inventa_benchmark`, `test_a9_autoridad_cache_sigue_fallando_cerrada_sin_recibo` |
| A4 sin `cache_created_at_future`; sesion abierta sin descargar | pasa | `test_a4_reloj_posterior_a_la_descarga_no_produce_cache_created_at_future`, `test_a4_sesion_no_cerrada_no_descarga`, `test_a4_descarga_caida_sigue_fail_open` |
| A5 overlay entrega `comparable` con retorno no nulo | pasa | `test_a5_overlay_entrega_comparable_con_los_cuatro_recibos` |
| A6 paridad total de trading | pasa | diffstat limitado a `spy_eod_authority.py`, `__init__.py` (bump) y dos tests. `performance_daily` sin diff; sin candidatos, scores, ranks, gates, sizing, planes, ordenes, precios, stops, exposicion ni limites |
| A7 sin backfill ni reescritura | pasa | `test_ficheros_existentes_no_se_reescriben_ni_se_borran`; sin esquema, sin tablas, sin `backfill_spy_eod_receipts` ejecutado |
| A8 bump 0.4.321 | pasa | `src/agente_bolsa/__init__.py` y pin en `tests/test_p59c_llm_selected_authority.py`. `0.4.321` no aparece reservado en `docs/plan_mejoras_y_tareas.md`; P-L148 sigue reservado en 0.4.250 |
| A9 cobertura cuenta la sesion tapada | pasa | `test_a9_cobertura_cuenta_la_sesion_tapada`: `sessions_comparable` 1 de 2, con `reason_codes == []` para 2026-09-24 |

## Reproduccion contra la base

Commit de caracterizacion `7a582920`, sin cambios de codigo de produccion:

```
pytest tests/test_p155_spy_eod_receipt_selection.py -q
7 failed, 8 passed in 17.59s
```

Rojos: A1 (dos tests), A2 (dos tests), A4 (reloj), A5 (overlay) y A9
(cobertura). El primero con la linea exacta del defecto:

```
E       AssertionError: ['eod_authority_unavailable', 'same_day_cache_not_eod']
E       assert 'unavailable' == 'comparable'
```

## Pruebas

- Focal del lote, candidato: `tests/test_p155_spy_eod_receipt_selection.py` —
  15 passed in 18.51s.
- Focales relacionadas (P-L155 + P-L121 + P-L127 + P-L153 + P-L146 + P-L140B +
  P-L143 + P-L123 + pin de version) — **96 passed in 24.13s**.
- Regresion amplia `-k "overlay or spy or eod or benchmark or telegram or
  performance"`: candidato **17 failed, 308 passed, 2346 deselected** en 129.12s;
  base `1b87e886` con el fix apartado mediante `git stash` **23 failed, 302
  passed**. `Compare-Object` de las dos listas de `FAILED`: **cero entradas
  solo en candidato**; las 6 diferencias son los tests de P-L155 que pasan.
- `ruff check src tests`: `All checks passed!`.
- `scripts/check_no_nulls.py`: `check_no_nulls: OK (537 archivos)`.
- `git diff --check`: exit 0.
- CLI aislado `spy-eod-coverage --from 2026-09-23 --to 2026-09-24 --json` con
  `DATA_DIR` temporal vacio: `ok: true`, `sessions_comparable: 0`, ambas
  sesiones con `receipt_missing`. Fail-closed honesto, sin inventar cierres.

### Fallos preexistentes, no introducidos

Los 17 fallos de la regresion amplia son copy de Telegram divergente y son
preexistentes. Verificado con el fix apartado en la misma base:
`tests/test_p71_eod_authority.py` da los mismos 3 fallos con y sin el cambio
(`test_future_bar_in_an_otherwise_valid_cache_is_rejected`,
`test_ui_and_telegram_use_same_eod_overlay_contract`,
`test_telegram_publish_without_authoritative_cache_never_falls_back_to_stale_scalar`).
El primero argumento esperado en el codigo de Telegram es
`'SPY (ETF S&P 500): n/d'` y el texto emitido es
`'SP500 n/d (sin datos comparables)'`. No se tapan con `skip` ni `xfail` y no se
tocan: son micro-lote de copy, fuera del alcance de P-L155.

### Gates omitidos y no aprobados

Suite completa (`pytest tests/ -x -q`), benchmark de 33.336 observaciones, smoke
`run-once --skip-crew`, `validate-agent-config --json`, `kernel-status --json` y
despliegue: **omitidos**, no aprobados. Motivo: mercado cerrado pero margen
operativo corto y este lote es N2 sobre un unico lector, con presupuesto
proporcional de caracterizacion, focales, regresion del area afectada y gates
estaticos. El benchmark de 33.336 observaciones es deliberadamente lento y
`storage.py` no tiene diff. `kernel-status` y `validate-agent-config` deben
repetirse desde la raiz y `DATA_DIR` productivos; un `unsealed` en temporal no
describe produccion.

## Paridad y limites

- Paridad de trading: intacta. El cambio solo decide que recibo ya existente se
  lee, y cuando se toma el reloj de un recibo recien capturado. No toca
  candidatos, scores, ranks, gates, sizing, microexperimentos, planes,
  cantidades, precios, stops, takes, trailing, ordenes, exposicion ni limites.
  `performance_daily` no se toca. La ruta sigue siendo observacional y no puede
  crear, bloquear ni retrasar ordenes.
- Sin backfill, sin reescritura de historico, sin reenvio de sesiones ya
  entregadas, sin cambio de esquema ni de tablas, sin dependencias nuevas.
- Sin broker, sin red, sin yfinance real, sin LLM operativo, sin SQLite
  productiva, sin `.env`, sin push, sin despliegue, sin reinicio. Ningun archivo
  protegido modificado.
- Efecto colateral declarado: `backfill_spy_eod_receipts` y
  `spy_eod_coverage` dejan de tratar como `unavailable` una sesion cuyo
  `comparable` estaba tapado, y `spy-eod-backfill` la contaria como `skipped` en
  vez de generar un recibo duplicado. Es el efecto buscado, y no se ha ejecutado
  ningun backfill.
- Limitacion de fidelidad de la fixture: no hay acceso autorizado a produccion
  (sin SSH, sin docker), asi que los cuatro ficheros de 2026-09-24 se
  reproducen con los **nombres y la distribucion de `comparison_status`
  exactos** de produccion y con el contenido generado por el productor real
  `build_spy_eod_receipt` sobre caches temporales. Los sufijos de nombre se
  replican literalmente; el `content_hash` interior de cada recibo lo calcula
  `_stable_hash` y por tanto no coincide con el de produccion, que no es
  legible sin abrir los ficheros del Jetson. El defecto reproducido es de orden
  por nombre, que depende solo del nombre y del `comparison_status`, no del hash
  interior. Los `captured_at` usados son plausibles y están elegidos en el caso
  mas duro: el `unavailable` mas reciente es tambien el ultimo alfabeticamente.
  Los `captured_at` reales de produccion siguen siendo `unavailable` para este
  lote.
- `test_p127_spy_slice_characterization.py::test_refresh_open_session_never_downloads`
  tiene un doble ineffective: parchea `spy_eod_authority.download_daily_prices_with_metadata`,
  pero la funcion importa el simbolo desde `.market_data` dentro del cuerpo, asi
  que el parche no se aplica y la prueba pasaria aunque se descargara. El test
  propio de A4 parchea el modulo de origen y verifica que no hay llamadas.

## Identidad del lote

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl155_spy_eod_post_session`,
  rama `codex/pl155-spy-eod-post-session`.
- Base exacta: `1b87e886a2f682d599ada157bd22074f0d622219`, tree
  `e7246bb057a9b75f0a94086824f9469ff0f8cee2`, v0.4.320.
- Commit de caracterizacion: `7a5829202b2d79160feb112c32b53fdf37db4a8a`, tree
  `17668a75f60365ccb04bb9b858b275f199cc1c71`.
- Commit funcional: `1de86db07875cc3a3002b96dda8cb31de3912ce1`, tree
  `30563d7ffa54b4d569ff63a60b4e409e4b491a37`, v0.4.321.
- Ficheros tocados: `src/agente_bolsa/tools/spy_eod_authority.py` (103 lineas,
  +94/-9), `src/agente_bolsa/__init__.py` (+3/-1, bump),
  `tests/test_p155_spy_eod_receipt_selection.py` (nuevo, 15 tests),
  `tests/test_p59c_llm_selected_authority.py` (pin de version).
- Hash del commit de documentacion: se registra tras el commit; este informe no
  se auto-referencia.
- XNYS: 2026-09-28 12:49:33Z / 14:49:33 Europe/Madrid, cerrado, `next_open`
  2026-09-28 15:30 Europe/Madrid. Produccion no tocada: sigue siendo
  `agente-bolsa:0.4.320-arm64` en el Jetson 192.168.1.186.

## Siguiente paso minimo

Ensayo de integracion con `merge --no-ff` del commit funcional
`1de86db07875cc3a3002b96dda8cb31de3912ce1` sobre la base exacta
`1b87e886a2f682d599ada157bd22074f0d622219`, comprobando que el tree del merge
deja los cuatro ficheros efectivos identicos al candidato, y repetir alli la
regresion amplia mas Ruff, NUL y `git diff --check`. Precondiciones: XNYS
cerrado, sin leases ni jobs activos, arboles limpios y version sin colision.
Despliegue sigue sin autorizacion y este lote no lo pide.
