# P-L136 — ledger append-only de flujos de caja (candidato Windows 0.4.240)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

El contrato P-L52B acepta `external_flow_ledger` pero ningun productor lo
suministraba (siempre `None`): EOD quedaba `unavailable` por
`external_flow_ledger_missing` aunque no hubiera movimientos. Sin ledger
de depositos/retiradas no hay ecuacion contable cerrada posible.

## Cambio (productor nuevo, sin politica ni protegidos)

- Nuevo `tools/cash_flow_ledger.py`, esquema
  `p-l136.cash-flow-ledger.v1` sobre `agent_events` append-only:
  `record_cash_flow` valida (kind deposit/withdrawal, amount > 0,
  currency ISO3, `occurred_at` ISO con zona; rechazo sin escribir) y
  persiste con idempotencia/conflicto del contrato append-only;
  `read_cash_flow_ledger` filtra por ventana/moneda y devuelve filas
  en la forma exacta que consume P-L52B (`flow_id/amount/currency/
  occurred_at/kind`), ordenadas y totalizadas.
- Signo: deposit +, withdrawal −. Sin enlace → nada; legacy sin flujos
  registrados queda `exact` con total 0.0 sobre eventos grabados (el
  consumidor decide; no se inventa historia).
- Compatibilidad probada: el builder P-L52B con estas filas da
  `flow_coverage exact`.
- Bump `0.4.239` → `0.4.240`; pin `test_p59c` actualizado.

Sin esquema nuevo, sin backfill, sin tocar PMR/ruta activa: el cableado
`external_flow_ledger` en el builder PMR queda para el siguiente lote
con paridad (requiere pasar store/flujos por postmarket).

## Commits (rama `codex/pl136-cash-flows`, base `ca876b97`)

- `b7cefc8b` test: 5 tests (rojo por coleccion + 2 correcciones de
  contrato P-L52B: kwargs y ruta `coverage.flow_coverage`).
- `cc289559` feat + bump 0.4.240 + pin version.

## QA (XNYS abierto; solo gates aislados)

- Focales: 5 passed (`test_p136_cash_flow_ledger`).
- Regresiones: 83 passed con P-L52B x3 + p59c.
- `ruff check src tests`: All checks passed.
- `scripts/check_no_nulls.py`: OK (506 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, merge y despliegue: OMITIDOS por XNYS abierto.

## Siguiente paso

Revision → `merge --no-ff` conjunto P-L130→P-L136 en ventana cerrada →
suite completa → cablear ledger al builder PMR (lote con paridad) →
port Jetson. Sin push. Sizing/politica: sin cambios.
