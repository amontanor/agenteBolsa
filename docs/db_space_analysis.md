# Análisis del crecimiento de la base de datos de estado

**Fecha inicial:** 17-jun-2026 · **Actualizado:** 20-jun-2026

## Resultado aplicado

La medición definitiva encontró que el consumidor dominante no era
`signal_outcomes`, sino `continuous_improvement_cycles`: 783 ciclos guardaban
una copia completa del contexto y del informe en cada ejecución, con medias de
7,3 MB y 3,5 MB respectivamente. La tabla ocupaba **8,49 GB**.

Se implantó compactación persistente con referencias a las tablas normalizadas,
se migraron los 783 ciclos, se aplicó retención y se ejecutó `VACUUM` con backup
previo y servicios detenidos. Resultado verificado:

- BD: **10,2 GB → 1,74 GB** (`Estado: OK`).
- Snapshots CI: **7,9 GB → 143,5 MB**.
- Filas caducadas retiradas: **50.594**.
- `PRAGMA quick_check`: **ok**; 783 ciclos conservados.
- Snapshot histórico máximo tras migración: **331 KB**.
- Backup previo: `data/backups/agente_bolsa-before-maintenance-20260620-002908.sqlite3`.

El código de persistencia compacta también los ciclos nuevos, por lo que se
corrige la causa raíz. El mantenimiento semanal queda preparado mediante
`scripts/install_db_maintenance_task.ps1`; su registro requiere ejecutar ese
script desde PowerShell elevado por UAC.

## Diagnóstico inicial (histórico)

**BD:** `data/state/agente_bolsa.sqlite3` · **Tamaño observado:** ~8.2 GB (estado **DOWN**, umbral OK < 3 GB)

## Resumen ejecutivo

La base de datos crece sin freno porque **nada borra filas de ella**. El módulo
`retention.py` solo limpia ficheros de disco (informes, logs, cache); las tablas
de SQLite acumulan indefinidamente. El consumidor dominante es `signal_outcomes`.
El espacio **no es fragmentación pura** (el freelist es ~9 MB, despreciable): es
volumen real de datos, más un ~35-40% de páginas medio vacías por los UPDATE
repetidos sobre `signal_outcomes`.

Conclusión práctica: **un VACUUM por sí solo no basta** para bajar de 3 GB.
Hace falta combinar retención + VACUUM + (para que sea sostenible) reducir el
tamaño por fila de `signal_outcomes`.

## Qué ocupa el espacio (medido sobre una copia)

| Tabla | Filas | Tamaño | Notas |
|---|---|---|---|
| **signal_outcomes** | ≥ 200k (varios GB) | **el grueso del fichero** | 3 columnas JSON, ~1.6 KB/fila. Upsert por señal cada ciclo → re-escritura → 61% de llenado de página (≈39% desperdiciado). Desde 28-abr. |
| learning_observations | 29.094 | 185 MB | 76% lleno. May-09 → Jun-16. |
| continuous_improvement_decisions | 23.990 | 102 MB | ~1.500 filas/día (16 días). |
| agent_events | 88.014 | ≥ 66 MB | `payload_json` por evento y ciclo. |
| continuous_improvement_cycles / llm_responses | 660 / 653 | volcados LLM grandes | El "laboratorio" corre cada ~1.3 min. |
| Resto (operativa, estrategias, etc.) | — | < 50 MB total | No es el problema; **no se tocan**. |

Datos de la cabecera: `page_size=4096`, `page_count≈2.0M`, `freelist≈2.260
páginas (~9 MB)`, `auto_vacuum=NONE`, modo WAL.

## Causa raíz

1. **Sin retención en la BD.** `retention.py` no ejecuta ningún `DELETE` sobre
   SQLite. Existía `scripts/db_maintenance.py` (16-jun) pero no estaba
   programado ni se había aplicado, y su corte por defecto (120 días) no borra
   nada porque los datos solo tienen ~50 días.
2. **`signal_outcomes` escribe mucho y pesado.** ~1.6 KB de JSON por fila,
   reescrita con cada maduración del outcome → ~90 MB/día estimados.
3. **`auto_vacuum=NONE`.** El espacio liberado por borrados no vuelve al SO sin
   un VACUUM completo (lock exclusivo, costoso).

## Solución propuesta (3 capas)

### Capa 1 — Operativa inmediata (en ventana de mantenimiento, mercado cerrado)

Con el scheduler parado, el wrapper `scripts/run_db_maintenance.ps1` hace todo
de forma segura (para → mantiene → arranca):

```powershell
# 1) ver qué se borraría (seguro, no para el scheduler)
powershell -ExecutionPolicy Bypass -File scripts\run_db_maintenance.ps1 -Mode dryrun

# 2) one-time: pasar a auto_vacuum incremental (para que futuros borrados liberen espacio)
powershell -ExecutionPolicy Bypass -File scripts\run_db_maintenance.ps1 -Mode autovac

# 3) borrar filas antiguas (retención por tabla: signal_outcomes 45d, ...) + VACUUM completo
powershell -ExecutionPolicy Bypass -File scripts\run_db_maintenance.ps1 -Mode apply
```

Efecto esperado: el VACUUM recupera el ~35-40% de páginas medio vacías
(≈8.2 GB → ~5 GB) y el borrado >45 días reduce algo más. **Sale de DOWN, pero
probablemente queda en zona WARN (~4-5 GB)**, porque con 45-60 días de retención
y el tamaño de fila actual, `signal_outcomes` por sí solo ronda los 3-4 GB.

### Capa 2 — Automatización recurrente

Programar el mantenimiento semanal (domingos 03:00, mercado cerrado). El bloque
de registro está al final de `run_db_maintenance.ps1`:

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"C:\Antonio\Bref\agenteBolsa\scripts\run_db_maintenance.ps1`" -Mode apply"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am
Register-ScheduledTask -TaskName "AgenteBolsaDBMaintenance" -Action $action -Trigger $trigger `
    -Description "Retención + VACUUM semanal de la BD de estado."
```

### Capa 3 — Estructural: que 45-60 días quepan cómodos bajo 3 GB

Para que la retención de 45-60 días sea sostenible por debajo de 3 GB sin
acortar el histórico, hay que reducir lo que pesa `signal_outcomes`. Tres
opciones (de menor a mayor cambio de código):

- **(A) Comprimir los JSON de `signal_outcomes`.** Medido sobre filas reales:
  **~54% de reducción** (1.6 KB → ~0.74 KB por fila). Mecánico, sin pérdida de
  información. Patch retrocompatible (las filas antiguas en JSON plano se siguen
  leyendo) — ver abajo. Combinado con la Capa 1, deja la BD en ~2-2.5 GB y la
  mantiene ahí.
- **(B) Retención más corta solo para `signal_outcomes`** (p. ej. 30 días).
  Cero cambios de código: basta editar `DEFAULT_RETENTION` en
  `db_maintenance.py`. Reduce el histórico de señales disponible para análisis.
- **(C) Recortar campos de `features_json`** (813 B/fila de media). Mayor ahorro,
  pero requiere revisar qué features son imprescindibles para el aprendizaje.

**Recomendación:** Capa 1 + Capa 2 ya + **opción (A)** para el objetivo cómodo
< 3 GB conservando 45-60 días.

#### Patch retrocompatible de compresión (opción A) — `src/agente_bolsa/storage.py`

Helpers (codifican comprimido como texto con prefijo `z:`; el resto se lee como
JSON normal, así no hace falta migrar nada):

```python
import base64, zlib, json

_ZPREFIX = "z:"

def _dumps_z(obj) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _ZPREFIX + base64.b85encode(zlib.compress(raw, 6)).decode("ascii")

def _loads_z(text: str):
    if text is None:
        return None
    if text.startswith(_ZPREFIX):
        return json.loads(zlib.decompress(base64.b85decode(text[len(_ZPREFIX):])))
    return json.loads(text)   # filas antiguas en JSON plano
```

En `save_signal_outcome` / `save_signal_outcomes_bulk`: sustituir `_dumps(...)`
por `_dumps_z(...)` para `features`, `gate` y `outcome`. En toda lectura de esas
columnas, usar `_loads_z(...)`. (Opcional: un script de migración que recodifique
las filas existentes para liberar espacio de inmediato, no solo el dato nuevo.)

## Objetivo "cómodo" y alarma

- **Steady-state objetivo: ~2 GB.** Con Capa 1+2+A se alcanza y se mantiene.
- El panel ya avisa: OK < 3 GB, WARN 3-8 GB, DOWN ≥ 8 GB
  (`system_status.py`). Con el mantenimiento semanal no debería volver a WARN.

## Notas de seguridad

- No se modificó la BD en producción: el mercado está abierto y VACUUM exige
  lock exclusivo. Todo está preparado para ejecutarlo tú en una ventana con el
  mercado cerrado.
- El mantenimiento **no toca** tablas de operativa (órdenes, planes,
  estrategias, estado): solo tablas tipo log/aprendizaje.
- Antes del primer `--apply`, conviene una copia: `copy data\state\agente_bolsa.sqlite3 backup\`.
