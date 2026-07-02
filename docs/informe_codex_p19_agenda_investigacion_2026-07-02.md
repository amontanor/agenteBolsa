# Informe Codex P19 - Agenda de investigacion y KPIs

## Objetivo

Medir la salud de investigacion por estudios ejecutados e hipotesis cerradas, no
por actividad bruta. La entrega agrega persistencia simple, CLI y seccion nueva en
el digest diario.

## Cambios entregados

- Persistencia JSON: `data/research/research_agenda.json`.
- Modulo: `src/agente_bolsa/continuous_improvement/research_agenda.py`.
- CLI:
  - `research-agenda list --json`
  - `research-agenda add --title ... --target-date ... --json`
  - `research-agenda close --id ... --status matada|promovida --json`
- Digest:
  - Nueva seccion `KPIs de investigacion`.
  - Nueva seccion `Agenda de investigacion`.
- Tests:
  - `tests/test_research_agenda.py`.
  - Cobertura sintetica en `tests/test_ci_phase3_digest.py`.
- Version subida a `0.4.100`.

No se tocaron archivos protegidos del suelo de kernel.

## Agenda sembrada

| Hipotesis | Estado | Fecha objetivo |
|---|---|---|
| pullback | pendiente | 2026-07-06 |
| horizonte salida 5-10d | matada | 2026-07-02 |
| telegram radar | pendiente | 2026-07-20 |
| overlay activacion | en_curso | 2026-07-05 |
| anomalia ORCL | pendiente | 2026-07-02 |

## KPIs

Definicion implementada:

- `estudios_ejecutados/semana`: experimentos de mejora continua creados desde el
  lunes UTC de la semana actual.
- `hipotesis_matadas/semana`: filas de agenda con `status=matada` y `closed_at`
  dentro de la semana actual.
- `hipotesis_promovidas/semana`: filas con `status=promovida` y `closed_at` dentro
  de la semana actual.

## Ejecucion real

Listado de agenda real:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main research-agenda list --json
```

Resultado: `ok=true`, 5 hipotesis cargadas desde
`data/research/research_agenda.json`.

Smoke add/close en ruta temporal:

```powershell
$tmp='data\research\research_agenda_cli_smoke.json'
$add = .\.venv\Scripts\python.exe -m agente_bolsa.main research-agenda add --path $tmp --title 'smoke hypothesis' --target-date 2026-07-10 --json | ConvertFrom-Json
$id = $add.item.hypothesis_id
.\.venv\Scripts\python.exe -m agente_bolsa.main research-agenda close --path $tmp --id $id --status matada --notes 'smoke closed' --json
Remove-Item $tmp
```

Resultado: `ok=true`, item cerrado como `matada`.

Digest:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days 7 --json
```

Resultado relevante:

```json
{
  "research_agenda": {
    "kpis": {
      "week_start": "2026-06-29",
      "estudios_ejecutados_semana": 194,
      "hipotesis_matadas_semana": 1,
      "hipotesis_promovidas_semana": 0
    }
  }
}
```

Salida humana verificada con `Select-String`: aparecen `KPIs de investigacion`,
`Agenda de investigacion`, `anomalia ORCL` y `horizonte salida 5-10d`.

## Verificacion

- Focales:
  `.\.venv\Scripts\python.exe -m pytest tests\test_research_agenda.py tests\test_ci_phase3_digest.py -q`:
  `13 passed`.
- Suite completa: `.\.venv\Scripts\python.exe -m pytest tests\ -x -q`:
  `911 passed, 1 warning`.
- Lint: `.\.venv\Scripts\ruff.exe check src tests scripts`: limpio.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: `trading_mode=paper`,
  `allow_live_trading=false`.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`:
  `ok=true`.
- Flags efectivos: `allow_auto_apply_improvements=false`.
- `data/config/core_sleeve.json`: `dry_run=true`.
- `data/config/lab_book.json`: `enabled=false`, `mode=log_only`.
- Smoke real:
  `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`.
  Resultado: ciclo `20260702-222506`, `used_crew=false`, `market_state_quality=PARTIAL`,
  sin envio automatico de ordenes.
