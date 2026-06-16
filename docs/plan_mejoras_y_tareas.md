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
