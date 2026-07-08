# Micro-lote P-L6 para Codex — mañana del 8-jul — flecos antes de la primera sesión operativa

Cuatro tareas pequeñas, en orden, commits e informes separados. Verificación
estándar en cada una (pytest completo, ruff, bump, ejecución real, staging
explícito, paper/live/auto-apply intactos, sin suelo de kernel, escritura atómica
en ficheros grandes). El mercado abre 15:30: nada de esto debe tocar el camino de
trading de hoy.

## A — Catch-up de supervisores diarios (el digest se perdió 2 mañanas)

El último `ci_digest_*.md` es del 5-jul: los restarts de los días 6-7 mataron al
supervisor después de su hora y el patrón "espera a RunAt de mañana" se traga las
ejecuciones perdidas.

1. En el patrón supervisor común (o en cada uno de los 5): al arrancar, si HOY ya
   pasó su RunAt y el artefacto del día no existe (digest del día, overlay del
   día, etc. — usa el marcador natural de cada job), ejecutar el one-shot
   inmediatamente antes de programar el NEXT_RUN. Con test del helper de decisión.
2. Ejecución real: genera el digest de HOY (que faltaba) y verifica que sale con
   la línea Safety nueva (`learning_mode=ON, shadow_first=False` + authorized_by).
3. De paso: el fichero digest escribe "PIDE APROBACIÃ“N" (mojibake al escribir el
   .md). Arregla el encoding de escritura para que el operador lea UTF-8 limpio.

## B — El approve no dijo qué test falló (regresión de observabilidad P14)

Anoche `approve ci_prop_b3f950033a99` devolvió `REJECTED_BY_TESTS ...
failed_test=` (VACÍO). P14 exigía persistir e imprimir el test culpable.

1. Reproduce el hueco: ¿por qué `failed_test` quedó vacío en ese rechazo? (mira
   el artefacto `code_diff_human_approval_rejected` de anoche: ¿tiene la cola de
   pytest? ¿el parser del nombre del test no casó con el formato de salida?).
2. Arregla y cubre con test (formato real de salida de pytest -x actual).
3. Documenta en el informe QUÉ test tumbó anoche a b3f950 (la evidencia debe
   estar en el artefacto o en el log).

## C — Relanzar la propuesta caída (sección lab_book del digest)

`ci_prop_b3f950033a99` quedó REJECTED_BY_TESTS con artefacto desfasado (base
0.4.118; entre medias entraron P-L5A/B/C y 2 applies).

1. Reactívala por el cauce habitual y relanza `gen-diff` contra el árbol actual
   (la maquinaria de autocorrección + contexto + bump determinista ya existe).
2. Si pasa sandbox+suite: déjala en READY_FOR_HUMAN_REVIEW con los comandos
   `review`/`approve` para Antonio. Si falla, evidencia literal y NO fallback.

## D — Higiene de la agenda de investigación

1. Cierra `anomalia ORCL` (P21 la verificó: dato REAL, doble descarga
   independiente; estado `matada` con nota "dato real confirmado, gate lo
   rechazó correctamente").
2. Actualiza `pullback` con target 2026-07-10 (re-lectura con datos maduros) y
   `overlay activacion` a estado `matada` con nota "manga SPY apagada por giro de
   objetivo 7-jul (desvío reconocido); estudios archivados como activo".
3. Añade hipótesis nueva: "learning_experiment: ¿aprende?" target 2026-09-01,
   notas "criterio pre-registrado semanas 5-8 vs 1-4 + contrafactual (P-L4)".
