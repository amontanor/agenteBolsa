# Informe Codex - Telegram radar scheduling - 2026-07-02

## Objetivo

Dejar el radar Telegram ejecutable de forma diaria y aislada del runtime de
trading. No se tocaron `kernel.py`, `tools/broker.py`, `tools/execution.py`,
`tools/risk.py`, `config.py`, `.env` ni el scheduler operativo
`agente_bolsa.main schedule`. No se crearon ordenes y no se arranco la tarea.

## Cambios

### `telegram-radar report --out`

El comando `telegram-radar report` acepta ahora:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main telegram-radar report --days 7 --out data\research\telegram\reports\radar_2026-07-02.md
```

Si `--out` se omite, mantiene el comportamiento anterior e imprime markdown por
stdout. Si se pasa `--out`, escribe markdown en UTF-8 mediante Python y evita el
problema habitual de redireccion PowerShell a UTF-16.

### Script one-shot diario

Nuevo script:

```powershell
.\scripts\run_telegram_radar_daily.ps1
```

Hace:

1. `telegram-radar ingest --backfill 1 --json`
2. valida que la ingesta devuelva JSON y `ok=true`;
3. `telegram-radar report --days 7 --out data\research\telegram\reports\radar_<fecha>.md --json`;
4. loggea inicio, salida y fin en `data\logs\telegram_radar.log`.

Si Telegram/red falla y la ingesta devuelve `ok=false`, el script registra
`ingest_failed_cleanly` y sale con codigo `2`, sin traceback ni cambios
operativos.

### Supervisor sin admin

Nuevo script:

```powershell
.\scripts\run_telegram_radar_supervisor.ps1
```

Por defecto espera hasta las 23:00 hora local y lanza una vez al dia
`run_telegram_radar_daily.ps1`. Registra su actividad en
`data\logs\telegram_radar_supervisor.log`.

No requiere privilegios de administrador y no registra una Tarea Programada de
Windows. Es un bucle local independiente; Antonio puede dejarlo en una consola
propia o lanzarlo desde su mecanismo externo preferido.

Para cambiar la hora:

```powershell
.\scripts\run_telegram_radar_supervisor.ps1 -RunAt 23:15
```

## Arranque y parada

Arranque manual del supervisor:

```powershell
cd C:\Antonio\Bref\agenteBolsa
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_telegram_radar_supervisor.ps1
```

Parada:

- cerrar esa consola, o
- `Ctrl+C` en la consola del supervisor.

No hay requisito de administrador con este mecanismo.

## Salidas

- Informe diario: `data\research\telegram\reports\radar_<fecha>.md`
- Log one-shot: `data\logs\telegram_radar.log`
- Log supervisor: `data\logs\telegram_radar_supervisor.log`

`data/research/` permanece fuera de git como estado local/runtime de
investigacion.

## Verificacion

- `.\.venv\Scripts\python.exe -m pytest tests\test_telegram_radar_phase_b.py -q` -> 5 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` -> 842 passed, 1 warning externa de `websockets.legacy`.
- `.\.venv\Scripts\ruff.exe check src tests` -> OK.
- `.\.venv\Scripts\python.exe -m agente_bolsa.main telegram-radar report --help` -> muestra `--out`.
- Parseo sintactico PowerShell: `run_telegram_radar_daily.ps1` y `run_telegram_radar_supervisor.ps1` -> OK.
- Estado operativo: `trading_mode=paper`, `allow_live_trading=false`.
- Version final: `0.4.80`.
