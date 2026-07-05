# Informe Codex - Core sleeve hardening pre-activacion

Fecha: 2026-07-05
Version: 0.4.113
Commit previsto: `Manga: hardening pre-activacion + automatizacion diaria + informe de paridad`

## Alcance

- Modulo operativo: `src/agente_bolsa/strategies/core_sleeve.py`.
- Scripts: `scripts/run_core_sleeve_daily.ps1`, `scripts/run_core_sleeve_supervisor.ps1`.
- Tests: `tests/test_core_sleeve.py`.
- No se tocaron bloqueados: `kernel.py`, `broker.py`, `execution.py`, `risk.py`, `config.py`, `.env`.
- No se cambio la semantica de `enabled`/`dry_run` ni la matematica del vol-target.
- No se arranco ni reinicio ningun proceso.

## Guardas anadidas

- Idempotencia real por `data_date`:
  - `client_order_id` estable: `core-sleeve-YYYYMMDD`.
  - reserva atomica local antes del submit real: `core_sleeve_rebalance_YYYYMMDD.lock`.
  - una segunda ejecucion el mismo dia devuelve `already_rebalanced_today` y no llama al submitter.
- Tope duro de notional:
  - knob por entorno `CORE_SLEEVE_MAX_ORDER_NOTIONAL`.
  - default finito: `50000`.
  - el notional queda topado ademas del limite por fraccion de manga.
- Guardas de no envio:
  - `enabled=false`: no carga portfolio ni envia.
  - `dry_run=true`: registra `would_submit`, no envia.
  - mercado cerrado: `market_closed`, no envia.
  - equity/precio ausente: no genera orden.
- Preview:
  - CLI: `python -m agente_bolsa.strategies.core_sleeve --json --preview`.
  - muestra `side`, `notional`, `qty`, exposicion y decision sin enviar orden.

## Automatizacion diaria

El one-shot `scripts/run_core_sleeve_daily.ps1` ejecuta:

1. `python -m agente_bolsa.strategies.core_sleeve --json`
2. `scripts/core_sleeve_parity_check.py`
3. guarda el informe humano en `data/research/core_sleeve/parity_<fecha>.md`

El supervisor `scripts/run_core_sleeve_supervisor.ps1` queda con `RunAt=22:15` por
defecto. Respeta `data/config/core_sleeve.json`: no fuerza live ni cambia
`dry_run`.

Arranque manual para Antonio, sin admin:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_core_sleeve_supervisor.ps1
```

Preview de pre-vuelo:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.strategies.core_sleeve --config data\config\core_sleeve.json --log-dir data\research\core_sleeve --json --preview
```

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests/test_core_sleeve.py tests/test_core_sleeve_parity_check.py -q`: `14 passed`.
- `.\.venv\Scripts\python.exe -m pytest tests/ -x -q`: `975 passed, 1 warning`.
- `.\.venv\Scripts\python.exe -m ruff check src tests`: limpio.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: `trading_mode=paper`, `allow_live_trading=false`.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`: `ok=true`.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`: sin traceback; no envia ordenes.
- Diff de bloqueados: vacio.
