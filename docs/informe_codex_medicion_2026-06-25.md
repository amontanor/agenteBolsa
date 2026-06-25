# Informe Codex medicion 2026-06-25

## Objetivo

Se creo una herramienta read-only para comparar la expectativa forward de `builtin_pullback` (SHADOW) frente a `builtin_breakout` (ACTIVE) usando `signal_outcomes`, lista para usar cuando maduren los outcomes de los proximos dias.

No cambia conducta de runtime, decision, riesgo ni ejecucion. No se tocaron `risk.py`, `kernel.py`, `tools/broker.py`, `tools/execution.py`, `config.py` ni `.env`.

## Esquema real encontrado

Fuente: `src/agente_bolsa/storage.py`.

Tabla `signal_outcomes`:

| columna | uso en la herramienta |
|---|---|
| `signal_id` | identificador, no usado para agrupar |
| `source_run_id` | reportado/diagnostico; SHADOW usa sufijo `:shadow` desde v0.4.51 |
| `source` | origen del scan |
| `symbol` | parte de la clave de dedup |
| `signal_date` | parte de la clave de dedup y filtro `--since` |
| `decision` | no usado para edge por estrategia |
| `features_json` | contiene `strategy_name`, `strategy_version`, `strategy_status`, `shadow_candidate` |
| `gate_json` | no usado |
| `outcome_json` | contiene `return_1d`, `return_3d`, `return_5d`, `return_10d` y estado de madurez |
| `created_at` | desempate secundario |
| `updated_at` | se usa para quedarse con la fila mas reciente al deduplicar |

Conclusion importante: `strategy_name`, `strategy_status` y `shadow_candidate` no son columnas fisicas; viven dentro de `features_json`. Los forward returns viven dentro de `outcome_json`.

## Herramienta creada

Archivo: `scripts/study_strategy_edge_compare.py`.

CLI:

```powershell
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 10
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --strategies builtin_pullback,builtin_breakout --db data\state\agente_bolsa.sqlite3
```

Diseno:

- Abre SQLite con `sqlite_connect_ro(... mode=ro)` y `PRAGMA query_only=ON`.
- Lee solo `signal_outcomes`.
- Deduplica por `(signal_date, symbol, strategy_name)`.
- Conserva la fila mas reciente por `updated_at`.
- Calcula por estrategia y horizonte: `n`, media, mediana, hit-rate, std, media neta de costes y coverage.
- Coste round-trip configurable con `--cost-bps`, default `10`.
- Calcula delta `builtin_pullback - builtin_breakout` por horizonte.
- Gestiona outcomes nulos o pendientes sin fallar.

Decision de diseno: la deduplicacion incluye `strategy_name`. Si se deduplicara solo por simbolo-dia, una estrategia podria pisar a otra y no se podria comparar pullback vs breakout cuando coinciden en el mismo simbolo.

## Salida actual de ejemplo

Comando:

```powershell
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 10
```

Salida:

```text
=== Strategy edge compare (read-only) ===
since=2026-06-25 | strategies=builtin_pullback, builtin_breakout | cost_bps=10.0
filas deduplicadas estrategia-simbolo-dia: 538

Caveat: no concluir con pocas muestras, horizons inmaduros o un unico regimen de mercado.

strategy          horizon        n  pending  coverage      mean    median     hit      std   mean_net
builtin_pullback  return_1d      0       42     0.00%       n/d       n/d     n/d      n/d        n/d
builtin_pullback  return_3d      0       42     0.00%       n/d       n/d     n/d      n/d        n/d
builtin_pullback  return_5d      0       42     0.00%       n/d       n/d     n/d      n/d        n/d
builtin_pullback  return_10d     0       42     0.00%       n/d       n/d     n/d      n/d        n/d
builtin_breakout  return_1d      0      496     0.00%       n/d       n/d     n/d      n/d        n/d
builtin_breakout  return_3d      0      496     0.00%       n/d       n/d     n/d      n/d        n/d
builtin_breakout  return_5d      0      496     0.00%       n/d       n/d     n/d      n/d        n/d
builtin_breakout  return_10d     0      496     0.00%       n/d       n/d     n/d      n/d        n/d

=== Delta pullback - breakout ===
horizon     pull_n   brk_n   mean_delta   net_delta
return_1d        0       0          n/d         n/d
return_3d        0       0          n/d         n/d
return_5d        0       0          n/d         n/d
return_10d       0       0          n/d         n/d
```

Lectura actual:

- `builtin_pullback`: 42 filas deduplicadas desde `2026-06-25`.
- `builtin_breakout`: 496 filas deduplicadas desde `2026-06-25`.
- Coverage maduro actual: 0% en horizontes 1/3/5/10 dias.
- Esto es esperado: los datos limpios empiezan el 25-jun y aun no hay barras futuras suficientes.

## Tests

Archivo: `tests/test_strategy_edge_compare.py`.

Casos cubiertos:

- Dedup por `(signal_date, symbol, strategy_name)` conserva la fila mas reciente.
- Agregacion matematica valida media, mediana, hit-rate, std, media neta de costes y coverage.
- Delta `pullback - breakout` por horizonte.

## Validacion ejecutada

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\study_strategy_edge_compare.py tests\test_strategy_edge_compare.py src\agente_bolsa\__init__.py
.\.venv\Scripts\python.exe -m pytest tests\test_strategy_edge_compare.py -q -p no:warnings
.\.venv\Scripts\python.exe -m ruff check scripts\study_strategy_edge_compare.py tests\test_strategy_edge_compare.py src tests
.\.venv\Scripts\python.exe scripts\study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 10
```

Resultado parcial antes de suite completa:

- Test focalizado: `2 passed`.
- Ruff: OK.
- Script real: OK, read-only, con coverage 0% por outcomes inmaduros.
- Suite completa: `758 passed in 172.28s`.

## Caveats

- No concluir nada con `n=0` maduro.
- Cuando haya 1-3 dias, `return_1d`/`return_3d` serviran solo como lectura temprana.
- La comparacion util sera `return_5d` y `return_10d`, neta de costes, con varios dias y preferiblemente varios regimenes.
- El historico anterior a v0.4.51 sigue contaminado por duplicados; por eso el default `--since 2026-06-25` empieza en datos limpios.
- La herramienta mide edge de candidatos, no ejecuciones reales. Para decisiones de promocion hay que combinarlo con evidencia paper, slippage y checklist de promocion.

## Tarea opcional 2

No se extendio `cycle-funnel` en esta entrega. La prioridad fue dejar lista la herramienta de medicion forward read-only con tests y sin ampliar la superficie del CLI operativo.
