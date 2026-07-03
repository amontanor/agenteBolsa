# Lote 4 para Codex — 3-jul-2026 — la firma trabaja 24/7 y come trabajo ejecutable

Hallazgos del responsable que motivan este lote: (a) el runtime del lab está
detrás de `_market_window` (runtime.py ~875) → la firma no piensa con mercado
cerrado; (b) el estreno real del nightly encontró 15 propuestas inelegibles, todas
`not_code_change` → los especialistas no alimentan el pipeline de código; (c) falta
el supervisor del nightly (P23 entregó solo CLI).

Tres tareas en orden, cada una con commit e informe propios.

**Bloque de verificación estándar (cada tarea):** `pytest tests\ -x -q` verde;
`ruff check src tests scripts` limpio; bump de `__version__`; ejecución real
documentada; commit revisable; confirmar `trading_mode=paper`,
`allow_live_trading=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`,
`core_sleeve.json` `dry_run=true`; NO tocar los 6 ficheros del suelo de kernel.

---

## P24 — Modo investigación con mercado cerrado + supervisor del nightly

1. **Research-mode del lab:** modifica el gate de `_market_window` en el runtime
   CI para que, con mercado CERRADO, en lugar de MARKET_BLOCKED ejecute un ciclo
   en `mode=research`: solo actividades sin dependencia de mercado (validaciones,
   estudios, lifecycle, generación/refinado de propuestas, digest de estado).
   Explícitamente EXCLUIDO en research-mode: cualquier cosa que toque candidatos
   vivos, órdenes, sizing o snapshots de mercado en tiempo real. Config en fichero
   propio `data/config/ci_research_mode.json` (`{"enabled": false, ...}`) —
   default OFF, human-gated (añádelo a la lista del gate de agresividad/gobierno
   para que la firma no se lo encienda sola). Con tests: mercado cerrado + flag
   ON → ciclo research; flag OFF → MARKET_BLOCKED como hoy; research-mode nunca
   invoca los caminos de trading (mock/spy que falle si lo hace).
2. **Supervisor del nightly** (cabo suelto de P23): script one-shot
   `scripts/run_codegen_nightly.ps1` + supervisor sin admin (mismo patrón que
   telegram/digest), hora por defecto 03:00. No lo arranques: documenta el
   comando para Antonio.
3. Presupuesto: el research-mode respeta los presupuestos LLM existentes del lab
   y añade contador visible en el digest (ciclos research corridos, coste tokens).
Informe: `docs/informe_codex_p24_research_mode_<fecha>.md`.

## P25 — Puente hallazgo→propuesta ejecutable + zanjar la fijación con observaciones

Objetivo: que el nightly tenga trabajo legítimo que comer.

1. **Puente determinista `findings_to_proposals`:** módulo del lab que lee fuentes
   de hallazgos MEDIDOS (agenda de investigación, edge tables, KPIs del digest,
   informes de estudios en docs/ listados explícitamente) y genera propuestas
   CODE_CHANGE bien formadas (targets en allowlist, test_requirement, evidencia
   citada, rollback plan) para mejoras concretas de observabilidad/herramientas.
   Siembra inicial (hazla tú, con criterio, 3-5 propuestas): p. ej. sección del
   digest para el lab book cuando se encienda; test de cobertura para estados del
   overlay shadow; mejora del parity check para múltiples días. Nada de trading.
   Cap: no más de 3 propuestas nuevas por ejecución; dedupe contra existentes.
2. **Zanjar las observaciones:** las 3 propuestas micro-batch en VALIDATING
   (`ci_prop_4c6c76e3e77f`, `ci_prop_6d884bc7fe00`, `ci_prop_71120d536576`) y la
   familia entera de `observation_execution_*`: estudia QUÉ son las 160
   observaciones pendientes y POR QUÉ no se ejecutan (diagnóstico read-only
   primero). Decide con datos: (a) si ejecutarlas en micro-lotes es valioso y
   seguro → conviértelo TÚ en UNA propuesta CODE_CHANGE con spec completa
   (límites, errores, tests) y déjala para el nightly/aprobación humana;
   (b) si no aporta o es riesgoso → rechaza la familia entera con razón
   documentada y añade regla de dedupe para que la firma deje de reproponerla.
   El informe debe explicar la decisión con la evidencia.
Informe: `docs/informe_codex_p25_puente_hallazgos_<fecha>.md`.

## P26 — Auditoría de producto: configuración efectiva + utilización del cast (read-only)

1. **Volcado de configuración efectiva:** tabla con los ~40 flags/parámetros más
   relevantes (trading, gates, LLM, lab, autonomía, presupuestos): valor efectivo
   actual (con .env cargado), default de código, y si está documentado en el plan
   maestro. Señala incoherencias o flags muertos.
2. **Utilización del cast de agentes:** desde las tablas del lab, por agente
   proponente (últimas 4 semanas): propuestas, % ejecutables, % rechazadas por
   constitución/gates, % que llegó a experimento/diff. Ranking de aporte vs ruido.
   Recomendación: qué especialistas retirar, re-instruir o potenciar.
3. **Gasto LLM por rol:** desde `llm_usage`, tokens/coste por rol (decisión,
   sentimiento, mejora, codegen, overnight) últimas 2 semanas; señala
   despilfarros (p. ej. el overnight degradado del 2-jul: `overnight_llm_response_invalid`
   — diagnostica si repite con el código nuevo y si es el mismo patrón de
   truncado/parsing ya arreglado en otros roles; si lo es, arréglalo igual).
4. Veredicto de producto en el informe: 5 recomendaciones priorizadas.
Informe: `docs/informe_codex_p26_auditoria_producto_<fecha>.md`.
