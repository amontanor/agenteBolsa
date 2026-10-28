# Despliegue 0.4.381 en Jetson — 28-oct-2026

Dictamen: `partially_verified_deployed`. Código .381 activo y verificado;
quedan residuales operativos que no invalidan el despliegue pero impiden
declarar salud plena.

## Autorización y contexto

- El operador autorizó expresamente desplegar durante XNYS abierto.
- Hora del corte: 2026-10-28 14:22:41 UTC (15:22 Europe/Madrid).
- XNYS abierto; cierre 21:00 Europe/Madrid.
- No se forzaron leases, no se borraron locks, no se re-selló el kernel.

## Identidad del candidato

- Rama: `codex/oct19-corrective-integration`.
- Base integrada: `3147c1932e275e25675496c8e54f98771d135ca4`.
- Merge de la corrección de Carga: `1a3b30ed9ac6fbe7c1129410d68f8e74f3401895`
  (`learning_scoreboard.py` y su test; filas completas para llamadas normales,
  `compact=True` solo en el scoreboard programado).
- HEAD final: `91ebb6960456f177a7a3ff5488e95d8785520b7c`.
- Árbol final: `1f40019c77d69af4f3b7ead3ea99bb3f61aaab58`.
- Versión: `0.4.381`.
- Los documentos del hilo coordinador quedaron sin commitear y no se tocaron.

## Gates ejecutados

- Suite completa Windows sobre el árbol final: **3163 passed, 1 failed,
  1 skipped**, 105 warnings, 783,89 s.
  - Fallo: `tests/test_web_research.py::test_search_company_news_without_provider_is_no_provider`
    (`assert 'ok' == 'no_provider'`). Pasa aislado y el fichero completo pasa
    (8/8). Se clasifica como contaminación de orden de tests, no regresión del
    lote; el módulo no fue modificado por `1a3b30ed`.
- Ruff: `All checks passed!`.
- `check_no_nulls.py`: `OK (596 archivos)`.
- `git diff --check`: sin errores (solo avisos CRLF de documentos ajenos).
- `validate-agent-config --json`: sin error.
- La prueba ARM de 200.000 señales no se ejecutó: el operador renunció a los
  gates pendientes y pidió desplegar.
- Las correcciones Linux `6065369c` y `3147c193` ya estaban integradas.

## Imagen construida

- Tag: `agente-bolsa:0.4.381-arm64`.
- ID: `sha256:3749d4b0f114ea4f148c79093e9955d938063c1b962985c41a845cb503429f9c`.
- Base: `agente-bolsa:0.4.321-arm64`
  (`sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae`).
- Labels: versión `0.4.381`, revisión `91ebb696`,
  árbol `1f40019c`, base `0.4.321-arm64`.
- Build incremental `FROM .321` + `src/agente_bolsa`, `scripts`,
  `pyproject.toml`, `requirements.lock`; sin dependencias nuevas.
- Smoke sin red ni volúmenes: versión `0.4.381`, imports de scheduler/web/
  learning_spool/scoreboard, `build_parser()` OK, `_cohort_rows` acepta
  `compact`, `compileall` completo OK.
- Hashes protegidos dentro de la imagen coinciden con el manifiesto sellado:
  - `kernel.py` `89f62f75...`
  - `broker.py` `7656e0be...`
  - `execution.py` `e3b46b5b...`

## Corte

- Backup del selector: `/etc/agente-bolsa/runtime.env.bak-pl-0381`.
- Selector nuevo: `AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.381-arm64`.
- `jetson-ops diagnose-agente-bolsa`: `agenteBolsa preflight=ok`.
- `jetson-ops deploy-agente-bolsa` recreó `init-db`, scheduler, web y auxiliar.
- El helper terminó con `ERROR: timeout esperando agentes healthy|0|false (120s)`
  porque el auxiliar no alcanzó `healthy`; los tres contenedores sí quedaron
  arriba con la imagen nueva.

## Verificación post-arranque

- Los tres contenedores ejecutan exactamente
  `sha256:3749d4b0f114ea4f148c79093e9955d938063c1b962985c41a845cb503429f9c`.
- Runtime del scheduler: `0.4.381`.
- Scheduler: `healthy`, `RestartCount=0`, `OOMKilled=false`.
- Web: `healthy`, `RestartCount=0`, `OOMKilled=false`.
- Auxiliar: `running`, `RestartCount=0`, `OOMKilled=false`, `unhealthy`.
- Doble comprobación separada >75 s y observación >600 s sin OOM.
- HTTP: `/`, `/health` y `/_stcore/health` = 200 desde Jetson y desde Windows.
- Listener único en `0.0.0.0:8081`; un solo contenedor scheduler.
- Lock: pid 8, token `8110017`, escrito `2026-10-28T14:22:47Z`.
- Kernel: `ok=true`, `violations=[]`, los cuatro ficheros coinciden.
- Kill switch de integridad: limpiado por la ruta normal; fichero ausente.
- Flags: `TRADING_MODE=paper`, `ALPACA_PAPER=true`,
  `ALLOW_LIVE_TRADING=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- Ciclo posterior: `mkt_60d4068c1b16` completado en 391,62 s.
- Orden paper: `e92849e1-c701-4c3a-856c-cf3ff41da08f`, CNC buy 14 @ 68,03,
  `dry_run=true`, `allow_live_trading=false`, estado `filled`.
- Memoria al final: scheduler 1,307 GiB/2 GiB; web 681 MiB/1 GiB;
  auxiliar 17,5 MiB/256 MiB; sin líneas OOM en dmesg.

## Residuales

1. Auxiliar `unhealthy`: `ci_digest` falló hoy a las 07:31:35Z con
   `returncode=-9` (previo al despliegue). El latch de salud dura hasta el
   siguiente intento programado; no se reejecutó a mano.
2. Lease de reconciliación `brkrec_64db6465bc6f`, sesión `2026-10-26`,
   `status=active` desde `2026-10-27T03:50:45Z`, sin terminal. No se forzó.
3. Diez avisos `database is locked` en `signal_learning`, en una sola ráfaga
   a las 14:26:51Z durante el primer ciclo tras el arranque. El ciclo terminó
   `completed`. La cola reciente de `system.log` (115 MB) contiene 884
   coincidencias desde septiembre, incluidas del 27-oct; se clasifica como
   contención preexistente, no como regresión de .381.
4. LLM con `401 api_key_expired` a las 14:28:27Z y 14:30:33Z. La decisión cayó
   a `deterministic_fallback`; la orden se ejecutó en paper.
5. Avisos de saturación del scheduler (`maximum number of running instances`,
   un `missed` de portfolio watch). No hubo reinicio ni OOM.

## Rollback

- Selector anterior: `agente-bolsa:0.4.321-arm64`.
- Backup: `/etc/agente-bolsa/runtime.env.bak-pl-0381`.
- Imagen .321 conservada.
- Procedimiento: restaurar el selector y ejecutar
  `sudo -n jetson-ops deploy-agente-bolsa`. No ejecutado.

## Siguiente paso

Renovar la clave LLM, resolver el lease por la ruta normal de propietario y
evento terminal, y dejar que `ci_digest` se reintente en su ventana. La prueba
ARM de volumen sigue pendiente y debe hacerse antes de declarar validación
completa del lote.
