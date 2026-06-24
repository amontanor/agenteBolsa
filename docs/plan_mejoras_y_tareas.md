# Plan maestro de mejoras y tareas — agenteBolsa

> **Este documento es la fuente unica de verdad de la mejora del sistema.**
> Contiene la vision, lo ya ejecutado, el diagnostico vigente, las tareas con su
> estado (terminado / no terminado) y las propuestas siguientes.
> **Toda mejora futura se gestiona anadiendo pasos AQUI** (no en hilos sueltos ni
> en otros documentos). Cada entrega debe: (1) anadir/actualizar su paso en este
> fichero con su estado, (2) subir la version en `src/agente_bolsa/__init__.py`
> (se muestra en la barra lateral del dashboard), y (3) dejar el sistema levantado
> con los cambios cargados (ver seccion 7).

- Rama: `codex/mejora_continua`
- Version actual: **0.4.0** (0.1.13 -> 0.2.0 -> 0.3.0 -> 0.4.0)
- Ultima actualizacion: 2026-06-16
- Modo operativo: paper (Alpaca paper). Live trading bloqueado por diseno.

---

## 1. Vision y punto de vista

El objetivo no es "operar con un LLM", sino sostener un grupo de agentes que
investiga, detecta oportunidades, aprende de aciertos y errores, genera hipotesis
falsables, las prueba en sandbox y solo promueve cambios cuando hay evidencia.

Principios:

- **Autonomia alta** en investigacion, aprendizaje, paper trading y mejora continua.
- **Autonomia baja** en ejecucion real, credenciales, broker, sizing critico y live.
- No aceptar narrativas sin evidencia y trazabilidad.
- Promover por evidencia (champion/challenger, shadow) antes que por intuicion.
- Proteger siempre el nucleo (`broker.py`, `execution.py`, `risk.py`, `config.py`,
  kernel inmutable).

El sistema debe comportarse como un equipo buy-side disciplinado: investiga,
documenta, contrasta, prueba, aprende y solo entonces cambia.

---

## 2. Estado real a 2026-06-16 (contrastado con datos)

El plumbing esta vivo (scheduler corriendo, jobs completados, reportes generados),
pero **varias capas estan construidas pero inertes** y, sobre todo, **el sistema
lleva ~10 dias sin operar de verdad**. Resumen de evidencia:

- Equity paper ~70.676 USD, practicamente plano (variacion ~-21 USD en 14 dias).
- `executed_observations: 0` sobre 19.940 observaciones; `duplicate_ratio` 0,90.
- Solo 32 `broker_orders` en toda la historia, **todas en `PENDING_NEW`** (sin
  reconciliacion de estado final).
- `research_evidence`: **0 filas**; `latest_research_evidence.json` no existia.
- Laboratorio: **0 cambios de codigo aplicados**, 1.092 propuestas RECHAZADAS,
  1.203 validaciones PENDING, 0 reglas activas (13 en shadow), 0 strategy_versions,
  0 distilled_lessons. Las 677 decisiones de `promotion_gate` estan todas en
  `approved=0`.
- BD de estado: **6,9 GB** con freelist ~0 (no es espacio libre: es fragmentacion
  por UPDATEs repetidos; el contenido real es ~750 MB).

### 2.1 Diagnostico: por que NO entramos ni salimos en un dia alcista

Causa raiz encadenada (de mas a menos critica):

1. **El LLM de decision y el de sentimiento llevan caidos desde ~6-jun.** En
   `llm_usage` no hay una sola llamada de `trade_decision` ni `news_sentiment`
   despues del 6-jun. El proveedor primario se cambio a **MiMo**
   (`mimo-v2.5-pro`, xiaomimimo.com) y falla (262 `continuous_improvement_llm_failed`);
   el fallback local **qwen3.6-27b** (`127.0.0.1:8080`) tampoco responde. Resultado:
   el sistema opera en **fallback determinista silencioso**.
2. **El fallback determinista es muy estrecho:** propone un unico candidato "strong"
   (HSIC) cada 15 min, con la razon literal *"Fallback determinista por fallo del
   LLM"*. No evalua los lideres reales del dia (QQQ, XLK +8,8%, etc.). Ademas HSIC
   estaba sobrecomprado (RSI 82, volumen z -2,33).
3. **El backtest-gate rechaza ese unico candidato cada ciclo:** *"regimenes
   negativos 2 > maximo 1 con minimo 2 trades"*. Por tanto `approved_buys = []` y
   `rejected = 0` (ni siquiera llega a plan de orden).
4. **Sentimiento vacio:** los 24 simbolos quedan marcados `material_risk=true` con
   `sentiment_score: null` (el LLM de sentimiento no corre), restando soporte a
   cualquier compra.
5. **Politica de regimen defensiva:** `profile=neutral`, `size_multiplier=0.5`,
   `requires_micro_experiment=true`, que estrangula aun mas la operativa.

En una frase: **el grupo de agentes esta efectivamente sin cabeza** (LLMs caidos),
funcionando con un fallback minimo que los propios gates rechazan. Por eso un dia
alcista no produjo ninguna entrada ni salida.

---

## 3. Mejoras YA ejecutadas

### 3.1 Heredadas (anteriores a este plan) — TERMINADO

- Pipeline de aprendizaje real (signal_outcomes, memorias por setup/simbolo).
- Shadow rules y walk-forward presentes.
- Sandbox de codigo integrado y autonomia por niveles.
- Mejora continua con iniciativas/propuestas/validaciones.
- Dashboard amplio (Research Inbox, Learning Lab, Code Changes, Strategy Lab,
  Agent Roster, etc.).
- Tuning adaptativo funcional (`adaptive_config.json`; p.ej. endurecimiento de
  `LLM_EXIT_EXCEPTION_*` tras post-market review). **Esta es la unica
  auto-modificacion que hoy funciona end-to-end.**

### 3.2 Entregadas en esta iteracion (2026-06-16)

| # | Mejora | Artefacto | Estado | Verificacion |
|---|--------|-----------|--------|--------------|
| E1 | Subida de version 0.1.13 -> 0.2.0 | `src/agente_bolsa/__init__.py` | TERMINADO | Fuente unica; se ve en sidebar |
| E2 | Chequeo de salud del LLM (aborda causa raiz) | `scripts/llm_health_check.py` | TERMINADO | Ejecutado: detecta primario y fallback caidos |
| E3 | Mantenimiento de BD (retencion + VACUUM, dry-run por defecto) | `scripts/db_maintenance.py` | TERMINADO | Ejecutado dry-run contra BD real; logica validada |
| E4 | Informe semanal de mejora (markdown desde BD) | `scripts/weekly_improvement_report.py` | TERMINADO | Ejecutado end-to-end; genera informe correcto |
| E5 | Refresco de evidencia externa (poblar tabla + json) | `scripts/refresh_research_evidence.py` | HECHO, PENDIENTE EJECUCION en venv | Compila; requiere .venv del proyecto para correr |
| E6 | Reconciliacion de estado de broker_orders contra Alpaca | `scripts/reconcile_broker_orders.py` | HECHO, PENDIENTE EJECUCION en venv | Compila; requiere .venv + credenciales Alpaca |
| E7 | Este documento maestro + fuente de verdad | `docs/plan_mejoras_y_tareas.md` | TERMINADO | — |
| E8 | Punteros de fuente de verdad | `README.md`, `docs/versioning.md` | TERMINADO | — |

> Nota: E2–E6 son **scripts/herramientas** deliberadamente desacoplados del
> proceso del scheduler para NO arriesgar el sistema en marcha. La integracion de
> E5/E6 como jobs programados es una tarea siguiente (ver seccion 5, T3 y T5).

### 3.3 Entregadas en la iteracion 0.3.0 (2026-06-16) — resiliencia y oportunidades

Objetivo: que **el grupo de agentes funcione bien aunque el LLM falle** y que el
sistema vea **las mejores oportunidades** de forma determinista.

| # | Mejora | Artefacto | Estado | Verificacion |
|---|--------|-----------|--------|--------------|
| E9 | Motor determinista de ranking de oportunidades (RS vs benchmark, tendencia, momentum, extension, volumen; stop por ATR) | `src/agente_bolsa/tools/opportunity_ranker.py` | TERMINADO | 6 tests unitarios verdes + ejecutado sobre snapshot real |
| E10 | Watchdog de LLM degradado (detecta grupo "sin cabeza" desde la BD y emite alerta accionable) | `src/agente_bolsa/tools/llm_degraded_watchdog.py` | TERMINADO | 4 tests verdes + ejecutado: detecta CRITICAL (LLM caido 246h) |
| E11 | Runner combinado salud + oportunidades (escribe `latest_agents_healthcheck.json` y `latest_opportunities.json`) | `scripts/agents_healthcheck.py` | TERMINADO | Ejecutado end-to-end contra BD y snapshot vivos |
| E12 | Tests unitarios de E9 y E10 | `tests/test_opportunity_ranker.py`, `tests/test_llm_degraded_watchdog.py` | TERMINADO | 10/10 verdes en sandbox |
| E13 | Version 0.2.0 -> 0.3.0 | `src/agente_bolsa/__init__.py` | TERMINADO | Compila; visible en sidebar tras reinicio |

Diseno: el nucleo (E9/E10) son modulos **sin dependencias pesadas** (solo stdlib),
asi que el runtime del proyecto puede importarlos sin riesgo y son testables de
forma aislada. NO se ha editado `scheduler.py`/`cycle_runner.py` (codigo de
arranque del sistema vivo que no puede validarse en este entorno); la activacion
como job se entrega como hook listo en la seccion 4.1.

Hallazgo adicional al ejecutar E11: el `market_snapshot_*.json` solo cubre ~9
megacaps, no el universo amplio. Para que el ranking surta candidatos de verdad
hay que alimentarlo con el scan amplio (breakout_scan / closed_market_technical_study).
Queda como tarea T11.

### 4.1 Hook de integracion como job (listo para pegar)

Para activar la vigilancia automatica del grupo de agentes, anadir en
`scheduler.py` un job que llame al runner (import perezoso y envuelto en
try/except para no afectar al arranque):

```python
def agents_healthcheck_job(settings, store, reporter, run_id):
    """Vigila modo degradado del LLM y publica mejores oportunidades."""
    try:
        from agente_bolsa.tools.llm_degraded_watchdog import evaluate
        from agente_bolsa.tools.opportunity_ranker import rank_opportunities
        wd = evaluate(settings.database_path)
        if wd.get("degraded"):
            reporter.emit(
                "orchestrator", "llm_degraded_alert", run_id,
                "Grupo de agentes en modo degradado (LLM de decision no disponible).",
                wd,
            )
        # rank_opportunities(snapshot, top_n=15) -> publicar en data/reports
    except Exception as exc:  # noqa: BLE001 - la vigilancia nunca debe romper el ciclo
        reporter.emit("orchestrator", "agents_healthcheck_failed", run_id, str(exc), {})
```

Registrar con la cadencia deseada (p.ej. cada 30 min en mercado abierto). Mientras
no se integre, se puede ejecutar a mano o por el cron del SO:
`python scripts/agents_healthcheck.py`.

### 3.4 Entregadas en la iteracion 0.4.0 (2026-06-16) — integracion en el sistema

Incidente previo: al editar `scheduler.py` por una via insegura (lectura truncada
del mount) se corrompio el fichero y se perdieron cambios sin commitear de
`scheduler.py`; se restauro y Codex re-integro `overnight_learning_heartbeat`.
Leccion aplicada: los ficheros grandes del nucleo se editan SOLO con la
herramienta de ficheros (escritura segura), nunca leyendo+reescribiendo por bash.

| # | Mejora | Artefacto | Estado | Verificacion |
|---|--------|-----------|--------|--------------|
| E14 | **T1b**: job `agents_healthcheck` registrado en el scheduler (cada 30 min, configurable) que emite `llm_degraded_alert` y publica oportunidades | `tools/agents_healthcheck.py` (nuevo), `scheduler.py` (job + add_job), `config.py` (`AGENTS_HEALTHCHECK_INTERVAL_MINUTES`) | HECHO, pendiente test suite + reinicio | Modulo nuevo compila; ediciones de scheduler/config verificadas en disco; pendiente `pytest` en el entorno con deps |
| E15 | **T11**: ranking sobre el universo amplio (~500 simbolos) via adaptadores del estudio tecnico / breakout scan | `tools/opportunity_ranker.py` (`snapshot_from_technical_study`, `snapshot_from_breakout_scan`) | TERMINADO | Ejecutado: surge CCL, MGM, HPE, DAL/UAL con fuerte RS |
| E16 | **T2b**: el fallback determinista reordena candidatos por score de oportunidad (RS/momentum/tendencia), bajo flag **OFF por defecto** | `tools/opportunity_ranker.py` (`prioritize_candidates`), `trade_decision.py` (hook flag-gated), `config.py` (`OPPORTUNITY_RANKER_FALLBACK_ENABLED`) | HECHO, flag OFF; pendiente validacion shadow | 11/11 tests del motor verdes; hook verificado en disco; NO cambia conducta hasta activar el flag |
| E17 | Version 0.3.0 -> 0.4.0 | `src/agente_bolsa/__init__.py` | TERMINADO | Compila; visible en sidebar tras reinicio |

Cómo activar T2b (cuando se quiera, tras validar): poner en `.env`
`OPPORTUNITY_RANKER_FALLBACK_ENABLED=true` y reiniciar. Recomendado observarlo
primero en paper/shadow.

Pasos para dejarlo corriendo con estos cambios:

1. `pytest` en el entorno del proyecto (deben seguir verdes, incluidos los nuevos).
2. Reiniciar panel web + scheduler (seccion 7) para cargar el job y la v0.4.0.
3. Verificar en `schedule-status` que aparece `agents_healthcheck` y, si el LLM
   esta caido, que se emite `llm_degraded_alert` y se escribe
   `data/reports/latest_opportunities.json`.

---

## 4. Como ejecutar lo entregado (operativa)

Desde la raiz del proyecto, con el `.venv` del proyecto:

```powershell
# 1) Diagnostico de la causa raiz (LLM). Exit code 1 = ningun LLM de decision.
.\.venv\Scripts\python.exe scripts\llm_health_check.py

# 2) Mantenimiento de BD: primero dry-run (seguro con sistema arriba)
.\.venv\Scripts\python.exe scripts\db_maintenance.py --days 120
#    Compactar de verdad (PARAR el scheduler antes):
.\.venv\Scripts\python.exe scripts\db_maintenance.py --vacuum-only

# 3) Informe semanal de mejora
.\.venv\Scripts\python.exe scripts\weekly_improvement_report.py --days 7 --out data\reports\weekly_improvement.md

# 4) Poblar evidencia externa (deja latest_research_evidence.json)
.\.venv\Scripts\python.exe scripts\refresh_research_evidence.py

# 5) Reconciliar ordenes con Alpaca (dry-run; --apply para persistir)
.\.venv\Scripts\python.exe scripts\reconcile_broker_orders.py
```

---

## 5. Tareas siguientes (backlog priorizado)

Estado: PENDIENTE salvo indicacion. Marcar aqui al completarlas.

| # | Tarea | Por que | Riesgo | Estado |
|---|-------|---------|--------|--------|
| T0 | **Restaurar el stack LLM**. Validar con `llm_health_check.py`. | Es la causa nº1 de no operar. Sin LLM no hay comite ni sentimiento. | Bajo (operativo) | **HECHO** (commit `ddb950e`). Causa raiz real: NO era MiMo ni la clave, sino una dependencia rota (`jiter`) que tumbaba el import de `openai` y hacia que el router marcara todos los proveedores como caidos. Ver seccion 10. |
| T1 | **Alerta de modo degradado** cuando el grupo opera sin LLM. | Hoy la caida del LLM pasa desapercibida. | Bajo | **HECHO** (E10 watchdog + E11 runner). Falta solo registrar el job (hook 4.1) -> T1b |
| T1b | Registrar `agents_healthcheck_job` en el scheduler con cadencia (hook seccion 4.1). | Activar la vigilancia automatica. | Bajo (edita scheduler, requiere reinicio) | PENDIENTE (requiere reinicio del sistema) |
| T2 | **Motor de mejores oportunidades determinista** (varios lideres por RS/momentum/tendencia, no un unico nombre sobrecomprado). | El fallback evaluaba un solo nombre. | Medio | **HECHO** (E9 `opportunity_ranker` + tests). Falta conectarlo al fallback -> T2b |
| T2b | Conectar el ranking de E9 al `deterministic_trade_fallback_recommendations` para ampliar el slate de candidatos. | Que el motor alimente la decision real, no solo el reporte. | Medio (toca decision; validar en shadow) | PENDIENTE |
| T11 | Alimentar el ranking de oportunidades con el **universo amplio** (breakout_scan / closed_market_technical_study), no solo el snapshot de 9 megacaps. | El snapshot actual es muy estrecho y limita los candidatos. | Bajo-Medio | PENDIENTE |
| T3 | **Integrar `refresh_research_evidence` como job** (junto al daily_study o inicio de sesion) y conectar la evidencia a mas capas que `trade_decision`. | La capa de evidencia esta inerte. | Bajo-Medio | PENDIENTE |
| T4 | **Revisar calibracion del backtest-gate** para paper/micro-experimentos: permitir entradas SHADOW que no consuman el veto, con reporting. | Hoy el gate bloquea incluso el unico candidato. | Medio (toca gates) | PENDIENTE |
| T5 | **Integrar `reconcile_broker_orders` como job** post-sesion y enlazar fills con `signal_outcomes.executed_buy`. | Sin reconciliacion no se sabe que se ejecuto; el aprendizaje no ve ejecuciones. | Bajo-Medio | PENDIENTE |
| T6 | **Dedupe de ejecucion same-symbol** antes de generar el plan (no despues). | `duplicate_ratio` 0,90; HSIC repetido cada ciclo. | Bajo | PENDIENTE |
| T7 | **Desatascar el embudo del laboratorio**: drenar 1.203 validaciones PENDING y definir gates de promocion que de hecho aprueben en paper. | 0 applied_changes, 0 reglas activas: la mejora continua no mejora nada. | Medio | PENDIENTE |
| T8 | **Champion/challenger end-to-end**: ventanas, metricas de promocion, rechazo y rollback automaticos para paper. | Cerrar el ciclo idea -> shadow -> promocion. | Medio-Alto | PENDIENTE |
| T9 | **Programar `weekly_improvement_report`** (cron semanal) y publicarlo en el dashboard. | Reporting de que cambio/mejoro/empeoro/revertido. | Bajo | PENDIENTE |
| T10 | **Mantenimiento de BD periodico**: VACUUM + retencion automatizados con el scheduler parado (ventana de mantenimiento). | Evitar que la BD vuelva a inflarse. | Bajo | PENDIENTE |

---

## 6. Riesgos a vigilar

1. Sobreajuste disfrazado de aprendizaje si se promocionan reglas con poca muestra.
2. Dependencia de fuentes informales si no se endurece el scoring de fiabilidad.
3. Saturacion del laboratorio con propuestas medianas (ya visible: 1.092 rechazos).
4. Agentes dinamicos sin medicion de utilidad rica.
5. Mezclar narrativa de investigacion con edge estadistico sin criterio de peso.
6. **Degradacion silenciosa por caida de LLM** (causa del incidente actual): mitigar con T1.

---

## 7. Operativa del sistema "siempre levantado" y versionado

- El sistema **suele estar levantado** (panel web en `:8501`, scheduler en
  background, LLM local en `:8080`). Ver `docs/startup_runbook.md`.
- **Tras aplicar cambios de codigo, el sistema debe seguir levantado pero con los
  cambios cargados.** Un proceso Python ya en marcha NO recoge cambios en caliente:
  hay que **reiniciar** el scheduler y el panel web para que carguen el codigo nuevo.
  Secuencia recomendada (PowerShell, tras parar los procesos previos):

  ```powershell
  cd C:\Antonio\Bref\agenteBolsa
  # parar panel y scheduler previos (ver startup_runbook seccion 7), luego:
  Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @("-m","agente_bolsa.main","web","--host","127.0.0.1","--port","8501") -WorkingDirectory "C:\Antonio\Bref\agenteBolsa" -WindowStyle Hidden
  Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @("-m","agente_bolsa.main","schedule","--quiet") -WorkingDirectory "C:\Antonio\Bref\agenteBolsa" -WindowStyle Hidden
  .\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
  ```

- **Versionado:** en cada entrega se sube `__version__` en
  `src/agente_bolsa/__init__.py` (fuente unica; `pyproject.toml` y el sidebar la
  leen de ahi). Tras reiniciar el panel, la nueva version debe verse en la barra
  lateral. Convencion: `MAJOR.MINOR.PATCH`.

---

## 8. Como gestionar futuras mejoras (proceso)

1. Anadir la mejora como nueva fila en la seccion 5 (backlog) con estado PENDIENTE.
2. Al ejecutarla: mover/duplicar la fila a la seccion 3.2 con su artefacto, marcar
   TERMINADO o HECHO-PENDIENTE-VALIDACION, y anotar como se verifico.
3. Subir la version (seccion 7) y reiniciar el sistema para que cargue los cambios.
4. Si la mejora toca decision/ejecucion/gates, validar primero en SHADOW/dry-run y
   documentar el resultado aqui antes de activarla.
5. Mantener este documento como indice vivo: lo terminado y lo pendiente siempre
   reflejan el estado real.

## 9. Dejar el sistema corriendo de forma persistente

Diagnostico (16-jun-2026): al lanzar el scheduler en background oculto, arrancaba,
hacia bootstrap y registraba `scheduler_started`, pero el proceso se cerraba. NO
es un bug: `run_scheduler_forever` bloquea correctamente con un bucle
`while True: time.sleep(1)`. El proceso moria por quedar colgado de una sesion
transitoria (la del agente que lo lanzaba); al cerrarse esa sesion, moria el hijo.

Solucion: ejecutar como **Tarea Programada de Windows** (sobrevive al cierre de
ventana y de sesion). Artefactos entregados:

- `scripts/install_scheduler_task.ps1` — registra y arranca la tarea
  `AgenteBolsaScheduler` (al iniciar sesion, reinicio ante fallo, sin limite de
  tiempo, una sola instancia).
- `scripts/install_web_task.ps1` — idem para el panel web (`AgenteBolsaWeb`).
- `scripts/run_scheduler.bat` — lanzador manual en ventana normal (alternativa
  simple; vive mientras la ventana este abierta).

Instalacion (PowerShell en sesion de usuario normal):

```powershell
cd C:\Antonio\Bref\agenteBolsa
powershell -ExecutionPolicy Bypass -File scripts\install_scheduler_task.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_web_task.ps1
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status   # debe listar agents_healthcheck
```

Desinstalar: `Unregister-ScheduledTask -TaskName "AgenteBolsaScheduler" -Confirm:$false`
(idem `AgenteBolsaWeb`).

## 10. T0 cerrado: causa raiz del modo degradado (jiter)

Fecha: 2026-06-16. Commit: `ddb950e`.

El sistema llevaba ~10 dias sin llamadas LLM reales de decision/sentimiento. La
causa **no** era la config de MiMo ni la clave (MiMo respondia por HTTP en el
health check directo), sino una **dependencia transitiva rota en el venv**:
`jiter` (parser JSON en Rust que usa internamente el cliente `openai`) impedia
`import openai`. Como el `llm_router` capturaba ese `ImportError`, marcaba TODOS
los endpoints como no disponibles y el grupo caia a fallback determinista en
silencio.

Resolucion y blindaje:

- Reinstalado `jiter==0.13.0` y **pineado** en `requirements.txt` y `pyproject.toml`
  (era transitiva sin pin; por eso una reinstalacion del venv lo rompio).
- `tests/test_openai_client_health.py`: test de regresion que importa/crea el
  cliente OpenAI (detecta este fallo en `pytest`).
- `llm_router.py` ahora distingue `llm_client_import_broken` de "proveedor caido",
  para que el modo degradado sea diagnosticable y no se confunda con un endpoint
  inaccesible.

Validacion: `pip check` limpio, `pytest -q` 650 verdes, `llm_health_check.py`
MiMo OK + CI OK, `agents_healthcheck.py` `[OK]`, `schedule-status` lista
`agents_healthcheck`, panel 200, scheduler vivo tras 10 min.

Pendiente operativo (no de codigo): registrar las tareas programadas
(`install_scheduler_task.ps1` / `install_web_task.ps1`) desde una PowerShell con
permisos suficientes; desde el contexto del agente Windows devolvia "Acceso
denegado". Mientras tanto, scheduler y panel quedan arrancados en sesion.

Leccion: un fallo de import de dependencia puede disfrazarse de "LLM caido". El
watchdog `agents_healthcheck` (E10) fue precisamente lo que hizo visible que el
grupo llevaba dias sin LLM real; conviene mantenerlo y vigilar su alerta.

## 11. Fase edge: que el grupo gane, no que opere mas

Objetivo: subir la **expectativa real medida por setup**, no el volumen de
operaciones. Todo en paper, cambios sensibles en SHADOW y detras de flags; no
tocar `risk.py`/kernel ni `ALLOW_LIVE_TRADING`.

### 11.1 Diagnostico medido (bloques 0-1, commit `1cd7773`) — HECHO

Instrumentacion entregada por Codex: `tools/broker_reconciliation.py`,
`scripts/trading_block_metrics.py`, `scripts/reconcile_broker_orders.py`, job
`broker_reconciliation` en el scheduler.

Datos (ultimos 7 dias):

- 99 recomendaciones de compra -> **1 orden enviada**. Cuello de botella claro.
- Vetos por gate: `backtest_gate` **103**, `deterministic_review` 1. (Ni entry
  quality ni risk manager son el problema.)
- Top razones del `backtest_gate`: regimenes negativos 2>max1 (33); hit-rate
  43,75%<45% (15) y 44,44%<45% (14); profit-factor 1,01<1,05 (9); trade-window
  alpha −0,25%<0% (9). **Casi todos los vetos son "por poco".**

Reconciliacion (bloque 1): las 32 ordenes pasaron de `PENDING_NEW` a `filled`
(17 buy / 15 sell). `signal_executed_observations`=320. **P&L realizado FIFO =
−782,18** en 16 lotes cerrados; equity paper ~70.676 (plano), Sharpe60 negativo.

**Conclusion clave:** el edge actual es marginal/negativo. Relajar el gate a
secas haria operar mas setups perdedores. El trabajo es **mejorar y medir el
edge por setup**, ahora posible porque la ejecucion ya se reconcilia.

### 11.2 Backlog "Fase edge" (PENDIENTE salvo indicacion)

| # | Tarea | Criterio de exito | Estado |
|---|-------|-------------------|--------|
| F2b | Edge por setup/estrategia con las 320 ejecuciones + outcomes: expectativa, hit-rate, PF, alpha por `setup_quality`/tag/regimen. Subir prioridad/sizing a edge+ y mandar a shadow/vetar edge−. | Tabla de edge por setup; identificados pockets ganadores/perdedores. | PENDIENTE |
| F2 | Shadow A/B del `backtest_gate` con criterio de **expectativa forward** (1/3/5/10d) del cohorte vetado, por razon de veto. Relajar SOLO los umbrales cuyo cohorte demuestre expectativa positiva. | Recalibracion umbral a umbral basada en evidencia; nada se relaja sin expectativa+. | PENDIENTE |
| F5 | Disciplina de salida: analizar por que el realized P&L es negativo; revisar `exit_policy_v2`, stops/take-profit/trailing, holding y drawdown por trade. | Cortar perdidas y realizar ganadores; P&L realizado mejora. | PENDIENTE |
| F3 | A/B `opportunity_ranker` (lideres RS/momentum) vs scanner actual en paper (`OPPORTUNITY_RANKER_FALLBACK_ENABLED=true`). | Comparativa de forward returns; se queda si mejora, se revierte si no. | PENDIENTE |
| F6 | Cerrar embudo lab: drenar validaciones `PENDING` y promocion champion/challenger que apruebe con expectativa forward+ y estabilidad por regimen. | Reglas con edge pasan de shadow a active; `applied_changes`>0 con criterio. | PENDIENTE |
| F7 | Scoreboard de rentabilidad (equity, P&L, hit-rate, PF, expectancy, maxDD, alpha vs SPY por setup y regimen). | Panel/reporte para guiar y medir "mas listo". | PENDIENTE |

Orden recomendado: **F2b → F2 → F5 → F3 → F6/F7**. Empezar por el edge por setup:
dira si algun setup gana de verdad antes de tocar el gate.

### 11.3 Resultados F2b/F2 (commit `eaee6b0`, v0.4.2) — HECHO

Entregado: `tools/edge_analysis.py`, `tools/execution_linking.py`,
`scripts/edge_shadow_analysis.py` (`--since-date`), y un **fix serio**: la
reconciliacion propagaba el fill por `symbol` a señales recientes equivocadas;
ahora enlaza con la señal previa correcta por fecha/hora. `pytest` 654 verdes.

Edge por setup (muestras pequeñas, direccional):
- **Malo y accionable**: `confirmed_pattern` n=8, expectancy_5d **−5,25%**, hit 14%,
  PF 0,07. Tags débiles: `volume_z:lt0` −4,72%, `sma20_dist:0_6pct` −6,74%,
  `rsi:60_75` −3,86%.
- **Prometedor pero muestra corta**: `orderly_breakout` +4,89% (n=1),
  `volume_z:gt1` +4,89% (n=2), `sma20_dist:6_12pct` +1,17% PF 3,57 (n=3).

Cohortes vetados por `backtest_gate`: **no hay base para relajar en bloque**.
- Mantener/endurecer: `trades 0<10` (−40,76%), alpha negativos, `PF 0,73`.
- Prometedores pero inmaduros: `alpha −0,15%<0` (+2,70%, n=9), `hit 44%<45%`
  (+2,64%, n=7), `trades 8<10` (+0,90%, n=16).
- Near-miss sin muestra madura aún: `43,75%`, `44,44%`, `PF 1,0147`,
  `regimenes negativos 2>1` (solo 1d maduro).

Decision operativa (disciplinada, asimetrica): **no relajar nada en paper hoy**;
reducir exposicion a lo probadamente malo y NO añadir a lo "bueno" todavia (n
insuficiente). Abrir shadow solo para 3 near-miss: `hit 44%<45%`,
`alpha −0,15%<0`, `trades 8<10`.

Limites de dato detectados (a corregir antes de F6/F7):
- `alpha vs SPY` no computa: falta benchmark SPY en cache local para el script.
- `regime` sale `unknown`: el ledger no persiste `market_regime` en la señal.

### 11.4 Backlog actualizado (siguiente)

| # | Tarea | Estado |
|---|-------|--------|
| F5 | **Disciplina de salida** (shadow `stale_guard_v2`). | **HECHO** (commit `7d9a178`, OFF) |
| F2b-act | **Routing por setup** (penalización reversible de pockets malos) + fix de cableado de `Settings`. | **HECHO** (commit `1d43511`) |
| F-infra | Persistir `market_regime` + benchmark SPY en el analizador. | **HECHO** (commit `2a5c364`) |
| F2-shadow | Shadow de los 3 near-miss con expectativa+. | **HECHO** (commit `dc5ed0e`) |
| F3 | A/B `opportunity_ranker` (líderes RS/momentum) vs scanner; flag activado en fallback. | **HECHO** (commit `696549e`) |
| F6 | Evaluador champion/challenger estricto (solo-propuesta) + guardas anti-sobreajuste. | **HECHO** (commit `7a8660c`) |
| F7 | Scoreboard de rentabilidad en dashboard + CLI. | **HECHO** (commit `7a8660c`) |
| F8 | Consolidación: drenar backlog CI (94 cierres TTL), democión automática de pockets probadamente malos con evidencia, review semanal con scoreboard. Acumular muestra. | PENDIENTE (siguiente) |

### 11.5 Resultados F5 + F2b-act (commits `7d9a178`, `1d43511`) — HECHO

**F5 — salidas** (`exit_shadow_analysis.py`, `stale_guard_v2` OFF por defecto):
- `stop_loss`: 3 trades, hold **21d**, ret −5,06%, MFE −3,22%, MAE −10,43%.
- `take_profit`: 2 trades, hold 9,5d, ret **+13,21%**.
- `time_stop_v2`: 2 trades, hold 5d, ret −3,70%.
- Lectura: el daño no es vender pronto, sino **perdedores que se eternizan hasta el stop completo** (WELL, SBUX). El shadow `stale_guard` mejora hit (28,6%→42,9%) y PF (1,17→1,34); expectancy similar. Muestra corta → dejar OFF y seguir midiendo.

**F2b-act — routing de pockets negativos** (penalización reversible por flag):
- Aparta de la parte alta: `confirmed_pattern`, `volume_z<0`, `rsi:60_75`, `sma20_dist:0_6pct`. Top-4: `rsi:60_75` baja de 3→1.
- **Fix de cableado importante**: varios flujos (`scheduler`, `main`, `opportunities`, `trade_decision`) reconstruían `Settings(DATA_DIR=...)` y **perdían flags efectivos** de selección. Corregido: ahora la config runtime llega igual a scheduler, CLI y snapshot.
- Hallazgo: el routing ayuda al margen, pero **el universo sigue dominado por setups flojos** → la mejora de fondo es la calidad de candidatos (F3).

Pendiente: F-infra (alpha + régimen) y F2-shadow. Tests: 656 verdes.

### 11.6 Resultados F-infra + F2-shadow + F3 (commits `2a5c364`, `dc5ed0e`, `696549e`) — HECHO

**F-infra**: `edge_shadow_analysis.py` ya calcula **alpha vs SPY** y desglose por
**régimen**. Se persiste `market_regime`/`volatility_regime`/`risk_posture` en
`signal_outcomes.features` para señales nuevas; el histórico infiere régimen
desde tendencia de SPY. Edge con alpha: `orderly_breakout` alpha_10d **+16,9%**
(n=1); `confirmed_pattern` negativo en todos los horizontes; régimen `neutral`
n=9 negativo.

**F2-shadow**: logging shadow (sin cambiar conducta) en
`gate["backtest_near_miss_shadow"]` (`mode=shadow_only`) para `hit 44%<45%`,
`alpha −0,15%<0`, `trades 8<10`. Excluidos `43,75%`, `44,44%`, `PF 1,0147`,
`regímenes negativos 2>1`.

**F3**: `OPPORTUNITY_RANKER_FALLBACK_ENABLED=true` por defecto (solo fallback,
reversible). A/B (`opportunity_ranker_ab.py`):
- Ranker top: alpha_1d **+0,72%**, 3d −0,68%, 5d −0,74%, 10d **+3,94%**.
- Scanner top: alpha_1d +0,21%, 3d +0,51%, 5d −1,30%, 10d −0,00%.
- Ranker mete líderes (CCL, DAL, DDOG, DELL, CRWD). Mejora clara a 1d y 10d,
  peor a 3d/5d → activado solo en fallback, sin subir agresividad global aún.
- Lectura: confirma que los líderes por RS tienen mejor edge a 10d; conviene
  alinear el horizonte de salida con donde está el edge (ver F6/exits).

Tests: 660 verdes.

**Setup-edge bias (commit `d7dba99`, v0.4.27)**:
- `tools/setup_edge.py` queda como fuente comun para clasificar setups y
  calcular `edge_table` desde `signal_outcomes` con ventana train walk-forward.
- `trade_decision.py` lo cablea al fallback solo detras de
  `SETUP_EDGE_BIAS_ENABLED` (default **OFF**); al activarlo reordena el slate y
  deja comparativa shadow en `data/reports/latest_setup_edge_shadow.json`.
- `entry_quality` no se relaja en real: solo registra en shadow que rutas se
  desbloquearian al retirar el requisito duro de `confirmed_pattern`.
- Telemetria: `signal_learning` persiste `market_regime` y
  `volatility_regime` desde el reporte o el candidato para evitar cobertura
  cero por regimen.
- Config registrada: `SETUP_EDGE_BIAS_ENABLED=false`,
  `SETUP_EDGE_BIAS_TRAIN_WINDOW_DAYS=120`,
  `SETUP_EDGE_BIAS_MIN_SAMPLES=20`.

### 11.7 Siguiente: F6 (sistema de mejora sólido) + F7 (scoreboard)

Ahora que hay alpha y régimen, toca cerrar el lazo de mejora con **guardas
anti-sobreajuste** (muestras aún pequeñas, n=1/8/9): promoción champion/challenger
solo con muestra mínima, expectativa/alpha forward positivos, estabilidad por
régimen y validación out-of-sample; democión/retiro de lo que no rinde. Y un
scoreboard de rentabilidad para dirigir por datos.

### 11.8 Resultados F6 + F7 (commit `7a8660c`, v0.4.8) — HECHO

Entregado: `tools/profitability_scoreboard.py` + `scripts/profitability_scoreboard.py`,
`continuous_improvement/promotion_readiness.py` + `scripts/promotion_readiness.py`,
ambos expuestos en el dashboard (Profitability Scoreboard + readiness en Strategy
Lab). Política F6 **solo-propuesta** (no auto-aplica conducta). Tests 664 verdes.

Estado medido: equity 70.676 (plano), 9 fills enlazados, SPY 136 puntos.
- Promociones: **0** (bloqueadas correctamente por muestra/estabilidad).
- Demociones propuestas (no aplicadas): `confirmed_pattern` (alpha5d −6,21%, PF 0,07),
  `rsi:60_75` (−4,61%, PF 0,25), `volume_z:lt0` (−5,78%, PF 0,09).
- Backlog CI: 1.297 pendientes, 94 cierres por TTL recomendados.

**Inflexión honesta:** la maquinaria de mejora ya está completa y es correcta.
El limitante ahora es **muestra** (9 fills): no hay con qué promover todavía. Las
ganancias de P&L vendrán de (1) cortar ya los pockets probadamente malos,
(2) los mejores candidatos del ranker RS, y (3) **dejar correr el sistema** para
acumular muestra y poder promover ganadores. No hay atajo: es disciplina + tiempo.

### 11.9 F8 — Consolidación (siguiente)

- Drenar el backlog CI: aplicar los 94 cierres por TTL; criterio de cierre para
  que no se reacumule.
- Democión automática (no solo propuesta) de pockets con evidencia negativa
  suficiente (`confirmed_pattern` ya penalizado por F2b-act); promoción sigue
  manual/estricta.
- Review semanal automatizada con el scoreboard (cron) para decidir promociones a
  medida que madura la muestra.
- Mantener el sistema corriendo de forma persistente (tareas programadas) para
  acumular muestra.

## 12. Plan consolidado tras el estudio semanal (semana 23-jun-2026)

Lectura del estudio (`docs/weekly_study_2026-06-19.md`): la semana estuvo dominada
por fallos de infraestructura (crew sin deps 11-15, cuotas LLM y sentimiento
caido), no por la estrategia. Direccion correcta, resultados pendientes de una
semana limpia. Objetivo permanente: mas listo, mas autonomo, mas rentable.

Hallazgo clave de estrategia: **el edge aparece a 5-10 dias; el sistema evalua/sale
a 1-3 dias** (donde domina el ruido). Alinear el horizonte es probablemente la
mayor palanca de rentabilidad.

### Capa 1 — Estabilidad (bloqueante; sin esto el sistema opera ciego)
- **C1.1** Arreglar dependencias pip del scheduler (causa del 100% fallback 11-15 jun). Pinear/`pip install -r requirements.txt` en el venv del scheduler y verificar que el crew arranca. Idealmente, freeze de versiones para que no se rompa al reinstalar.
- **C1.2** LLM continuo: kimi-k2.6 (opencode-go) como primario de DECISION y SENTIMIENTO, con fallback configurado; respetar Retry-After/backoff ante 429/403. Validar con `scripts/llm_health_check.py` antes de apertura.
- **C1.3** Restaurar la capa de sentimiento (cuota). Fue el bloqueo nº1 de compras (vetó las 3 de APH y ~120 ciclos).

#### Resultado Capa 1 (20-jun-2026, v0.4.15)

- **C1.1 HECHO**: `pip install -r requirements.txt` ejecutado sobre el venv;
  `pip check` sin dependencias rotas. Smoke real: `build_crew()` crea 6 agentes
  y 6 tareas sin el error `Instala dependencias...`. Se añade
  `requirements.lock` con todas las dependencias transitivas fijadas
  (`crewai==1.14.7`, `crewai-tools==1.14.7`, `openai==2.41.1`,
  `jiter==0.13.0`).
- **C1.2 HECHO**: decision y sentimiento quedan fijados como roles separados a
  `kimi-k2.6` en `https://opencode.ai/zen/go/v1`, con fallback local configurado.
  El router respeta `Retry-After` y aplica backoff exponencial acotado ante
  HTTP 429/403. `llm_health_check.py`: decision OK, sentiment OK, mejora
  continua OK; el fallback local esta configurado pero apagado.
- **C1.3 HECHO**: ciclo real de sentimiento AAPL con 3 noticias, score `-1`,
  confianza `0.6`, sin warnings y `sentiment_failed=false`. Se eleva el limite
  del rol a 4.000 tokens porque Kimi consumia 1.200 en razonamiento y devolvia
  `{}`; ahora una respuesta incompleta se rechaza explic
### 12.1 Capa 2 — HECHA (medicion + shadow, commits ee51f8e/0411ce0/fb0d927/efcf8ee)

- Alpha vs SPY numerico (1d +0,80% / 3d -1,01% / 5d -0,45% / 10d +4,33%); cobertura SPY 7/7.
- Regimen real persistido (ej. AAPL -> bullish); ya no "unknown".
- **Hallazgo clave confirmado (horizonte):** salida actual 1-3d expectativa -1,78% (PF 0,25) vs shadow 5-10d +1,18% (PF 1,34). Mejora pareada +2,95% retorno / +1,54% alpha. NO promovido (n=4).
- stale_guard y shadow-penalty confirmed_pattern: OFF, midiendo en el informe semanal.

### 12.2 Decisiones a tomar el viernes 26-jun (con mas muestra)

1. **Activar horizonte de salida 5-10d** si la ventaja se mantiene con n>=20 (palanca nº1 de rentabilidad).
2. Valorar activar `stale_guard` si corta perdedores sin dañar ganadores.
3. Formalizar/activar penalizacion de `confirmed_pattern` si sigue con edge negativo y muestra alta.
4. Comparar calidad de decision kimi vs etapa MiMo (primera semana limpia con kimi).

Hasta el viernes: NO tocar nada; dejar acumular muestra con Capa 1 estable + Capa 2 en shadow.
unknown").

#### Resultado C2.4-C2.5 (20-jun-2026, v0.4.16)

- **C2.4 HECHO**: el fetcher de SPY usa el cache de mercado y amplía el rango
  para cubrir retornos forward y tendencia de régimen. `edge_shadow_analysis`
  obtiene 932 puntos benchmark; alpha a 1/3/5/10d: `+0,80%`, `-1,01%`,
  `-0,45%`, `+4,33%`. El scoreboard rellena SPY sin convertir ausencias en
  cero: cobertura 7/7 y alpha acumulado `-1,6839%`.
- **C2.5 HECHO**: el ciclo real ya copia `market_state` al ledger. El lote
  `opp_80c74db42155`, creado el 19-jun sobre la última sesión disponible
  (17-jun), persiste `market_regime=bullish`. Para históricos sin régimen, el
  analizador usa tendencia SPY con 300 días de contexto y declara el origen;
  cobertura actual de compras enlazadas: 4/4, todas `bullish`.

#### Resultado C2.1 (20-jun-2026, v0.4.17)

- Se incorpora una comparación contrafactual sobre compras paper reconciliadas:
  último outcome maduro de la ventana actual 1-3d frente al último de 5-10d.
  Reporta expectativa, hit-rate, profit-factor, alpha y delta pareada.
- Es análisis `SHADOW` puro (`changes_trading_behavior=false`) y nunca promociona
  la política automáticamente; requiere ampliar la muestra paper madura.

#### Resultado C2.2-C2.3 (20-jun-2026, v0.4.18)

- `stale_guard` permanece con conducta OFF y se calcula contrafactualmente en
  el informe semanal, con elegibles, disparos y métricas actual vs shadow.
- La penalización de `confirmed_pattern` queda formalmente en shadow: el flag de
  conducta pasa a OFF por defecto; el routing calcula y persiste la penalización
  que habría aplicado, pero no la resta del score. El informe semanal muestra
  muestra madura y edge por 1/3/5/10d.
- El informe semanal integra scoreboard, alpha SPY, régimen y comparación de
  horizonte. Ningún cálculo de esta sección modifica compras o ventas.

### Capa 3 — Mas autonomo
- **C3.1** Promocion/democion automatica del lab con guardas (champion/challenger) cuando haya muestra y expectativa+.
- **C3.2** El watchdog (`agents_healthcheck`) debe ALERTAR de forma visible si el grupo vuelve a quedarse en fallback varios ciclos (lo de 11-15 paso desapercibido).

Orden: Capa 1 (antes del lunes) -> Capa 2 (durante la semana, shadow + medir) ->
Capa 3 (cuando 1 y 2 esten estables). Nada que cambie compras/ventas reales sin
shadow + evidencia; no tocar risk.py/kernel ni ALLOW_LIVE_TRADING.

### 11.10 Publicacion manual en LLM Trading Leaderboard (21-jun-2026, v0.4.34) — HECHO

- El dashboard publica manualmente `model=AMR` y `gain_pct` usando el P/L porcentual
  de referencia calculado desde el 1 de abril (`DEFAULT_START_DATE=2026-04-01`).
- El ultimo envio confirmado queda trazado en `agent_events` y visible junto al boton.
- La eliminacion remota mediante `DELETE /api/data` exige casilla de advertencia y
  escribir exactamente `BORRAR TODO`; exitos y errores tambien quedan auditados.
- Rutas verificadas contra OpenAPI: `POST /api/submit` y `DELETE /api/data`;
  host configurable con `LEADERBOARD_API_BASE_URL`. Verificacion: tests unitarios de
  POST, DELETE y recuperacion del ultimo envio, sin llamadas reales a red.

### 11.11 Correccion de regresiones de decision y reconciliacion (22-jun-2026, v0.4.37) — HECHO

- El error medio del prior deja de ser un veto duro de entrada. El digest vigente
  contiene 19.930 observaciones, 0 compras ejecutadas y 90,03 % de duplicados: la
  metrica sirve como senal auxiliar, pero no justifica bloquear compras. Se conserva
  la penalizacion existente en ranking y sizing (20 % al superar 0,04) y se expone
  `prior_error_advisory` en la trazabilidad del gate.
- Los tests de entry-quality que no prueban aprendizaje quedan aislados de los
  reportes operativos de `data/`, evitando resultados dependientes de la maquina.
- El fixture de reconciliacion incluye la fecha real del plan, respetando el guard
  de antiguedad maxima de cinco dias que evita asociar fills a senales historicas.
- Verificacion: tests dirigidos, suite completa, Ruff y smokes operativos.

## 12. Plan de mejora 24-jun — desatascar la entrada (el dinero)

Contexto: tras arreglar el LLM (deepseek), los ciclos completan y el gate trabaja
con criterio, pero siguen 0 compras. Dos causas reales:
1. **El `market_state` sale PARTIAL / regime=unknown CADA ciclo** -> fuerza modo
   defensivo (`requires_micro_experiment`, size 0.5x, soft-override OFF) y NUNCA
   puede clasificar bullish, aunque la amplitud sea 95-100% positiva. Es un BUG de
   datos: el benchmark (SPY) no trae `close/sma_50/sma_200/atr` poblados
   (`benchmark_return_20d=0.0`), y `_quality_status` queda en PARTIAL por falta de
   earnings/macro/cobertura (FMP).
2. **El universo de candidatos es 100% `confirmed_pattern`** (lideres extendidos
   que el gate rechaza con razon); el edge validado OOS esta en `sin_patron|strong`
   y no se surfacea ni opera.

### A1 — Arreglar dato de benchmark + quality del market_state (BUG, max prioridad)
Poblar tecnicas de SPY en `build_market_snapshot`/`build_market_state` y revisar por
que `quality_status=PARTIAL`. Es arreglo de datos (no cambia conducta), de altisimo
impacto: destraba el modo defensivo y re-habilita el soft-override. Con test.
Estado: **HECHO (v0.4.38, A1a).** Bug encontrado y corregido: `build_market_snapshot`
descargaba el benchmark (SPY) pero el bucle iteraba solo `symbols` (candidatos), asi
que SPY NUNCA entraba en `snapshot["symbols"]` -> regime="unknown" + `benchmark_return_20d=0`
+ fuerza relativa rota. Fix: iterar `unique_symbols`. Test `test_market_snapshot_benchmark.py`.
- **A1b (decision tomada): NO conectar FMP por ahora.** El plan gratuito de FMP NO
  incluye calendario de earnings (es de pago), asi que no arreglaria `has_earnings`.
  Ademas PARTIAL **no bloquea** comprar (solo baja size a 0.5x y apaga soft-override):
  no es la causa de los 0 trades. Se aparca FMP hasta ver el sistema operar y tener
  evidencia de que earnings/macro mejoran decisiones en paper.

### A2 — Surfacear setups con edge + promocionar el sesgo (shadow->active)
- Verificar si la SELECCION surfacea `sin_patron|strong` (en logs eran 100%
  confirmed_pattern -> posible cuello aguas arriba).
- `SETUP_EDGE_BIAS_SHADOW_ENABLED=true` (mide en vivo sin tocar conducta) varias
  sesiones; si confirma OOS, `SETUP_EDGE_BIAS_ENABLED=true` (guarded). Relajar el
  requisito duro de `confirmed_pattern` (M2) tras flag, medido. Neto de costes.
Estado: **EN CURSO (v0.4.39, shadow por ciclo implementado).** Estudio del funnel:
el ranker (`opportunity_ranker`) NO prefiere confirmed_pattern; el selector
(`_selection_score_for_candidate`) tiene perfiles que SI exigen patron confirmado
(high_conviction, leader_momentum, top_long_alignment) y otros que NO (emerging/parabolic
leader), asi que sin_patron PUEDE pasar pero los perfiles de patron dominan. El
shadow del sesgo ya existia pero **solo corria en el fallback del LLM**. Nueva funcion
`record_setup_edge_cycle_shadow` (en `trade_decision.py`, llamada desde `cycle_runner`)
mide en CADA ciclo, tras `SETUP_EDGE_BIAS_SHADOW_ENABLED=true`, el funnel de
setup-quality (cuantos `sin_patron|strong` aparecen), el reorden baseline-vs-sesgo y
si las claves casan con la `edge_table`; escribe `latest_setup_edge_cycle_shadow.json`.
Pura observabilidad, sin tocar la seleccion. Test `test_setup_edge_cycle_shadow.py`.
Pendiente: encender el flag, recoger varias sesiones, y decidir promover (o arreglar
el etiquetado de `setup_quality` si las claves no casan).

**Hallazgo 24-jun (primer shadow en vivo, `mkt_6305f7697897`):** el shadow funciona y
revelo dos cosas. (1) BUG de etiquetado: los candidatos en vivo daban la clave
`confirmed_pattern` (sin calidad, por el short-circuit de `setup_name` en
`setup_quality_key`) mientras la `edge_table` usa `confirmed_pattern|strong` etc. ->
no casaban -> `setup_edge_bias=0` en todo, mecanismo INERTE. Corregido en **v0.4.41**
(la clave ahora es siempre `{base}|{quality}`, ignorando setup_name). (2) ESTRUCTURAL:
la seleccion surfacea 24/24 `confirmed_pattern` y **0 `sin_patron`**; los grupos de
edge positivo (sin_patron|mixed +0.49%, confirmed_pattern|watchlist +0.21%) no aparecen,
y el grupo que si aparece (confirmed_pattern|strong) tiene edge medido -0.15%. Bonus: A1
confirmado (benchmark_return_20d=-0.0178, ya poblado, no 0). Siguiente: validar que tras
v0.4.41 `keys_without_edge_match` se vacia, y luego atacar el surfaceo de `sin_patron`
(cuello estructural en la seleccion).

### B1 — A/B de modelo en decision (flash vs deepseek-pro vs glm), midiendo edge. PENDIENTE.
### B2 — Report diario del embudo en el panel (candidatos->gates->decision->fill). PENDIENTE.
### C1 — Experimento: el LLM bate al fallback determinista? (offline). PENDIENTE.
### C2 — Paralelizar sentimiento (~20s/simbolo secuencial) y revisar propuestas del lab. PENDIENTE.

Orden: A1 (bug, destraba) -> A2 (shadow del sesgo) -> B2 -> B1/C. Disciplina:
shadow -> guarded -> active; nunca tocar risk.py/kernel/ALLOW_LIVE; pytest verde.
