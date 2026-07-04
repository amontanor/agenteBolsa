# Prompt P31 para Codex — lunes 6-jul-2026 — bump automático y contexto del módulo bajo test

Contexto: primer run autónomo del nightly (4-jul, `ci_codegen_nightly_6f75d401179a`):
2 propuestas intentadas, 2 rechazadas en sandbox. Post-mortem con evidencia (ver
plan §20): (1) `test_version_policy` tumba cualquier diff que no bumpee versión, y
el modelo, al intentar bumpear, inventó el contenido de `__init__.py` porque no
estaba en su contexto ("No se encontró bloque old"); (2) los tests generados
fallan porque el modelo aserta comportamientos de módulos que no ha visto
(propuestas cuyo target es solo el fichero de tests). Tres arreglos mecánicos.

**Bloque de verificación estándar:** `pytest tests\ -x -q` verde; `ruff check src
tests scripts` limpio; bump de `__version__`; ejecución real documentada; commit
revisable; confirmar `trading_mode=paper`, `allow_live_trading=false`,
`ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` `dry_run=true`; NO tocar
los 6 ficheros del suelo de kernel; ficheros grandes SOLO con escritura atómica
verificada.

## Parte 1 — El bump de versión es del pipeline, no del modelo

1. En el flujo de preview/codegen: tras aplicar el patch del modelo en sandbox,
   el PIPELINE bumpea `src/agente_bolsa/__init__.py` de forma determinista
   (parsear versión actual, +1 al patch level, escribir) y lo añade al diff del
   artefacto. El prompt de codegen instruye explícitamente al modelo: NO toques
   `__init__.py`, el sistema lo hace por ti. Si el modelo lo toca igualmente,
   descarta su hunk de `__init__.py` y usa el bump determinista.
2. Cuidado con el conflicto en `approve`: si entre la generación y el approve la
   versión real cambió, el bump del artefacto queda desfasado — el apply robusto
   de P11 (3way/normalización) debería resolverlo; añade un test que cubra ese
   caso (artefacto bumpea a X, árbol ya está en X → re-bumpear a X+1 en apply o
   rechazar con mensaje claro; elige y justifica).
3. Tests: diff sin bump → artefacto final lo incluye; modelo intenta bumpear →
   se ignora su versión y manda la del pipeline.

## Parte 2 — Contexto del módulo bajo test

4. Cuando una propuesta CODE_CHANGE tenga como target SOLO ficheros de tests,
   el contexto de codegen debe incluir además el código fuente de los módulos
   que esos tests importan/ejercitan (deterministico: parsear imports
   `agente_bolsa.*` del fichero de test existente, y/o campo explícito
   `modules_under_test` en el payload — soporta ambos). Respeta el límite de
   líneas de contexto ya existente.
5. Actualiza las 3 propuestas de P25 (`ci_prop_b3f950033a99`,
   `ci_prop_0327e166f163`, `ci_prop_82a01dd92356`) añadiendo
   `modules_under_test` correctos.
6. Test: propuesta test-only → prompt contiene el módulo bajo test.

## Parte 3 — Relanzamiento real

7. Relanza el nightly manualmente (`codegen-nightly --json`) con los fixes: debe
   volver a intentar las propuestas fallidas (ajusta la regla de "rechazadas
   previamente" para distinguir fallo de generación —reintentable tras fix— de
   rechazo humano/constitucional —definitivo—; documenta el criterio).
8. Lo que pase sandbox queda en READY_FOR_HUMAN_REVIEW; cierra el informe con
   `review`/`approve` para Antonio. NO ejecutes approve.

Informe: `docs/informe_codex_p31_bump_contexto_<fecha>.md`.
