# Micro-lote P-L5 para Codex — pulido post-giro (nada bloquea la operativa de mañana)

Contexto: learning_mode está AUTORIZADO por Antonio y operativo
(enabled=true, shadow_first=false). Tres pulidos, en orden, commits e informes
separados. Verificación estándar en cada uno: pytest completo verde, ruff limpio,
bump `__version__`, ejecución real, staging explícito, paper/live/auto-apply
intactos, sin tocar suelo de kernel, ficheros grandes con escritura atómica.
OJO: puede haber approves humanos recientes con commits en la rama — haz `git log`
antes y trabaja sobre lo último; UN solo escritor de git a la vez.

## A — Semántica del Safety para learning_mode autorizado

Hoy `config-audit`/digest marcan `Safety: ALERTA -> learning_mode.enabled` porque
el check espera enabled=false. Eso era correcto ANTES de la autorización; ahora es
un falso rojo permanente. Cambio:

1. `learning_mode.enabled` deja de ser violación por sí mismo. Violación real:
   `human_gated=false`, o config no parseable. El estado ON/OFF + shadow_first se
   muestra SIEMPRE en la línea Safety como información
   (`Safety: OK (... ) | learning_mode=ON, shadow_first=False`).
2. Extra de gobierno: soporta campo opcional `authorized_by` en
   `learning_mode.json` (string libre, p. ej. "Antonio 2026-07-07"); si
   enabled=true y `authorized_by` vacío → ALERTA `learning_mode.sin_autorizacion`.
   Añade el campo al JSON real con la autorización de hoy.
3. Actualiza los tests de config_audit/digest afectados.

## B — restart_services encadena stack_up

`restart_services.ps1` mata TODOS los procesos (incluidos los 5 supervisores) pero
solo relanza scheduler+web; los supervisores quedan muertos con locks huérfanos
hasta un stack_up manual (nos ha pasado dos veces). Al final del script: invocar
`stack_up.ps1` y mostrar `stack_status`. Verifica con una ejecución real que tras
el restart quedan 7/7 CORRIENDO.

## C — Etiqueta deshonesta en capacity fills + verificación LLM del ciclo

En el shadow real de hoy (`learning_mode_shadow_*.json` del 7-jul), el LLM produjo
una recomendación real (TECH, tesis de opa Merck) y aun así los capacity fills
salieron etiquetados "Fallback determinista por fallo del LLM".

1. Diagnostica: ¿fue fallo parcial real del LLM en ese ciclo (mira `llm_usage` y
   errores del ciclo `20260707-145337`) o es una etiqueta heredada que se pone a
   todo capacity fill aunque el LLM haya respondido?
2. Fix de honestidad: el reason debe distinguir `capacity_fill_tras_llm_ok`
   (el LLM respondió pero dejó capacidad sin usar) de
   `capacity_fill_por_fallo_llm` (fallo real). Esto importa para el aprendizaje:
   el cohorte debe saber qué señales vienen de cabeza pensante y cuáles de
   relleno determinista — es una dimensión de análisis del scoreboard.
3. Asegura que esa distinción llega a `signal_outcomes` (features del cohorte)
   para poder comparar aprendizaje LLM vs determinista más adelante. Con tests.

Informes: `docs/informe_codex_pl5a_...md`, `pl5b`, `pl5c` (o uno consolidado con
tres secciones si prefieres). No toques `learning_mode.json` salvo lo dicho en A.
