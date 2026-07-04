# Informe Codex P30 - stack idempotente

Fecha: 2026-07-04.
Rama: `codex/mejora_continua`.

## Cambios

- Añadido helper PowerShell compartido `scripts/stack_common.ps1` para locks
  `data/run/<servicio>.pid`, deteccion de procesos compatibles, locks huerfanos,
  puerto web y estado de servicios.
- Integrados locks de instancia unica en:
  `run_telegram_radar_supervisor.ps1`,
  `run_overlay_shadow_supervisor.ps1`,
  `run_ci_digest_supervisor.ps1`,
  `run_codegen_nightly_supervisor.ps1`,
  `run_core_sleeve_supervisor.ps1`.
- Añadidos `scripts/stack_status.ps1`, `scripts/stack_up.ps1` y
  `scripts/stack_down.ps1`.
- El comando `agente_bolsa.main web` comprueba el puerto antes de lanzar
  Streamlit y evita duplicar el panel.
- Sustituido `use_container_width=True` por `width="stretch"` en `web_app.py`.
- Version subida a `0.4.109`.

## Ejecucion real

Estado antes de arrancar supervisores, tras normalizar la deteccion por raiz de
proceso:

| Servicio | Estado | PID raiz | Observacion |
|---|---:|---:|---|
| scheduler | CORRIENDO | 49392 | tarea `AgenteBolsaScheduler`; procesos hijos 9656 y 48916 |
| web | CORRIENDO | 53044 | HTTP 8501 OK; procesos hijos 61924, 62060 y 52840 |
| telegram_radar_supervisor | PARADO | - | sin lock |
| overlay_shadow_supervisor | PARADO | - | sin lock |
| ci_digest_supervisor | PARADO | - | sin lock |
| codegen_nightly_supervisor | PARADO | - | sin lock |
| core_sleeve_supervisor | PARADO | - | sin lock |

No se mataron procesos: no habia duplicados logicos despues de colapsar la cadena
normal venv -> Python base -> Streamlit. La primera deteccion bruta listaba PIDs
hijos como si fueran duplicados; por eso `stack_status` conserva `process_pids`
en JSON pero decide `DUPLICADO` solo con raices logicas independientes.

Ejecucion de `stack_up.ps1 --json`:

| Servicio | Accion |
|---|---|
| scheduler | already |
| web | already |
| telegram_radar_supervisor | started |
| overlay_shadow_supervisor | started |
| ci_digest_supervisor | started |
| codegen_nightly_supervisor | started |
| core_sleeve_supervisor | started |

Segunda ejecucion de `stack_up.ps1 --json`:

| Servicio | Accion | PID |
|---|---|---:|
| scheduler | already | 49392 |
| web | already | 53044 |
| telegram_radar_supervisor | already | 39172 |
| overlay_shadow_supervisor | already | 59428 |
| ci_digest_supervisor | already | 33916 |
| codegen_nightly_supervisor | already | 51048 |
| core_sleeve_supervisor | already | 61176 |

Estado final legible:

```text
service                    state     pids  lock_pid lock_ok lock_orphan port http_ok
scheduler                  CORRIENDO 49392            False       False
web                        CORRIENDO 53044            False       False 8501 True
telegram_radar_supervisor  CORRIENDO 39172 39172       True       False
overlay_shadow_supervisor  CORRIENDO 59428 59428       True       False
ci_digest_supervisor       CORRIENDO 33916 33916       True       False
codegen_nightly_supervisor CORRIENDO 51048 51048       True       False
core_sleeve_supervisor     CORRIENDO 61176 61176       True       False
```

Smoke web:

```text
Panel web ya corriendo en http://127.0.0.1:8501; no se lanza otra instancia.
```

## Seguridad

- `trading_mode=paper`.
- `allow_live_trading=false`.
- `.env`: `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- `core_sleeve.json`: `dry_run=true`.
- No se tocaron los ficheros protegidos del kernel.

## Verificacion

- `py_compile src/agente_bolsa/main.py src/agente_bolsa/web_app.py`: OK.
- `scripts/stack_status.ps1 --json`: OK.
- Parse PowerShell de `stack_up`, `stack_down` y los cinco supervisores: OK.
- `agente_bolsa.main status`: OK.
- `validate-agent-config --json`: OK.
- `kernel-status --json`: OK, sin violaciones.
- `schedule-status`: OK; mercado cerrado el 2026-07-04, proxima apertura
  2026-07-06 15:30 Europe/Madrid.
- `pytest tests\ -x -q`: 948 passed, 1 warning externo de `websockets`.
- `ruff check src tests scripts`: OK.
- `run-once --skip-crew`: OK, sin CrewAI ni envio automatico de ordenes.
