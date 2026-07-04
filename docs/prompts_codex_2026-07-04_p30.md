# Prompt P30 para Codex — 4-jul-2026 — arranque idempotente y stack-status

Contexto: el proceso de levantado no es idempotente y ya ha producido duplicados
dos veces (supervisores Telegram el 2-jul; ahora 2+ instancias de Streamlit
arrancadas el 3-jul a las 08:02 y 09:37). Nada comprueba "¿ya estoy corriendo?".
Objetivo: que Antonio gestione todo el stack con dos comandos y que duplicarse
sea imposible.

**Bloque de verificación estándar:** `pytest tests\ -x -q` verde; `ruff check src
tests scripts` limpio; bump de `__version__`; ejecución real documentada; commit
revisable; confirmar `trading_mode=paper`, `allow_live_trading=false`,
`ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` `dry_run=true`; NO tocar
los 6 ficheros del suelo de kernel. OJO: `scheduler.py` y `web_app.py` son
ficheros grandes — edítalos SOLO con escrituras atómicas verificadas (lección
§3.4 del plan y del informe del responsable P27-P29).

## Parte 1 — Locks de instancia única

1. Mecanismo común (módulo pequeño, p. ej. `tools/single_instance.py` o helper
   PowerShell compartido): fichero `data/run/<servicio>.pid` con el PID; al
   arrancar, si el fichero existe Y ese PID sigue vivo con línea de comando
   compatible → salir limpiamente con "ya corriendo (PID X desde HH:MM)"; si el
   PID está muerto → tomar el lock (huérfano). Al salir, liberar.
2. Aplícalo a TODOS los supervisores/one-shots residentes:
   `run_telegram_radar_supervisor.ps1`, `run_overlay_shadow_supervisor.ps1`,
   `run_ci_digest_supervisor.ps1`, `run_codegen_nightly_supervisor.ps1`,
   `run_core_sleeve_supervisor.ps1`.
3. Panel web: antes de lanzar Streamlit, comprobar si el puerto 8501 ya responde
   (o lock pid) → si sí, NO lanzar otro (mensaje claro). Aplícalo en el punto de
   arranque del panel (script/lanzador), sin tocar el runtime del scheduler
   operativo más de lo imprescindible.

## Parte 2 — stack-status y stack-up

4. `scripts/stack_status.ps1` (y/o subcomando CLI `stack-status`): tabla de
   servicios esperados → estado (CORRIENDO pid/hora | PARADO | DUPLICADO pids):
   scheduler (tarea programada), web :8501, y los 5 supervisores. Detección por
   locks + procesos reales (no solo por el lock). Salida legible + `--json`.
5. `scripts/stack_up.ps1`: arranca SOLO lo que falta (nunca duplica, reutiliza
   los locks), informa qué arrancó y qué ya estaba. `scripts/stack_down.ps1`
   para parar supervisores (no toca las tareas programadas del scheduler/web
   salvo flag explícito).
6. Runbook breve `docs/runbook_stack.md`: levantar, revisar, parar, y qué hacer
   con duplicados/huérfanos.

## Parte 3 — Limpieza de duplicados actuales + warnings

7. En la ejecución real: detecta los duplicados vivos AHORA (Streamlit ×N y
   cualquier supervisor repetido), documenta PIDs y déjalo en el informe; mata
   los sobrantes SOLO si es inequívoco (mismo comando exacto, mas antiguo), o
   deja el comando exacto para Antonio si prefieres no matar procesos tú.
8. Menor: los logs del panel están llenos de `use_container_width` deprecado de
   Streamlit — reemplazo mecánico por `width='stretch'` en `web_app.py`
   (atómico, con parse + smoke del panel), para que el log vuelva a ser legible.

Informe: `docs/informe_codex_p30_stack_<fecha>.md` con la ejecución real de
`stack-status` antes/después.
