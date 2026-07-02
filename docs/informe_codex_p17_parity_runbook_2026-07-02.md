# Informe Codex P17 - Parity check y runbook core sleeve

## Objetivo

Preparar una activacion humana segura de la manga core SPY sin cambiar conducta
real de trading. La entrega queda read-only salvo la escalera informativa de
configuracion y documentacion operativa.

## Cambios entregados

- Nuevo script read-only `scripts/core_sleeve_parity_check.py`.
- Tests sinteticos de paridad limpia y divergencia en
  `tests/test_core_sleeve_parity_check.py`.
- Campo informativo `max_sleeve_fraction_ladder: [0.30, 0.50, 0.70]` en
  `data/config/core_sleeve.json`.
- Runbook human-gated `docs/runbook_core_sleeve_activacion.md`.
- Version subida a `0.4.98`.

No se tocaron archivos protegidos del suelo de kernel.

## Metodo de paridad

La comparacion usa la ultima fila por `data_date` en cada log:

- Core sleeve dry-run: `data/research/core_sleeve/core_sleeve_log.jsonl`, campo
  `exposure`.
- Overlay shadow: `data/research/overlay_shadow/overlay_shadow_log.jsonl`, campo
  `target_exposures.vol_target_12pct`.
- Recalculo deep: `target_vol / realized_vol_20d_annualized`, acotado a `0..1` y
  redondeado a 6 decimales, la misma regla documentada por `overlay_shadow.py` y
  `exposure_vol_target`.

La tolerancia de exposicion es `1e-6`. Una fecha solo presente en uno de los logs
se marca como discrepancia de `data_date`.

## Ejecucion real

Comando:

```powershell
.\.venv\Scripts\python.exe scripts\core_sleeve_parity_check.py --json
```

Resultado:

```json
{
  "ok": true,
  "tolerance": 1e-06,
  "rows_checked": 1,
  "rows": [
    {
      "data_date": "2026-07-01",
      "ok": true,
      "issues": [],
      "core_status": "no_order",
      "core_exposure": 0.656465,
      "overlay_exposure": 0.656465,
      "recalculated_exposure": 0.656466,
      "core_overlay_delta": 0.0,
      "core_recalc_delta": -1e-06,
      "realized_vol_annualized": 0.182797,
      "target_vol": 0.12
    }
  ]
}
```

No hay divergencia fuera de tolerancia. La diferencia de recalculo es exactamente
`1e-6` porque el log conserva `realized_vol_annualized` redondeado a 6 decimales;
queda dentro de la tolerancia pre-registrada.

## Gobierno

La escalera `[0.30, 0.50, 0.70]` es solo informativa. El codigo no escala solo:
`sleeve_fraction` sigue siendo manual y human-gated. Cada subida requiere:

1. `>=5` sesiones de paridad limpia en el escalon actual.
2. Revision del responsable.
3. Cambio manual de Antonio.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_core_sleeve_parity_check.py -q`:
  `2 passed`.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q`: `899 passed, 1 warning`.
- `.\.venv\Scripts\ruff.exe check src tests scripts`: limpio.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main status`: `trading_mode=paper`,
  `allow_live_trading=false`.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json`:
  `ok=true`.
- Flags efectivos: `allow_auto_apply_improvements=false`; `data/config/core_sleeve.json`
  conserva `dry_run=true`.
- Smoke real:
  `.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew`.
  Resultado: ciclo `20260702-220746`, `used_crew=false`, `market_state_quality=PARTIAL`,
  sin envio automatico de ordenes.
