# Runbook core sleeve: activacion, escalado y rollback

Este runbook es human-gated. Ningun paso debe ejecutarse automaticamente por la
firma. Antes de tocar config confirma que el sistema sigue en paper:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
.\.venv\Scripts\python.exe scripts\core_sleeve_parity_check.py
```

Condiciones de seguridad previas:

- `trading_mode=paper`.
- `allow_live_trading=false`.
- `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- Paridad limpia entre core sleeve, overlay shadow y recalculo deep.
- Revision explicita del responsable.

## Activar dry_run=false

Solo tras al menos 5 sesiones de mercado con paridad limpia en el escalon actual.
La activacion no cambia `sleeve_fraction`; solo permite que el runner envie orden
paper cuando el mercado este abierto y la decision salga fuera de banda.

```powershell
.\.venv\Scripts\python.exe scripts\core_sleeve_parity_check.py
$path = "data\config\core_sleeve.json"
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.enabled = $true
$cfg.dry_run = $false
$cfg | ConvertTo-Json -Depth 8 | Set-Content $path -Encoding UTF8
.\scripts\run_core_sleeve_daily.ps1
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status --json
```

Si el parity check devuelve codigo distinto de 0, no activar.

## Subir escalon

La escalera pre-registrada vive en `data/config/core_sleeve.json` como campo
informativo: `[0.30, 0.50, 0.70]`. El codigo no escala solo. Para subir de
escalon hacen falta estas tres puertas:

1. Cinco sesiones o mas de paridad limpia en el escalon actual.
2. Revision del responsable.
3. Cambio manual de Antonio en `sleeve_fraction`.

Comando literal para subir a 50%:

```powershell
.\.venv\Scripts\python.exe scripts\core_sleeve_parity_check.py
$path = "data\config\core_sleeve.json"
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.sleeve_fraction = 0.50
$cfg | ConvertTo-Json -Depth 8 | Set-Content $path -Encoding UTF8
.\scripts\run_core_sleeve_daily.ps1
```

Comando literal para subir a 70%:

```powershell
.\.venv\Scripts\python.exe scripts\core_sleeve_parity_check.py
$path = "data\config\core_sleeve.json"
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.sleeve_fraction = 0.70
$cfg | ConvertTo-Json -Depth 8 | Set-Content $path -Encoding UTF8
.\scripts\run_core_sleeve_daily.ps1
```

## Rollback inmediato

Primer rollback: apagar la manga y volver a `dry_run=true`.

```powershell
$path = "data\config\core_sleeve.json"
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.dry_run = $true
$cfg.enabled = $false
$cfg | ConvertTo-Json -Depth 8 | Set-Content $path -Encoding UTF8
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status --json
```

Segundo rollback, solo si el responsable decide liquidar SPY de la manga en paper.
No usar `run_core_sleeve_daily.ps1` para liquidacion inmediata si ya hubo rebalance
en la misma fecha: el runner tiene guardia de una rebalance por dia. Esta orden
cierra la posicion SPY completa en paper; antes confirma que SPY no mezcla otra
tesis ajena a la manga.

```powershell
.\.venv\Scripts\python.exe -c "from agente_bolsa.config import get_settings; from agente_bolsa.tools.execution import submit_paper_order_plan; s=get_settings(); plan={'symbol':'SPY','side':'sell','notional':0,'payload':{'recommendation':{'action':'exit'},'risk_decision':{'checks':{'action':'exit'}}}}; print(submit_paper_order_plan(s, plan, client_order_id='manual-core-sleeve-exit'))"
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status --json
```

Despues de cualquier rollback, ejecutar de nuevo el parity check y revisar
`data/research/core_sleeve/core_sleeve_log.jsonl` antes de reactivar.
