# Lote 2 de prompts para Codex — 2-jul-2026 (tarde) — dirección revisada del responsable

Dirección aprobada por Antonio: (1) desplegar capital con control de riesgo es la
palanca nº1; (2) resucitar el hallazgo del horizonte de salida 5-10d; (3) separar
libro core y libro laboratorio; (4) KPIs de investigación (hipótesis matadas), no de
actividad; (5) la firma debe aprender a editar ficheros grandes.

Ejecuta las tareas EN ESTE ORDEN (P16 → P21). Cada una con su commit e informe
propios. Si una se bloquea, documenta y pasa a la siguiente. NINGUNA cambia conducta
de trading real: todo es read-only, flag OFF o human-gated.

**Bloque de verificación estándar (aplícalo a CADA tarea):** `pytest tests\ -x -q`
verde; `ruff check src tests scripts` limpio; bump de `__version__`; ejecución real
documentada; commit con diff revisable; confirmar `trading_mode=paper`,
`allow_live_trading=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`,
`core_sleeve.json` con `dry_run=true`; NO tocar los 6 ficheros del suelo de kernel
(`kernel.py`, `tools/broker.py`, `tools/execution.py`, `tools/risk.py`, `config.py`,
`.env`).

---

## P16 — Relectura del horizonte de salida 5-10d con la muestra acumulada (read-only)

El hallazgo más valioso sin explotar (Capa 2, ~20-jun): salidas actuales 1-3d con
expectativa −1,78% (PF 0,25) vs shadow 5-10d +1,18% (PF 1,34), no promovido por
n=4. Desde entonces hay ~2 semanas más de datos.

1. Re-ejecuta la comparación contrafactual de horizonte (la maquinaria de C2.1
   existe) con TODA la muestra madura disponible: expectativa, hit-rate, PF, alpha
   vs SPY, delta pareada, por horizonte 1-3d vs 5-10d, neto de 10 y 20 bps.
2. Desglosa por régimen y por mes (¿es estable o lo dispara un tramo?). Reporta n
   maduro por celda. Incluye también el contrafactual de `stale_guard`.
3. Criterios pre-registrados por el responsable (evalúalos, no los reinterpretes):
   promover el horizonte 5-10d a GUARDED solo si n>=20 pareado maduro, delta de
   expectativa positiva neta de 20 bps, y ventaja presente en >=2 meses distintos
   y >=2 regímenes. Veredicto binario CUMPLE/NO CUMPLE.
4. NO cambies conducta: si CUMPLE, deja diseñado (no activado) el cambio guarded
   con su flag y su plan de medición, para decisión humana.
Informe: `docs/informe_codex_p16_horizonte_salida_<fecha>.md`.

## P17 — Herramienta de paridad y runbook de activación/escalado de la manga

Prepara todo lo necesario para que la activación de la manga (decisión humana) sea
un trámite seguro:

1. Script `scripts/core_sleeve_parity_check.py` (read-only): compara, por fecha,
   la exposición del dry-run (`core_sleeve_log.jsonl`), la del overlay shadow
   (`overlay_shadow_log.jsonl`) y la recalculada por el motor del estudio deep con
   los mismos datos. Reporta divergencias (tolerancia 1e-6 en exposición; explica
   cualquier discrepancia de data_date). Salida legible + `--json`.
2. Escalera de escalado pre-registrada en `data/config/core_sleeve.json`: añade
   campo `max_sleeve_fraction_ladder: [0.30, 0.50, 0.70]` (informativo) y documenta
   en el runbook las puertas de cada escalón: >=5 sesiones de paridad limpia en el
   escalón actual + revisión del responsable + cambio manual de Antonio. El código
   NO escala solo: `sleeve_fraction` sigue siendo un valor manual human-gated.
3. Runbook `docs/runbook_core_sleeve_activacion.md`: pasos exactos para (a) activar
   dry_run=false, (b) subir escalón, (c) rollback inmediato (volver a dry_run=true
   y/o liquidar la manga), con los comandos literales.
4. Tests del parity check con datos sintéticos (paridad limpia y divergencia).
Informe: `docs/informe_codex_p17_parity_runbook_<fecha>.md`.

## P18 — Libro laboratorio (diseño + implementación en modo LOG-ONLY)

Resuelve el hambre de muestra sin sobre-operar el libro real: un libro paper
separado, tamaño minúsculo, cuya única función es generar outcomes para aprender.

1. Diseño primero (sección del informe): fuentes de candidatos (el embudo actual
   pre-gate, para medir lo que los gates rechazan), tamaño fijo por trade (p. ej.
   $200 notional), cap diario (p. ej. 10), etiquetado `source=lab_book` en
   `signal_outcomes` TOTALMENTE separado del libro real, y muralla: jamás afecta a
   sizing/decisiones del libro real ni cuenta para promociones sin OOS.
2. Implementación en modo LOG-ONLY (sin órdenes, ni siquiera paper): runner aislado
   (patrón telegram) que cada día registra los trades hipotéticos del lab book con
   entradas/stops/takes y los deja madurar vía el pipeline de outcomes existente.
   Config propia `data/config/lab_book.json` con `enabled=false` por defecto
   (`mode: "log_only"` como único modo implementado en esta entrega; el modo con
   órdenes paper queda para una tarea futura tras revisión).
3. Gobierno: añade los parámetros del lab book al aggressiveness_gate/human-gate
   (la firma no puede encendérselo ni engordarlo).
4. Tests: sizing fijo, cap diario, etiquetado, no-op con enabled=false.
Informe: `docs/informe_codex_p18_lab_book_<fecha>.md`.

## P19 — KPIs de investigación + agenda de hipótesis en el digest

1. Nueva sección del digest "Agenda de investigación": tabla de hipótesis abiertas
   con estado (pendiente/en curso/matada/promovida) y fecha objetivo. Siembra las
   actuales: pullback (6-jul), horizonte salida 5-10d (P16), telegram radar
   (~20-jul), overlay activación (esta semana), anomalía ORCL (P21).
   Persistencia simple (tabla SQLite o JSON en data/research/), con CLI para
   añadir/cerrar hipótesis.
2. KPIs nuevos en el digest: `estudios_ejecutados/semana`,
   `hipotesis_matadas/semana`, `hipotesis_promovidas/semana` — la salud de una
   firma de investigación es su tasa de mortalidad honesta, no su actividad.
3. Tests sintéticos de la sección y los KPIs.
Informe: `docs/informe_codex_p19_agenda_investigacion_<fecha>.md`.

## P20 — Codegen: diagnóstico de los fallos "bloque old" persistentes

La firma falló 3/3 en P15 pese a contexto completo y autocorrección. Sin esto no
puede mantener su propio código.

1. Post-mortem con los artefactos `code_diff_attempt` de P15: para cada intento,
   compara el bloque `old` generado con el fichero real — cuantifica el tipo de
   mismatch (espacios, líneas parafraseadas, contexto desplazado, bloque
   inexistente). Tabla en el informe.
2. Según el diagnóstico, implementa UNA mejora (la que los datos indiquen):
   (a) subir `CODEGEN_FULL_CONTENT_MAX_LINES` para permitir modo fichero-completo
   en targets como digest.py (~700 líneas) — el modelo reescribe el fichero entero
   y el diff se computa con git (elimina la clase entera de fallos old-block);
   (b) edición por anclas (número de línea + verificación); o (c) otra que
   justifiques con los datos. Con tests.
3. Valida con un caso real acotado: re-siembra una propuesta trivial de docs o
   digest y verifica que gen-diff entrega READY_FOR_HUMAN_REVIEW. NO apruebes.
Informe: `docs/informe_codex_p20_codegen_oldblock_<fecha>.md`.

## P21 — Micro-tarea: anomalía ORCL en el radar Telegram (read-only)

El radar registró ORCL con `ext_sma20=-23.35%` y `rsi=11.25`. O Oracle se desplomó
de verdad o hay dato corrupto contaminando el scorecard.

1. Verifica contra el cache de mercado/yfinance el precio real de ORCL en las
   fechas de la mención. ¿Es real la extensión -23%? Contrasta con un segundo
   símbolo del mismo post.
2. Si es dato corrupto: identifica la causa (símbolo mal extraído, precio de otro
   activo, split), corrígela con test, y marca/purga las filas afectadas del
   scorecard (documentando cuáles).
3. Si es real: documéntalo y no toques nada.
Informe: `docs/informe_codex_p21_orcl_anomalia_<fecha>.md` (breve).
