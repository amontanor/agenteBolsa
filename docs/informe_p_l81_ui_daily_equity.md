# P-L81 - coherencia de ganancia global diaria y continuidad UI

## Dictamen actual

`deployed`. P-L81A quedo integrado y desplegado el 04-ago-2026 con XNYS
cerrado. El merge productivo es `32c4025b4d148a9a6e54296e409639339c8f04cc`,
con padres `91ad200b` y `dc5df89e`, tree `0619f5b6ab5ed7bd9e5b0dd5f4cad42a6c0d0036`
y version `0.4.217`.

## Contrato y causa

La tarjeta de cuenta reutilizaba `opening_context.account_current`, por lo que
un lunes preapertura podia mostrar apertura-a-ahora como «hoy». El contrato
canonico queda centralizado en `tools/equity_metrics.py`:

`daily_equity_pl = current_equity - previous_close_equity`

`daily_equity_return = daily_equity_pl / previous_close_equity`

`previous_close_equity` procede de `account.last_equity` y la ventana es cierre
XNYS anterior -> instante actual. Si falta o no es valido, el resultado es
`unavailable`/`n/d`; no se sustituye por exposicion, porcentajes de posiciones,
trade history ni apertura XNYS. El P/L abierto, el P/L diario de posiciones,
el resultado del periodo y desde apertura conservan sus ventanas propias.

El carry se hace desde la captura de cuenta ya existente, sin llamada de broker
adicional desde UI. Los payloads legacy sin carrier permanecen explicitamente
en la ruta legacy.

## UX

- La tarjeta activa se etiqueta «Ganancia/perdida global de hoy» y muestra
  importe, porcentaje, cierre anterior y fechas.
- «Resultado del periodo», «P/L abierto» y «Rendimiento desde apertura» no se
  mezclan con la metrica diaria.
- La grafica Sistema vs SPY mantiene historicos solidos y dibuja el intervalo
  vigente como segmento discontinuo desde el ultimo final hasta el punto
  actual. El tooltip conserva la sesion e intervalo exactos.

## Validacion original conservada

El candidato `7bc4648cfa5fd22758231357ce5380f359eacd78`, tree
`fc6916c25b9901b7f8f2ab3ae079fd76ca6c1844`, v0.4.217, obtuvo `2422 passed`,
1 skip preexistente y 1 warning; la validacion post-merge obtuvo `2423 passed`.
Los focales P-L81/UI fueron `168 passed`; Ruff, NUL, compile, diff, version
policy, validate-agent-config y smoke aislado fueron verdes.

## Rollback historico

El merge original `e8f7874edbd1b2afc01cec880c22a9dad41046eb` fue revertido con
`6f86f26044ee7372ca0caa615843de07417ebc93` porque el carry read-only cambiaba
el hash protegido de `broker.py`. El estado seguro restaurado fue el tree
funcional `ce15c1b02991ad0a20d11039d46c554e138eff40`, v0.4.216. No se ejecuto
`kernel-seal` en aquel intento.

## P-L81R: frontera caracterizada

P-L81R demostro con un cliente fake que el SDK entrega
`account.last_equity=950.0`, pero las fronteras publicas de `broker.py` lo
descartan antes de crear `PortfolioSnapshot`; tampoco existe un carrier en el
constructor EOD, storage, scheduler o web. Por tanto no hay una via equivalente
sin tocar el adaptador protegido, hacer otra llamada o inventar un baseline.

## P-L81A: reaplicacion y despliegue auditados

La reaplicacion partio de produccion `91ad200bebe4253f909226ed0a3026aa172c9c5e`
mediante el revert-of-revert auditable de `6f86f260`; no se fusiono directamente
`7bc4648c`. El candidato limpio fue `dc5df89ec45a72d4eaa951d117dec2bdfb4524ba`
en `pl81a_last_equity_authority` / `codex/pl81a-last-equity-authority`.
El diff de `broker.py` queda limitado a:

```diff
+ "previous_close_equity": _optional_float_attr(account, "last_equity"),
+ previous_close_equity=_optional_float_attr(account, "last_equity"),
```

No cambia endpoint, credenciales, submit, cancel, reconcile, ejecucion,
riesgo, seleccion ni politica. La version desplegada es 0.4.217.

La suite fresca post-merge termino `2422 passed, 1 skipped preexistente, 1
warning` en `975.02s`; los focales UI/P-L81 fueron `109 passed, 1 warning`.
Ruff, NUL, compilacion, diff, version policy, validate-agent-config aislado,
kernel temporal y smoke `run-once --skip-crew` con proveedores fake quedaron
verdes. El warning es la deprecacion externa de `websockets.legacy`; no se
anadieron skips/xfails.

El `kernel-seal` canonico se ejecuto una sola vez tras revisar los hashes, a
`2026-08-04T06:44:18.051786Z`. `kernel-status` productivo quedo `ok=true` sin
violaciones; el unico hash protegido diferente al estado previo fue
`broker.py`, el carry read-only autorizado. Kernel, execution, risk (objeto
Git), config y `.env` conservaron sus objetos/valores previos.

La salud 1 fue `2026-08-04T08:45:16.586121+02:00` y la salud 2
`2026-08-04T08:47:19.7616468+02:00` (123 s): raiz y `/health` 200/200,
scheduler unico con owner/token coherentes, listener unico, paper activo,
live y auto-apply desactivados, 0 criticos y los 3 warnings preexistentes.
No se ejecutaron probe DeepSeek, jobs manuales, PMR/reconciliacion, backfill ni
push. El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` permanece intacto.

## Seguridad y limites

El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` permanece intacto. No hay
backfill. La UI no obtiene autoridad de trading y la paridad exigida cubre
candidatos, scores, ranks, gates, sizing, planes, cantidades, precios,
stops/takes, ordenes, exposicion y limites.

La produccion desplegada queda en v0.4.217 con paper activo, live y auto-apply
desactivados. No se ejecutan jobs manuales, postmarket, reconciliacion,
backfill ni probe LLM para este lote.
