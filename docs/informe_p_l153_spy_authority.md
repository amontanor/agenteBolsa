# P-L153 — autoridad temporal SPY + tarjetas honestas en cerrado (candidato 0.4.253)

Dictamen: `ready_for_review`. Sábado 19-sep-2026, XNYS cerrado; trabajo
aislado en worktree, sin broker/red/LLM en pruebas, sin despliegue.

## Causa

Tras el corte 0.4.308 la tabla de sesiones colapsó (30→1 comparaciones,
36 omitidas): los jobs nocturnos descargan SPY y crean candidatos con
valores realmente distintos para la misma apertura (09-17: `759.5` vs
`763.15`). Mecanismo: barras diarias descargadas **durante la sesión**
(a medio formar) conviven con las post-cierre (revisadas); el loader
las trataba como evidencia igual y fabricaba conflictos eternos. P-L143
hace bien en no fusionarlas: hay que elegir, no promediar.

## Cambio

- `_session_settled_at` (apertura + 6h45m) + `_candidate_settled`:
  exime capturas dedicadas `explicit_benchmark_open`, conserva sin
  `created_at`/ilegible (fail-open a mantener dato) y cuarentena la
  barra parcial solo si existe candidato settled para la sesión.
- Warning `partial_session_bars_quarantined` + helper
  `quarantined_open_sessions` para medirlo.
- `_position_rows(blank_intraday=True)` desde el dashboard con el mismo
  criterio de la tarjeta (cero de proveedor + mercado cerrado): el P/L
  día por posición muestra `n/d`, no `$0.00`.
- Revertido antes del merge: se probó omitir el punto provisional en
  día sin sesión, pero rompe el contrato P-L63 (el equity actual siempre
  se anexa; `test_p63` exige `pl == -961.83` con el punto actual). El
  punto sábado con 0.00% es medida real, no ruido: se conserva.

## QA

- Nuevos: `tests/test_p153_spy_authority.py` (10 tests: frontera
  20:15Z, settled/parcial/autoridad, cuarentena con loader real,
  desacuerdo settled genuino que SIGUE en conflicto, blank_intraday).
- Regresiones: P-L72/P-L74/P-L82/P-L82R/P-L88/P-L143 (50), P-L152,
  web_app, daily equity, version policy. Total: 57+ en batería final.
- Pin de versión P-L59C a 0.4.253. Ruff/diff verdes; NUL verde salvo el
  fallo preexistente de encoding en `docs/plan_mejoras_y_tareas.md`
  (byte 0x97, fichero no tocado por este lote).
- Omitidos (fin de semana): suite completa, smoke, config/kernel.

## Límites

- Si solo hay barras parciales para una sesión, se conservan (sin dato
  es peor que dato provisional marcado).
- No borra ni reescribe cachés; la cuarentena es solo de lectura.
