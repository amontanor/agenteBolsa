# Lote del GIRO — 7-jul-2026 — modo compra/venta de aprendizaje funcionando HOY

Contexto: LLM vivo (P-L1, v0.4.114). Mercado ABIERTO (sesión de hoy hasta 22:00
CEST). Objetivo del día: el modo experimento de aprendizaje corriendo en SHADOW
durante la sesión de hoy, listo para operar de verdad mañana a la apertura (o esta
misma tarde si Antonio lo decide tras revisar el shadow). Los agentes al 100%:
pipeline dinámico + firma nocturna.

Ejecuta las tareas EN ESTE ORDEN. Commit e informe propios por tarea. Si una se
bloquea >30 min, documenta y sigue con la siguiente (salvo G0, que es requisito
de todas). Verificación estándar en cada una: `pytest tests\ -x -q` verde;
`ruff check src tests scripts` limpio; bump de `__version__`; ejecución real;
staging explícito; `trading_mode=paper`, `allow_live_trading=false`,
`ALLOW_AUTO_APPLY_IMPROVEMENTS=false`; sin tocar los 6 ficheros del suelo de
kernel; ficheros grandes solo con escritura atómica.

## G0 — URGENTE: suite completa verde (bomba de relojería en tests)

`tests/test_lab_book_wall.py::test_lab_book_source_is_excluded_from_real_book_consumers`
falla con `linked_executed_buys == 0`. Casi seguro: fecha de señal hardcodeada
(~2026-07-02) que ha envejecido más allá del guard de matching de 5 días.

1. Confirma la causa; arregla generando las fechas sintéticas DINÁMICAMENTE
   (relativas a hoy / última sesión de mercado), nunca hardcodeadas.
2. Barrido preventivo: `grep "2026-0" tests/` — cualquier otro test con fechas
   recientes hardcodeadas + ventanas de antigüedad es la misma bomba; arréglalos
   igual.
3. La suite completa verde es GATE del approve humano y del nightly: sin G0 la
   firma entera está bloqueada. Ciérralo primero.
Informe breve: `docs/informe_codex_g0_suite_<fecha>.md`.

## G1 — P-L2: modo experimento de aprendizaje (spec completa en
`docs/prompts_codex_giro_aprendizaje.md`, sección P-L2 — implémentala TAL CUAL)

Añadidos operativos de hoy:

4. Tras el commit: reinicia servicios (`scripts\restart_services.ps1` o las
   tareas programadas) para cargar el modo, y verifica con `config-audit` que
   `learning_mode` aparece (enabled=false al entregar).
5. Enciende `enabled=true` con `shadow_first=true` (eso NO opera: solo loguea)
   y deja la sesión de HOY corriendo en shadow. Si queda sesión al cerrar la
   tarea, incluye en el informe el primer `learning_mode_shadow_<fecha>.json`
   real: qué habría comprado, por qué gate pasó, a qué tamaño.
6. El flip a operar de verdad (`shadow_first=false`) es de Antonio, no tuyo.

## G2 — P-L3: bucle de aprendizaje cerrado (spec en el mismo fichero)

Constrúyelo YA aunque los fills reales lleguen mañana: la sección del digest
"Aprendizaje de ayer", la verificación eslabón a eslabón instrumentada, y el
puente de la firma. En el informe: qué eslabones quedaron verificados con el
shadow de hoy y cuáles quedan pendientes del primer fill real (lista explícita).

## G3 — P-L4: scoreboard de aprendizaje (spec en el mismo fichero)

Con tests sintéticos; correrá vacío hasta que el cohorte exista. Los criterios
pre-registrados van VERBATIM en el informe y en el código (semanas 5-8 vs 1-4 +
pendiente positiva + batir al contrafactual).

## G4 — P31: fixes del nightly (spec en `docs/prompts_codex_2026-07-06_p31.md`)

Bump de versión por el pipeline (el modelo no toca `__init__.py`), contexto del
módulo bajo test, relanzamiento de las 2 propuestas fallidas. Con G0 verde, lo
que pase sandbox quedará en READY_FOR_HUMAN_REVIEW para el approve de Antonio.

## Cierre del lote

Resumen final único con: estado de cada tarea, versión final, qué debe hacer
Antonio (comandos exactos): revisar el shadow de hoy, decidir el flip, y la cola
de approve si G4 dejó diffs listos.
