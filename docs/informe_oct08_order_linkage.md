# Informe único — order linkage N2 (8-oct-2026)

Dictamen: `ready_for_integration_rehearsal`.

El defecto era reproducible y estaba presente antes de este lote: `Store` no
exponía `order_plan_linkage_summary` y `build_production_health_report` no
publicaba `order_linkage`. Los cuatro tests de
`tests/test_p135_order_linkage.py` fallaron igual sobre el candidato inicial
`ab28bd86193ef48a18d1f058e2f79492721c1412` (tree
`daa3f125e2da5b0504924dce5a6858764a9aa1f9`) y sobre la base de reproducción
`1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`. La causa histórica queda
identificada en la reconstrucción `784e6cd7`: retiró helpers de la línea Jetson
`.310`; el contrato original está conservado en P-L135 (`9b2cfcbe`, documentado
en `ca876b97`).

## Alcance y contrato restaurado

- Rama aislada: `codex/oct08-order-linkage`.
- Base exacta: `ab28bd86193ef48a18d1f058e2f79492721c1412` / tree
  `daa3f125e2da5b0504924dce5a6858764a9aa1f9`.
- `Store.order_plan_linkage_summary(recent_days=30)` hace una lectura sobre
  `broker_orders` y `order_plans`, enlazando exclusivamente por `plan_id`.
  Reutiliza `FILLED_STATUSES` y devuelve `total`, `filled`,
  `filled_with_plan`, `filled_without_plan`, `coverage`, el bloque `recent`,
  `recent_days` y `unverified_label=legacy_unverified`.
- Un `broker_order` sin plan se cuenta como evidencia histórica no verificada;
  nunca se reconstruye por símbolo, fecha, texto o “última compra”. Sin fills,
  `coverage` queda en `null`.
- `build_production_health_report` añade el carrier en `summary.order_linkage`
  y en el nivel superior `order_linkage`. Si la lectura falla, publica
  `{"status": "unavailable"}` y conserva el health fail-open.
- Revisión de eficiencia N2: el lector ya no hace `fetchall` ni conserva filas.
  Ejecuta una única consulta agregada SQL para los totales globales y recientes,
  usa `Store.read_connection` (`mode=ro`, `query_only=ON`) y cierra su cursor
  en `finally`, sin cerrar la conexión read-only compartida de otro lector.
  No abre transacción writable.
- Solo se reañaden lecturas y cableado observacional. No hay esquema, índice,
  configuración, backfill, reescritura histórica, cambios de autoridad de
  trading ni archivos protegidos.
- Versión reservada: `0.4.345` (el slot `.344` queda para coordinación y `.346`
  para uplift).

## Commits e identidad

- Implementación + bump + pin de versión: `ce950742d99abd8021cfea643de2ec893a5d50c6`.
- Optimización agregada read-only: `8dc3b307`.
- QA focal de límites: `b58c5b88`.
- El informe original se actualiza ahora en un commit documental separado.
- Sin push, merge, despliegue, reinicio ni escritura de producción.

## QA ejecutada

- Focal directa: `tests/test_p135_order_linkage.py` — **4 passed**.
- Revisión posterior a la optimización: `tests/test_p135_order_linkage.py` —
  **6 passed**, incluyendo estados `FILLED`/`partially_filled`, cutoff
  lexicográfico UTC, enlace ausente, tienda vacía, no mutación y DB ausente sin
  creación.
- Regresiones relacionadas (`p135`, `p59c`, `p133`, `operational_health`,
  `order_plan_expiration`) sobre el candidato previo a la optimización —
  **70 passed**.
- Harness autorizado `validate_oct08_isolated.py` sobre las mismas focales y
  regresiones del candidato previo, con `DATA_DIR` temporal, `_env_file=None`,
  paper y red externa bloqueada — **70 passed**.
- `ruff check src tests` — `All checks passed`.
- `scripts/check_no_nulls.py` — `OK (544 archivos)`.
- `git diff --check` — limpio.
- `validate-agent-config --json` aislado — `ok=true`, sin errores ni warnings.
- `kernel-status --json` aislado — `status=unsealed`, esperado en DATA_DIR
  temporal sin manifest; no se tocó ningún protegido ni se ejecutó seal.

La revisión de eficiencia no repitió los 70 tests de regresión: la evidencia de
70/70 corresponde al candidato previo, mientras que la consulta nueva quedó
cubierta por las seis focales, Ruff focal y diff-check. La suite amplia y los
gates operativos siguen pendientes del ensayo cerrado.

## Límites y siguiente paso

No se ejecutaron suite completa, smoke, benchmark, ensayo de integración,
lecturas de SQLite productiva, broker, red, LLM, job, reinicio ni despliegue.
La cobertura real de producción sigue sin medirse en este lote. El siguiente
paso requiere revisión del coordinador y ensayo de integración cerrado con la
identidad exacta de este candidato; no autoriza promoción ni despliegue por sí
solo.
