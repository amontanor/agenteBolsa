# Informe Codex PL8A - kill switch con frescura de kernel - 2026-07-08

## Problema

`data/state/operational_kill_switch.json` podia quedar activo por una violacion `kernel_integrity` de una sesion anterior y seguir bloqueando compras al dia siguiente aunque el operador ya hubiera re-sellado el kernel y `kernel-status` devolviera `ok`.

## Cambio aplicado

- `src/agente_bolsa/tools/operational_health.py`
  - Nuevo helper `clear_kernel_integrity_override_if_recovered(...)`.
  - Si el override persistente viene de `kernel_integrity_violation`, se revalida la integridad actual antes de bloquear.
  - Si el kernel ya verifica `ok`, el override se elimina, se deja traza en `data/logs/system.jsonl` con `event_type=kernel_integrity_override_cleared` y `load_operational_block_context(...)` deja de bloquear.
- `src/agente_bolsa/main.py`
  - `kernel-seal` ahora intenta limpiar automaticamente ese override tras regenerar el manifest.
  - En salida JSON devuelve `kill_switch_cleanup` con el resultado de la limpieza.

## Tests

- `tests/test_operational_health.py`
  - Verifica que `load_operational_block_context(...)` autocaduca el override si el kernel ya esta recuperado.
- `tests/test_kernel.py`
  - Verifica que `command_kernel_seal(...)` limpia el override de `kernel_integrity` tras re-sellar.

## Verificacion dirigida

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operational_health.py tests/test_kernel.py -x -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

Resultado:

- `20 passed`
- `ruff check src tests`: OK
