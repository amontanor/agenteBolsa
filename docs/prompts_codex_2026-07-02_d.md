# Prompt P7 para Codex — 2-jul-2026 (tarde) — reparar el programador de la firma

Contexto: en P6, `continuous-improvement-lab gen-diff` falló 3/3 con
`primary_error=LLM response without text content` (provider `opencode-go`, model
`glm-5.2`) y `local_fallback_error=Connection error`. Sin codegen operativo, la firma
no puede entregar diffs y la Fase 2 está muerta en runtime. Este es EL bloqueante del
hito "la firma funciona". Dos partes.

## Parte 1 — Diagnóstico y arreglo del codegen LLM

Precedentes en este mismo repo (estúdialos antes de tocar nada, el patrón de fallo es
conocido):
- C1.3 (v0.4.15): Kimi consumía ~1.200 tokens en razonamiento y devolvía `{}`; se
  arregló subiendo el límite del rol a 4.000 tokens y rechazando respuestas
  incompletas de forma explícita.
- Telegram radar B.1 (v0.4.79): `chat_for_role("deep")` devolvía prosa/fences; se
  arregló con extractor de JSON balanceado + reintento acotado.

Pasos:

1. **Diagnóstico con evidencia primero**: reproduce UNA llamada del rol de codegen y
   captura la respuesta CRUDA del proveedor (raw body): ¿hay `reasoning_content` sin
   `content`? ¿`finish_reason=length`? ¿Qué límite de tokens tiene el rol de codegen
   vs el tamaño del prompt que le manda `CodegenPatchAgent`? Documenta la respuesta
   literal en el informe ANTES de decidir el fix. No arregles a ciegas.
2. **Fix según lo que encuentres**, en este orden de preferencia:
   a. límite de tokens del rol insuficiente → súbelo (como C1.3) y rechaza
      explícitamente respuestas truncadas;
   b. contenido en campo de razonamiento no parseado → extracción robusta (como B.1);
   c. si `glm-5.2` resulta inadecuado para codegen tras a+b, cambia el modelo del rol
      de codegen a uno que ya funcione en el stack (p. ej. el de decisión/deep),
      documentando el criterio. NO toques los roles de decisión/sentimiento que
      funcionan.
3. **Visibilidad anti-degradación silenciosa** (lección repetida del proyecto):
   extiende `scripts/llm_health_check.py` (o el watchdog) para cubrir el rol de
   CODEGEN explícitamente, de modo que su caída aparezca en el health-check y no se
   descubra tres semanas tarde. Reporta también el estado esperado del fallback local
   (`127.0.0.1:8080`): si está apagado por diseño, que el mensaje de error lo diga en
   vez de un `Connection error` ambiguo.
4. **Test de regresión**: respuesta con solo razonamiento/truncada → error diagnosticable
   (no "sin contenido" genérico); respuesta válida → patch parseado.

## Parte 2 — Reintento e2e real + saneo de cola

5. **Reintento del e2e de la firma** con el codegen ya arreglado, esta vez por el
   cauce NORMAL de validación (no sembrar directamente en READY_TO_APPLY como en P6):
   propuesta nueva y real dentro del allowlist — sección "Core sleeve" en el digest
   diario que lea `data/research/core_sleeve/core_sleeve_log.jsonl` y muestre la
   última decisión (fecha, status would_submit/submitted/no_op, exposición objetivo,
   orden hipotética), con advertencia si no hay registro en >3 sesiones de mercado.
   Hasta 3 intentos de `gen-diff`; si pasa sandbox+tests, déjala en
   `READY_FOR_HUMAN_REVIEW` y cierra el informe con los comandos `review`/`approve`
   exactos para Antonio. Si vuelve a fallar tras el fix, las respuestas literales al
   informe y NO apliques fallback (queremos ver el fallo real).
6. **Saneo de la cola READY_TO_APPLY** según las recomendaciones de P6 (revisa cada
   payload antes de decidir, no las apliques a ciegas):
   - Rechazar con razón auditable: `ci_prop_p6_overlay_shadow_digest`
     (`superseded_by_fallback`), `ci_prop_712ea5e73d18` (dependiente de propuesta de
     gobierno rechazada), `ci_prop_9688d540359c` (target incompleto), y
     `ci_prop_08f79290fec2` / `ci_prop_d952ddf82197` SOLO si confirmas que son
     duplicadas/prosa (documenta el payload literal en el informe).
   - Las 3 de micro-batch de observaciones (`ci_prop_4c6c76e3e77f`,
     `ci_prop_6d884bc7fe00`, `ci_prop_71120d536576`): degradarlas de READY_TO_APPLY a
     VALIDATING con razón `requires_executable_spec` — la cola humana solo debe
     contener cosas aplicables. No las rechaces: la idea de fondo (ejecutar
     observaciones en micro-lotes con límites) puede tener mérito si alguien la
     convierte en spec.
   - Resultado esperado: cola READY_TO_APPLY vacía o solo con artefactos aprobables.
     Lista el estado final en el informe.

Informe único: `docs/informe_codex_p7_codegen_fix_<fecha>.md`.

Bloque de verificación obligatorio:
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` verde con tests nuevos.
- `.\.venv\Scripts\ruff.exe check src tests scripts` limpio; lint ajeno en commit aparte.
- Bump de `__version__`.
- Ejecuciones reales: la llamada cruda diagnosticada, `llm_health_check.py` mostrando
  el rol codegen, y el `gen-diff` del reintento (éxito o fallo literal).
- Commit(s) con diff revisable.
- Confirmar al cierre: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` con `dry_run=true`.
- NO tocar: `src/agente_bolsa/kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`.
