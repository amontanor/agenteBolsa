# Guía del proyecto y de la operación

## 1. Propósito y alcance

agenteBolsa es un sistema de trading **paper** con investigación, análisis, selección, riesgo, ejecución, aprendizaje y observabilidad. La prioridad es:

1. seguridad de trading y preservación de capital;
2. integridad de identidad, temporalidad y datos;
3. paridad entre la ruta activa y sus consumidores;
4. evidencia auditable;
5. rendimiento y comodidad operativa.

Este documento es una guía estable. Los estados dependientes de una fecha, una versión, una Raspberry o una sesión deben contrastarse en el informe del lote correspondiente.

## 2. Cómo leer el repositorio

### 2.1 Código de aplicación

| Ruta | Responsabilidad |
|---|---|
| `src/agente_bolsa/main.py` | CLI y punto de entrada de comandos operativos |
| `src/agente_bolsa/scheduler.py` | Jobs recurrentes, coordinación y leases |
| `src/agente_bolsa/cycle_runner.py` | Fases del ciclo de mercado y carriers de decisión |
| `src/agente_bolsa/storage.py` | Frontera normal de persistencia SQLite mediante `Store` |
| `src/agente_bolsa/models.py` | Contratos y modelos de dominio |
| `src/agente_bolsa/web_app.py` | Dashboard Streamlit; no adquiere autoridad de trading |
| `src/agente_bolsa/config.py` | `Settings` y configuración; archivo protegido |
| `src/agente_bolsa/kernel.py` | Gates, sellado y seguridad; archivo protegido |
| `src/agente_bolsa/tools/` | Broker, riesgo, ejecución, auditorías, reports y consumidores |
| `src/agente_bolsa/continuous_improvement/` | Laboratorio, propuestas, evidencias y aprendizaje |
| `src/agente_bolsa/docker_supervisor.py` | Supervisor Linux de auxiliares Docker |
| `src/agente_bolsa/runtime_paths.py` | Rutas del intérprete en Windows y contenedor |

Archivos protegidos que no se modifican sin revisión humana explícita:

- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`
- `.env`

### 2.2 Tests, scripts y datos

| Ruta | Uso |
|---|---|
| `tests/` | Tests aislados; nunca leen SQLite ni servicios productivos |
| `scripts/stack_*.ps1` | Helpers canónicos del stack Windows |
| `scripts/check_no_nulls.py` | Gate sin NUL |
| `scripts/check_services.ps1` | Diagnóstico de servicios Windows |
| `scripts/check_services.ps1` | Diagnóstico de servicios Windows |
| `scripts/raspberry_preflight.py` | Preflight Raspberry read-only con salida JSON |
| `scripts/sqlite_cold_snapshot.py` | Snapshot frio SQLite con WAL/SHM, hashes y receipt |
| `scripts/run_*_supervisor.ps1` | Supervisores auxiliares Windows |
| `data/state/` | Estado SQLite productivo |
| `data/reports/` | Informes y artefactos operativos |
| `data/config/` | Configuración versionada que puede entrar en la imagen |
| `docs/plan_mejoras_y_tareas.md` | Fuente única de backlog y estado |
| `docs/RELEVO_DIRECCION_TECNICA.md` | Relevo técnico y siguiente secuencia |
| `docs/startup_runbook.md` | Runbook operativo Windows |
| `docs/tutorial_arranque_diario.md` | Comprobaciones diarias |
| `docs/operating_model.md` | Modelo operativo y promoción |
| `docs/promotion_checklist.md` | Checklist de promoción |
| `docs/guia_proyecto_y_operacion.md` | Este mapa estable del proyecto |
| `docs/informe_codex_p_l89_raspberry_docker.md` | Informe único de la migración Raspberry |

## 3. Flujo funcional de alto nivel

```text
scheduler
  -> market/session gates
  -> cycle_runner
  -> research/selection/decision
  -> risk gates and sizing
  -> execution/broker (paper)
  -> fills/post-decision
  -> append-only events, runtime_state and reports
```

Reglas de interpretación:

- `agent_events` conserva historia; `runtime_state` es la vista latest.
- Identidades canónicas: `cycle_id`, `signal_capture_id`, `signal_id`, `candidate_id`, `recommendation_id`, `plan_id`, `broker_order_id` y `client_order_id`.
- BUY y EXIT no se identifican solo por símbolo o fecha.
- Los tiempos de identidad se normalizan a UTC; la presentación usa Europe/Madrid.
- `null`, `unavailable`, `not_generated` y `not_applicable` no son equivalentes.
- Una ruta shadow puede publicar evidencia, pero no crear, bloquear, retrasar ni cambiar órdenes.
- Un P/L intradía o una sesión aislada no demuestra causalidad ni readiness.

## 4. Persistencia y SQLite

La SQLite productiva canónica es `data/state/agente_bolsa.sqlite3`.

En Raspberry se monta dentro del USB en `/var/lib/agente-bolsa/state/agente_bolsa.sqlite3`.

Normas:

- usar `Store` en código normal;
- auditar con URI `mode=ro` y `PRAGMA query_only=ON`;
- no hacer backfill, VACUUM, checkpoint, reparación ni reescritura histórica sin autorización;
- tratar `-wal` y `-shm` como sidecars vivos, no copiarlos a ciegas;
- antes de un corte, detener escritores canónicamente y validar `quick_check`, `integrity_check`, bytes y SHA-256;
- conservar backups y documentar procedencia y rollback;
- no restaurar una SQLite histórica después de nuevos eventos, fills u órdenes sin congelar y reconciliar la autoridad de datos.

## 5. Política operativa

Configuración objetivo autorizada para la migración PAPER:

| Variable | Valor objetivo |
|---|---|
| `TRADING_MODE` | `paper` |
| `BROKER` | `alpaca` |
| `ALPACA_PAPER` | `true` |
| `AUTO_PAPER_TRADING` | `true` |
| `REQUIRE_HUMAN_APPROVAL` | `false` |
| `ALLOW_LIVE_TRADING` | `false` |
| `ALLOW_AUTO_APPLY_IMPROVEMENTS` | `false` |

La combinación permite operar automáticamente en PAPER, bloquea LIVE y bloquea auto-apply. Siempre se comprueba el valor efectivo en código, env y Compose; no basta el nombre de una imagen.

No cambiar en una migración de infraestructura: selección, scoring/ranks, sizing, exits, riesgo, broker, ejecución, modelo, política activa ni credenciales.

## 6. Operación Windows

Helpers canónicos:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stack_status.ps1
powershell -ExecutionPolicy Bypass -File scripts/stack_down.ps1 -IncludeScheduled
powershell -ExecutionPolicy Bypass -File scripts/stack_up.ps1
```

Preflight:

```powershell
./.venv/Scripts/python.exe -m agente_bolsa.main status
./.venv/Scripts/python.exe -m agente_bolsa.main schedule-status --json
./.venv/Scripts/python.exe -m agente_bolsa.main validate-agent-config --json
./.venv/Scripts/python.exe -m agente_bolsa.main kernel-status --json
./.venv/Scripts/python.exe -m agente_bolsa.main broker-status
./.venv/Scripts/python.exe -m agente_bolsa.main portfolio-status
./.venv/Scripts/python.exe -m agente_bolsa.main operational-health --json
powershell -ExecutionPolicy Bypass -File scripts/stack_status.ps1
```

Antes de desplegar o cortar:

- comprobar XNYS mediante `schedule-status`, no solo por la hora;
- exigir postmarket terminal, leases vacíos y ningún job competidor;
- confirmar PAPER, `live=false` y `auto-apply=false`;
- confirmar lock, PID, token y heartbeat;
- detener y arrancar mediante helpers, nunca matar Python genérico;
- validar salud dos veces separadas al menos 75 segundos.

## 7. Operación Raspberry y Docker

### 7.1 Identidad y rutas

| Elemento | Valor observado; revalidar antes de operar |
|---|---|
| Hostname | `Raspberryi5` |
| IP privada | `192.168.1.234` |
| Usuario SSH | `antonio` |
| Arquitectura | `aarch64/ARM64` |
| Sistema | Debian 13 |
| Proyecto | `/opt/agente-bolsa` |
| Env protegido | `/etc/agente-bolsa/application.env` |
| Datos | `/var/lib/agente-bolsa` |
| Backups | `/var/backups/agente-bolsa` |
| Red Docker propia | `agente-bolsa-net` |
| Puerto candidato | `0.0.0.0:8081 -> 8501` |

La clave SSH se usa desde `C:/Users/utopi/.ssh/codex_raspberry_ed25519`. Su contenido nunca se copia, imprime ni incluye en Git.

El USB objetivo es `/dev/sda1`, SanDisk, ext4, UUID `1a8cb7c0-3a65-4d72-866f-340db4c6bafc`, montado en `/var/lib/agente-bolsa`. Root y Docker siguen en la microSD salvo operación posterior documentada.

### 7.2 Puertos y servicios compartidos

No reutilizar:

- `22`: SSH;
- `8080`: servicio Docker existente `whale-copy`;
- `4002`: IBKR Gateway/Java.

El proyecto usa `agente-bolsa-net` y no debe conectarse a redes de otros proyectos. `whale-copy` es independiente: no detenerlo, reiniciarlo, reconfigurarlo ni borrar sus datos como parte de esta migración.

### 7.3 Compose y salud

El Compose Raspberry debe:

- separar `init-db`, `scheduler`, `web` y `auxiliary`;
- ejecutar el auxiliar Linux secuencialmente para limitar memoria;
- usar temporal persistente dentro de `/data` para SQLite y `ci_digest`;
- mantener `read_only`, `no-new-privileges`, `cap_drop: ALL`, usuario no root cuando sea posible y rotación de logs;
- usar red propia y bind mount del USB;
- comprobar Streamlit mediante `/_stcore/health`;
- distinguir `/health` HTML de Streamlit de un endpoint JSON semántico;
- no iniciar dos schedulers a la vez.

Comprobación remota sin revelar env:

```powershell
$RaspKey = "$env:USERPROFILE/.ssh/codex_raspberry_ed25519"
ssh -i $RaspKey -o IdentitiesOnly=yes antonio@192.168.1.234 "hostname; uname -m; docker --version; docker compose version; df -h; free -h"
ssh -i $RaspKey -o IdentitiesOnly=yes antonio@192.168.1.234 "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
```

Compose:

```bash
sudo docker compose \
  --env-file /etc/agente-bolsa/application.env \
  -f /opt/agente-bolsa/deploy/docker-compose.yml \
  -f /opt/agente-bolsa/deploy/docker-compose.raspberry.override.yml \
  config

sudo docker compose \
  --env-file /etc/agente-bolsa/application.env \
  -f /opt/agente-bolsa/deploy/docker-compose.yml \
  -f /opt/agente-bolsa/deploy/docker-compose.raspberry.override.yml \
  ps
```

Salud:

```bash
curl -fsS http://127.0.0.1:8081/_stcore/health
curl -fsS http://127.0.0.1:8081/kindle
```

Túnel SSH preferido:

```powershell
ssh -i $RaspKey -N -L 18081:127.0.0.1:8081 antonio@192.168.1.234
```

La publicación LAN en `0.0.0.0:8081` solo se valida dentro de la red privada; no abrir Internet, router o firewall público sin autoridad explícita.

### 7.4 Preflight Raspberry automatizado

El helper `scripts/raspberry_preflight.py` ejecuta únicamente lecturas por SSH:
identidad, UUID/montaje, espacio e inodos, memoria, procesos en estado `D`,
errores recientes de USB/ext4, Docker, salud de los tres contenedores core,
imagen candidata y flags PAPER. No ejecuta Compose, no detiene procesos, no
abre ni repara SQLite y devuelve código `2` si una precondición falla.
El gate de bytes exige al menos 10 GiB libres y el de inodos bloquea por encima
del 90% por defecto; ambos umbrales se pueden ajustar explícitamente.

Uso desde PowerShell:

```powershell
& ".\.venv\Scripts\python.exe" scripts\raspberry_preflight.py `
  --identity "$env:USERPROFILE\.ssh\codex_raspberry_ed25519" `
  --json
```

Con `--require-windows-stopped`, el helper audita el `stack_status.ps1` del
checkout principal resuelto mediante `git-common-dir`, aunque el comando se
ejecute desde un worktree candidato. Se puede fijar con `--windows-repo` si
existe más de un checkout operativo.

El resultado debe conservarse en el informe del lote. La comprobación de
SQLite queda `unavailable` mientras la base activa tenga WAL/SHM o no exista
un receipt local de snapshot frío validado. Un receipt aceptable debe tener
schema `p-l89.sqlite-cold-snapshot.v2`, estado `ok`, `quick_check=ok`,
`integrity_check=ok`, `source_host`, `target_host`, montaje, UUID y SHA-256 de
64 caracteres:

```powershell
& ".\.venv\Scripts\python.exe" scripts\raspberry_preflight.py `
  --identity "$env:USERPROFILE\.ssh\codex_raspberry_ed25519" `
  --sqlite-receipt .\sqlite-cold-snapshot.json `
  --json
```

El receipt no sustituye al snapshot: solo permite verificar de forma
reproducible una evidencia producida por el procedimiento autorizado. Nunca
se debe fabricar, editar o reutilizar un receipt de otra Raspberry, UUID o
estado de SQLite.

El snapshot se genera con `scripts/sqlite_cold_snapshot.py` solo despues de
detener canonicamente todos los escritores y confirmar exclusividad. Exige la
bandera explicita `--writers-stopped`, no sobrescribe un destino existente,
copia la SQLite y los sidecars presentes, valida el conjunto copiado y deja
`receipt.json` dentro del directorio nuevo:

```bash
python scripts/sqlite_cold_snapshot.py \
  --source /var/lib/agente-bolsa/state/agente_bolsa.sqlite3 \
  --destination-dir /var/backups/agente-bolsa/cold-YYYYMMDD-HHMMSS \
  --source-host Windows-Productivo \
  --target-host Raspberryi5 \
  --target-mount /var/lib/agente-bolsa \
  --target-device-uuid 1a8cb7c0-3a65-4d72-866f-340db4c6bafc \
  --writers-stopped --json
```

El comando no hace `VACUUM`, `checkpoint`, backfill ni reparacion. Si la
fuente cambia durante la copia, o el `quick_check`/`integrity_check` del
conjunto copiado falla, elimina solo su directorio temporal parcial y no crea
un receipt valido.

## 8. Migración Raspberry: estado documentado

El informe único con la fotografía, hashes y secuencia es [Informe P-L89 Raspberry Docker](informe_codex_p_l89_raspberry_docker.md).

Estado conocido de esa fotografía:

- dictamen `precondition_not_met` en el cierre operativo;
- Windows estaba detenido;
- la imagen ARM64 estaba construida, transferida y cargada;
- Compose candidato validaba, pero el env protegido aún apuntaba a la imagen anterior;
- los contenedores activos seguían usando `0.4.229-arm64`;
- el scheduler Raspberry estaba `unhealthy` y había presión de recursos;
- XNYS estaba abierto cuando se intentó cerrar la operación;
- no se hizo corte, no se arrancó la imagen candidata y no se declaró `deployed`;
- SQLite, WAL/SHM, `whale-copy`, otros discos y credenciales no se modificaron.

La etiqueta candidata `0.4.230-arm64` no significa que esté desplegada. Solo puede afirmarse `deployed` después de comprobar el stack real, configuración efectiva, exclusividad del scheduler, dos saludes separadas y ausencia de órdenes inesperadas.

## 9. Git, worktrees y versiones

```powershell
git status --short
git rev-parse HEAD
git rev-parse "HEAD^{tree}"
Get-Content src/agente_bolsa/__init__.py
```

Reglas:

- producción permanece limpia;
- desarrollo funcional y despliegue se preparan en worktrees `codex/<lote>` basados en un commit exacto;
- caracterización, implementación, QA y documentación usan commits separados;
- no hacer push salvo petición explícita;
- no usar reset destructivo;
- todo cambio funcional, UI, comportamiento o producto requiere bump de versión;
- documentación y tests no requieren bump salvo que lo exija la política;
- un árbol sucio bloquea la promoción hasta reconciliar cada archivo.

## 10. Diccionario de dictámenes

| Dictamen | Significado |
|---|---|
| `precondition_not_met` | Falta una condición de seguridad/operación; no ejecutar corte |
| `needs_fix` | Hay un fallo reproducible que requiere corrección |
| `ready_for_closed_market_deployment` | Candidato y gates preparados; falta una ventana cerrada |
| `partially_verified_*` | Solo una parte de la evidencia está verificada |
| `deployed` | Stack real arrancado y validado dos veces |
| `blocked` | El mismo bloqueo externo persiste tras tres turnos sin alternativa segura |

Siempre separar hechos verificados, inferencias y datos `unavailable`.

### Nota operativa: sonda de liveness ARM64

El healthcheck del scheduler candidato usa `scripts/container_scheduler_health.py`.
Valida lock/PID/proceso vivo y no abre SQLite ni ejecuta `schedule-status` completo;
esta ultima orden sigue siendo la comprobacion funcional del preflight. No se
debe declarar salud por un HTTP 200 de Streamlit ni por la sonda de liveness
aislada. La Raspberry continua en `0.4.229-arm64`; la lectura del 2026-08-13
mostro el scheduler healthy pero con 37 reinicios acumulados, pendiente de
rebuild ARM64 y de una validacion post-corte con `restart=0`.

## 11. Rollback

Si el candidato Raspberry falla:

1. no arrancar Windows simultáneamente;
2. detener solo el Compose de agenteBolsa Raspberry;
3. conservar logs, imagen, configuración y datos;
4. no restaurar una SQLite histórica a ciegas;
5. reanudar Windows únicamente mediante `scripts/stack_up.ps1`;
6. validar Windows con status, scheduler, broker, portfolio y health;
7. documentar motivo, hora, identidad de versión y hashes.

Nunca usar `docker system prune`, borrar `/opt/*`, borrar volúmenes ni tocar `/dev/mmcblk0p2` como limpieza de una migración.
