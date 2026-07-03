# Informe del responsable — P27 + P28 + P29 — 2026-07-03

Entrega ejecutada directamente por el responsable (no por Codex), a petición de
Antonio para medir desempeño. Verificación final pendiente de ejecución en el
venv de Windows (mi entorno no puede correr pytest/ruff reales); los comandos
exactos están al final.

## Incidencia de método (relevante para el futuro)

Durante la edición de `agents.py` (130KB) detecté **corrupción por truncado en la
capa de sincronización de ficheros** entre mi entorno y el disco real: una vista
de `digest.py` cortada exactamente en el byte 29.768 (prefijo limpio de HEAD) y
un `agents.py` truncado tras ediciones sucesivas. Respuesta aplicada:

- Restauré `agents.py` desde git y **abandoné la edición directa de ficheros
  grandes**: todos los cambios sobre `agents.py`, `digest.py` y `main.py` van en
  scripts de parche atómicos (`data/tmp/patch_p27_agents.py`,
  `data/tmp/patch_p28.py`) con: anclas únicas verificadas, `ast.parse` antes de
  escribir, escritura a temporal + relectura + `os.replace`.
- El parche de `agents.py` quedó aplicado y verificado desde mi lado
  (+42 líneas, diff limpio). Los de `digest.py`/`main.py` DEBE ejecutarlos
  Antonio con el venv (lado de la verdad) — el script aborta sin escribir si
  algo no casa. Misma familia de incidente que el episodio scheduler.py de
  §3.4 del plan: los ficheros grandes de este repo se tratan solo con
  escrituras atómicas verificadas.

## P27 — Gobierno del cast

- Nuevo `src/agente_bolsa/continuous_improvement/cast_governance.py`:
  - `weekly_cap_no_evidence` (OrchestratorAgent: 10/semana sin evidencia medida);
  - contrato ejecutable obligatorio para `SoftwareReliabilityAgent` y
    `DataQualityAgent` (CODE_CHANGE + targets en allowlist de codegen +
    test_requirement + rollback + evidencia);
  - retiro como proponentes de `StrategyEvaluatorAgent` y
    `ExperimentDesignerAgent` (conservan evaluación/validación);
  - evidencia medida = referencia a artefacto verificable (docs/informe,
    docs/estudio, data/reports, experiment_id); las métricas numéricas sueltas
    NO cuentan (lección de la familia de observaciones).
- Config en `data/config/cast_governance.json` (enabled=true, human_gated=true),
  protegida por autogobierno: añadidos `cast_governance`, `weekly_cap_no_evidence`,
  `retired_proposers`, `contract_agents` a `SELF_GOVERNANCE_FORBIDDEN_IDENTIFIERS`.
- Cableado en `ValidationAgent.validate` tras constitución y antes del gate de
  agresividad, con el mismo formato de rechazo determinista. Razones nuevas:
  `cast_cap_exceeded_no_evidence`, `proposal_contract_violation`,
  `agent_not_a_proposer`.
- Digest: los tres motivos tienen contador propio en "rechazadas"
  (vía `data/tmp/patch_p28.py`).
- Tests: `tests/test_cast_governance.py` (7 casos: defaults, evidencia,
  retiro e2e por ValidationAgent, contrato prosa/completo, cap semanal con 10
  sembradas, protección constitucional, flag off).

## P28 — Auditoría de configuración efectiva

- Nuevo `src/agente_bolsa/tools/config_audit.py`: ~39 campos con valor efectivo
  vs default de código y marca de divergencia; configs file-based de
  `data/config/`; bloque `safety` (paper, live off, auto-apply off,
  core_sleeve dry_run) con lista de violaciones.
- CLI `config-audit [--json]` (vía `data/tmp/patch_p28.py` sobre `main.py`).
- Digest diario: línea `Safety: OK` / `Safety: ALERTA -> ...` como chequeo de
  seguridad matinal (el CLI del digest pasa el bloque; los tests lo inyectan).
- Tests: `tests/test_config_audit.py` (7 casos, incluidos safety NOK por
  auto-apply y por sleeve sin dry-run, ficheros ausentes, divergencia, y el
  render del digest con/sin safety + contadores nuevos de P27).

## P29 — Dieta de tokens del LLM de decisión (solo medición)

- Nuevo `scripts/study_decision_token_cost.py` (stdlib, read-only, conexión ro):
  llamadas y tokens por día, distribución de prompt por llamada (avg/p50/p90/max),
  `order_plans` en ventana y **tokens por plan de orden producido** — la métrica
  honesta: pensar cuesta; pensar sin decidir, más.
- Tests sintéticos: `tests/test_decision_token_cost.py` (filtra rol/ventana,
  render, ventana vacía).
- Análisis estático del prompt de decisión (sin tocarlo): los bloques grandes
  son las listas de candidatos técnicos (3 listas compactadas), los breakout
  (2 listas), sentimiento, research_evidence y los digests de aprendizaje
  (daily/operational/post-market). Con ~36k tokens/llamada de media (P26) y
  ~196 llamadas/2 semanas, las 3 palancas candidatas a estudiar tras medir:
  (1) cachear el bloque de instrucciones+aprendizaje entre ciclos del mismo
  día; (2) cap más duro de candidatos enviados cuando el gate previo ya
  rechaza por extensión; (3) no re-adjuntar research_evidence si no cambió.
  Cualquier cambio real del prompt será tarea aparte, shadow y medida.

## Verificación pendiente (Antonio)

Los comandos exactos están en el mensaje del responsable; en resumen:
aplicar `data/tmp/patch_p28.py` con el venv, comprobar parse/diff, correr tests
focales nuevos, suite completa + ruff, `config-audit --json`, script P29 real, y
commit. Versión: 0.4.108.
