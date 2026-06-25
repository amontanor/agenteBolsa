# Informe Codex — migración T6 aplicada parcialmente — 2026-06-25

## Resumen

Se aplicó la compactación histórica de `signal_outcomes` solo sobre los grupos sin conflicto del dry-run aprobado. Los 10.969 grupos conflictivos exportados en `docs/signal_outcomes_migration_conflicts_2026-06-25.json` quedaron excluidos explícitamente.

No se tocaron decisiones, riesgo, broker, ejecución, configuración ni `.env`.

Versión: `0.4.56`.

## Backup previo

Comando ejecutado antes de tocar datos:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main backup-db
```

Backup verificado:

```text
run_id: db_backup_4ee4a69ae019
backup_path: data\backups\agente_bolsa_db_backup_4ee4a69ae019.sqlite3
size_bytes: 2015764480
```

La copia existe en:

```text
C:\Antonio\Bref\agenteBolsa\data\backups\agente_bolsa_db_backup_4ee4a69ae019.sqlite3
```

## Script añadido

`scripts/migrate_signal_outcomes_compact.py`

Propiedades:

- Dry-run por defecto.
- `--apply` requerido para escribir.
- Lee y excluye `docs/signal_outcomes_migration_conflicts_2026-06-25.json`.
- Usa `BEGIN IMMEDIATE` en modo apply antes de recalcular planes y conteos para evitar carreras con el scheduler.
- Aplica todo en una transacción.
- Hace rollback ante cualquier verificación fallida.
- Conserva la fila más reciente por `(updated_at, created_at, signal_id)`.
- Preserva el `outcome_json` efectivo siguiendo T6: si la fila más reciente no tiene outcome útil, se conserva el outcome previo del grupo.

Se añadió test sintético:

`tests/test_migrate_signal_outcomes_compact.py`

Cubre:

1. Conservación de outcome antiguo cuando la fila más reciente trae `{}`.
2. Aplicación sobre SQLite temporal: compacta grupo seguro, deja intacto grupo conflictivo y conserva el payload de outcome.

## Incidencia controlada antes del apply final

El primer dry-run real sin cutoff devolvió:

```text
groups_to_compact: 1047
rows_to_delete: 9525
before_total_rows: 322792
```

Esto no coincidía con el objetivo aprobado de ~8.988 filas. La diferencia era +537 filas, atribuible a un nuevo ciclo intradía añadido por el scheduler después del dry-run original.

Para no ampliar alcance, se acotó el universo aprobado con:

```text
--max-created-at 2026-06-25T18:00:00+00:00
```

Ese cutoff reproduce exactamente el alcance del dry-run aprobado:

```text
groups_to_compact: 1039
rows_to_delete: 8988
before_scoped_rows: 322255
```

Hubo un primer intento de `--apply` que abortó con rollback por una verificación demasiado estricta sobre filas con `return_*`:

```text
RuntimeError: forward_return_row_count_unexpected
```

Verificación inmediata tras ese fallo:

```text
total: 322792
scoped: 322255
```

Es decir: no hubo commit parcial.

La verificación se corrigió para distinguir:

- payload `outcome_json` no vacío,
- filas con `return_*`,
- payloads de outcome preservados en la fila conservada.

## Dry-run final antes de aplicar

Comando:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_signal_outcomes_compact.py --conflicts docs\signal_outcomes_migration_conflicts_2026-06-25.json --max-created-at 2026-06-25T18:00:00+00:00
```

Salida:

```text
=== signal_outcomes compact T6 safe groups (DRY-RUN) ===
db: data\state\agente_bolsa.sqlite3
conflicts: docs\signal_outcomes_migration_conflicts_2026-06-25.json
max_created_at: 2026-06-25T18:00:00+00:00
conflict_groups_loaded: 10969
groups_to_compact: 1039
rows_to_delete: 8988
groups_with_outcome: 1039
nonempty_outcome_rows_in_plans: 10027
deleted_nonempty_outcome_rows: 8988
keep_promotions_to_nonempty: 0
deleted_forward_return_rows: 39
keep_promotions_to_forward_return: 0
before_total_rows: 322792
before_scoped_rows: 322255
before_nonempty_outcome_rows: 322792
before_forward_return_rows: 312263
apply: false (no se escribio en la BD)
```

Nota: tras la maduración masiva, `outcome_json != '{}'` ya no equivale a “forward return maduro”; muchas filas tienen payload de estado. Por eso la verificación de seguridad real comprueba que los payloads no vacíos borrados quedan representados por el `outcome_json` final de la fila conservada.

## Apply final

Comando:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_signal_outcomes_compact.py --conflicts docs\signal_outcomes_migration_conflicts_2026-06-25.json --max-created-at 2026-06-25T18:00:00+00:00 --apply
```

Salida:

```text
=== signal_outcomes compact T6 safe groups (APPLY) ===
db: data\state\agente_bolsa.sqlite3
conflicts: docs\signal_outcomes_migration_conflicts_2026-06-25.json
max_created_at: 2026-06-25T18:00:00+00:00
conflict_groups_loaded: 10969
groups_to_compact: 1039
rows_to_delete: 8988
groups_with_outcome: 1039
nonempty_outcome_rows_in_plans: 10027
deleted_nonempty_outcome_rows: 8988
keep_promotions_to_nonempty: 0
deleted_forward_return_rows: 39
keep_promotions_to_forward_return: 0
before_total_rows: 322792
before_scoped_rows: 322255
before_nonempty_outcome_rows: 322792
before_forward_return_rows: 312263
after_total_rows: 313804
after_scoped_rows: 313267
after_nonempty_outcome_rows: 313804
after_forward_return_rows: 312224
rows_deleted: 8988
conflict_groups_checked: 10969
verifications: OK
```

Interpretación:

- Se eliminaron exactamente 8.988 filas.
- Los 10.969 grupos conflictivos quedaron con el mismo recuento.
- No hubo pérdida de payloads de outcome: cada payload no vacío borrado estaba duplicado/preservado en la fila conservada del grupo.
- El recuento bruto de filas con `outcome_json` no vacío baja porque se han eliminado filas duplicadas que ya tenían payload; eso es esperado después de la maduración masiva. La comprobación fuerte es que el payload lógico del grupo permanece.

## Verificación post-aplicación

Dry-run residual con el mismo cutoff:

```text
groups_to_compact: 0
rows_to_delete: 0
before_total_rows: 313804
before_scoped_rows: 313267
before_nonempty_outcome_rows: 313804
before_forward_return_rows: 312224
apply: false (no se escribio en la BD)
```

Conteos por fuente después:

```text
total: 313804
forward_rows: 312224

intraday_scan: 270622 filas, 12013 grupos
opportunity_snapshot: 26565 filas, 8010 grupos
closed_market_study: 12464 filas, 11465 grupos
manual_scan: 3493 filas, 998 grupos
closed_market_study_backfill: 660 filas, 489 grupos
```

Integridad SQLite:

```text
PRAGMA quick_check -> ok
```

## Pendiente explícito

Los 10.969 grupos conflictivos no se tocaron. Siguen requiriendo una regla humana posterior para decidir cómo fusionar outcomes no vacíos distintos.

## Comandos de validación

Ejecutados antes del apply:

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\migrate_signal_outcomes_compact.py tests\test_migrate_signal_outcomes_compact.py src\agente_bolsa\__init__.py
.\.venv\Scripts\ruff.exe check scripts\migrate_signal_outcomes_compact.py tests\test_migrate_signal_outcomes_compact.py src\agente_bolsa\__init__.py
.\.venv\Scripts\python.exe -m pytest tests\test_migrate_signal_outcomes_compact.py -q -p no:warnings
```

La validación final global (`ruff`, suite completa, modo paper/live false) queda registrada en el cierre del commit.
