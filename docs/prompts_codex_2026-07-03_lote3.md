# Lote 3 para Codex — 3-jul-2026 — muralla del lab book + orquestador-lite Fase 3

Dos tareas, en orden. Cada una con commit e informe propios.

**Bloque de verificación estándar (cada tarea):** `pytest tests\ -x -q` verde;
`ruff check src tests scripts` limpio; bump de `__version__`; ejecución real
documentada; commit revisable; confirmar `trading_mode=paper`,
`allow_live_trading=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`,
`core_sleeve.json` `dry_run=true`, `lab_book.json` `enabled=false` (hasta orden
del responsable); NO tocar los 6 ficheros del suelo de kernel.

---

## P22 — Auditoría de consumidores de signal_outcomes (muralla del lab book)

Antes de habilitar el lab book (aunque sea log-only), hay que garantizar que sus
filas jamás contaminan estudios ni decisiones del libro real.

1. Inventario exhaustivo: TODO código que lee `signal_outcomes` (edge_analysis,
   setup_edge, study_strategy_edge_compare, exit_horizon_shadow,
   profitability_scoreboard, promotion_readiness, weekly reports, learning/memories,
   cycle_runner, lo que encuentres). Tabla en el informe: consumidor → ¿filtra
   source? → riesgo de contaminación por `source=lab_book`.
2. Donde falte filtro: exclúyelo por defecto (`source != 'lab_book'` o allowlist de
   sources reales), con la opción explícita de INCLUIRLO solo en herramientas que
   analicen el propio lab book. Cambios mínimos y con test por consumidor tocado.
3. Test-candado global: un test que inserte una fila sintética `source=lab_book` y
   verifique que los consumidores principales (edge, comparador, scoreboard,
   readiness) NO la cuentan. Este candado protege también el veredicto pullback
   del lunes.
4. Veredicto final del informe: "SEGURO/NO SEGURO habilitar lab book log-only".
   NO lo habilites tú: decisión del responsable con tu informe.
Informe: `docs/informe_codex_p22_muralla_lab_book_<fecha>.md`.

## P23 — Orquestador-lite del pipeline de código (Fase 3, primer paso real)

Hoy cada gen-diff exige siembra/reactivación manual (los `P9/P10/P11/P15
ManualCodegenGate`). Objetivo: que la firma trabaje sola de noche y el humano solo
apruebe de día. SIN apply automático jamás.

1. Job diario aislado (patrón supervisor sin admin, como telegram/digest):
   `continuous-improvement-lab codegen-nightly` (o script equivalente) que:
   a. selecciona propuestas CODE_CHANGE elegibles: con evidencia/validación
      objetiva positiva, targets 100% dentro del allowlist de codegen, sin
      violaciones de constitución/agresividad, no rechazadas previamente;
   b. ejecuta `gen-diff` para un máximo de 2 propuestas/día (presupuesto de
      tokens acotado y configurable en fichero propio, NO en config.py);
   c. deja lo que pase sandbox+suite en READY_FOR_HUMAN_REVIEW;
   d. registra en el digest matinal: intentos, éxitos, fallos con causa, y la
      cola PIDE APROBACIÓN resultante.
2. Salvaguardas duras con test: nunca llama a approve/apply; máximo diario;
   presupuesto de tokens; se detiene si `ALLOW_AUTO_APPLY_IMPROVEMENTS` no es
   false (paradoja intencional: si alguien enciende auto-apply, el nightly se
   NIEGA a generar — doble freno); los parámetros del nightly son human-gated
   (la firma no puede subirse su propio cupo).
3. Limpieza de estados colgados (auditable): rechaza la demo
   `ci_prop_codegen_demo_51f112150ca0` (razón `demo_cleanup`); verifica que
   `ci_prop_p15_core_sleeve_null_order_digest` quedó coherente tras el hotfix
   (APPLIED con referencia al commit fa126d40); lista cualquier otra propuesta
   en estado inconsistente que encuentres, con recomendación.
4. No arranques el supervisor: deja el comando documentado para Antonio.
Informe: `docs/informe_codex_p23_orquestador_lite_<fecha>.md`.
