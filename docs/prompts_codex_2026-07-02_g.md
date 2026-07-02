# Prompt P11 para Codex — 2-jul-2026 — el apply humano no aplica en Windows (EOL/encoding)

Contexto: el responsable aprobó el contenido del diff `ci_artifact_dda66b200e41`
(propuesta `ci_prop_p7_core_sleeve_digest`), pero el `approve` real falló:

```
APPROVE | status=REJECTED_BY_TESTS | error=error: patch failed: src/agente_bolsa/continuous_improvement/digest.py:94
error: src/agente_bolsa/continuous_improvement/digest.py: patch does not apply
error: patch failed: tests/test_ci_phase3_digest.py:184
error: tests/test_ci_phase3_digest.py: patch does not apply
```

El sandbox validó el mismo patch con tests verdes; el árbol real lo rechaza. Es un
bug del CAMINO DE APPLY, no del diff. Hipótesis del responsable (verifícala, no la
asumas): discrepancia byte a byte entre el diff del artefacto y el working tree
real — line endings (git de Antonio tiene `core.autocrlf` activo: los avisos "LF
will be replaced by CRLF" salieron en su último commit) y/o encoding (la línea de
contexto del test contiene mojibake real: `PIDE APROBACIÃ“N`).

## Parte 1 — Diagnóstico con evidencia (antes de tocar nada)

1. Reproduce el fallo: extrae el diff del artefacto y corre `git apply --check -v`
   sobre el árbol real. Documenta el error exacto.
2. Evidencia de bytes: `git config core.autocrlf`; terminaciones de línea reales de
   `digest.py` y `tests/test_ci_phase3_digest.py` (CRLF vs LF) vs las del diff del
   artefacto; y bytes reales de la línea `PIDE APROBACIÓN` en el fichero (¿mojibake
   genuino en disco?).
3. Explica por qué el sandbox SÍ aplicó: ¿el GitSandbox normaliza EOL al clonar/
   escribir? Esa asimetría sandbox-vs-real es el bug de fondo.

## Parte 2 — Fix del camino de apply

4. Haz el apply humano robusto a esta clase de discrepancias, en este orden de
   preferencia (elige el primero que funcione y justifica):
   a. `git apply --index --3way` (resuelve contra los blobs del index);
   b. `git apply --index --ignore-whitespace`;
   c. normalizar EOL del diff del artefacto a los del working tree antes de aplicar.
   La solución debe valer para futuros artefactos, no solo para este.
5. Asegura simetría: el diff que guarda el preview/codegen debe generarse contra
   los BYTES reales de los ficheros del árbol (no una copia normalizada), o bien
   ambos caminos deben normalizar igual. Documenta cuál eliges.
6. Test que reproduzca el caso: repo sintético con fichero CRLF + artefacto con
   diff LF → antes fallaba, ahora aplica (o se normaliza y aplica).
7. Limpieza menor directa (commit aparte): la aserción con mojibake real en
   `tests/test_ci_phase3_digest.py` (`PIDE APROBACIÃ“N`) — corrígela a UTF-8 limpio
   si es un artefacto de doble encoding, ajustando lo necesario para que el test
   siga probando lo mismo.

## Parte 3 — Reintento final del e2e

8. Reactiva `ci_prop_p7_core_sleeve_digest` (quedó REJECTED_BY_TESTS por este bug),
   regenera el diff con `gen-diff` (la spec del esquema real ya está en el payload)
   y déjalo en `READY_FOR_HUMAN_REVIEW`. El contenido esperado es el mismo que el
   responsable ya aprobó (campos `exposure`, `decision.reason`, `decision.order.*`);
   si el nuevo diff difiere materialmente de eso, dilo en el informe.
9. NO ejecutes `approve`: eso es de Antonio. Cierra el informe con los comandos
   `review`/`approve` y la salida del `review`.

Informe: `docs/informe_codex_p11_apply_eol_<fecha>.md`.

Bloque de verificación obligatorio:
- `pytest tests\ -x -q` verde con tests nuevos; `ruff check src tests scripts` limpio.
- Bump de `__version__`.
- `git apply --check` del nuevo artefacto contra el árbol real DEBE pasar antes de
  cerrar (es la prueba de que el bug está muerto) — documéntalo.
- Commit(s) con diff revisable.
- Confirmar: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` con `dry_run=true`.
- NO tocar los 6 ficheros del suelo de kernel.
