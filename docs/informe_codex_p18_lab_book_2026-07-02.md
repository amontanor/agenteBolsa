# Informe Codex P18 - Lab book log-only

## Diseno

Objetivo: generar muestra adicional sin sobre-operar el libro real. El lab book
no envia ordenes, no cambia sizing real y no alimenta promociones sin evidencia
OOS posterior.

Fuentes de candidatos:

- Embudo tecnico pre-gate ya existente (`closed_market_technical_study`).
- `all_candidates`: candidatos ACTIVE antes de decision/ejecucion.
- `shadow_candidates`: candidatos SHADOW que ya estaban fuera de ejecucion.

Registro:

- Tabla: `signal_outcomes`.
- Separacion: `source="lab_book"`.
- Decision: `candidate`.
- Etiquetas en `features`: `lab_book=true`, `lab_book_mode="log_only"`,
  `fixed_notional`, `hypothetical_notional`, `selected_for_llm=false`,
  `affects_real_book=false`, `promotion_eligible_without_oos=false`.
- Gate: `orders_disabled=true`, `executed_buy=false`, `affects_real_book=false`.

Sizing y limites:

- Notional fijo por trade hipotetico: `200`.
- Cap diario por defecto: `10`.
- Solo direccion `long` en esta entrega.
- Stops/takes vienen del `risk_plan`; si faltan, fallback determinista:
  `stop=-5%`, `take=+10%` sobre entrada.

Muralla:

- Unico modo implementado: `mode="log_only"`.
- `enabled=false` por defecto en `data/config/lab_book.json`.
- El runner no llama a broker ni a execution.
- Las filas maduran por el pipeline existente de `update_signal_outcomes`, igual
  que otras filas de `signal_outcomes`, pero quedan separadas por `source`.
- `lab_book.enabled` y `lab_book.mode` quedan human-gated.
- `lab_book.fixed_notional`, `lab_book.daily_cap` y `lab_book.max_universe_symbols`
  quedan en `aggressiveness_gate`; aumentar tamano/cap exige evidencia.

## Cambios entregados

- Modulo `src/agente_bolsa/tools/lab_book.py`.
- CLI `lab-book run --json`.
- Runner aislado `scripts/run_lab_book_daily.ps1`.
- Config `data/config/lab_book.json` con `enabled=false`.
- Tests `tests/test_lab_book.py`.
- Cobertura de gates en `tests/test_ci_aggressiveness_gate.py`.
- Version subida a `0.4.99`.

No se tocaron archivos protegidos del suelo de kernel.

## Ejecucion real

CLI:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main lab-book run --json
```

Resultado:

```json
{
  "ok": true,
  "status": "disabled",
  "mode": "log_only",
  "recorded": 0,
  "orders_submitted": 0,
  "config_path": "data\\config\\lab_book.json"
}
```

Runner:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_lab_book_daily.ps1
```

Resultado en `data/logs/lab_book.log`: `START`, payload `status=disabled`,
`recorded=0`, `orders_submitted=0`, `DONE`.

## Verificacion

- Focales:
  `.\.venv\Scripts\python.exe -m pytest tests\test_lab_book.py tests\test_ci_aggressiveness_gate.py -q`:
  `14 passed`.
- Suite completa: `.\.venv\Scripts\python.exe -m pytest tests\ -x -q`:
  `906 passed, 1 warning`.
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
  Resultado: ciclo `20260702-221714`, `used_crew=false`, `market_state_quality=PARTIAL`,
  sin envio automatico de ordenes.
