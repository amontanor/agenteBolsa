# Relevo de dirección técnica — agenteBolsa

> **Última actualización: 2026-07-08 ~20:15 CEST (v0.4.134; P-L10 low-sample y
> hotfix P-L11 de restart_services entregados; stack corriendo con ambos).**
> Este documento es el traspaso completo para el LLM que asuma la dirección técnica.
> Es un documento VIVO: quien dirija debe actualizarlo con cada hito relevante.

---

## 1. Qué es este proyecto y cuál es el objetivo REAL

**agenteBolsa** es un sistema multi-agente (CrewAI) de trading en **paper** (cuenta
simulada de Alpaca) sobre acciones del S&P 500, corriendo en el PC Windows de Antonio
en `C:\Antonio\Bref\agenteBolsa`.

**El objetivo NO es ganar dinero ya, ni invertir en índices** (Antonio invierte en
SPY por su cuenta, fuera de este proyecto; hubo una "manga SPY" que se construyó por
error de enfoque y se desactivó el 7-jul — desvío reconocido). El objetivo es:

- **Que el grupo de agentes opere de forma 100% autónoma en paper**: compra y vende
  solo, validado por sus propios gates, sin botón humano por operación.
- **Que aprenda de sus propias operaciones cada día** (ciclo: fill → reconciliación →
  outcomes → post_market_review → lecciones → ajustes) y mejore con el tiempo.
- **Medir con rigor si de verdad aprende.** Criterio PRE-REGISTRADO (scoreboard P-L4):
  "aprende" si la expectativa neta de las semanas 5-8 supera a las semanas 1-4, con
  pendiente positiva, y bate al cohorte contrafactual. Veredicto a las 8 semanas
  (hipótesis en agenda con target **2026-09-01**). Si no mejora, se dice honestamente.
- Perder al principio es aceptable. Lo inaceptable: no medir, o ablandar los criterios
  para fingir éxito. Ni "nunca operar sin edge probado" (sobre-cautela vieja) ni
  "operar basura y llamarlo aprendizaje".

## 2. Reparto de papeles (cómo se trabaja aquí)

- **Antonio** (humano, dueño): NO programa. Ejecuta comandos copy-paste en PowerShell
  y pega las salidas. Autoriza decisiones de gobierno. Quiere respuestas CONCISAS.
- **Director técnico (tú, el LLM que lee esto)**: NO escribe código en la máquina.
  Diseña, diagnostica, decide, y produce (a) comandos exactos para Antonio y
  (b) prompts de trabajo para Codex. Revisa críticamente las entregas de Codex.
- **Codex** (LLM ingeniero, corre en el venv de Windows): implementa. Se le pueden dar
  lotes largos con varias tareas; se organiza bien. Entrega commits + informes en docs/.

**Formato de respuesta que Antonio espera**: 1) Resumen breve del último paso,
2) "Comando para ti (Antonio)" con bloques copy-paste exactos, 3) "Comando para Codex"
con el prompt completo listo para pegar (o "espera"). Tablas día·hora·comando cuando
hay agenda. Sin paja.

## 3. Restricciones de seguridad (INAMOVIBLES, verbatim)

- Solo paper. `ALLOW_LIVE_TRADING=false` y `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, sellados en kernel.
- NUNCA tocar (suelo de kernel): `src/agente_bolsa/kernel.py`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py`, `config.py`, `.env`. Knobs nuevos por `os.getenv` o JSON en `data/config/`.
- Todo cambio: pytest verde + ruff limpio + bump `__version__` + informe único en docs/ + commit por staging explícito (no `git add -A`). Un solo escritor de git a la vez.
- Cambios kernel/.env requieren `kernel-seal` + `kernel-status` ok:true.
- Apply de la firma human-in-the-loop; no aprobar propuestas que debiliten seguridad/gobierno ni amplíen agresividad sin evidencia.
- No exponer rutas internas de sandbox. Ficheros grandes SOLO con escritura atómica verificada (hubo incidentes reales de truncado).

## 4. Arquitectura en 10 líneas

- **Ciclo de mercado cada ~15 min** (scheduler residente): escaneo S&P 500 → candidatos
  técnicos → decisión LLM estructurada → gates (review determinista, adversarial,
  entry-quality, backtest) → órdenes a Alpaca paper. Todo en `cycle_runner.py`.
- **Estado**: SQLite (~2GB) en `data/state/`; eventos de agentes en `agent_events`;
  planes en `order_plans` (estados PENDING/SUBMITTED/EXPIRED con TTL desde P-L9B).
- **Stack de procesos** (7): scheduler, web (panel Streamlit :8501), y 5 supervisores
  (telegram_radar, overlay_shadow, ci_digest, codegen_nightly, core_sleeve). Se maneja
  con `scripts\stack_status.ps1 / stack_up.ps1 / stack_down.ps1 / restart_services.ps1`
  (restart encadena stack_up y mata procesos ajenos al venv). Tareas programadas de
  Windows: AgenteBolsaScheduler, AgenteBolsaWeb, AgenteBolsaDBMaintenance.
- **La "firma"** (`continuous_improvement/`): agentes que proponen mejoras de código
  sobre sí mismos. Pipeline codegen con autocorrección, sandbox con pytest+ruff, gates
  (new_code_requires_tests, autogobierno, cast_governance P27: cap 10/semana sin
  evidencia para OrchestratorAgent, contratos, proponentes retirados), y **apply
  siempre humano** (`approve` de Antonio, con observabilidad failed_step/failed_subject).
- **Digest diario** (mañanas, `ci_digest_supervisor`): informe md auto-generado que
  Antonio solo LEE. Incluye línea Safety (config_audit), estado learning_mode,
  kill_switch, frescura de market_cycle, contadores cast, "Aprendizaje de ayer".

## 5. Modo aprendizaje (el corazón del giro)

`data/config/learning_mode.json`: `enabled=true, human_gated=true, shadow_first=false,
authorized_by="Antonio 2026-07-07"`. Presupuesto: **3 órdenes/día × $1.000 nocional,
máx 15% exposición**. Cohorte etiquetado `source=learning_experiment` con muro
(excluido de estudios del libro real, patrón P22).

- `human_gated=true` NO significa aprobar cada compra: es invariante de gobierno
  (solo Antonio puede activar/ampliar el modo editando el JSON; los agentes no pueden
  autoconcederse permisos). **Las compras son autónomas.**
- Suavizados del gate backtest dentro del modo (near-miss): hit-rate ≥ umbral−3pp,
  PF ≥ 0.95, regímenes negativos ≤2, alpha ≥ −0.5%. El gate de extensión sigue DURO.
  market_state PARTIAL no estrangula; sentiment nulo no veta solo.
- **Excepción low-sample (autorizada por Antonio 2026-07-08)**: una señal bloqueada
  SOLO por muestra insuficiente (trades < mínimo) puede operar dentro del cupo,
  **máximo 1 al día**, etiquetada `low_sample_exploration`. Nunca aplica si además
  falla hit-rate/PF/regímenes, y el resto de gates (entry-quality, extensión,
  adversarial) siguen exigiéndose. Implementación: P-L10.
- Flags de autonomía verificados 8-jul: `AUTO_PAPER_TRADING=true`,
  `REQUIRE_HUMAN_APPROVAL=false`, `TRADING_MODE=paper`, live off. Topes: 4 órdenes/ciclo.

## 6. Kill switch operacional y sello de kernel

- Kill switch: dos fuentes en `tools/operational_health.py::load_operational_block_context`
  — (a) override persistente `data/operational_kill_switch.json` (si existe),
  (b) alertas críticas de `data/reports/latest_operational_health.json`. Desde P-L8A
  hay expiración por antigüedad del informe y limpieza automática si el kernel re-sella
  OK. CLI: `operational-health` (regenera el informe). **Lección del 8-jul**: un informe
  rancio (27h) bloqueó todo un día de trading; si hay 0 órdenes, mirar esto PRIMERO.
- Sello de kernel: `kernel-seal` / `kernel-status` cubren kernel.py, broker.py,
  execution.py, .env. Editar .env ⇒ re-sellar.

## 7. Estado actual (a fecha de la última actualización)

- **Versión**: 0.4.132 (P-L9A d25b8984, P-L9B 3eb5b58d). 1020 tests verdes, ruff limpio.
- **8-jul = primer día de operativa autónoma real.** Cadena verificada de punta a punta:
  ciclo 15:21 UTC → LLM recomendó 4 compras (FDS/BA/AON/AMP) → entry-quality tumbó 2 →
  backtest tumbó 2 (hit-rate 30%<45%; muestra 6<10 trades) → 0 órdenes, correctamente.
  La autonomía funciona; los gates vetaron señales flojas de verdad. Contadores base:
  order_plans=25→(expirados P-L9B, pending=0), broker_orders=33.
- **Incidente resuelto 8-jul**: stack paralelo con Python311 del sistema (web+schedule+
  streamlit) competía con el venv — causa raíz: `web_app._start_schedule()` usaba
  `sys.executable` y restart no mataba streamlit. Blindado en P-L9A (ruta absoluta del
  venv siempre, detección/matanza de raíces ajenas en stack scripts). Nota: ver hijos
  Python311 colgando del wrapper del venv en Windows es NORMAL (no son raíces).
- **Low-sample IMPLEMENTADO (P-L10, v0.4.133, 1027 tests)**: excepción activa con
  cupo 1/día en learning_mode.json; embudo y digest muestran `low_sample_usage`.
  Pendiente: verificar primer uso real y que el scoreboard separe el sub-cohorte.
- **Aparcado**: propuesta `ci_prop_b3f950033a99` (sección lab_book en digest) —
  rechazada por gate new_code_requires_tests (diff solo src); necesita regeneración
  con tests. No bloquea nada.
- **Agenda de investigación**: re-lectura de `pullback` el 2026-07-10; hipótesis
  `learning_experiment: ¿aprende?` target 2026-09-01. ORCL cerrada (dato real,
  el gate lo rechazó bien). Overlay SPY matado (giro de objetivo).
- **Scoreboard de aprendizaje**: `pending_no_executed_cohort` — se activa con los
  primeros fills del cohorte.

## 8. Comandos de operación diaria (los que Antonio usa)

```powershell
cd C:\Antonio\Bref\agenteBolsa
# Salud del stack (7/7 CORRIENDO + sin procesos ajenos)
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
# ¿Qué hizo el último ciclo y dónde se atascó?
.\.venv\Scripts\python.exe -m agente_bolsa.main cycle-funnel
# Heartbeat de jobs programados
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
# Contadores rápidos (órdenes nuevas = broker_orders sube)
.\.venv\Scripts\python.exe -m agente_bolsa.main status | Select-String '"order_plans"|"broker_orders"'
# Auditoría de flags críticos
.\.venv\Scripts\python.exe -m agente_bolsa.main config-audit | Select-String "Safety|auto_paper|require_human|allow_live"
# Salud operativa (regenera el informe que alimenta el kill switch)
.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health
# Sello de kernel
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status
# Reinicio completo y seguro del stack
powershell -ExecutionPolicy Bypass -File scripts\restart_services.ps1
# Propuestas de la firma (flujo humano)
.\.venv\Scripts\python.exe -m agente_bolsa.main review <id>
.\.venv\Scripts\python.exe -m agente_bolsa.main approve <id>
```

El digest de la mañana aparece solo en `data/reports/` (`ci_digest_*.md`); Antonio
solo lo lee — no se lanza a mano (el supervisor tiene catch-up si se perdió su hora).

## 9. Lecciones aprendidas (errores que NO hay que repetir)

1. **Si hay 0 órdenes, buscar el bloqueo con evidencia** (`cycle-funnel`, agent_events),
   no teorizar. El embudo dice exactamente qué gate/candado cortó y por qué.
2. **Informes rancios matan**: el kill switch leyó 27h un informe viejo. Todo lo que
   bloquee trading debe tener TTL y auto-recuperación (ya implementado, vigilar).
3. **Un solo entorno**: cualquier proceso `agente_bolsa` fuera del venv es un intruso
   (carga otro `.env` y se comporta distinto). `stack_status` ya los detecta.
4. **Árbol git limpio antes de approve**: la firma bloquea applies con árbol sucio.
   Commitear restos (o gitignorar `experiments/`) antes de aprobar.
5. **Escritura atómica en ficheros grandes**: hubo truncados reales vía mount y file
   tools. Parches con anclas + `ast.parse` + `os.replace`, ejecutados en el venv.
6. **Etiquetas honestas**: un "fallback por fallo del LLM" que no era verdad contaminaba
   el análisis. Distinguir `capacity_fill_tras_llm_ok` vs `_por_fallo_llm` (P-L5C).
7. **No inventar nombres de API en snippets**: verificar firmas en el código antes de
   dar comandos a Antonio (pasó con `verify_kernel_integrity`, que no existía).
8. **El cast se gobierna con topes, no con sermones**: cast_governance rechazó 20
   propuestas sin evidencia en un día. Mantenerlo.
9. **Los .ps1 se verifican en el host real** (`powershell.exe` 5.1, el que usa
   Antonio), no en pwsh: un parámetro llamado `Pid` (variable automática read-only)
   pasó la verificación de P-L9A y reventó el restart en producción (hotfix P-L11).
10. **Codex deja los lotes staged, no commiteados**: tras cada entrega, comprobar
   `git status --short` y commitear (lo hace Antonio con mensaje dado por el director).

## 10. Qué vigilar los próximos días (encargo al nuevo director)

1. **Primeras órdenes del cohorte learning_experiment**: cuando `broker_orders` suba,
   verificar la cadena de aprendizaje completa (fill → reconciliación → signal_outcomes
   → post_market_review → lecciones → "Aprendizaje de ayer" en el digest).
2. **Scoreboard semanal**: revisar cada viernes; expectativa neta por semana, cohorte
   real vs contrafactual. No tocar el criterio pre-registrado.
3. **Digest de cada mañana**: línea Safety OK, kill_switch inactivo, market_cycle fresco.
4. **10-jul**: re-lectura del experimento pullback con datos maduros.
5. **P-L10 (low-sample, autorizado)**: revisar entrega de Codex, verificar en vivo el
   primer uso (etiqueta `low_sample_exploration`, tope 1/día) y que el scoreboard
   separa ese sub-cohorte.
6. **b3f950**: relanzar cuando la regeneración incluya tests.
7. **Mantener este documento al día.** Es parte del trabajo, no un extra.
