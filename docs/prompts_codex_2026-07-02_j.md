# Prompt P14 para Codex — 2-jul-2026 — approve falla la suite y no dice por qué

Contexto: tras el fix P13, `approve --proposal ci_prop_p7_core_sleeve_digest` aplica
el patch pero devuelve `REJECTED_BY_TESTS | error=Suite fallida tras apply humano`
(dos intentos idénticos, rollback limpio ambos). Problema doble: (a) no sabemos qué
test falla — el mensaje no guarda la salida de pytest; (b) el sandbox validó ese
artefacto solo con suites FOCALIZADAS, así que "sandbox verde" no implica "approve
verde". Tres partes.

## Parte 1 — Diagnóstico del fallo real

1. Reproduce lo que hace `approve` en una rama desechable: aplica el diff del
   artefacto `ci_artifact_dda66b200e41` (con la ruta robusta de P11), corre
   `pytest tests\ -x -q` COMPLETO y captura el test exacto que falla y su traza.
   Documenta la salida literal en el informe.
2. Según la causa, decide y justifica:
   - si el diff quedó desfasado frente al árbol actual (colisión con cambios de
     P11/P12/P13) → regenera o ajusta el artefacto para el árbol actual;
   - si es un test frágil/preexistente que el patch dispara indirectamente →
     arréglalo tú en commit separado, documentando por qué es frágil;
   - si es interferencia de entorno (procesos vivos, datos de `data/`, hora de
     mercado) → documenta el mecanismo exacto y hazlo determinista.

## Parte 2 — Observabilidad del approve (fix sistémico)

3. `approve` debe PERSISTIR la evidencia del fallo: en el artefacto
   `code_diff_human_approval_rejected`, guarda la cola de la salida de pytest
   (últimas ~50 líneas), el test que falló y el returncode. El CLI debe imprimir el
   nombre del test fallido, no solo "Suite fallida".
4. Test: un approve con suite fallida deja el artefacto de rechazo con esa
   evidencia consultable.

## Parte 3 — Simetría sandbox ↔ approve (fix sistémico)

5. Un artefacto no puede quedar `READY_FOR_HUMAN_REVIEW` si no ha pasado LO MISMO
   que ejecutará `approve`: añade a la validación de sandbox (o a un paso previo a
   marcar READY) la suite completa `pytest tests\ -x -q`, no solo los tests del
   diff. Si el coste en tiempo es alto, es aceptable: es el precio de que la cola
   humana solo contenga cosas aplicables de verdad.
6. Revalida el artefacto de esta propuesta con ese estándar nuevo: si pasa, déjalo
   READY; si no, ajústalo/regenéralo hasta que pase. Cierra con `review` limpio y
   los comandos para Antonio. NO ejecutes `approve`.

Informe: `docs/informe_codex_p14_approve_suite_<fecha>.md`.

Bloque de verificación obligatorio:
- `pytest tests\ -x -q` verde; `ruff check src tests scripts` limpio.
- Bump de `__version__`.
- Evidencia documentada: salida literal del test que fallaba y su resolución.
- Commit(s) con diff revisable.
- Confirmar: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` con `dry_run=true`.
- NO tocar los 6 ficheros del suelo de kernel.
