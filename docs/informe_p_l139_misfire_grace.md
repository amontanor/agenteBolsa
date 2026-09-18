# P-L139 — grace de misfire en jobs intradia (candidato Windows 0.4.245)

Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
push ni escritura productiva.

## Causa

Auditoria Jetson 17-sep (solo lectura): `market_cycle_15m` 22/22 runs
`missed`, `portfolio_watch_1m` 25 `missed`. Los logs muestran
despertares 1.4-2.7 s tarde con el default APScheduler de 1 s: todo run
tardio se descarta en vez de ejecutarse. Cero recomendaciones y cero
ordenes en sesion.

## Cambio (solo `scheduler.py`, sin trading ni protegidos)

- `misfire_grace_time`: 300 (ciclo 15 min), 120 (watch 1 min),
  120 (fill watch). Coalesce + max_instances intactos: tarde antes
  que nunca, sin backlog rancio.
- No corrige que el fill watcher cueste ~36 s con cadencia de 30 s
  (eso pide cadencia o coste, otro lote); ni el 400 del proveedor LLM
  (P-L142 con contrato verificado); ni `crew_observer` (modulo solo
  Jetson: nota de port P-L141).
- Bump `0.4.244` → `0.4.245`; pin `test_p59c` actualizado.

## Commits (rama `codex/pl139-scheduler-rescue`, base `39195b78`)

- `06b2c557` test: grace explicito (rojo confirmado).
- `0baf7aa3` feat + bump 0.4.245 + pin version (incluye teardown y
  flag del watcher en el test).

## QA (XNYS cerrado)

- Focales: 1 passed. Regresiones: 8 passed con p45b1; 47 passed con
  p59c.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (510 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa: en la integracion final.

## Siguiente paso

P-L142 (sesion LLM) → merge P-L139+P-L142 → suite → port Jetson →
corte. Sin push.
