# Prompt P9 para Codex — 2-jul-2026 (tarde) — codegen que entrega parches aplicables

Contexto: tras P7 (v0.4.87) el codegen de la firma ya responde (deepseek-v4-flash,
16k tokens, `codegen_ok=true`), pero su primer patch real murió en sandbox con
`ValueError: No se encontró bloque old en src/agente_bolsa/continuous_improvement/digest.py`
(`ci_artifact_f099eb2d1e34`). Es el fallo clásico de search/replace: el modelo no
reproduce exactamente el texto actual del fichero. Objetivo de esta tarea: que
`CodegenPatchAgent` entregue parches que APLIQUEN, con un bucle de autocorrección
acotado. Todo dentro del allowlist del lab; sin tocar trading.

## Parte 1 — Diagnóstico del contexto que recibe el modelo

1. Antes de cambiar nada, inspecciona QUÉ recibió el modelo en el intento fallido:
   ¿el prompt de `CodegenPatchAgent` incluye el contenido ACTUAL y COMPLETO de
   `digest.py`, o un extracto/versión truncada? `digest.py` ha crecido (~450+
   líneas tras P4/P6): comprueba si el presupuesto de contexto lo recorta.
   Documenta en el informe qué se le envió (tamaños, no el texto entero).
2. Guarda como artefacto de propuesta el patch crudo generado en cada intento
   (`code_diff_attempt`), aunque falle, para post-mortem. Hoy el fallo solo deja el
   mensaje de error; queremos ver QUÉ generó.

## Parte 2 — Bucle de autocorrección acotado

3. Cuando la aplicación del patch falle en sandbox (bloque `old` no encontrado,
   malformado, etc.), NO cuentes eso como intento perdido sin más: reenvía al
   modelo, en la misma cadena, (a) el error literal de aplicación, (b) el fragmento
   REAL del fichero alrededor de donde quería tocar (o el fichero completo si es
   <600 líneas), y (c) la instrucción de regenerar el patch con el texto exacto.
   Máximo 2 rondas de corrección por intento. Registra cada ronda en el artefacto.
4. Regla de formato alternativa: si el target es un fichero completo <300 líneas o
   un fichero NUEVO (tests nuevos, docs), permite que el modelo entregue el
   contenido íntegro del fichero en vez de search/replace (menos frágil). Para
   ficheros grandes existentes, search/replace con autocorrección.
5. Endurece la instrucción del prompt de codegen: el bloque `old` debe copiarse
   VERBATIM del contenido proporcionado (sin reformatear, sin normalizar espacios),
   y el modelo debe elegir bloques `old` cortos y únicos.

## Parte 3 — Reintento e2e real

6. Reactiva `ci_prop_p7_core_sleeve_digest` (está en VALIDATING con razón
   `codegen_failed_after_3_attempts...`) y corre `gen-diff` con la maquinaria
   nueva: hasta 3 intentos × 2 correcciones. El cambio objetivo sigue siendo la
   sección "Core sleeve" del digest (leer
   `data/research/core_sleeve/core_sleeve_log.jsonl`, última decisión, advertencia
   si >3 sesiones sin registro).
7. Si el sandbox pasa (tests verdes): deja el artefacto en `READY_FOR_HUMAN_REVIEW`
   y cierra el informe con los comandos `review`/`approve` exactos para Antonio.
   Será la primera aplicación humana de un diff generado por la firma.
8. Si vuelve a fallar tras 3×2: respuestas y patches literales al informe, SIN
   fallback manual, y tu recomendación técnica (¿cambiar de formato de patch?
   ¿modelo distinto para codegen? ¿descomponer la tarea?). Esa decisión la tomará
   el responsable con tus datos.

## Tests

- Autocorrección: primer patch inválido + corrección válida → aplica (LLM mockeado).
- Agotamiento: 2 correcciones fallidas → intento FAILED con artefactos registrados.
- Modo fichero-completo: entrega de fichero nuevo íntegro → aplica.
- Verbatim: el prompt de codegen contiene el contenido actual del target (test que
  falle si alguien reintroduce truncado silencioso).

Informe único: `docs/informe_codex_p9_codegen_selfcorrect_<fecha>.md`.

Bloque de verificación obligatorio:
- `.\.venv\Scripts\python.exe -m pytest tests\ -x -q` verde con tests nuevos.
- `.\.venv\Scripts\ruff.exe check src tests scripts` limpio; lint ajeno en commit aparte.
- Bump de `__version__`.
- Ejecución real del `gen-diff` documentada (éxito con comandos para Antonio, o
  fallos literales).
- Commit(s) con diff revisable.
- Confirmar al cierre: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` con `dry_run=true`.
- NO tocar: `src/agente_bolsa/kernel.py`, `tools/broker.py`, `tools/execution.py`,
  `tools/risk.py`, `config.py`, `.env`.
