# P-L81 - cierre productivo y resultado

## Dictamen

`needs_fix`. El candidato P-L81 quedo validado, pero el despliegue fue revertido
porque el cambio read-only autorizado en `broker.py` modifica un archivo cubierto
por el manifest del kernel. No se ejecuto `kernel-seal`, tal como exige el lote.

## Evidencia

- Candidato: `7bc4648cfa5fd22758231357ce5380f359eacd78`, tree
  `fc6916c25b9901b7f8f2ab3ae079fd76ca6c1844`, v0.4.217.
- Merge intentado: `e8f7874edbd1b2afc01cec880c22a9dad41046eb`, padres
  `e4fe1ddb` y `7bc4648c`, tree funcional `fc6916c2`.
- Suite del candidato: `2422 passed, 1 skipped preexistente, 1 warning`.
- Suite post-merge desde produccion: `2423 passed, 1 warning`.
- Focales P-L81/UI: `168 passed, 1 warning`; Ruff, NUL, compile, diff,
  version policy, validate-agent-config y smoke aislado verdes.
- Smoke aislado: `run-once --skip-crew`, `used_crew=false`, DATA_DIR temporal.

El unico gate rojo fue `kernel-status` productivo tras el merge: esperado de
`broker.py` `b75016...`, actual `16221f...`. El diff contiene solamente el
carry de `account.last_equity` hacia `PortfolioSnapshot`; kernel, execution,
risk y config no cambian. Por no usar `kernel-seal`, se ejecuto
`git revert -m 1 e8f7874...`, commit `6f86f26044ee7372ca0caa615843de07417ebc93`,
restaurando tree `ce15c1b0` y v0.4.216.

## Estado operativo final

Tras el rollback, kernel `ok` sin violaciones, HTTP raiz y `/health` 200 en dos
comprobaciones separadas por mas de 75 segundos, scheduler owner/token validos,
paper activo, live y auto-apply desactivados, PMR terminal y lease vacio. Salud
operativa: 0 criticos y 3 warnings preexistentes. No se ejecutaron jobs manuales,
postmarket, reconciliacion, backfill, broker operativo, LLM real ni push.

## Siguiente precondicion unica

Revisar y autorizar explicitamente el procedimiento de sello para el hash exacto
de `broker.py` tras este carry, o escoger una frontera equivalente que no cambie
el archivo protegido. Despues repetir preflight, gates y despliegue cerrado; no
modificar la captura P-L80 ni la politica de trading.
