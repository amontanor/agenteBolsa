# Lote 5 para Codex — 3-jul-2026 — gobierno del cast y dieta de tokens

Motivado por la auditoría P26: OrchestratorAgent 969 propuestas/4 semanas con 98%
de rechazo; 88,5% de prosa; decisión LLM 7,09M tokens/2 semanas con 0 trades.
Tres tareas en orden, commits e informes separados.

**Bloque de verificación estándar (cada tarea):** `pytest tests\ -x -q` verde;
`ruff check src tests scripts` limpio; bump de `__version__`; ejecución real
documentada; commit revisable; confirmar `trading_mode=paper`,
`allow_live_trading=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`,
`core_sleeve.json` `dry_run=true`; NO tocar los 6 ficheros del suelo de kernel.

---

## P27 — Gobierno del cast: capar el ruido, re-instruir, retirar

Aplica las recomendaciones 2 y 5 de P26, todo en el lab (allowlist):

1. **Cap del OrchestratorAgent:** máximo de propuestas nuevas por semana SIN
   evidencia medida adjunta (p. ej. 10/semana; configurable en fichero propio
   `data/config/cast_governance.json`, human-gated en el gate de gobierno). Una
   propuesta "con evidencia" debe citar un artefacto medible (estudio en docs/,
   experimento PASSED, edge table, KPI del digest). Superado el cap → la
   propuesta se rechaza en intake con razón `cast_cap_exceeded_no_evidence`.
2. **Contrato P25 para los proponentes:** `SoftwareReliabilityAgent` y
   `DataQualityAgent` deben emitir propuestas con el mismo contrato del puente
   (CODE_CHANGE con target_files en allowlist + test_requirement + evidencia +
   rollback) o quedan rechazadas en intake con razón
   `proposal_contract_violation`. Ajusta sus prompts/plantillas para que sepan
   cumplirlo.
3. **Retirar como proponentes** (no como evaluadores): `StrategyEvaluatorAgent` y
   `ExperimentDesignerAgent` dejan de crear propuestas; conservan su rol de
   validación/diseño. Rechazo en intake con razón `agent_not_a_proposer` si lo
   intentan.
4. Todo con tests (cap, contrato, retiro) y visible en el digest: sección o
   contadores de rechazos por estas razones nuevas.
Informe: `docs/informe_codex_p27_gobierno_cast_<fecha>.md`.

## P28 — CLI de auditoría de configuración efectiva

Automatiza la sección 1 de P26 para que no vuelva a hacerse a mano:

1. Comando `config-audit --json`: vuelca los parámetros relevantes con valor
   efectivo (con .env cargado), default de código, divergencia sí/no, e incluye
   las configs file-based (`core_sleeve.json`, `lab_book.json`,
   `ci_research_mode.json`, `codegen_nightly.json`, `cast_governance.json`).
   Marca los flags de seguridad críticos (paper, live, auto-apply, dry_run) con
   un bloque `safety` propio.
2. El digest matinal añade una línea de resumen: `safety: OK` o la lista de
   flags críticos fuera de su valor esperado (esto convierte el digest en
   chequeo diario de seguridad).
3. Tests: divergencia detectada; safety OK/NOK; fichero file-based ausente no
   rompe.
Informe: `docs/informe_codex_p28_config_audit_<fecha>.md`.

## P29 — Dieta de tokens del LLM de decisión (SOLO medición, cero cambios de conducta)

7,09M tokens/2 semanas para 0 trades merece diagnóstico, no tijera a ciegas.

1. Instrumentación read-only: desde `llm_usage` + reportes de ciclo, calcula por
   llamada de `trade_decision`: tokens de prompt, % del prompt que es contexto
   repetido entre ciclos consecutivos (mismo día), tokens por candidato evaluado,
   y tokens por decisión distinta de "no operar". Script
   `scripts/study_decision_token_cost.py` con salida JSON + markdown.
2. Identifica los 3 bloques de prompt más caros (por tamaño medio) y cuantifica
   cuánto se ahorraría con cache/recorte de cada uno. SOLO análisis: NO cambies
   el prompt de decisión ni ningún flujo de trading en esta tarea.
3. El informe termina con propuestas concretas de ahorro (cada una con estimación
   de tokens/€ y riesgo), para decisión del responsable.
Informe: `docs/informe_codex_p29_dieta_tokens_<fecha>.md`.
