# Informe Codex PL8C - digest safety con market_cycle y kill switch - 2026-07-08

## Problema

El bloque `Safety` del digest no enseñaba dos señales operativas críticas en la sesión real:

- la frescura del último `market_cycle`
- si el `kill_switch` seguía activo y desde cuándo

Así, una mañana sin ciclos recientes o con bloqueo operativo podía parecer sana.

## Cambio aplicado

- `src/agente_bolsa/continuous_improvement/digest.py`
  - `build_lab_digest(...)` ahora enriquece `safety` con:
    - `market_cycle`: estado, detalle y antigüedad del último runtime `scheduler_job_status:market_cycle`
    - `kill_switch`: activo/inactivo, motivo y antigüedad
  - El render de `Safety` ahora añade dos líneas:
    - `ultimo market_cycle: ...`
    - `kill_switch: ...`
  - Si no hay registro de `market_cycle` o el `kill_switch` está activo, la cabecera sube a `Safety: ALERTA`.
- `src/agente_bolsa/__init__.py`
  - Versión `0.4.129 -> 0.4.130`.

## Tests

- `tests/test_ci_phase3_digest.py`
  - Verifica que el digest muestra la frescura del `market_cycle` y del `kill_switch`.
  - Verifica que un `kill_switch` activo y ausencia de ciclos hacen gritar el Safety.
- `tests/test_config_audit.py`
  - Ajusta expectativas del render para el nuevo bloque Safety enriquecido.

## Verificacion dirigida

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ci_phase3_digest.py tests/test_config_audit.py -x -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

Resultado:

- `22 passed`
- `ruff check src tests`: OK
