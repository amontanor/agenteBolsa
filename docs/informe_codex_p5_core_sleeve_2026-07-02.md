# Informe Codex P5 - Manga core SPY vol-target 12%

Fecha: 2026-07-02

## Resumen

- Modulo nuevo: `src/agente_bolsa/strategies/core_sleeve.py`.
- Ubicacion elegida: `strategies/`, porque la manga core es una politica de asignacion de cartera y sizing, no una herramienta de datos.
- Estado de entrega: codigo disponible con `enabled=false` y `dry_run=true`.
- No se registra en el scheduler operativo.
- No toca `config.py`, `.env`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py` ni `kernel.py`.

## Configuracion

Archivo: `data/config/core_sleeve.json`

Campos:

- `enabled`: activa la manga core. Default `false`.
- `dry_run`: si `true`, registra la orden hipotetica y no llama al broker. Default `true`.
- `sleeve_fraction`: fraccion maxima del equity paper dedicada a SPY. Default `0.30`.
- `rebalance_band_pp`: banda muerta en puntos porcentuales de la manga. Default `5`.
- `target_vol`: volatilidad objetivo del overlay. Default `0.12`.

Estado final verificado:

```json
{
  "enabled": false,
  "dry_run": true,
  "sleeve_fraction": 0.3,
  "rebalance_band_pp": 5,
  "target_vol": 0.12
}
```

## Logica

Objetivo:

```text
objetivo_SPY = equity_paper * sleeve_fraction * exposicion_vt12
```

La exposicion VT12 viene del mismo motor usado por `research/overlay_shadow.py`.

Controles duros:

- Solo opera `SPY`.
- Nunca genera corto.
- Nunca apalanca.
- La manga no puede superar `sleeve_fraction` del equity.
- Maximo 1 rebalanceo por `data_date` de mercado.
- No opera si la desviacion no supera `equity * sleeve_fraction * rebalance_band_pp / 100`.

## Gobierno

Se extendio el gate de agresividad:

- `sleeve_fraction`: subir requiere experimento `PASSED` con edge neto.
- `target_vol`: subir requiere experimento `PASSED` con edge neto.
- `core_sleeve.enabled`: bloqueado como self-governance.
- `core_sleeve.dry_run`: bloqueado como self-governance.

## Scripts

One-shot:

```powershell
.\scripts\run_core_sleeve_daily.ps1
```

Supervisor sin admin, no arrancado:

```powershell
.\scripts\run_core_sleeve_supervisor.ps1 -RunAt 15:45
```

## Demo real dry-run

Pasos ejecutados:

1. Ejecucion con flag OFF para crear/verificar config:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.strategies.core_sleeve --config data\config\core_sleeve.json --log-dir data\research\core_sleeve --json
```

Resultado: `status=disabled`.

2. Activacion temporal solo para demo: `enabled=true`, `dry_run=true`.

Resultado registrado en `data/research/core_sleeve/core_sleeve_log.jsonl`:

- `status`: `would_submit`
- `data_date`: 2026-07-01
- `equity`: 70653.37
- `price`: 745.76001
- `exposure`: 0.656465
- `target_notional`: 13914.44
- `current_notional`: 0.0
- `order`: buy SPY por 13914.44 USD

3. Restauracion final: `enabled=false`, `dry_run=true`.

## Runbook de activacion humana

Paso 1 - dry-run real durante unas sesiones:

```powershell
$path = "data\config\core_sleeve.json"
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.enabled = $true
$cfg.dry_run = $true
$cfg | ConvertTo-Json -Depth 5 | Set-Content $path -Encoding UTF8
.\scripts\run_core_sleeve_daily.ps1
```

Revisar `data/research/core_sleeve/core_sleeve_log.jsonl` durante al menos 5 sesiones de paridad.

Paso 2 - activo en paper:

```powershell
$path = "data\config\core_sleeve.json"
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.enabled = $true
$cfg.dry_run = $false
$cfg | ConvertTo-Json -Depth 5 | Set-Content $path -Encoding UTF8
.\scripts\run_core_sleeve_daily.ps1
```

Solo ejecutar en horario de mercado. El runner bloquea envio real paper si el mercado esta cerrado.

## Verificacion P5

- Tests focalizados P5/gate: `14 passed`.
- Suite completa: `872 passed, 1 warning`.
- `ruff check src tests scripts`: limpio.
- Demo real dry-run: OK.
- `core_sleeve.json` restaurado con `enabled=false`.
- Version P5: `0.4.85`.
