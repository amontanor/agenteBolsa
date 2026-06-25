# Informe Codex 2026-06-25

## Resumen

Se reviso `builtin_pullback` en SHADOW, se confirmo que genera candidatos no extendidos y se corrigio el tracking para que `shadow_candidates` entren en `signal_outcomes` sin pasar por decision/ejecucion. Tambien se implemento T6 para nuevas escrituras: dedup por fuente+dia+estrategia+simbolo con UPSERT y preservacion de outcomes ya calculados.

La conducta de trading no cambia: `builtin_breakout` sigue ACTIVE, `builtin_pullback` sigue SHADOW, `ALLOW_LIVE_TRADING=false` y no se tocaron `risk.py`, `kernel.py`, `broker.py`, `execution.py`, `config.py` ni `.env`.

## Tarea 1 - Diagnostico de `builtin_pullback`

Fuente: `data/reports/latest_closed_market_technical_study.json`.

- `run_id`: `mkt_791afa5080c0`
- `as_of`: `2026-06-25T16:47:56.672502+00:00`
- `all_candidates`: 496, estrategia `builtin_breakout`
- `shadow_candidates`: 42, estrategia `builtin_pullback`

`builtin_pullback` no esta vacio. El filtro no parece demasiado estricto para el mercado de hoy: encuentra 42 pullbacks con distancia a SMA20 entre -4.55% y +7.93%, RSI 40.35-58.59 y tendencia 60d positiva. No propongo relajar el filtro ahora; la conclusion operativa sigue siendo medir varios dias/regimenes antes de tocar thresholds.

| symbol | distance_sma20 | rsi_14 | return_5d | return_20d | return_60d | score |
|---|---:|---:|---:|---:|---:|---:|
| ADI | 0.0105 | 47.78 | 0.0159 | 0.0128 | 0.3930 | 9 |
| ALGN | 0.0163 | 55.56 | 0.0122 | 0.0783 | 0.0564 | 12 |
| AMD | 0.0153 | 49.42 | 0.0134 | 0.0481 | 1.6493 | 12 |
| ANET | 0.0264 | 51.45 | 0.0186 | 0.0887 | 0.4467 | 14 |
| BEN | 0.0345 | 58.45 | -0.0030 | 0.0480 | 0.4699 | 13 |
| BNY | 0.0250 | 54.53 | 0.0042 | 0.0497 | 0.2786 | 10 |
| CCL | 0.0205 | 54.93 | -0.0271 | 0.0400 | 0.2220 | 11 |
| CHRW | -0.0216 | 45.81 | -0.0277 | 0.0238 | 0.1159 | 12 |
| CI | -0.0009 | 53.72 | -0.0023 | 0.0011 | 0.1085 | 13 |
| CMI | 0.0540 | 57.91 | -0.0029 | 0.0716 | 0.4030 | 13 |
| CPAY | -0.0282 | 40.35 | -0.0314 | -0.0294 | 0.1787 | 12 |
| CRWD | -0.0158 | 40.39 | -0.0008 | 0.0575 | 0.7956 | 12 |
| DELL | -0.0016 | 45.86 | -0.0303 | 0.3318 | 1.4772 | 14 |
| DXCM | -0.0455 | 42.66 | -0.0208 | -0.0073 | 0.1267 | 10 |
| EMR | 0.0079 | 53.16 | -0.0299 | 0.0346 | 0.1771 | 12 |
| EQIX | 0.0030 | 47.11 | -0.0089 | 0.0081 | 0.1246 | 11 |
| EXPD | -0.0014 | 52.92 | 0.0058 | 0.0054 | 0.1477 | 10 |
| EXR | -0.0008 | 51.39 | 0.0062 | 0.0135 | 0.1411 | 10 |
| FDX | -0.0040 | 50.23 | 0.0074 | -0.0104 | 0.1923 | 12 |
| FTV | 0.0128 | 49.31 | 0.0106 | 0.0236 | 0.1437 | 10 |
| GD | -0.0054 | 53.03 | -0.0454 | 0.0107 | 0.0211 | 9 |
| GM | -0.0197 | 42.27 | 0.0046 | -0.0476 | 0.1011 | 9 |
| GS | 0.0278 | 49.57 | -0.0079 | 0.0991 | 0.3561 | 14 |
| HLT | 0.0071 | 57.77 | -0.0166 | 0.0201 | 0.1615 | 9 |
| HST | 0.0141 | 53.27 | 0.0022 | 0.0509 | 0.3153 | 12 |
| IFF | 0.0031 | 58.05 | -0.0024 | -0.0147 | 0.0692 | 9 |
| JBL | 0.0198 | 52.03 | 0.0085 | 0.0183 | 0.5284 | 11 |
| JCI | 0.0156 | 47.64 | 0.0100 | 0.0525 | 0.1491 | 14 |
| MAR | -0.0195 | 46.35 | -0.0356 | -0.0137 | 0.1942 | 12 |
| MCHP | 0.0012 | 48.55 | 0.0065 | -0.0219 | 0.5851 | 12 |
| MET | 0.0064 | 57.07 | -0.0017 | 0.0300 | 0.2649 | 10 |
| MGM | -0.0001 | 44.41 | 0.0066 | 0.1263 | 0.3265 | 13 |
| MRVL | 0.0014 | 42.38 | -0.0494 | 0.3852 | 2.1361 | 13 |
| MS | 0.0386 | 56.23 | -0.0032 | 0.1122 | 0.4235 | 15 |
| NTRS | 0.0327 | 57.04 | 0.0116 | 0.0588 | 0.3052 | 12 |
| PFG | -0.0067 | 57.28 | -0.0351 | 0.0251 | 0.2150 | 10 |
| PM | 0.0033 | 55.02 | -0.0027 | -0.0169 | 0.0857 | 13 |
| RTX | 0.0288 | 58.20 | -0.0292 | 0.0587 | 0.0031 | 12 |
| STX | 0.0793 | 58.59 | -0.0383 | 0.1776 | 1.8289 | 15 |
| TJX | -0.0082 | 54.41 | -0.0216 | 0.0228 | 0.0342 | 11 |
| TPR | 0.0090 | 57.34 | 0.0000 | 0.0537 | 0.0684 | 14 |
| TROW | 0.0192 | 57.75 | -0.0036 | 0.0433 | 0.2246 | 12 |

### Tracking de shadow

Antes del cambio, `signal_outcomes` tenia 0 filas con `builtin_pullback`: `record_signal_candidates` solo leia `all_candidates`, no `shadow_candidates`, y `_signal_features` no persistia `strategy_name`.

Cambio aplicado:

- `record_signal_candidates` ahora procesa `all_candidates` + `shadow_candidates`.
- Las features guardan `strategy_name`, `strategy_version`, `strategy_status` y `shadow_candidate`.
- Las filas SHADOW usan `source_run_id = "<run_id>:shadow"`, para que `update_signal_decisions` y `update_signal_execution_status` no las actualicen por accidente.

Verificacion en BD real tras registrar el ultimo reporte con la nueva ruta:

- `record_signal_candidates(...)`: 538 filas procesadas (496 active + 42 shadow).
- Filas `builtin_pullback` en `signal_outcomes`: 42.
- Ejemplo: `closed_market_study:2026-06-25:BUILTIN_PULLBACK:ADI | mkt_791afa5080c0:shadow | ADI | 2026-06-25`.

## Tarea 2 - T6 dedup de `signal_outcomes`

Problema inicial medido con `scripts/study_signal_duplication.py`:

- filas totales: 320179
- combinaciones `(simbolo, dia)`: 11970
- duplicate_ratio real: 96.3%
- filas por simbolo-dia media: 26.75, max: 71
- rango: 2026-05-11 -> 2026-06-25

Implementacion:

- `signal_id` estable para nuevas escrituras: `<source>:<signal_date>:<strategy_name>:<symbol>`.
- Uso de UPSERT sobre `signal_id`.
- En conflicto, `source_run_id` se actualiza al ciclo mas reciente para que decision/ejecucion del ciclo actual sigan encontrando la fila activa.
- En conflicto, `outcome_json` se preserva si la nueva escritura trae `{}`; asi un backfill o nuevo scan no borra outcomes ya calculados.
- Se incluye `strategy_name` en la clave para evitar que una estrategia SHADOW machaque una ACTIVE del mismo simbolo-dia. Es una desviacion intencional del "solo simbolo-dia": sin estrategia en la clave no se podria medir pullback vs breakout cuando coinciden en simbolo.
- Las filas SHADOW quedan fuera de decision/ejecucion por `source_run_id` con sufijo `:shadow`.

Verificacion despues de aplicar y registrar el ultimo reporte:

- filas totales: 320717
- combinaciones `(simbolo, dia)`: 11970
- duplicate_ratio real: 96.3%
- filas por simbolo-dia media: 26.79, max: 71

Lectura: el script global no baja porque no se hizo compactacion historica; conserva las 320k filas antiguas. La mejora aplica a nuevas escrituras. Una migracion historica seria otra tarea y debe hacerse con cuidado para no perder outcomes, gates ni decisiones ya atribuidas.

Tests obligatorios:

- Mismo simbolo/estrategia/dia grabado en dos ciclos -> 1 fila.
- La fila deduplicada sigue aceptando `update_signal_decisions` con el `source_run_id` mas reciente.
- `update_signal_outcomes` sigue calculando forward returns para la fila deduplicada.
- `shadow_candidates` se guardan con `source_run_id=:shadow` y `selected_for_llm=false`.

## Comandos ejecutados

- `git status --short`
- `Get-Content .agents/skills/buenas-practicas/SKILL.md`
- `Get-Content .agents/skills/start-agente-bolsa/SKILL.md`
- `Get-Content docs/tutorial_arranque_diario.md`
- `Get-Content docs/plan_mejoras_y_tareas.md`
- `Get-Content docs/plan_desbloqueo_embudo_2026-06-25.md`
- `Get-Content src/agente_bolsa/tools/signal_learning.py`
- `Get-Content src/agente_bolsa/storage.py`
- `Get-Content tests/test_signal_learning.py`
- `Get-Content scripts/study_signal_duplication.py`
- `.\.venv\Scripts\python.exe scripts\study_signal_duplication.py`
- `.\.venv\Scripts\python.exe -m py_compile src\agente_bolsa\tools\signal_learning.py src\agente_bolsa\storage.py tests\test_signal_learning.py`
- `.\.venv\Scripts\python.exe -m pytest tests\test_signal_learning.py -q -p no:warnings`
- `.\.venv\Scripts\python.exe -m pytest tests\test_signal_learning.py tests\test_builtin_pullback.py tests\test_strategy_registry.py -q -p no:warnings`
- `.\.venv\Scripts\python.exe -m ruff check src tests`
- `.\.venv\Scripts\python.exe -m pytest -q -p no:warnings`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health --json`
- `powershell -ExecutionPolicy Bypass -File scripts\restart_services.ps1`
- `powershell -ExecutionPolicy Bypass -File scripts\check_services.ps1`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main strategy-registry --list-registry --json`
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`

## Validacion final

- `py_compile`: OK para `signal_learning.py`, `storage.py` y tests tocados.
- Conteo post-edicion: `signal_learning.py` 960 lineas; `storage.py` 4302 lineas.
- Tests focalizados: `33 passed`.
- Suite completa: `756 passed in 166.82s`.
- `ruff check src tests`: OK.
- `status`: `trading_mode=paper`, `allow_live_trading=false`.
- `kernel-status --json`: `ok=true`, `violations=[]`.
- Broker Alpaca paper activo; portfolio sin posiciones ni ordenes abiertas.
- `strategy-registry`: `builtin_breakout=ACTIVE`, `builtin_pullback=SHADOW`.
- Reinicio: `scripts/restart_services.ps1` completo; verificacion posterior con 1 scheduler logico y panel HTTP 200.
- `operational-health`: warning sin criticos. Avisos presentes: `job_slow` del ultimo ciclo, deterioro de `confirmed_pattern`/`baseline_trend`, y backlog CI.
- `validate-agent-config --json`: comando no existe en el parser actual; la guia esta desactualizada en ese punto.

## Hallazgos

- `builtin_pullback` si genera candidatos hoy: 42. El problema no era generacion, era tracking.
- La medicion historica sigue contaminada por duplicados. Los estudios nuevos iran limpios desde v0.4.51; el historico requiere migracion separada si se quiere compactar.
- No se relajo el gate de extension, no se promociono `builtin_pullback`, no se toco `§1` ni ninguna ruta de ejecucion/riesgo.
