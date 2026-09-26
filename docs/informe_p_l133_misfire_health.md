# P-L133 — delays de misfire y vaciedad de outcomes en health (candidato Windows 0.4.237)

Dictamen: `ready_for_review`. XNYS abierto durante todo el lote; sin merge,
despliegue, push ni escritura productiva.

## Causa

La auditoria P-L95 dejo misfires del scheduler de 1-13 s sin cuantificar
por job y un 74,8 % de outcomes recientes vacios sin visibilidad en el
health: el operador no podia distinguir un scheduler sano de uno que
pierde ciclos ni ver de un vistazo la madurez de la evidencia. Medir
antes de optimizar: este lote solo observa, no repara.

## Cambio (solo observacional, sin politica ni protegidos)

- `scheduler._skip_delay_seconds`: segundos entre `scheduled_run_time`
  y el momento de deteccion (naive = UTC, skew negativo → 0.0, no
  parseable → None). Campo aditivo `delay_seconds` en el payload
  `p-l45b1.scheduler-event.v1` (misma version: lectores tolerantes;
  `event_id` sin cambios, idempotencia intacta, delay congelado al
  primer write por semantica append-only).
- `operational_health.scheduler_skip_summary(store)`: agregacion
  read-only por `job_id` (`missed`, `max_instances`,
  `max_delay_seconds`, `last_at`); eventos pre-P-L133 cuentan sin delay.
- `operational_health.signal_outcome_emptiness(store)`: `{total, empty,
  pct_empty}` sobre outcomes canonicos recientes (excluye lab_book /
  learning_experiment como el resto de lectores).
- Ambas secciones entran en `build_production_health_report` (summary
  y top-level) con wrapper fail-open individual → `{"status":
  "unavailable"}`. Sin alertas nuevas: visibilidad primero, umbrales
  con pre-registro en otro lote.
- Bump `0.4.236` → `0.4.237`; pin `test_p59c` actualizado.

Sin cambios en kernel/broker/execution/risk/config/`.env`, sin backfill,
ruta activa y cadencias intactas (sin tocar `misfire_grace_time`).

## Alcance recortado (declarado)

La cobertura de linkage filled-sin-plan pasa al LOTE 5 (R2b), su lote
natural junto a la reparacion del linkage. Este lote no toca
`storage.py`.

## Commits (rama `codex/pl133-misfire-health`, base `d44beb52`)

- `c46254c4` test: 7 tests (rojo por ImportError + campos ausentes).
- `30def441` feat + bump 0.4.237 + pin version.

## QA (XNYS abierto; solo gates aislados)

- Focales: 7 passed.
- Regresiones: 69 passed con p45b1 + operational_health + p59c.
- `ruff check src tests`: All checks passed (1 auto-fix de imports
  en el test, re-verificado).
- `scripts/check_no_nulls.py`: OK (501 archivos).
- `git diff --check`: limpio.
- `validate-agent-config --json` (DATA_DIR temporal): `ok=true`.
- Suite completa, merge y despliegue: OMITIDOS por XNYS abierto.

## Siguiente paso (tras revision del operador, XNYS cerrado)

1. `merge --no-ff` conjunto P-L130→P-L133 a `codex/astra`.
2. Suite completa sobre el arbol mergeado + doble salud.
3. Port mecanico a Jetson.

Sin push salvo peticion explicita. Sizing/politica: sin cambios.

## Re-add P-L133-R (candidato 0.4.318, 26-sep-2026)

Dictamen: `ready_for_integration_rehearsal`. XNYS cerrado; sin merge,
despliegue, push ni escritura productiva.

### Causa del re-add

La reconstruccion Jetson `784e6cd7` elimino `scheduler_skip_summary` y
`signal_outcome_emptiness` de `operational_health.py` conservando
`tests/test_p133_misfire_health.py` (error de coleccion ImportError). La
parte scheduler (`_skip_delay_seconds` + `delay_seconds` en el payload
`p-l45b1.scheduler-event.v1`) sobrevivio intacta y no se toca.

### Cambio (solo operational_health.py, 58 inserciones)

Port campo a campo del diff `30def441`, byte-identico: los 2 helpers
puros read-only + wiring fail-open individual en
`build_production_health_report` (summary y top-level). Sin grace P-L139,
UI P-L140, costes/scoreboard, politica, schema DB ni telemetria nueva.
Sin alertas ni gates nuevos; missing permanece `unavailable`
(`pct_empty=None` con total 0; `{"status": "unavailable"}` ante fallo de
lectura).

### Commits (rama `codex/pl133-skip-emptiness-readd`, base `26f144fa`)

- `769e26db` feat: re-add observacional (solo operational_health.py).
- `92834f76` test: bump `0.4.317` -> `0.4.318` + pin version policy P-L59C
  (slot libre verificado en plan principal y candidato).
- Docs en commit separado (este informe + plan + relevo en candidato).

### QA (XNYS cerrado; gates N2 proporcionales)

- Focales `tests/test_p133_misfire_health.py`: 7 passed.
- Relacionadas (p137 + operational_health + scheduler observability/lock
  + autonomous_operations + pin p59c): combinada 98 passed.
- `ruff check` focal, `scripts/check_no_nulls.py` OK (536),
  `git diff --check` limpio, `validate-agent-config --json` aislado
  `ok=true`.
- Suite completa, smoke, benchmark, kernel-status: OMITIDOS (N2 aislado;
  deuda de suite preexistente en lotes aparte, sin ocultar).
- Protegidos sin diff; produccion Jetson 0.4.316 no tocada; sin push.

### Siguiente paso

Revision direccion -> ensayo de integracion aislado en ventana cerrada;
sin merge ni despliegue desde este lote.
