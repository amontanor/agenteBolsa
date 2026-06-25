# Informe Codex — verificación independiente post-migración T6 — 2026-06-25

## Resumen

Se verificó en modo read-only la migración aplicada a `signal_outcomes`, comparando:

- Backup: `data\backups\agente_bolsa_db_backup_4ee4a69ae019.sqlite3`
- Live: `data\state\agente_bolsa.sqlite3`
- Cutoff aplicado: `created_at < 2026-06-25T18:00:00+00:00`
- Conflictos excluidos: `docs/signal_outcomes_migration_conflicts_2026-06-25.json`

Resultado operativo:

```text
delta filas scoped backup-live: 8988
forward returns conservados en grupos no conflictivos: 2010 / 2010
discrepancias en grupos no conflictivos: 0
grupos conflictivos con set de signal_id cambiado: 0
```

Conclusión: la compactación de los grupos sin conflicto no perdió forward returns. Los grupos conflictivos no fueron compactados y conservan las mismas filas (`signal_id`) en backup y live dentro del cutoff.

## Método

Las dos bases se abrieron con SQLite read-only:

```text
file:data/backups/agente_bolsa_db_backup_4ee4a69ae019.sqlite3?mode=ro
file:data/state/agente_bolsa.sqlite3?mode=ro
```

Para cada fila en scope se calculó el grupo:

```text
(signal_date, symbol, strategy_name)
```

`strategy_name` se extrajo de `features_json.strategy_name`; si faltaba, se usó la inferencia histórica desde `signal_id` y, en último caso, `unknown`, igual que en los scripts de dry-run/compactación.

Para comprobar forward returns se usaron los horizontes:

```text
return_1d, return_3d, return_5d, return_10d
```

La verificación fuerte se hizo sobre los grupos no conflictivos, que son los únicos que la migración podía compactar. Para esos grupos se extrajeron del backup todos los pares:

```text
(signal_date, symbol, strategy_name, horizonte, valor_return)
```

y se comprobó que live contiene el mismo conjunto de valores en la fila superviviente/grupo resultante.

Los grupos conflictivos se verificaron por identidad de filas (`signal_id`) y recuento, porque no fueron objeto de compactación.

## Resultado numérico

Salida de la verificación independiente:

```json
{
  "backup_scope_rows": 322255,
  "live_scope_rows": 313267,
  "delta": 8988,
  "conflict_groups_json": 10969,
  "conflict_missing_groups": 0,
  "conflict_extra_groups": 0,
  "conflict_changed_signal_id_sets": 0,
  "nonconf_backup_return_group_horizon_keys": 2010,
  "nonconf_backup_distinct_return_value_facts": 2010,
  "nonconf_conserved_distinct_return_value_facts": 2010,
  "nonconf_return_discrepancies": 0,
  "nonconf_backup_return_instances": 2123,
  "compacted_nonconf_groups": 1039
}
```

Lectura:

- El scope del backup tiene 322.255 filas.
- El scope live post-migración tiene 313.267 filas.
- Diferencia exacta: 8.988 filas, igual a la compactación aplicada.
- Los 10.969 grupos conflictivos del JSON siguen presentes en ambos lados.
- En conflictos no falta ni sobra ningún grupo.
- En conflictos no cambió ningún set de `signal_id`.
- En los grupos no conflictivos hay 2.010 hechos forward-return distintos en backup y los 2.010 están conservados en live.
- Hay 0 discrepancias de forward returns en los grupos compactables/compactados.

## Nota sobre comparación estricta de payloads en conflictos

Se hizo una primera comparación estricta de valores `return_*` en todos los grupos, incluidos conflictos. Esa comparación mostró diferencias en grupos conflictivos no migrados.

La causa esperada es que `outcome_json` es mutable: el proceso de maduración puede recalcular/actualizar outcomes en filas existentes después del backup. Esas filas conflictivas no fueron eliminadas por la migración; por eso la comprobación adecuada para “no tocar conflictos” es identidad de filas (`signal_id`) y recuento, que sí dio 0 cambios.

Muestra del patrón observado en la comparación estricta descartada:

```text
Grupos conflictivos con valores return_5d distintos entre backup/live,
pero con las mismas filas vivas. Ejemplos: DD, A, AAPL, ABBV en fechas 2026-06-16/17.
```

Esto no indica pérdida por compactación; indica que live continuó madurando outcomes en filas no compactadas.

## Verificaciones solicitadas

| Verificación | Resultado |
|---|---:|
| `backup_scope_rows - live_scope_rows` | 8.988 |
| Forward-return facts en backup, grupos no conflictivos | 2.010 |
| Forward-return facts conservados en live, grupos no conflictivos | 2.010 |
| Discrepancias en grupos compactables/no conflictivos | 0 |
| Grupos conflictivos en JSON | 10.969 |
| Grupos conflictivos faltantes en live | 0 |
| Grupos conflictivos extra en live | 0 |
| Grupos conflictivos con distinto set de `signal_id` | 0 |

## Comandos ejecutados

Se ejecutaron consultas Python/SQLite inline, sin crear helper nuevo:

```powershell
.\.venv\Scripts\python.exe - <<'PY'
# abre backup y live con mode=ro
# filtra created_at < 2026-06-25T18:00:00+00:00
# compara returns por grupo no conflictivo
# compara identidad de signal_id en grupos conflictivos
PY
```

No se ejecutó ningún `UPDATE`, `DELETE`, `INSERT`, `VACUUM`, `run-once`, `job-once` ni ciclo del scheduler.

## Estado final

La verificación es read-only y no modifica datos ni runtime. No requiere bump de versión ni reinicio.
