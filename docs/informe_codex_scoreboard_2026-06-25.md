# Informe Codex scoreboard shadow 2026-06-25

## Objetivo

Agregar una vista read-only para vigilar a diario si `builtin_pullback` sigue generando candidatos SHADOW sanos mientras maduran los outcomes.

## Implementacion

Se extendio `cycle-funnel` con el flag:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel --shadow-scoreboard --history 5
.\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel --shadow-scoreboard --history 5 --json
```

Fuente de datos:

- Reutiliza los reportes `closed_market_technical_study_*.json` que ya usa el funnel tecnico.
- Excluye `latest_closed_market_technical_study.json` y `*.manifest.json`.
- No lee ni escribe tablas de trading. No modifica BD, decisiones, ordenes, gates ni estrategias.

Metricas por reporte y estrategia:

- `shadow_candidates`: recuento.
- `distance_sma20`: min, q1, mediana, q3, max.
- `rsi_14`: min, q1, mediana, q3, max.

La tabla compacta muestra min/mediana/max para lectura diaria rapida.

## Salida real de ejemplo

Comando:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel --shadow-scoreboard --history 5
```

Salida:

```text
SHADOW SCOREBOARD  ultimos 5 reportes tecnicos
------------------------------------------------------------------------------------------------------------
run_id            strategy                n  dist min  dist p50  dist max  rsi min  rsi p50  rsi max
mkt_9fa6afa3936c  builtin_pullback       42     -4.5%      0.7%      7.9%     40.4     53.0     58.6
mkt_e85fb8660582  builtin_pullback       42     -4.5%      0.7%      7.9%     40.4     53.0     58.6
mkt_9d9c5ea275a1  builtin_pullback       42     -4.5%      0.7%      7.9%     40.4     53.0     58.6
mkt_74d3b49d9339  builtin_pullback       42     -4.5%      0.7%      7.9%     40.4     53.0     58.6
opp_422d264d7f88  builtin_pullback       42     -4.5%      0.7%      7.9%     40.4     53.0     58.6
```

Lectura actual:

- `builtin_pullback` sigue produciendo 42 candidatos por reporte.
- La extension esta dentro del rango esperado: mediana ~0.7% sobre SMA20 y max ~7.9%.
- RSI mediano ~53, dentro del rango constructivo definido para pullbacks.
- No hay senal de degradacion del generador en los ultimos 5 reportes.

## Test

Se agrego cobertura en `tests/test_cycle_funnel.py`:

- Agrupa candidatos SHADOW por `strategy_name`.
- Valida recuento por estrategia.
- Valida cuartiles de `distance_sma20` y `rsi_14`.
- Valida formato textual del scoreboard.

## Validacion

- `py_compile`: OK para `cycle_funnel.py`, `main.py`, `tests/test_cycle_funnel.py` y `__init__.py`.
- Test focalizado: `tests/test_cycle_funnel.py` -> `4 passed`.
- `ruff check src tests scripts/study_strategy_edge_compare.py`: OK.
- Suite completa: `760 passed in 154.04s`.
- JSON smoke: `cycle-funnel --shadow-scoreboard --history 2 --json` devuelve 2 reportes con `builtin_pullback`, 42 candidatos cada uno y cuartiles correctos.

## Notas

Durante la primera prueba real aparecieron filas `(sin shadow)` porque el glob incluia `*.manifest.json`. Se corrigio excluyendo manifests para que el scoreboard lea solo reportes tecnicos reales.

No requiere restart ni kernel-seal: es CLI read-only y no cambia el runtime persistente.
