# Informe Codex — dry-run migración histórica T6 signal_outcomes — 2026-06-25

## Resumen

Se añadió un dry-run 100% read-only para planificar la compactación histórica de `signal_outcomes` pre-v0.4.51. No se ejecutó ninguna migración ni se escribió en la base de datos.

Artefactos:

- Script: `scripts/migrate_signal_outcomes_dryrun.py`
- Test: `tests/test_migrate_signal_outcomes_dryrun.py`
- Conflictos detectados: `docs/signal_outcomes_migration_conflicts_2026-06-25.json`
- Versión: `0.4.55`

## Esquema confirmado

En `src/agente_bolsa/storage.py`, `signal_outcomes` tiene:

- `signal_id TEXT PRIMARY KEY`
- `source_run_id TEXT NOT NULL`
- `source TEXT NOT NULL`
- `symbol TEXT NOT NULL`
- `signal_date TEXT NOT NULL`
- `decision TEXT NOT NULL`
- `features_json TEXT NOT NULL`
- `gate_json TEXT NOT NULL`
- `outcome_json TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

La estrategia se extrae de `features_json.strategy_name`. Si falta, el dry-run intenta inferirla desde `signal_id`; en filas históricas antiguas sin estrategia codificada queda como `unknown`.

## Regla de simulación

El dry-run agrupa por:

```text
(signal_date, symbol, strategy_name)
```

Para cada grupo duplicado, simula la semántica de UPSERT introducida por T6:

1. La fila más reciente por `(updated_at, created_at, signal_id)` sería la fila física conservada.
2. `source_run_id`, `source`, `decision`, `features_json` y `gate_json` se consideran metadatos actualizados a la fila más reciente.
3. `outcome_json` se preserva si la escritura nueva trae `{}`.
4. Si la escritura nueva trae un `outcome_json` no vacío, reemplaza el outcome anterior.
5. Si un grupo contiene más de un `outcome_json` no vacío distinto, el grupo se marca como conflicto y requiere decisión humana antes de migrar.

Esta regla replica la parte crítica del UPSERT actual:

```sql
outcome_json=CASE
    WHEN excluded.outcome_json = '{}' THEN signal_outcomes.outcome_json
    ELSE excluded.outcome_json
END
```

## Resultado del dry-run real

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_signal_outcomes_dryrun.py --conflicts-out docs\signal_outcomes_migration_conflicts_2026-06-25.json
```

Salida:

```text
=== signal_outcomes historical T6 migration dry-run (read-only) ===
Regla simulada: grupo=(signal_date, symbol, strategy_name); fila mas reciente conserva metadatos;
outcome_json se preserva si la escritura nueva trae '{}', y se marca conflicto si hay outcomes no vacios distintos.
filas totales: 322255
grupos totales simbolo-dia-estrategia: 12516
grupos duplicados: 12008
filas a eliminar si se compacta todo: 309739
filas a eliminar sin conflictos: 8988
filas con outcome no vacio a fusionar sin perdida: 4978
filas con outcome que se perderian bajo la regla segura: 0
grupos con conflicto humano: 10969
filas outcome no vacio dentro de conflictos: 300751
conflictos escritos en: docs\signal_outcomes_migration_conflicts_2026-06-25.json
```

Lectura operativa:

- El problema histórico es real: 309.739 de 322.255 filas son potencialmente compactables si todos los duplicados se resolvieran.
- Solo 8.988 filas son compactables bajo la regla segura sin conflictos.
- Hay 10.969 grupos con múltiples `outcome_json` no vacíos y distintos.
- Bajo la regla segura propuesta, las filas con outcome que se perderían son 0 porque los grupos conflictivos no se migran automáticamente.
- Ejecutar una compactación ciega sobre todos los grupos no es aceptable: afectaría grupos con outcomes históricos distintos.

## Test añadido

`tests/test_migrate_signal_outcomes_dryrun.py` cubre:

1. Una fila antigua con `outcome_json` no vacío y una fila más reciente con `{}`: el plan conserva la fila más reciente pero preserva el outcome antiguo.
2. Dos filas del mismo símbolo-día-estrategia con outcomes no vacíos distintos: el grupo queda marcado como conflicto humano.

## Recomendación para la migración real

No ejecutar todavía una migración automática global.

Plan seguro recomendado:

1. Hacer backup físico de `data/state/agente_bolsa.sqlite3` y de sus ficheros WAL/SHM si existen, con servicios parados o usando backup SQLite consistente.
2. Recalcular el dry-run inmediatamente antes de migrar y guardar checksums/resúmenes:
   - total de filas
   - total de grupos
   - nº de outcomes no vacíos
   - distribución de `matured_horizons` / claves `return_*d` si aplica
3. Ejecutar en una transacción única solo los grupos sin conflicto:
   - actualizar la fila conservada con el `outcome_json` simulado final si procede
   - eliminar las filas duplicadas del grupo
   - no tocar grupos con más de un outcome no vacío distinto
4. Verificación post-migración:
   - `COUNT(*)` baja exactamente por `rows_to_delete_without_conflicts`
   - nº de outcomes no vacíos no baja
   - para cada grupo migrado, el outcome final coincide con el dry-run
   - `update_signal_outcomes` sigue encontrando y madurando filas activas y shadow
5. Resolver aparte los 10.969 grupos conflictivos con una regla explícita, por ejemplo:
   - conservar el outcome más completo por número de claves maduras, si contiene todas las claves previas
   - si hay retornos contradictorios para el mismo horizonte, no fusionar automáticamente y exportar revisión
   - documentar la regla antes de tocar datos históricos

## Validación

Comandos ejecutados hasta el informe:

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\migrate_signal_outcomes_dryrun.py tests\test_migrate_signal_outcomes_dryrun.py src\agente_bolsa\__init__.py
.\.venv\Scripts\python.exe -m pytest tests\test_migrate_signal_outcomes_dryrun.py -q -p no:warnings
.\.venv\Scripts\ruff.exe check scripts\migrate_signal_outcomes_dryrun.py tests\test_migrate_signal_outcomes_dryrun.py src\agente_bolsa\__init__.py
.\.venv\Scripts\python.exe scripts\migrate_signal_outcomes_dryrun.py --conflicts-out docs\signal_outcomes_migration_conflicts_2026-06-25.json
```

Resultado parcial:

- Test específico: `2 passed`
- Dry-run: completado, sin escrituras en BD
- Conflictos: exportados a `docs/signal_outcomes_migration_conflicts_2026-06-25.json`

La validación final de suite completa y ruff global queda registrada en el commit de cierre.
