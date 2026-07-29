# Modelo operativo

## Principios

- Produccion opera en paper. Live y auto-apply requieren autorizacion humana.
- XNYS es la autoridad temporal.
- `unavailable` no significa cero; `collecting` no se interpreta.
- Telemetria observa y puede fallar abierta; kernel, riesgo, gates y kill switch
  fallan cerrados.
- Un LLM no aprueba su propia hipotesis ni concede permisos.

## Servicios gestionados

Las tareas `AgenteBolsaScheduler` y `AgenteBolsaWeb` usan el Python de `.venv`.
No se mantienen servicios iniciados manualmente.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
powershell -ExecutionPolicy Bypass -File scripts\stack_down.ps1 -IncludeScheduled
powershell -ExecutionPolicy Bypass -File scripts\stack_up.ps1
```

Un stack sano tiene un scheduler logico, PID/lock vivo, heartbeat fresco y HTTP
200. `schedule-status` por si solo no demuestra vida.

## Ciclo de mercado

1. Preflight de modo, kernel, calendario y datos.
2. Candidatos con identidad canonica.
3. Ranking y contexto pre-decision.
4. Decision y gates deterministas.
5. Controles desde planes/rechazos reales.
6. Planes finales y, si procede, ordenes paper.
7. Telemetria sin reejecutar decisiones.

Decision context, gate path, comparable controls y execution quality no cambian
ranking, gates, cantidades ni ordenes.

Las integraciones externas deben exponer interfaces y snapshots canónicos del
dominio. Los SDK y payloads propios de cada proveedor quedan confinados en
adaptadores; reconciliación, eventos y notificaciones no importan tipos del
proveedor. Así se puede sustituir el proveedor sin tocar trading, riesgo ni
consumidores.

## Portfolio watch y salidas

`portfolio_watch` revisa posiciones durante XNYS abierto. Stop-loss, take-profit
y trailing preceden al time-stop.

- Activa: `legacy_calendar_days`.
- Shadow: cinco sesiones XNYS posteriores al fill.
- Autoridad: buy order exacta y `first_fill_at`; parcial sin primer fill queda
  `unavailable`.
- Historia append-only por lote; runtime state es latest view.

Shadow nunca crea, bloquea o retrasa ordenes.

## Postmarket

1. Lease/coordinacion por sesion.
2. Reconciliacion interna unica.
3. Una actualizacion de outcomes.
4. Aprendizaje reutilizando ese resultado.
5. Informe y performance benchmark.
6. Gates, scoreboard, cohortes e investigacion.
7. Digest, watchdog y tesis.
8. Terminal `completed|failed|skipped`.

P-L45B1 coordina bootstrap/scheduler/reconciliacion y evita terminales huerfanos.
P-L45B2 prepara fuera de SQLite y escribe observations en chunks de 250, una
transaccion corta por chunk.

No ejecutar postmarket/reconciliacion manual para reparar una sesion.

## Evidencia y promocion

- Outcomes maduran por sesiones posteriores; fills/P&L no sustituyen forward.
- Hipotesis y criterios se pre-registran.
- Linaje, control, cobertura, muestra, concentracion y madurez bloquean readiness
  si son insuficientes.
- Orden: `shadow -> guarded_active -> active`.
- Mejor retorno con peor drawdown/MAE/tail loss no se promociona.
- Apply y configuracion sensible siguen human-gated.

## Desarrollo con XNYS abierto

Solo worktrees aislados, DATA_DIR temporal, `_env_file=None`, reloj congelado y
sin broker/red/LLM/servicios. No merge, reinicio ni despliegue.

Usar `.venv` productiva con `PYTHONPATH=<worktree>/src`; el interprete global
puede validar dependencias o codigo incorrectos.

## Integracion y despliegue

1. Caracterizacion.
2. Implementacion separada.
3. QA adversarial y merge `--no-ff`.
4. Suite/Ruff/NUL/diff/config/kernel/smoke aislado.
5. Despliegue cerrado, sin jobs activos y con rollback por revert.
6. Arranque por tareas y dos comprobaciones de salud.
7. Varias sesiones de observacion antes de interpretar.

Candidatos paralelos reservan versiones diferentes; no squash/rebase/amend
commits validados.

## Comandos de lectura

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
.\.venv\Scripts\python.exe -m agente_bolsa.main production-health --json
.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health --json
```

Auditorias SQLite usan URI `mode=ro` y no reconstruyen IDs por simbolo/fecha.
