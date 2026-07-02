# Prompts P5 + P6 para Codex — 2-jul-2026 (tarde) — dirección del responsable

Decisión estratégica del responsable (aprobada por Antonio): el sistema adopta una
**manga core de SPY en paper gobernada por vol-target 12%** (evidencia: informe deep
v0.4.82, criterios pre-registrados CUMPLE), con el stock-picking como satélite en
shadow. Despliegue disciplinado: el código se entrega con FLAG OFF y modo dry-run;
la activación la hará el humano tras ~5 sesiones de paridad del overlay shadow.

Son dos tareas independientes (P5 y P6). Entrega cada una con su commit e informe
propios. Si una se bloquea, entrega la otra.

---

## PROMPT P5 — Manga core SPY con vol-target 12% (paper, flag OFF, dry-run)

Objetivo: que el portfolio paper tenga exposición de mercado gobernada por la única
palanca validada, sin activarla todavía.

Diseño requerido (arquitectura decidida por el responsable):

1. **Nuevo módulo** `src/agente_bolsa/strategies/core_sleeve.py` (o `tools/` si encaja
   mejor con el proyecto; justifica la elección):
   - Calcula la posición objetivo: `objetivo_SPY = equity_paper * sleeve_fraction *
     exposicion_vt12`, donde `exposicion_vt12` viene del MISMO motor que
     `research/overlay_shadow.py` (reutiliza, no dupliques).
   - Decide la orden de rebalanceo (compra/venta de SPY) SOLO si la desviación entre
     posición actual y objetivo supera la banda muerta (default 5 puntos porcentuales
     de la manga) — control de turnover, lección de la casa.
   - Límites duros codificados: solo símbolo SPY (allowlist de 1), nunca corto, nunca
     apalancado, máximo 1 orden de rebalanceo por día de mercado, y la manga nunca
     supera `sleeve_fraction` del equity.
2. **Configuración FUERA de `config.py`** (suelo de kernel: prohibido tocarlo). Usa un
   fichero propio `data/config/core_sleeve.json` con defaults seguros creado por el
   módulo si no existe: `{"enabled": false, "dry_run": true, "sleeve_fraction": 0.30,
   "rebalance_band_pp": 5, "target_vol": 0.12}`. Documenta cada campo.
3. **Runner aislado** (patrón telegram/overlay): script one-shot
   `scripts/run_core_sleeve_daily.ps1` + supervisor sin admin. NO registrar en el
   scheduler operativo en esta entrega. Flujo del one-shot:
   - lee la señal del día (reutilizando overlay_shadow o recalculando con el motor);
   - calcula la orden objetivo;
   - si `enabled=false` → log y salir;
   - si `enabled=true` y `dry_run=true` → registra en
     `data/research/core_sleeve/core_sleeve_log.jsonl` la orden que HABRÍA enviado
     (fecha, equity, exposición, objetivo, actual, orden, motivo), sin llamar al broker;
   - si `enabled=true` y `dry_run=false` → envía la orden paper LLAMANDO a las APIs
     existentes de ejecución/broker (queda PROHIBIDO modificar `tools/broker.py`,
     `tools/execution.py`, `tools/risk.py`; solo consumir sus funciones públicas).
     Respeta horario de mercado.
4. **Gobierno**: añade `sleeve_fraction` y `target_vol` de la manga a la categoría de
   agresividad del `aggressiveness_gate` (subir fracción o target_vol = más agresivo,
   human-gated con evidencia). `enabled`/`dry_run` deben quedar cubiertos como
   human-gated (la firma no puede proponerse a sí misma activarlo).
5. **Tests**: sizing correcto con casos sintéticos; banda muerta (no opera dentro de
   banda); flag off = no-op; dry-run = cero llamadas a broker (mock); nunca genera
   corto ni excede la manga; paridad de exposición con el motor del estudio deep.
6. Informe: `docs/informe_codex_p5_core_sleeve_<fecha>.md` con runbook de activación
   en 2 pasos (dry_run real → activo) para el humano, y una ejecución real en dry-run
   (flag temporalmente enabled+dry_run SOLO para esa demo, y devuelto a false; deja
   evidencia del JSON generado).

## PROMPT P6 — Primer cambio real de la firma end-to-end + fix CLI menor

Objetivo: ejercitar la cadena completa de la firma (proponer → codegen → sandbox →
cola humana) con una mejora REAL y útil, no una demo.

1. **Cambio objetivo para la firma** (está dentro del allowlist de codegen:
   `continuous_improvement/`): el digest diario debe incluir una sección nueva
   "Overlay shadow" con la última señal registrada en
   `data/research/overlay_shadow/overlay_shadow_log.jsonl` (fecha de datos, vol
   realizada, exposición objetivo VT10/VT12/SMA200) y una advertencia si el dato
   tiene más de 3 días de mercado (señal de que el supervisor está caído).
2. **Hazlo VÍA LA FIRMA, no directamente**: siembra la iniciativa/propuesta en el lab,
   usa `continuous-improvement-lab gen-diff` (CodegenPatchAgent) para producir el
   patch, deja que el sandbox corra tests, y deja el artefacto en
   `READY_FOR_HUMAN_REVIEW` con `tests_ok=true`. NO lo apliques tú: el informe debe
   terminar con los comandos exactos de `review` y `approve` para que Antonio ejecute
   la primera aplicación humana real. Si el codegen LLM falla tras 3 intentos,
   documenta el fallo con las respuestas literales (es dato valioso sobre la calidad
   del programador de la firma) y aplica el cambio tú como fallback en commit separado
   claramente etiquetado.
3. **Fix directo de Codex (no de la firma), commit separado**: registra el comando
   `validate-agent-config --json` en el parser CLI de `main.py` (la función
   `validate_agent_task_config` existe y no está cableada — hallazgo de P4). Con test.
4. **Pendiente de P4**: lista en el informe las propuestas que quedan HOY en
   `READY_TO_APPLY` tras el saneo (id, target, y si tienen evidencia enlazada), con tu
   recomendación apply/reject para cada una. Solo lectura: no cambies sus estados.

Informe: `docs/informe_codex_p6_firma_e2e_<fecha>.md`.

---

Bloque de verificación obligatorio (para P5 y P6, cada una):
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` verde con los tests nuevos.
- `.\.venv\Scripts\ruff.exe check src tests scripts` limpio; lint ajeno en commit separado.
- Bump de `__version__` (uno por entrega).
- Ejecuciones reales documentadas (dry-run del sleeve; digest con la sección nueva
  solo si Antonio aprueba el diff — no la fuerces).
- Commit(s) con diff revisable.
- Confirmar al cierre: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, y `core_sleeve.json` con `enabled=false`.
- NO tocar: `src/agente_bolsa/kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`.
