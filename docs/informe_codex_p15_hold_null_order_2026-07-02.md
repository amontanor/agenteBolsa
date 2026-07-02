# Informe Codex P15 - core sleeve `order: null`

Fecha: 2026-07-02

## Evidencia del crash

Comando que fallaba antes del hotfix:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days 1 --out data\reports\ci_digest_post_apply.md
```

Traza reproducida:

```text
File "C:\Antonio\Bref\agenteBolsa\src\agente_bolsa\continuous_improvement\digest.py", line 363, in latest_core_sleeve_signal
  "decision_order_side": (decision.get("order", {}).get("side") if decision else None),
AttributeError: 'NoneType' object has no attribute 'get'
```

Ultima linea real de `data/research/core_sleeve/core_sleeve_log.jsonl` que lo
disparaba:

```json
{"created_at": "2026-07-02T13:45:05.206059+00:00", "status": "no_order", "symbol": "SPY", "data_date": "2026-07-01", "price": 745.76001, "realized_vol_annualized": 0.182797, "exposure": 0.656465, "config": {"enabled": true, "dry_run": true, "sleeve_fraction": 0.3, "rebalance_band_pp": 5.0, "target_vol": 0.12}, "decision": {"data_date": "2026-07-01", "equity": 70653.37, "price": 745.76001, "exposure": 0.656465, "sleeve_fraction": 0.3, "target_notional": 13914.44, "current_notional": 0.0, "max_sleeve_notional": 21196.01, "rebalance_band_notional": 1059.8, "delta_notional": 13914.44, "order": null, "reason": "already_rebalanced_today"}}
```

## Contrato del productor

Fuente: `src/agente_bolsa/strategies/core_sleeve.py`.

| Status | Cuándo se emite | Forma de `decision` | Forma de `decision.order` |
|---|---|---|---|
| `disabled` | `config.enabled=false` | `null` | no existe |
| `no_order` | `decision.order is None` | dict con métricas y `reason` | `null`; también debe tolerarse ausente |
| `would_submit` | `dry_run=true` y hay orden | dict | dict con `symbol`, `side`, `notional`, `payload` |
| `market_closed` | `dry_run=false`, hay orden, mercado cerrado | dict | dict |
| `submitted` | `dry_run=false`, mercado abierto, orden enviada | dict | dict; además `submitted_order` |

Razones posibles de `no_order`: `within_rebalance_band`,
`already_rebalanced_today`, `missing_equity`, `missing_price` o un caso de venta
sin posición larga actual.

## Intentos de la firma

Se sembró `ci_prop_p15_core_sleeve_null_order_digest` por el cauce normal con:

- targets: `digest.py`, `tests/test_ci_phase3_digest.py`, `src/agente_bolsa/__init__.py`;
- requisito de tests para la línea real y todos los estados del contrato;
- muestra real de `data/research/core_sleeve/core_sleeve_log.jsonl`.

Se ejecutó `gen-diff` tres veces. Resultado:

1. Fallo tras autocorrecciones internas:

```text
ValueError: No se encontro bloque old en src/agente_bolsa/continuous_improvement/digest.py
```

2. Fallo idéntico:

```text
ValueError: No se encontro bloque old en src/agente_bolsa/continuous_improvement/digest.py
```

3. Generó un diff, pero el test de la firma escribía el log fuera del path real
`research/core_sleeve`:

```text
FAILED tests/test_core_sleeve_signal.py::test_normal_order_returns_order_data
E       AssertionError: assert None == 'SPY'
E        +  where None = <built-in method get of dict object at 0x000001976361D300>('symbol')
E        +    where <built-in method get of dict object at 0x000001976361D300> = {'available': False, 'reason': '...\\test_normal_order_returns_orde0\\research\\core_sleeve\\core_sleeve_log.jsonl no existe'}.get
```

Por plazo operativo se aplicó hotfix directo.

## Hotfix directo

Commit: `fa126d40 Hotfix core sleeve digest null order`.

Cambio:

```python
decision = latest.get("decision") if isinstance(latest.get("decision"), dict) else {}
order = decision.get("order") if isinstance(decision.get("order"), dict) else {}
```

Así `decision: null`, `decision.order: null` y `decision` sin clave `order`
renderizan `decision.order.side/notional = n/d` sin crashear.

Tests añadidos:

- línea real del crash copiada verbatim;
- `decision.order: null`;
- `decision.order` ausente;
- estados `disabled`, `no_order`, `would_submit`, `market_closed`, `submitted`.

## Lección sistémica

Commit: `0ea61f00 Teach codegen to cover nested null samples`.

Cambios:

- El prompt de codegen exige cubrir valores `null` y claves ausentes en campos
  anidados presentes en `data_samples`, por ejemplo `decision.order`.
- `src/agente_bolsa/__init__.py` queda permitido en codegen para que la firma
  pueda incluir bumps de versión obligatorios.

## Digest final

El comando obligatorio ya termina OK:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main continuous-improvement-lab digest --days 1 --out data\reports\ci_digest_post_apply.md
# Digest escrito: data\reports\ci_digest_post_apply.md
```

Sección renderizada:

```text
Core sleeve
- data_date: 2026-07-01
- status: no_order
- exposure: 0.656465
- decision.reason: already_rebalanced_today
- decision.order.side: n/d
- decision.order.notional: n/d
```

La propuesta P15 se marcó `APPLIED` por `CodexP15Hotfix` con razón
`manual_hotfix_after_codegen_failures`.

## Verificación final

Versión: `0.4.96`.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
# 897 passed, 1 warning

.\.venv\Scripts\ruff.exe check src tests scripts
# All checks passed

.\.venv\Scripts\python.exe -m agente_bolsa.main status
# trading_mode=paper; allow_live_trading=false

.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
# ok=true; errors=[]; warnings=[]

.\.venv\Scripts\python.exe -m agente_bolsa.main run-once --skip-crew
# cycle_id=20260702-184425; used_crew=false; market_state_quality=PARTIAL
```

Flags confirmados:

```json
{
  "trading_mode": "paper",
  "allow_live_trading": false,
  "allow_auto_apply_improvements": false,
  "core_sleeve_path": "data\\config\\core_sleeve.json",
  "core_sleeve_dry_run": true
}
```

No se tocaron los ficheros protegidos:

- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`
- `.env`
