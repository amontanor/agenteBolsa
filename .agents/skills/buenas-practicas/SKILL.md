---
name: buenas-practicas
description: >
  Convenciones, seguridad y Definition of Done de agenteBolsa. Usar al crear o
  revisar codigo, tests, configuracion, estrategias, documentacion, versiones,
  worktrees, integraciones y despliegues.
---

# Buenas practicas — agenteBolsa

## 1. Codigo y configuracion

- El codigo fuente vive en `src/agente_bolsa/`; los tests en `tests/`.
- Identificadores en ingles; mensajes y logs para el operador en espanol.
- Parametros operables pertenecen a `Settings`, con alias en mayusculas y
  ejemplo documentado. No hardcodear thresholds de trading.
- No modificar `.env` para hacer pasar una prueba o gate.
- Todo subsistema consultable expone CLI `--json` cuando aporta valor operativo.

## 2. Persistencia SQLite

- Acceder mediante `Store` en `storage.py`.
- Reutilizar tablas/bloques JSON antes de crear otro esquema. No hacer backfill
  ni reescritura historica sin autorizacion expresa.
- Evidencias historicas son append-only: repeticion identica es no-op; contenido
  distinto conserva el original y crea conflicto. No usar `INSERT OR REPLACE`.
- Preparar, validar y serializar fuera de SQLite.
- Mantener `BEGIN IMMEDIATE` y transacciones durante el minimo imprescindible.
- Para volumen, usar chunks cortos y memoria acotada. Nunca una conexion por fila
  ni una transaccion global que incluya calculo externo.
- Auditorias: URI `mode=ro`, `query_only=ON`, sin reparaciones implicitas.

## 3. Identidad, eventos y temporalidad

- Nada importante sucede sin evento durable.
- Runs efimeros pueden usar `new_id(prefix)`; snapshots idempotentes usan IDs y
  hashes deterministas derivados de identidad canonica y version de contrato.
- Todo `started` termina en `completed`, `failed` o `skipped`.
- `runtime_state` es vista operativa/latest; `agent_events` conserva historia.
- No unir por simbolo/fecha si puede existir ambiguedad. Missing permanece
  `unavailable`; nunca se inventa `UNKNOWN` ni se convierte en cero.
- Separar pre-decision, decision-time y post-decision. Fills/P&L no sustituyen
  retornos forward y no entran en features pre-decision.
- Calendario XNYS y sesiones estrictamente posteriores son la autoridad cuando
  el contrato habla de sesiones.

## 4. Tests aislados

- Sin red, broker real, LLM, yfinance ni servicios productivos.
- Usar el Python del proyecto y `PYTHONPATH=<worktree>/src`; nunca el interprete
  global ni el editable de otra rama.
- Usar `DATA_DIR` temporal, `_env_file=None`, configuracion explicita y reloj
  congelado. No leer `.env`, SQLite o informes productivos.
- Concurrencia mediante barreras deterministas, no sleeps arbitrarios.
- Cubrir idempotencia, conflictos, legacy, fallos intermedios, retry y paridad.
- No ocultar fallos con skip/xfail. Un fallo preexistente se reproduce contra la
  base y se clasifica antes de tocar codigo.

## 5. Definition of Done

1. `python -m pytest tests/ -x -q` verde.
2. `ruff check src tests` verde.
3. `scripts/check_no_nulls.py` y `git diff --check` verdes.
4. `status`, `validate-agent-config --json` y `kernel-status --json` coherentes.
5. Smoke `run-once --skip-crew` con DATA_DIR/proveedores temporales.
6. Paridad de trading si se toca una ruta compartida.
7. Plan maestro e informe unico del lote actualizados.

Con XNYS abierto no ejecutar smoke, job-once, postmarket, reconciliacion o broker
contra produccion.

## 6. Archivos protegidos

Sin revision humana explicita no tocar:

- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`
- `.env`

`kernel-status=unsealed` en un DATA_DIR temporal no describe produccion. Repetir
desde raiz, `.venv` y DATA_DIR productivos; nunca copiar/re-sellar el manifest
para ocultar una diferencia.

## 7. Worktrees, Git y versiones

- Produccion permanece limpia. Trabajar en worktree `codex/<lote>` basado en un
  commit exacto.
- Caracterizacion, implementacion, QA y documentacion usan commits separados.
- Integrar con `merge --no-ff`; no squash/rebase/amend commits ya validados.
- Candidatos paralelos reservan patches distintos y se renumeran si cambia el
  orden. No puede haber dos releases con la misma version.
- Rollback productivo mediante revert auditable, nunca reset destructivo.
- Preservar cambios ajenos y detenerse ante un arbol inesperadamente sucio.

## 8. Mercado abierto y despliegue

- Con XNYS abierto se permite trabajo aislado, sin acceso operativo, merge,
  reinicio, despliegue ni mutacion de datos/servicios.
- Desplegar solo con XNYS cerrado, sin jobs/pytest activos y con margen operativo.
- Parar/arrancar mediante tareas y `scripts/stack_*.ps1`, no procesos manuales.
- Tras arrancar: HTTP 200, scheduler unico, PID/lock vivo y heartbeat fresco en
  dos comprobaciones separadas.
- Telemetria puede fallar abierta; gates, riesgo, kernel y kill switch fallan
  cerrados. Shadow nunca crea, bloquea o retrasa ordenes.

## 9. Promocion de mejoras

- Orden: `shadow -> guarded_active -> active`.
- Exigir evidencia pre-registrada, costes, OOS/walk-forward, paper, muestra,
  clusters, concentracion, linaje y control.
- No promover `collecting`, `unavailable` ni resultados legacy no verificados.
- Mejor retorno con peor drawdown, MAE o tail loss no se promociona.
- Un LLM no decide readiness ni autoriza apply/configuracion.

## 10. Documentacion activa

- `docs/plan_mejoras_y_tareas.md`: unica fuente de backlog/estado.
- `docs/RELEVO_DIRECCION_TECNICA.md`: estado y secuencia del siguiente turno.
- `docs/operating_model.md`: modelo operativo.
- `docs/tutorial_arranque_diario.md` y `docs/startup_runbook.md`: operacion.
- `docs/promotion_checklist.md`: promocion.
- Un unico informe por lote; no crear planes paralelos.

## 11. Rigor proporcional por nivel (P-L86Q)

Antes de empezar, asigna el lote al nivel de riesgo más alto que toque:

- **N0:** documentación, copy o formato sin cambio de contrato.
- **N1:** UI/presentación aislada, sin nueva fuente, persistencia, proceso ni
  efecto operativo.
- **N2:** contrato, fuente, carrier, identidad, temporalidad o persistencia sin
  cambio de autoridad de trading.
- **N3:** trading, riesgo, archivos protegidos, configuración o despliegue.

Presupuesto blando mínimo: N0 revisión y `git diff --check`; N1 focales de la
UI, Ruff/NUL y diff; N2 caracterización, focales, regresiones y gates
proporcionales; N3 Definition of Done completa, preflight cerrado, paridad,
integración y doble salud. Si surge una dependencia nueva, persistencia o
esquema, proceso/servicio, frontera protegida, riesgo no clasificado o el
trabajo supera 2x el presupuesto, detén y consulta.

Solo cuenta una suite completa por árbol funcional final. Puede heredarse
evidencia previa si la identidad del árbol/objetos está demostrada y los cambios
posteriores son exclusivamente no semánticos. Un cambio semántico o en una ruta
compartida obliga a repetir los gates afectados; no se usan omisiones para
ocultar fallos.
