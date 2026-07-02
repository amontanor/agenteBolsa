# Prompt P13 para Codex — 2-jul-2026 — bug limit-before-filter en approve (micro-tarea)

Contexto: el `approve` de `ci_prop_p7_core_sleeve_digest` devuelve BLOCKED
("No hay diff validado READY_FOR_HUMAN_REVIEW") aunque `review` lista el artefacto
restaurado. Causa localizada por el responsable en
`src/agente_bolsa/continuous_improvement/human_apply.py`:

- `_latest_ready_diff_artifact()` llama a `_diff_artifacts(limit=1)`.
- `_diff_artifacts` hace `ORDER BY updated_at DESC LIMIT ?` en SQL y DESPUÉS filtra
  en Python por `status=READY_FOR_HUMAN_REVIEW` y `tests_ok=true`.
- Con `limit=1`, la fila recuperada es la más recientemente actualizada — el
  artefacto P11 RECHAZADO (`ci_artifact_9a6378dc448e`, actualizado en P12) — que el
  filtro descarta → None → BLOCKED. El artefacto restaurado y válido
  (`ci_artifact_dda66b200e41`) nunca llega a evaluarse.

Tarea (quirúrgica, nada más):

1. Corrige `_latest_ready_diff_artifact` para que el filtro se aplique ANTES de
   quedarse con uno: recupera un lote razonable (p. ej. `limit=20`) y devuelve el
   primero que pase el filtro. Alternativa equivalente: mover el filtro de
   status/tests_ok al SQL. Elige la más limpia y coherente con el código.
2. Test de regresión: propuesta con dos artefactos `code_diff_preview` — el más
   reciente RECHAZADO y uno anterior READY_FOR_HUMAN_REVIEW con tests_ok=true →
   `approve` debe seleccionar el anterior (verifica con mock/sandbox que llega a la
   fase de apply, no hace falta aplicar de verdad si el test ya cubre la selección).
3. Verifica contra la BD real que, tras el fix, la selección para
   `ci_prop_p7_core_sleeve_digest` devuelve `ci_artifact_dda66b200e41` (solo
   lectura, sin aplicar).
4. NO ejecutes `approve` real: es de Antonio.

Informe: `docs/informe_codex_p13_approve_limit_<fecha>.md` (puede ser breve).

Bloque de verificación obligatorio:
- `pytest tests\ -x -q` verde; `ruff check src tests scripts` limpio.
- Bump de `__version__`.
- Commit con diff revisable.
- Confirmar: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- NO tocar los 6 ficheros del suelo de kernel.
