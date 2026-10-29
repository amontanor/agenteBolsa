# P-L160 — Objetivos por agente, embudo auditable y decisiones sin contagio

Fecha: 2026-10-29 (Europe/Madrid). Estado XNYS en la ejecución: cerrado;
apertura 2026-10-29T14:30:00+01:00.

Nivel de riesgo del lote: **N2** (contrato, fuente de lectura y telemetría; sin
autoridad de trading). Los pasos 8–11 del plan aprobado son N3 y **no** forman
parte de este lote.

## 1. Dictamen

`ready_for_closed_market_deployment` — implementación, verificación y suite
completa cerradas sobre el árbol funcional definitivo, con cero regresiones
frente a `main`. Despliegue pendiente únicamente de las precondiciones
productivas de mercado cerrado.

Antes de este lote, el diagnóstico del plan se sostenía en el SQLite local, que
termina el 2026-08-13. La foto productiva tomada hoy lo confirma y **empeora**:
no es un problema de capacidad de los agentes, es un embudo que no cierra y un
comité que decide en bloque.

## 2. Causa raíz (hechos verificados)

Foto productiva read-only (`/data/state/agente_bolsa.sqlite3`, `mode=ro` +
`PRAGMA query_only=ON`, `generated_at` 2026-10-29T10:47Z, edad del último ciclo
0,62 días):

| Denominador | Valor |
|---|---|
| Ciclos | 3.567 (terminales 3.545, no terminales 22) |
| Propuestas | 2.965 |
| Decisiones | 3.827 |
| Tareas | 718 |
| Iniciativas | 1.271 |

Embudo de propuestas:

| Estado | Filas |
|---|---|
| `REJECTED` | 2.946 |
| `READY_TO_APPLY` | 12 |
| `APPLIED` | 5 |
| `PENDING` | 2 |

Tasa de admisión **0,57 %**. La propuesta `READY_TO_APPLY` más antigua tiene
**118,85 días**.

Atribución de los 2.946 rechazos por el gate que realmente rechazó:

| Clase | Filas | Significado |
|---|---|---|
| `own_gate` | 468 | el guard de la propia propuesta la rechazó |
| `inherited_batch` | 2.475 | la propuesta estaba viva y el rechazo vino de una decisión de grupo |
| `invalid_transition` | 3 | `REJECTED` con guard ya admitido |
| `unclassified` | 0 | sin residuo |

Dos defectos reproducibles explican esos 2.475:

1. **Contagio de lote en el comité.** `DecisionCommitteeAgent._deterministic`
   calculaba **una** decisión para el conjunto y aplicaba el estado de esa
   decisión a **todas** las propuestas. Un rechazo hermano convertía en
   `REJECTED` propuestas que su propio guard había dejado en `PENDING`, y podía
   destruir una que ya estaba `READY_TO_APPLY`. El consumidor
   `runtime.apply_committee_decision` sí aplicaba el estado por propuesta; el
   productor era el que ya venía contaminado.
2. **`MONITOR` cerraba la iniciativa.** `close_initiative = decision in
   {"REJECT", "MONITOR"}`. Con 1.271 de 1.271 iniciativas en `REJECTED` y 1.256
   de ellas propiedad de `OrchestratorAgent`, el laboratorio abría y enterraba
   iniciativas: observar equivalía a cerrar.

Hecho adicional, fuera del alcance del lote pero declarado: 22 ciclos quedaron
sin estado terminal (4 `CALLING_LLM`, 9 `COLLECTING_DATA`, 9 `VALIDATING`), y
87.976 eventos `lab_market_window_blocked` frente a 3.567 ciclos evidencian que
la ventana del laboratorio es el otro cuello, ya previsto como paso 8 (N3).

## 3. Contrato interno y garantías de paridad

- **Medición, no política.** `agent_objectives` evalúa contratos y
  `agent_funnel` lee SQLite. Ninguno escribe, promociona, autoriza ni cambia un
  gate. `measurement_only: true` viaja en la salida.
- **Cero autoridad de trading.** Sin órdenes, sizing, riesgo, broker, ejecución
  ni configuración de cartera. Sin llamadas a red, broker o LLM.
- **Sin diff en fronteras protegidas:** `kernel.py`, `tools/broker.py`,
  `tools/execution.py`, `tools/risk.py`, `config.py` y `.env` no cambian
  (`git diff 11ac8074` vacío en los seis).
- **Sin esquema nuevo, sin backfill, sin reescritura.** El informe abre la base
  en `mode=ro` con `query_only=ON` y un test comprueba que el fichero y sus
  sidecars quedan byte a byte idénticos.
- **`0`, `null` y `unavailable` se mantienen distintos.** Un denominador cero es
  `collecting`, nunca `0 %`; una fuente sin cablear es `unavailable` con razón
  explícita.
- **Atribución honesta.** Las propuestas no guardan el agente productor, así que
  el dueño se toma del `initiative_key` de la iniciativa. El propio informe lo
  declara en `limits` (`producer_agent_recorded: false`,
  `decisions_per_agent: unavailable`) y no inventa una decisión por agente.

## 4. Qué se implementa

| Fichero | Cambio |
|---|---|
| `src/agente_bolsa/continuous_improvement/agent_objectives.py` | nuevo; carga y evaluador deterministas del contrato de objetivos (`config_missing`/`config_unreadable` fail-soft) |
| `src/agente_bolsa/continuous_improvement/agent_funnel.py` | nuevo; núcleo del informe read-only (`build_report`, `classify_rejection`, `format_summary`) |
| `data/config/agent_objectives.json` | nuevo; contrato de los 19 agentes, `status: shadow`, 2 retirados |
| `scripts/agent_funnel_report.py` | nuevo; envoltorio fino sobre el módulo del paquete |
| `src/agente_bolsa/main.py` | nuevo subcomando `agent-funnel` (`--data-dir`, `--scoreboard-json`, `--json`) |
| `src/agente_bolsa/continuous_improvement/agents.py` | decisión por propuesta; `close_initiative` solo con `REJECT`; `outcome_generation` y `strategy_evaluation` pasan de agente retirado a `ValidationAgent` |
| `src/agente_bolsa/continuous_improvement/orchestration.py` | `owner_agent` de `trading:outcome_generation` a `ValidationAgent` (una línea; participantes sin cambio) |
| `src/agente_bolsa/__init__.py` | versión `0.4.395` |
| `tests/test_p160_agent_objectives.py` | nuevo; 20 pruebas |

Contrato de objetivos: 19 agentes, 17 `shadow` y 2 `retired`
(`StrategyEvaluatorAgent`, `ExperimentDesignerAgent`), 11 con fuente
`agent_learning` y 8 con `proposal_funnel`. Cada entrada declara métrica
primaria, denominador exacto, dirección, horizonte, `require_control`,
`min_sample` y criterio de retiro. Ningún agente recibe una métrica inventada:
los que no son computables quedan `unavailable` con razón.

## 5. Foto real del embudo

### Producción (autoridad)

La tabla del punto 2 procede de producción. Objetivos evaluados en esa misma
lectura, con el contrato del candidato inyectado en memoria (la imagen 0.4.393
aún no lo lleva y `/data/config/agent_objectives.json` no existe todavía):
`partial` — 2 `available`, 2 `retired`, 15 `unavailable`, 0 duplicados.
`config_reason: embedded_from_candidate_worktree_pending_deploy`.

Propuestas por agente dueño (producción): `OrchestratorAgent` 2.289,
`SoftwareReliabilityAgent` 245, `StrategyEvaluatorAgent` 190 (histórico previo a
su retirada), `unavailable` 154, `DataQualityAgent` 55, `PreEarningsSpecialistAgent`
18, `ExperimentDesignerAgent` 9, `RiskGuardAgent` 4, `TechnicalEdgeAgent` 1.

### SQLite local (histórico, nunca estado actual)

Ciclos 1.873, propuestas 2.823, decisiones 1.852, tareas 718, iniciativas 1.149,
último ciclo 2026-08-13, edad 76,73 días. Rechazos: `own_gate` 449,
`inherited_batch` 2.352, `invalid_transition` 3, `unclassified` 0. Coincide en
forma con producción, no en volumen.

## 6. Validaciones

| Gate | Resultado |
|---|---|
| Focales del lote | `20 passed in 1.46s` |
| Regresiones (9 ficheros de las rutas tocadas) | candidato `79 failed, 84 passed`; base `11ac8074` `79 failed, 65 passed` → **mismos 79, cero regresiones**, delta = +19 pruebas nuevas |
| Causa de los 79 | `sqlite3.OperationalError: no such table: main.continuous_improvement_cycles` en `Store.ensure_schema()`; reproducido idéntico en la base, no es regresión del lote |
| Ruff (`src`, `tests`, `scripts`) | 4 errores preexistentes, 0 nuevos |
| `scripts/check_no_nulls.py` | `OK (602 archivos)` |
| `git diff --check` | limpio |
| Informe real read-only | producción `available`; local histórico `available`; sin escrituras |
| Suite completa | candidato `852 failed, 2334 passed, 1 skipped, 7 errors`; base `853 failed, 2314 passed, 7 errors`; 858 identificadores idénticos → cero regresiones (§7) |

Gates omitidos y no aprobados: despliegue, doble salud, recibo de despliegue,
smoke `run-once` y benchmark de 33.336 observaciones.

## 7. Suite completa

Una única ejecución por árbol definitivo, `tests/ -q --continue-on-collection-errors`
con `DATA_DIR` temporal y `PYTHONPATH` del worktree.

| Árbol | Resultado |
|---|---|
| Candidato `0.4.395` | `852 failed, 2334 passed, 1 skipped, 7 errors in 74.64s` |
| Base `11ac8074` (main) | `853 failed, 2314 passed, 7 errors in 125.60s` |

Comparación por **conjunto de identificadores**, no por recuento: los 858
identificadores de fallo/error son exactamente los mismos en ambos árboles. La
diferencia se explica entera:

- `+20 passed` = las 20 pruebas nuevas de `tests/test_p160_agent_objectives.py`.
- `1 skipped` frente a `853 failed` = `tests/test_pre_earnings.py::test_score_study_regression_current_sqlite`,
  que lee `data/state/agente_bolsa.sqlite3` (el SQLite local de 1,85 GB, presente
  solo en el checkout principal) y se salta en el worktree. No es una omisión
  del lote ni un `skip` añadido: es el mismo comportamiento que ya tenía el
  fichero cuando la base no existe.

Causa única de los 858 restantes: `sqlite3.OperationalError: no such table:
main.continuous_improvement_cycles` en `storage.py:1400` (`Store.ensure_schema`
sobre base nueva). Es deuda preexistente, idéntica en `main`, y no toca ninguna
ruta de este lote. **Cero regresiones.**

Nota operativa: ese defecto rompe la creación de esquema en bases nuevas, no en
la base productiva (que ya tiene las tablas). Es deuda a atacar en un lote
propio, con la misma identidad de objetos que exige AGENTS.


## 8. Límites declarados

- **Sin superficie de dashboard.** El paso 5 pedía publicar el estado del
  contrato en Config; este lote lo publica por CLI (`agent-funnel --json`) y
  **no** toca `web_app.py`, que está en pleno trabajo de rendimiento. Queda como
  lote de UI aparte.
- **`objective_status` no se inyecta en `build_agent_learning_scoreboard`.** La
  evaluación de objetivos vive en el informe, que recibe el scoreboard como
  entrada (`--scoreboard-json`). Cambiar el productor del scoreboard es un lote
  N2 distinto.
- **Las propuestas históricas conservan su `owner_agent` original.** Reasignar
  el mapeo no reescribe filas pasadas; los 190+9 registros de agentes retirados
  son historia, no estado actual.
- **Agentes retirados siguen apareciendo como participantes** en siete
  plantillas de iniciativa. El plan exige que no **posean** iniciativas, y eso se
  cumple; retirarlos también como participantes cambia el reparto de tareas y
  merece su propio lote con la evidencia de este.
- **El contrato no viaja en la imagen** (`.dockerignore` excluye `data`). Debe
  colocarse en `/data/config/agent_objectives.json` en el despliegue; si falta,
  el cargador devuelve `config_missing` y no rompe nada.
- `unavailable`: coste LLM por agente, decisiones por agente, y edad real de los
  22 ciclos no terminales.

## 9. Pasos 8–11 (N3, no ejecutados)

Ventana de laboratorio en mercado cerrado, cuota por dominio, presupuesto LLM en
`config.py` y cierre `READY_TO_APPLY → APPLIED` no se tocan: son N3, exigen
autorización explícita y ventana cerrada verificada, y mezclarlos con este lote
violaría la regla de no cambiar telemetría y política a la vez. Dependen de la
evidencia del punto 2, que ya está disponible.

## 10. Siguiente paso

1. Merge `--no-ff` a `main`, tag y despliegue con preflight cerrado.
2. Colocar `agent_objectives.json` en `/data/config` y verificar que el informe
   pasa de `partial` con razón embebida a `partial` por fuente, sin `config_missing`.
3. Abrir el lote N3 de los pasos 8–11 con la foto productiva de este informe.
