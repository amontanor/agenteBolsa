# P-L82 — resolución autoritativa de apertura SPY y visibilidad de sesiones omitidas

## Dictamen provisional

`ready_for_closed_market_deployment`, pendiente únicamente de un preflight
productivo inmediato y de la integración secuenciada. No se ha modificado
producción ni se ha detenido el stack en este lote de implementación/QA.

## Base y alcance

- Base productiva: `2875b01263ecf0bb93513cd12a296cdcdbe66fb5`, tree
  `49c8e0224aa15f30e70fd795afb7536ea6d0dab3`, versión `0.4.217`.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl82_spy_opening_authority`.
- Rama: `codex/pl82-spy-opening-authority`.
- Commits: `e1538614` caracterización; `87919ee2` implementación y bump;
  `d5228ac4` cobertura QA; `b938eaa9` actualización de version policy.
- Versión candidata: `0.4.218`.
- XNYS cerrado; preflight inicial con próxima apertura
  `2026-08-04T15:30:00+02:00`. La producción sigue en paper, live=false y
  auto-apply=false, con kernel sellado/ok.

El lote solo cambia el resolver observacional de aperturas SPY, la visibilidad
de omisiones en la UI y las pruebas/documentación. No cambia broker, kernel,
execution, risk, config, `.env`, selección, gates activos, sizing, planes,
órdenes, exposición, límites ni la captura prospectiva P-L80. El cutoff
`2026-08-02T15:51:41.5484478Z` se conserva.

## Causa raíz reproducida

`load_cached_spy_open_observations()` en
`src/agente_bolsa/tools/opening_performance.py` agrupaba por `(price,
price_basis)` y, cuando había varios valores, inspeccionaba solo `group[0]`
para detectar `explicit_benchmark_open`. Así, un cache genérico del mismo
precio leído antes que el cache dedicado ocultaba la autoridad y devolvía
`conflict`; invirtiendo el orden, devolvía `available`.

La reproducción contra la base fue roja: `1 failed, 1 passed` en el nuevo
focal P-L82. La variante con el dedicado primero pasaba, demostrando que el
defecto dependía del orden de llegada/lectura, no del precio o de una regla de
autoridad distinta.

## Contrato aplicado

El resolver ahora:

1. forma grupos por valor canónico y `price_basis`;
2. busca autoridad dentro de todos los elementos de cada grupo, nunca solo en
   el primero;
3. acepta el único grupo con autoridad inequívoca y elige dentro de ese grupo
   de forma determinista;
4. conserva `conflict` cuando hay autoridades genuinamente discordantes o
   varios valores sin autoridad;
5. conserva la semántica legacy de un único valor sin autoridad y no usa
   timestamp/latest-wins para resolver la apertura;
6. no hace llamadas adicionales ni escribe caches: el lector sigue siendo
   local y read-only.

La UI no inventa puntos ni conecta sobre huecos. El contexto añade
`omitted_sessions` con `session_date`, `end_session_date`, `status`, `reason` y
la cobertura booleana de cuenta/SPY. El panel muestra esos datos incluso si no
hay filas comparables, mientras la tabla y el gráfico siguen mostrando solo
pares exactos. Razones cubiertas: `account_open_unavailable`,
`spy_open_conflict`, `spy_open_unavailable`, `price_basis_mismatch` y
`not_comparable`.

## Casos caracterizados y pruebas

- Genérico del mismo valor antes de autoridad dedicada: base roja, candidato
  verde y autoridad seleccionada.
- Autoridad antes del genérico: verde y misma autoridad.
- Dos autoridades con valores distintos: `conflict`, sin precio elegido.
- Dos valores sin autoridad: `conflict`, sin precio elegido.
- Basis no compatible o timestamp futuro: `unavailable`, sin apertura/current.
- Repetición y lectura: resultado idéntico y bytes de `.json`/`.pkl` sin
  mutación.
- Omisión: fecha, motivo y cobertura aparecen en el contexto y en el renderer
  UI.

QA focal de P-L65/P-L68/P-L71/P-L72/P-L74/P-L81/web/Telegram y P-L82:
`193 passed, 1 warning`. La warning es la deprecación externa
`websockets.legacy`; no se añadieron skips/xfails.

La primera suite completa terminó en `1555 passed, 1 failed, 1 warning` en
`712.95s`; el único fallo era el assertion stale de version policy que aún
esperaba `0.4.217`. Tras corregir solo esa expectativa, la suite fresca
terminó en `2430 passed, 1 skipped preexistente, 1 warning` en `716.88s`.

Gates adicionales:

- Ruff completo: verde.
- `scripts/check_no_nulls.py`: `OK (471 archivos)`.
- compilación temporal de `src`, `tests` y `scripts`: verde.
- `git diff --check`: verde.
- version policy focal: `1 passed`.
- `validate-agent-config --json` aislado: `ok=true`, 23 agentes, 6 tareas,
  6 habilitadas, sin errores/warnings.
- `kernel-status --json` temporal: `status=unsealed`, `violations=[]`,
  esperado sin manifest productivo; el kernel productivo inicial permaneció
  sellado/ok.
- smoke seguro de CLI: `run-once --skip-crew` con `run_cycle` fake,
  `DATA_DIR` temporal, `use_crew=false`, sin broker/red/LLM/SQLite
  productiva. No se ejecutó un ciclo real porque la CLI actual no ofrece un
  proveedor fake inyectable y hacerlo contactaría mercado/broker; no se
  clasifica esa sustitución como una llamada operativa.

## Paridad y seguridad

Los archivos funcionales cambiados son únicamente
`tools/opening_performance.py` y `web_app.py`, además del bump de versión. Los
tests de regresión confirmaron la ruta UI/Telegram y los contratos P-L65/P-L68/
P-L71/P-L72/P-L74/P-L81. No hay diff en `kernel.py`, `broker.py`,
`execution.py`, `risk.py`, `config.py` ni `.env`; no hay cambio en requests,
órdenes, gates, riesgo, sizing, exposición o límites.

No se usó broker, red, yfinance, LLM real, Telegram, SQLite productiva,
postmarket, reconciliación, jobs manuales, reinicio, kernel-seal, manifest ni
push.

## Siguiente transición

Con XNYS cerrado, PMR/leases terminales, ausencia de procesos competidores y
margen suficiente, corresponde el ensayo/integración `merge --no-ff` del HEAD
final de este worktree. Antes del despliegue debe repetirse el preflight; si
algún gate o margen falla, no se debe detener el stack. Si se integra y falla
un gate, el rollback permitido es `git revert` auditable del merge y
restauración del stack conocido.
