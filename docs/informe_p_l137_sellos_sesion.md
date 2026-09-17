# P-L137 — maduracion recortada a sesiones completas (candidato Windows 0.4.241)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

`update_signal_outcomes` descargaba hasta manana y alimentaba el frame
crudo a `_outcome_for_signal`, que cuenta toda barra posterior a la
senal: la barra same-day (mutable, sesion abierta) contaba como historia
madura e inflaba `bars_seen`/horizontes. Es el bug de finality same-day
de P-L71/P-L127, pero en barras del universo en vez de SPY.

## Cambio (ruta compartida con paridad, sin politica ni protegidos)

- Nuevo `trim_to_completed_sessions(frame, now?, calendar?)` en
  `signal_learning.py`: ultima sesion con `market_close <= now` via
  `MarketCalendar` (mcal local, sin red); sin calendario, regla weekday
  16:00 ET marcada `degraded` (ignora festivos). Devuelve
  (frame, recortadas, ultima_sesion, degraded).
- `update_signal_outcomes` recorta el frame una vez antes del bucle y
  publica `bars_trimmed_universe`, `last_completed_session` y
  `session_seal_degraded` (aditivos, tambien en retornos tempranos).
  Nuevo kwarg `now` (default real) para tests; llamantes con kwargs,
  sin cambios.
- `_outcome_for_signal` intacto: con historia cerrada el recorte es
  no-op y el resultado es bit-identico (paridad probada).
- Bump `0.4.240` → `0.4.241`; pin `test_p59c` actualizado.

Sin cambios en kernel/broker/execution/risk/config/`.env`, sin backfill,
sin red/LLM nuevos, decisiones y gates intactos.

## Commits (rama `codex/pl137-session-seals`, base `c785b0b1`)

- `7cd1bdd2` test: 4 tests (rojo por coleccion).
- `726d223b` feat + bump 0.4.241 + pin version.

## QA (XNYS abierto; solo gates aislados)

- Focales: 4 passed (`test_p137_session_seals`: recorte abierta,
  cerrada, no-maduracion mutable, paridad historica).
- Regresiones: 77 passed (signal_learning + p59c),
  20 passed (counterfactual_analysis, llamante directo).
- `ruff check src tests`: All checks passed (1 auto-fix de imports,
  re-verificado).
- `scripts/check_no_nulls.py`: OK (507 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, merge y despliegue: OMITIDOS por XNYS abierto.

## Siguiente paso

Revision → `merge --no-ff` conjunto P-L130→P-L137 en ventana cerrada →
suite completa → port Jetson. Sin push. Sizing/politica: sin cambios.
