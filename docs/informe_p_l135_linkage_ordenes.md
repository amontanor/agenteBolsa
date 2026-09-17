# P-L135 — cobertura de linkage orden-plan (candidato Windows 0.4.239)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

La auditoria P-L95 dejo 63 `filled` antiguas sin fila enlazable en
`order_plans`: sin medidor, el linaje es insuficiente para sizing y no
hay forma de verificar que las ordenes nuevas enlazan. Inspeccion del
codigo: la ruta activa (`cycle_runner` 2234 → 2328 → 2336) ya persiste
el plan antes del submit, asi que las 63 son legacy (inferencia por
codigo, no verificada contra produccion: la SQLite productiva no se
toco). Este lote entrega el medidor y la clasificacion, no reconstruye
nada.

## Cambio (lectura + clasificacion, sin politica ni protegidos)

- `Store.order_plan_linkage_summary(recent_days=30)`: LEFT JOIN
  `broker_orders → order_plans` por `plan_id` exacto; filled =
  `FILLED_STATUSES` canonico reutilizado (lazy import, sin ciclo).
  Devuelve total/filled/con/enlace, `coverage` (None sin fills) y
  ventana `recent` de 30 dias. Sin enlace → contado como
  `legacy_unverified`, jamas reconstruido por simbolo/fecha.
- Cableado a `build_production_health_report` (summary + top-level)
  con fail-open → `{"status": "unavailable"}`. Completa el S3 diferido
  de P-L133.
- Bump `0.4.238` → `0.4.239`; pin `test_p59c` actualizado.

`storage.py` solo gana un lector aditivo; sin esquema, sin escrituras,
sin tocar `execution.py`/ruta de submit.

## Commits (rama `codex/pl135-order-linkage`, base `5d7d998f`)

- `382e79a7` test: 4 tests (rojo 4/4 confirmado).
- `9b2cfcbe` feat + bump 0.4.239 + pin version.

## QA (XNYS abierto; solo gates aislados)

- Focales: 4 passed (`test_p135_order_linkage`).
- Regresiones: 70 passed con p59c + p133 + operational_health +
  order_plan_expiration.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (504 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, merge y despliegue: OMITIDOS por XNYS abierto.

## Siguiente paso

Revision del operador → `merge --no-ff` conjunto P-L130→P-L135 en
ventana cerrada → suite completa → medir cobertura real en produccion
via health → port Jetson. Sin push. Sizing/politica: sin cambios.
