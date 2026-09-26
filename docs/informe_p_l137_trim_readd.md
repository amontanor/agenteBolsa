# P-L137-R — re-add trim_to_completed_sessions (candidato 0.4.317)

Dictamen: `ready_for_integration_rehearsal`. XNYS cerrado (sabado 26-sep-2026,
next_open 28-sep 15:30). Sin merge, despliegue, push ni escritura productiva.

## Causa

El commit de reconstruccion Jetson `784e6cd7` (base del paquete `.310`)
elimino 4 helpers puros conservando sus tests, dejando 4 errores de coleccion
preexistentes (`test_p133`, `test_p137`, `test_p140a`, `test_p140b`). Este
lote re-anade unicamente el helper puro de sellos de sesion y su cableado,
sin tocar los otros 3 errores (lotes aparte, sin mezclar).

## Cambio (N2, ruta de outcomes sin autoridad de trading)

- Re-add `last_completed_session(now?, calendar?)` y
  `trim_to_completed_sessions(frame, now?, calendar?)` en
  `signal_learning.py`: ultima sesion XNYS con `market_close <= now` via
  `MarketCalendar` (mcal local, sin red); sin calendario, regla weekday
  16:00 ET marcada `degraded` (ignora festivos). Devuelve
  (frame_recortado, recortadas, ultima_sesion, degraded).
- `update_signal_outcomes` recorta el frame una vez antes del bucle y antes
  de `_persist_signal_outcome_captures`, y publica `bars_trimmed_universe`,
  `last_completed_session` y `session_seal_degraded` (tambien en retornos
  tempranos). Nuevo kwarg `now` (default real) para tests; `observed_at`
  conservado intacto. Llamantes con kwargs, sin cambios.
- `_outcome_for_signal` intacto: con historia cerrada el recorte es no-op y
  el resultado es bit-identico (paridad probada).
- Bump `0.4.316` -> `0.4.317`; pin `test_p59c` actualizado a `0.4.317`.

Sin cambios en kernel/broker/execution/risk/config/`.env`, sin backfill,
sin red/LLM nuevos, decisiones y gates intactos. Paridad de la ruta activa
preservada: el recorte solo descarta barras same-day (aun abiertas) antes de
madurar outcomes.

## Commits (rama `codex/pl137-trim-readd`, base `85e28447`)

- `c8ddabc7` feat: re-add trim_to_completed_sessions + cableado (0.4.317).
- `98d91bdc` test: pin version policy P-L59C a 0.4.317.

## QA (XNYS cerrado; gates proporcionales N2, sin suite completa)

- Focales: 4 passed (`test_p137_session_seals`: recorte abierta, cerrada,
  no-maduracion mutable, paridad historica).
- Regresiones: 27 passed (`test_signal_learning`) + 20 passed
  (`test_counterfactual_analysis`, llamante directo) = 47 passed.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (536 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, smoke y kernel-status: OMITIDOS (lote N2 aislado, sin
  autorizacion de despliegue; suite roja preexistente identica en base).

## Siguiente paso

Revision de direccion -> ensayo de integracion aislado en ventana cerrada.
Sin push. Sizing/politica: sin cambios. Despliegue: NO autorizado.
