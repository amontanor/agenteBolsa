# Prompt P10 para Codex — 2-jul-2026 — regenerar el diff de la firma con el esquema REAL

Contexto: el responsable revisó `ci_artifact_259b18101111` (propuesta
`ci_prop_p7_core_sleeve_digest`) y lo RECHAZÓ antes del approve. Motivo: la firma
inventó el esquema del log — el diff lee `target_exposure` y `hypothetical_order`,
pero el log real de `strategies/core_sleeve.py` escribe `exposure` y
`decision.order`. Sus tests sintéticos pasaban porque validaban datos fabricados por
ella misma. Con datos reales, la sección mostraría None en los campos clave.

Línea REAL del log (`data/research/core_sleeve/core_sleeve_log.jsonl`):

```json
{"created_at": "2026-07-02T11:12:06+00:00", "status": "would_submit", "symbol": "SPY", "data_date": "2026-07-01", "price": 745.76, "realized_vol_annualized": 0.182797, "exposure": 0.656465, "config": {"enabled": true, "dry_run": true, "sleeve_fraction": 0.3, "rebalance_band_pp": 5.0, "target_vol": 0.12}, "decision": {"equity": 70653.37, "target_notional": 13914.44, "current_notional": 0.0, "delta_notional": 13914.44, "order": {"symbol": "SPY", "side": "buy", "notional": 13914.44}, "reason": "buy_to_target"}}
```

Tarea (pequeña):

1. **Marca el artefacto rechazado**: `ci_artifact_259b18101111` no debe quedar
   aprobable (registra decisión `rejected_by_human_review`, razón
   `schema_mismatch_with_real_producer`, actor `Responsable`). Que `review` no lo
   liste ya como candidato.
2. **Corrige la spec de la propuesta** `ci_prop_p7_core_sleeve_digest`: incluye en
   `proposed_value`/payload la línea real de arriba como contrato de esquema, y los
   campos exactos a mostrar: `data_date`, `status`, `exposure`,
   `decision.reason`, `decision.order.side` + `decision.order.notional` (si
   `decision` es null, mostrar solo status), advertencia si >3 sesiones sin registro.
3. **Re-lanza `gen-diff`** (la autocorrección de P9 ya existe) hasta 3 intentos.
   Exige además que los tests generados incluyan UN caso construido con la línea
   real de arriba (copiada literal), no solo datos inventados — esa es la lección
   de este rechazo.
4. **Mejora sistémica (pequeña, tú directamente)**: cuando una propuesta CODE_CHANGE
   toque parsing de ficheros de datos, `CodegenPatchAgent` debe incluir en el
   contexto una muestra real del fichero de datos si existe (primeras/últimas ~5
   líneas), igual que ya incluye el contenido del target. Con test.
5. Si el nuevo artefacto pasa sandbox: déjalo en `READY_FOR_HUMAN_REVIEW` y cierra
   con los comandos `review`/`approve`. El responsable volverá a revisar el diff
   antes de que Antonio apruebe.
6. En el informe, incluye la salida de `review` (el diff nuevo) para revisión.

Informe: `docs/informe_codex_p10_regen_schema_<fecha>.md`.

Bloque de verificación obligatorio:
- `pytest tests\ -x -q` verde; `ruff check src tests scripts` limpio.
- Bump de `__version__`.
- Commit con diff revisable (solo tus cambios; los docs del responsable ya estarán
  commiteados por Antonio).
- Confirmar: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` con `dry_run=true`.
- NO tocar los 6 ficheros del suelo de kernel.
