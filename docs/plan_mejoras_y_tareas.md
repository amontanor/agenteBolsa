# Plan maestro de mejoras y tareas — agenteBolsa

## P-L70 — rediseño UX del resumen diario Telegram (candidato 0.4.203)

- Worktree aislado `pl70_telegram_summary_ux`, rama
  `codex/pl70-telegram-summary-ux`, desde `87d29018`/árbol `fd690a93`.
- Caracterización `b5b3fec4`, implementación `f78de077` y QA focal
  `0a18924c`; dictamen `ready_for_integration_rehearsal`; no despliegue.
- QA R1: `12de9be5` y `1b64dc5a`; la regresión de fecha P-L63 quedó
  determinista con reloj congelado. El recibo conserva texto exacto y
  `text_sha256` separado de `content_hash`; el límite se valida en 4096
  unidades UTF-16 y el truncado reconcilia visibles/omitidas.
- Cambia el resumen a `p-l70.telegram-daily-summary.v2`: equity sin signo,
  importe solo desde el par equity actual/anterior, comparación SP500
  provisional cuando P-L68 no permite comparabilidad, cobertura de posiciones,
  grupos deterministas y límite Telegram 4096 con truncado explícito.
- `telegram_trade_notifications.py`, reconciliación, PMR, scheduler cadence y
  trading permanecen sin cambios. Suite final aislada: `2261 passed, 1
  skipped, 1 warning`; el skip es el test condicional preexistente de historia
  SQLite local (`test_score_study_regression_current_sqlite`). Smoke real y
  mensaje Telegram no ejecutados.
- P-L70BR1 integrado sobre producción documental mediante merge `0083f414`, con
  QA `a64c493a`: `2261 passed`, focales `86 passed` y QA de integración `1
  passed`. Dictamen `ready_for_closed_market_deployment`; despliegue sigue
  pendiente y requiere sus precondiciones operativas habituales.

## P-L71 — autoridad EOD y coherencia temporal Sistema vs benchmark (0.4.205)

- Implementación aislada en `pl71_eod_authority`, rama
  `codex/pl71-eod-authority`; la base productiva `0.4.202` no se modificó.
- Se reprodujo la selección lexicográfica del cache SPY que publicaba
  `-0,304428%` desde una barra same-day mutable. El productor exige intervalo,
  rango, basis, fuente y autoridad temporal; same-day sin finality queda
  `unavailable` y un cache posterior puede proyectarse como
  `post_session_cache`.
- UI y Telegram consumen un overlay read-only que conserva el benchmark
  almacenado y declara `source`, `price_basis`, `generated_at/as_of` y estado.
  No hay backfill ni cambio de trading. Suite cerrada: 2260 passed, 1 skip
  preexistente y 1 warning; smoke real omitido por seguridad.

## P-L67R1 — Despliegue combinado 0.4.201 (28-jul-2026)

- Dictamen: `deployed`. Merge productivo `915481ab325d46c81a92986bfd603f13c5134dd9`;
  árbol funcional `f3a2eda76f3c317d68d8679ce00a7ea43a6aa023`, idéntico al
  candidato final `b25c9603`.
- Integra P-L63/P-L65B, P-L62 y P-L66. Suite productiva:
  `2243 passed, 1 warning`; Ruff, NUL, diff, configuración y kernel verdes.
- Dos comprobaciones postarranque: HTTP 200/200, scheduler único lógico,
  lock/token coherentes, cero órdenes desde el reinicio y lease postmarket
  vacío. El ciclo natural `mkt_2fe0c3db689e` terminó `completed`.
- Salud final `warning`, con cero alertas críticas. El resumen Telegram queda
  programado una vez por sesión a las 22:05 Europe/Madrid y los avisos de fills
  están activos mediante configuración local.

## P-L66 — Resumen diario por Telegram (0.4.201, desplegado)

- Primer intento a las 22:05 Europe/Madrid y fallback idempotente después del
  terminal durable del postmarket.
- Reutiliza la misma foto de cartera y la fila `performance_daily`; no añade
  llamadas al broker.
- Publica variación diaria de equity, SP500 y P/L total/diario por posición.
- Token y `chat_id` solo mediante entorno local; desactivado por defecto.
- Recibo append-only por sesión evita reenvíos después de un éxito confirmado.
- Integrado y desplegado dentro de P-L67R1.

## P-L71-R1 - wiring EOD comun para Telegram (0.4.205)

- Reproducido contra `7beeb135`: Telegram publicaba el `spy_pct` legacy
  `-0,304428%` aunque el benchmark proyectado EOD era `+0,250308%` y
  comparable.
- `publish_daily_summary` aplica ahora el mismo overlay read-only que la UI;
  job 22:05 y fallback PMR comparten esta frontera. Sin cache posterior con
  autoridad EOD se publica `n/d`, nunca el valor same-day persistido.
- No hay backfill, reenvio posterior automatico, cambio de instrumento,
  cambio de trading ni modificacion productiva. Candidato listo para ensayo
  de integracion cerrado; P-L70BR1 queda paralelo.

> **Este documento es la fuente unica de verdad de la mejora del sistema.**
> Contiene la vision, lo ya ejecutado, el diagnostico vigente, las tareas con su
> estado (terminado / no terminado) y las propuestas siguientes.

### P-L65A — contrato diario Sistema vs SP500 (28-jul-2026)

- Caracterización aislada en `pl65a_daily_vs_spy_contract`, versión `0.4.198`;
  XNYS abierto, sin cambios en `src` ni producción.
- La métrica primaria es variación de equity sobre cierre anterior. El
  porcentaje sobre invertido es secundario y no decide el ganador. SPY exige
  misma ventana, source, basis, as_of y calidad.
- Se reprodujo que `_performance_baseline_series` consume columnas legacy sin
  validar el bloque canónico, y que el selector de cartera usa días naturales:
  siete días pueden contener menos de siete sesiones XNYS. La cifra 13/17/0/9
  de 39 no existe en este árbol y queda sin atribución.
- Tooltip Sistema/SP500 verificado declarativamente: Fecha, `% ganancias`,
  Serie, `+.2%`, idéntico en línea/puntos, sin `y0`/`y1`.
- Dictamen: `ready_for_p65b_implementation`. Siguiente: implementar el
- Version policy required candidate `0.4.199`; no production logic changed.
  rowset canónico y contadores por sesiones, sin cambiar trading ni hacer
  llamadas adicionales al broker/red.

### P-L65A-R1 — alcance real del panel dirty (28-jul-2026)

- El checkout productivo dirty contiene P-L61/P-L62 que no están en P-L63R1:
  `web_app.py` SHA-256 `FC6ABAD9D799077D402866194A93D939657CC16CAC6943BC40B139A608D8205A`;
  `test_web_app.py` SHA-256
  `9580147B3E0C8F0E264A1721AA95D13C5EFF3E14F75634517E25C1C551EA1E1B`.
- P-L63R1/P-L65A comparten `web_app.py` SHA-256
  `33E5DE1F223080872F734CE389B8164409E99EDF4B29095E4164AC9BA1CC5FD1` y
  no tienen `_render_daily_vs_spy_table`; por tanto la captura `13/17/0/9 de
  39` solo puede atribuirse al objeto dirty, no a esa base.
- Caracterización aislada: `pl65a_r1_actual_ui_characterization`, 22 tests
  verdes. Se reproduce el contador global previo al recorte, el ganador por
  exposición frente a SPY y la divergencia tabla/gráfico por huecos. No se
  modificó `src` ni producción. Dictamen: `ready_for_p65b_implementation`
  condicionado a componer P-L63R1 con el diff dirty exacto documentado en
  `docs/P-L65A-R1_informe.md`.
- P-L65B conserva la reserva `0.4.200`; la prueba de version policy queda
  pendiente de ese bump en implementación, no se consume en esta
  caracterización tests/docs.
> **Toda mejora futura se gestiona anadiendo pasos AQUI** (no en hilos sueltos ni
> en otros documentos). Cada entrega debe: (1) anadir/actualizar su paso en este
> fichero con su estado, (2) subir la version en `src/agente_bolsa/__init__.py`
> (se muestra en la barra lateral del dashboard), y (3) dejar el sistema levantado
> con los cambios cargados (ver seccion 7).

- Rama de integracion desplegada: `codex/mejora_continua`
- Version productiva estable: **0.4.201** (P-L67R1 desplegado el 28-jul)
- Candidato final conservado: **0.4.201**, HEAD `b25c9603`, tree `f3a2eda7`
- Ultima actualizacion: 2026-07-28
- Estado P-L50BR1: worktree combinado candidato **0.4.188**; secuencia
  P-L49B 0.4.186 -> P-L46BR3 0.4.187 -> P-L50B 0.4.188. La linea anterior
  conserva el estado historico del ensayo individual P-L49B.
- Modo operativo: paper (Alpaca paper). Live trading bloqueado por diseno.

## P-L54B-T - caracterizacion del embudo shadow de capital (27-jul-2026)

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54bt_capital_funnel_characterization`,
  rama `codex/pl54bt-capital-funnel-characterization`, base P-L58R1 exacta,
  version conservada `0.4.193`.
- Dictamen: `ready_for_p54b_implementation`. Tests y documentacion solamente;
  no hay productor shadow ni wiring productivo.
- La fixture canonica separa 376 recomendaciones BUY, 15 planes y 15
  ordenes/fills. Exposicion observada 10,85%; target y notional objetivo
  permanecen `unavailable` si no existe autoridad estructurada.
- Siguiente paso unico: implementacion shadow aislada del contrato
  `p-l54b.capital-deployment-funnel-shadow.v1`; no desplegar ni cambiar
  politica con esta caracterizacion.

## P-L54B-T-R1 - invariantes de alcance y notional (27-jul-2026)

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54btr1_funnel_invariants`,
  rama `codex/pl54btr1-funnel-invariants`, desde `b99d6fc4`, version 0.4.193.
- Se reproduce y corrige el snapshot no secuencial: la tabla valida queda
  selection 376 -> gates 306 -> capacity 145 -> sizing 95 -> risk/plans 15.
  Caidas primarias exactas: 361; planes/ordenes/fills: 15.
- El notional risk-approved queda en 15.000 USD con cobertura 15/15; target
  exposure y notional objetivo siguen unavailable. No se modifica src ni
  productor.
- Siguiente paso unico: P-L54B-W sobre este contrato cerrado, en otro lote.

## P-L58R1 - ensayo combinado de seguridad de medicion (27-jul-2026)

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl58r1_measurement_safety_rehearsal`,
  rama `codex/pl58r1-measurement-safety-rehearsal`, version 0.4.193.
- Merges `--no-ff` en orden P-L53BR2 -> P-L43C-R1 -> P-L57A:
  `01c2c5644d449b235c594e79032b5260c8a82fe1`,
  `b61a3036ee05bfa8a6fd2edef90a34e548e9aa73`,
  `e0e1962534e0877fa96fcfd80c524f000a58dafe`.
- QA combinada: `b066b65c50d0a43713bbcd899304e5b3202753ec`.
- Resultado: `ready_for_closed_market_full_validation`. Suite cerrada:
  1987 passed, 1 skip preexistente; Ruff, NUL, diff, configuracion y version
  policy verdes. Smoke CLI no ejecutado por seguridad (`smoke_unavailable_by_safety`).
- No cambia trading: P-L53 queda fuera del PMR; P-L43C conserva
  submit -> save_broker_order -> telemetria fail-open; P-L57A solo hace
  null-safe a los consumidores observacionales.
- El perfil P-L53 de 500 candidatos registra evento de 757177 bytes y 17 MB
  de memoria pico; riesgo operativo medio, sin locks y con persistencia despues
  del envio. No se promociona ni despliega en este lote.

## P-L51C-T - carrier de provenance BUY -> SELL (21-jul-2026)

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl51c_provenance_carrier_tests`,
  rama `codex/pl51c-provenance-carrier-tests`, base `adf9a5c4`.
- Se caracteriza como frontera minima viable el metadata del `order_plan`
  transportado al payload local de `broker_order`; no cambia el request al
  broker y sobrevive la reconciliacion.
- La proyeccion actual P-L48 pierde el carrier arbitrario. Dictamen:
  `ready_for_p51c_implementation`; falta implementar solo esa proyeccion
  acotada y volver a demostrar captura futura real.
- Commit de tests: `9b12b07e`; no hay bump de version ni cambios en `src`.

## P-L51BR1 - ensayo combinado (21-jul-2026)

- Worktree candidato: `C:\Antonio\Bref\agenteBolsa_worktrees\pl49_pl46_pl50_pl51_combined_rehearsal`,
  rama `codex/pl49-pl46-pl50-pl51-combined-rehearsal`, version `0.4.189`.
- Merge `--no-ff` P-L51B-W: `5e3d2887aaa4f65ad67cda26885de9c09148af6d`.
- QA focal: `991cd95d`; 219 pruebas pasaron. Ruff, NUL, diff y
  `validate-agent-config --json` temporal pasaron.
- Dictamen: `needs_redesign`. Los objetos persistidos reales no contienen aun
  provenance BUY->SELL suficiente (`buy_broker_order_id`, allocations y fill
  fragments canonicos); el contrato responde unavailable/ambiguous y net null.
- No se toca produccion ni se ejecutan suite completa, smoke, servicios, broker,
  red, postmarket, reconciliacion ni validacion de mercado cerrado. El siguiente
  lote minimo debe rediseñar esa frontera y volver a demostrar captura futura
  real antes de cualquier integracion.

### P-L49B — shadow de calidad de datos por candidato (**ENSAYO 0.4.186**)

Fase A captura en memoria la observación de mercado exacta disponible en el
ciclo y Fase B la sella tras la ruta activa, antes de registrar/enviar planes.
El evento `data_quality_decision_shadow:<cycle_id>` es append-only, idempotente,
conflict-safe y fail-open. `blocked_exact_quality` exige identidad de observación,
identidad de candidato y temporalidad verificables; una anomalía posterior o no
enlazada no gobierna retroactivamente una decisión. SELL y salidas protectoras
permanecen fuera del shadow. Estado: `ready_for_integration_rehearsal`; no hay
activación de gate ni despliegue en este lote.

## Consolidacion operativa - 16-jul-2026

- `buenas-practicas` incorpora el trabajo aislado durante mercado abierto, eventos append-only, transacciones SQLite cortas y por lotes, fixtures deterministas y secuenciacion de versiones entre worktrees.
- `start-agente-bolsa` elimina la antigua contradiccion de arranque manual y fija `stack_status.ps1`, `stack_down.ps1` y `stack_up.ps1` como procedimiento autorizado mediante tareas programadas.
- `operating_model.md` y el relevo tecnico quedan alineados con P-L43B, P-L45B1/P-L45B2 y la reserva de versiones 0.4.175-0.4.178.
- Esta consolidacion documenta el arbol 0.4.177 desplegado; no modifica trading, configuracion sensible ni politicas economicas.
- P-L46B UI queda reservado para la version 0.4.178; P-L44B se mantiene en shadow sin autoridad sobre trading.

### P-L17 - Verdad de medicion: outcomes forward separados de ejecucion. **HECHO (v0.4.140).**
Se elimina la contaminacion que convertia P/L abierto de `trade_memory` en
`return_5d` maduro. El P/L vivo pasa a `execution_snapshot`; los retornos
1d/3d/5d/10d solo maduran cuando existen las barras posteriores del mercado.
`learning-scoreboard` publica schema v2, resuelve la fecha final por defecto,
ancla semanas al 7-jul y calcula drawdown sobre cartera diaria. La CI cubre ahora
Python, documentacion activa y JSON de gobierno contra NUL/UTF-8/sintaxis rota.
Verificacion: tests focales, suite completa, Ruff y gates operativos.

### P-L16 - Pausa operativa de pullback con sombra activa. **HECHO (v0.4.139).**
`builtin_pullback` permanece generando señales y outcomes, pero no puede crear
planes ni ordenes hasta la relectura pre-registrada del 20-jul. Desde esta
entrega se propaga la estrategia en planes nuevos; las seis ejecuciones previas
siguen sin atribucion historica verificable.

### P-L15 - Relectura pullback con datos maduros. **HECHO (estudio 2026-07-10).**
El horizonte 5d fue negativo (-1,25% neto, excess SPY -2,42%, n=295). Se extiende
la hipotesis hasta 20-jul porque 10d aun no era evaluable; no se promociona ni se
amplia exposicion.

### Backlog director vigente (2026-07-10)

| ID | Mejora | Estado |
|---|---|---|
| P-L18 | Linaje `decision_lineage` end-to-end y contrafactual comparable | HECHO (v0.4.141) |
| P-L19 | Contrato de evidencia, procedencia/TTL de diffs y autonomia por impacto | HECHO (v0.4.142) |
| P-L20 | Automatizacion postcierre, health ampliado y agenda semanal | HECHO (v0.4.143) |
| P-L21 | Reparar y probar el diagnostico PowerShell del stack | HECHO (v0.4.144) |
| P-L22 | Diagnostico auditable de LLM real, fallback y capacity-fill | HECHO (v0.4.145) |
| P-L23 | Diagnostico accionable de calidad de datos de mercado | HECHO (v0.4.146) |
| P-L23R | Prueba determinista de plan manual tras cierre XNYS | HECHO (v0.4.147) |
| P-L24 | Trazabilidad de duracion del ciclo de mercado | HECHO (v0.4.148) |
| P-L24R | Precision y aislamiento de la instrumentacion temporal | HECHO (v0.4.149) |
| P-L24R2 | Segmentos reales de decision, gates, persistencia e informes | HECHO (v0.4.150) |
| P-L24R3 | Integracion real y eliminacion de duplicacion temporal | HECHO (v0.4.151) |
| P-L26B | Contrato ejecutable desde hallazgos medidos | HECHO (v0.4.152) |
| P-L27B | Auditoria MFE/MAE y geometria stop/take | CORREGIDO Y ACEPTADO mediante P-L27BR; metricas dimensionales v1 invalidadas |
| P-L27BR | Correccion dimensional, conteos y pruebas MFE/MAE | HECHO (v0.4.154) |
| P-L27D | Cohorte prospectiva observacional reward/risk | HECHO (v0.4.155; recopilando desde 2026-07-13) |
| P-L27DR | Semantica de sesiones posteriores de cohorte RR | HECHO (v0.4.156) |
| P-L28B | Atribucion normalizada y digest de utilidad por origen | HECHO (v0.4.157) |
| P-L28BR | Propagacion y pruebas extremo a extremo de Origin | HECHO (v0.4.159, embudo y watchdog cubiertos) |
| P-L29B | Ciclo de vida central normalizado de `agent_run` | HECHO (v0.4.160) |
| P-L30B | Snapshot prospectivo de contexto de decision y regimen | HECHO (v0.4.161) |
| P-L31B | Captura prospectiva de controles contemporaneos comparables | HECHO (v0.4.162) |
| P-L31BR | Tratamientos y motivos reales desde planes finales | HECHO (v0.4.163) |
| P-L32B | Ledger prospectivo del camino real de gates por candidato | HECHO (v0.4.164) |
| P-L33B | Snapshot prospectivo de calidad de ejecucion | HECHO (v0.4.165) |
| P-L34B | Publicacion postmarket y health de calidad de gates | HECHO (v0.4.166) |
| P-L34BR | Gate de suite completa de P-L34B | HECHO (v0.4.166; 1.248 passed) |
| P-L35A | Auditoria de cartera autonoma de investigaciones e hipotesis | HECHO, solo lectura |
| P-L35B | Coordinador determinista de cartera de investigacion | DEFERRED; no autorizado todavia |
| P-L35R | Consolidacion documental y pausa tecnica de observacion | HECHO (v0.4.167) |
| P-L36C | Propagacion de identidad canonica de senal | HECHO (v0.4.168) |
| P-L36CR | Identidad canonica a traves del contexto compactado | HECHO (v0.4.169) |
| P-L38B1 | Cierre de promocion autonoma no autorizada de configuracion adaptativa | HECHO (v0.4.170) |
| P-L38B2 | Atribucion y agregacion canonica del analisis postmarket | HECHO (v0.4.171) |
| P-L37A | Auditoria de la primera captura real con identidad canonica | partially_verified_capture (solo lectura) |
| P-L37B | Sellado y propagacion de identidad por captura | HECHO (integrado y validado en P-L41R) |
| P-L40A | Comparacion frente a SPY y auditoria de ventas | insufficient_sample; lower_return_with_lower_risk; data_quality_blocked |
| P-L40B | Benchmark diario de cartera y SPY como observabilidad | HECHO (sin cambio de trading) |
| P-L41R/P-L41D | Ensayo secuencial y despliegue nocturno de P-L37B + P-L40B | HECHO (integración ensayada y despliegue) |

### P-L38B1 - Cierre de promocion autonoma no autorizada de configuracion adaptativa. **HECHO (v0.4.170).**

- `save_adaptive_config` es la frontera unica y fail-closed: solo el booleano
  literal `True` autoriza escribir o activar un override.
- Postmarket, tuning/CLI y cualquier helper que utilice la frontera reciben
  `blocked_by_policy` sin crear, modificar ni activar `adaptive_config.json`
  cuando la autorizacion es falsa, nula, ausente o no booleana.
- `minimal_improvements[*].auto_apply` del LLM se conserva como
  `requested_auto_apply`; nunca concede autorizacion.
- Se anade inventario de overrides y senal de gobernanza al digest y a health.
  Los seis overrides actuales se leen sin reescritura: cinco equivalentes y
  `MAX_ORDERS_PER_CYCLE` mas estricto (base 4, efectivo 2); todos quedan
  marcados `preexisting_unauthorized` con `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- El apply de codigo continua protegido por su propia frontera. P-L38B2
  (agregacion postmarket y recuperacion de candidatos) queda fuera de este lote.

### P-L38B2 - Atribucion y agregacion canonica del analisis postmarket. **HECHO (v0.4.171).**

- La unidad canónica de evaluación ejecutada es `broker_order_id`: los fragmentos
  de `trade_memory` conservan su cuenta y detalle, pero no inflan el número de
  operaciones.
- La procedencia determinista conserva `exit_trigger` y los IDs disponibles;
  `time_stop_v2` se publica como `automatic_time_stop`. Una pérdida nunca
  reetiqueta una salida automática como manual. Las contradicciones del LLM se
  registran sin sustituir la atribución estructurada.
- La revisión obligatoria lee `trade_recommendations` y rechazos de sesión sin
  excluir `learning_experiment`. Publica denominadores raw/unique, ciclos,
  tratamientos ejecutados, no ejecutados, bloqueados y legacy/unavailable.
- En la fixture del 13-jul se conservan 83 recomendaciones raw y 7 rechazos
  únicos; la exclusión global de `learning_experiment` ya no vacía el ledger.
- Se añaden métricas compactas al informe postmarket, digest y health. Los
  outcomes inmaduros siguen siendo `null` y la ejecución no se usa como retorno
  forward. La frontera de autorización de P-L38B1 y `adaptive_config.json` no
  se modifican.

### P-L37A - Auditoria de la primera captura real con identidad canonica. **PARTIALLY_VERIFIED_CAPTURE (solo lectura).**

La primera sesión prospectiva demostró captura principal de identidad, pero no
permitió verificar el 100% de enlaces del ciclo. Los históricos sin captura
permanecen `legacy_without_capture_history`; no se hizo backfill ni se usaron
uniones por símbolo/fecha.

### P-L37B - Identidad sellada por captura y propagada end-to-end. **HECHO (integrado en P-L41R/P-L41D).**

`signal_capture_id` es determinista para la combinación versionada de señal,
source run, fecha y estrategia. El historial append-only conserva capturas de
source runs distintos, los buckets independientes mantienen los IDs y la
resolución es exacta hasta las observaciones. Los merges recursivos y
transacciones cortas preservan ramas JSON existentes; fallos de telemetría son
fail-open y no cambian ranking, gates, planes, órdenes ni cantidades. Legacy se
lee explícitamente sin completar históricos.

### P-L40A - Comparacion rigurosa frente a SPY. **INSUFFICIENT_SAMPLE / LOWER_RETURN_WITH_LOWER_RISK / DATA_QUALITY_BLOCKED.**

En la ventana pre-registrada 7--13 jul la cuenta obtuvo `-0,0401%`, SPY
`+0,1953%` y la diferencia fue `-0,2354 pp`; la exposición EOD media aproximada
fue 5,17%. La muestra no demuestra edge ni autoriza cambiar política. La
exposición temporal y el benchmark ajustado por exposición permanecen
`unavailable` hasta contar con observaciones intradía verificables.

### P-L40B - Benchmark diario de cartera y SPY. **HECHO (observabilidad; sin cambio de trading).**

El contrato `p-l40b.performance-benchmark.v1` reutiliza un único
`PortfolioSnapshot`, lee SPY solo de la caché local y persiste el payload
completo, `alpha_vs_spy`, hash estable y conflictos sin sobrescritura. La foto
EOD se separa de la media temporal: `session_average_gross_exposure`, retorno
SPY ajustado por exposición y `cash_drag` permanecen `null` mientras no exista
una serie temporal suficiente. Las filas legacy no se reescriben y el fallo de
observabilidad es fail-open.

### P-L41R/P-L41D - Integracion secuencial y despliegue nocturno. **HECHO.**

La rama de ensayo integra P-L37B y P-L40B en ese orden y conserva las garantías
de identidad, benchmark, almacenamiento y orden postmarket. La suite completa
obtuvo 1.337 pruebas verdes y un único skip preexistente (`test_score_study_regression_current_sqlite`,
por muestra histórica local insuficiente de pre-earnings); no pertenece a
P-L37B/P-L40B/P-L41 y no se añadieron skips. El bump a 0.4.172 y el despliegue
productivo se ejecutan solo fuera de mercado y con postmarket terminal. Este
lote no altera horarios, límites, estrategias, órdenes ni `adaptive_config.json`.

### P-L36CR - Identidad canonica a traves del contexto compactado. **HECHO (v0.4.169).**

- Los buckets independientes del scheduler conservan literalmente el `signal_id` producido por el ledger.
- El contexto compactado transporta identidad y procedencia sin cambiar campos de seleccion o economia.
- Los 83 registros historicos del 13-jul permanecen intactos.

### P-L36C - Propagacion de identidad canonica de senal. **HECHO (v0.4.168).**

- La identidad concreta se crea en el productor y se transporta literalmente hasta lineage y contexto.
- Se separan `signal_source_run_id` y el ciclo de decision; no se infieren enlaces por simbolo o fecha.
- Los registros anteriores conservan su estado legacy/broken; no hubo backfill ni reescritura historica.

### P-L35R - Consolidacion documental y pausa tecnica de observacion. **HECHO (v0.4.167).**

- P-L35B queda **DEFERRED**, no rechazado: se reconsiderara al existir una investigacion `ready_for_analysis` o tras la primera revision de madurez de P-L27D.
- Se congela la incorporacion de instrumentos analiticos: solo se corrigen fallos reproducibles o alertas criticas.
- La prioridad se limita a `builtin_pullback`, reward/risk prospectivo y seleccion/gates/ejecucion; el resto queda backlog sin WIP analitico ni LLM hasta disponer de dependencias.

### Pausa tecnica de observacion

No se anaden instrumentos analiticos nuevos ni se cambian trading, estrategias, gates, ranking, stops, exposicion o limites. Las cohortes P-L27/P-L29/P-L30/P-L31/P-L32/P-L33 permanecen `collecting`; cero registros no equivale a rendimiento cero. Durante la pausa solo proceden reparaciones reproducibles o alertas criticas.

Agenda consolidada:

- **13-jul-2026:** primera sesion prospectiva completa; observar, no interpretar.
- **14-jul-2026:** revisar ciclo, snapshots, controles, gates, ejecucion, postmarket, digest y health.
- **20-jul-2026:** P-L25 `builtin_pullback`; aplicar criterios pre-registrados sin modificarlos.
- **27-jul-2026:** primera madurez tecnicamente posible de RR iniciado el 13-jul; no es evaluacion completa.
- **Tras muestra suficiente:** analizar controles, gates y ejecucion.
- **Tras 45 dias de `agent_run`:** evaluar utilidad de roles antes de fusionar, redefinir o suspender agentes.
- **1-sep-2026:** emitir `learning_confirmed` o `learning_not_confirmed` con el criterio original.

Proteccion de resultados: no promover una mejora que aumente retorno pero empeore drawdown, MAE o tail loss; tampoco con concentracion excesiva, linaje/control insuficientes o cualquier criterio `unavailable`. Ningun criterio puede cambiar despues de observar resultados.

### P-L34B - Publicacion postmarket y health de calidad de gates. **HECHO (v0.4.166).**

- Reutiliza el pipeline postmarket: publica un informe derivado despues de outcomes/observaciones y antes del digest.
- Lee exclusivamente snapshots prospectivos P-L32; no reclasifica `gate_json` historico ni reejecuta gates.
- Estado `collecting` se conserva sin tasas ficticias; fallo de publicacion degrada solo observabilidad.

### P-L34BR - Gate de suite completa. **HECHO (v0.4.166, commit `fde446d8`).**

La suite canónica terminó con **1.248 passed** y un warning de dependencia en aproximadamente **215 segundos**. Las ejecuciones previas se interrumpieron antes de esperar ese tiempo; no existía bloqueo real ni fue necesaria corrección funcional.

### P-L33B - Snapshot prospectivo de calidad de ejecucion. **HECHO (v0.4.165).**
Las nuevas ordenes conservan `p-l33b.execution-quality.v1` en los JSON ya
existentes: plan, respuesta de submit y reconciliacion. El snapshot propaga
IDs reales, conserva un historial de etapas idempotente, calcula bps y
latencias solo para compras con datos validos y registra outliers sin corregir
datos. El fill es telemetria de ejecucion y nunca outcome forward. Los 40
broker orders anteriores permanecen legacy; no se reconstruyen por simbolo ni
se consulta al broker adicionalmente. `execution-quality-report --json` y el
digest diario publican cobertura, estados, latencias y avisos sin interpretar
rentabilidad ni cambiar ordenes.

### P-L32B - Ledger prospectivo del camino real de gates por candidato. **HECHO (v0.4.164).**
Se añade un collector único que observa los resultados ya producidos por el
flujo real, conserva identidad, ciclo, orden, categoría, motivo, valores y
umbrales disponibles, y sella `p-l32b.gate-evaluation.v1` sin reejecutar gates.
El primer bloqueo es terminal y los gates posteriores quedan
`not_evaluated`; capacidad, seguridad, operación y portfolio permanecen
separados. Los snapshots no contienen outcomes, fills ni P&L y solo se
adjuntan a outcomes con `signal_id` verificable. El diagnóstico
`gate-effectiveness-quality --json` mantiene collecting/unavailable sin
recomendar cambios de gates ni alterar trading.

### P-L30B - Snapshot prospectivo de contexto de decision y regimen. **HECHO (v0.4.161).**
Las nuevas recomendaciones conservan un bloque `decision_context_snapshot`
con hash estable, ciclo exacto, referencia al `market_state` usado en memoria,
fuente de decision raw/normalizada, estado LLM/fallback, ranking y vinculo
estricto de senal. El snapshot se sella antes de cualquier plan, fill u outcome;
los campos post-decision se rechazan incluso anidados. Se propaga mediante los
JSON existentes a recomendaciones, planes, observaciones y outcomes solo cuando
la identidad es exacta; los historicos permanecen legacy. El digest publica
cobertura, enlaces rotos, fuentes desconocidas, contaminacion y conflictos sin
interpretar rendimiento ni cambiar trading.

### P-L31B - Captura prospectiva de controles contemporaneos comparables. **HECHO (v0.4.162).**
Se captura, en memoria y antes de construir planes, un `control_set` inmutable
por tratamiento seleccionado. El bloque usa `cycle_id`, `signal_id`,
`candidate_id` determinista, precio teorico, horizonte forward fijo de 10d,
hash del `market_state` exacto y un ledger ordenado de gates ya producidos. Solo
los candidatos posteriores al tratamiento cuya unica razon verificable es
`lower_rank` o `capacity_limit` pueden ser controles primarios; los bloqueados,
los de otro ciclo y los de contexto/precio ausente quedan separados o
`unavailable`. El mismo bloque viaja a recomendacion, plan y aprendizaje sin
crear tablas ni completar historicos. El diagnostico
`comparable-control-quality --json` mantiene denominadores, madurez por brazo,
controles parciales y legado separado. No calcula resultados durante la
captura, no interpreta cohortes y no modifica ranking, gates, cupos, ordenes ni
trading.

### P-L31BR - Tratamientos y motivos reales desde planes finales. **HECHO (v0.4.163).**
La captura se corrigio para ejecutarse despues de `build_order_plans`, limite
diario, cuota low-sample y separacion de estrategias pausadas, pero antes de
persistir planes o enviar ordenes. El tratamiento procede solo de los planes
buy finales; no se recrea ranking ni se fabrican rechazos de capacidad. Los
motivos se normalizan unicamente desde codigos reales, y los textos libres
quedan `unknown`/inelegibles. Los enlaces de gates distinguen identidad fuerte
de fallback por simbolo debil; un enlace debil o un gate no evaluado nunca es
`verified`. El schema v2 marca `selection_source=actual_final_plans` y los v1
se leen como `prospective_selection_legacy` sin reescritura. La actualizacion
del signal learning adjunta el control una sola vez sin repetir decisiones ni
gates.

### P-L29B - Ciclo de vida central normalizado de agent_run. **HECHO (v0.4.160).**
Las nuevas ejecuciones que atraviesan CrewAI, el ejecutor central de mejora
continua y `findings_to_proposals` emiten eventos append-only normalizados en
`AgentEvent`: apertura, terminal, duracion monotona, tipo, rol, referencias y
motivos saneados. El digest reconstruye runs, estados, percentiles, vinculos con
hallazgos/propuestas y diagnosticos de runs abiertos, huerfanos o conflictivos,
sin reinterpretar los 162.800 eventos historicos como ejecuciones completas.
La retencion inicial hereda los 45 dias de `AgentEvent`; no se crea tabla ni se
anaden llamadas LLM. La cobertura queda limitada a los puntos centrales y no
instrumenta individualmente los 23 agentes ni mide todavia productividad real.

### P-L28B - Atribucion normalizada y digest de utilidad por origen. **HECHO (v0.4.157).**
Los contratos nuevos exigen `origin` inmutable y validado antes de admision:
rol normalizado, run, tipo, clase de evidencia, productor/version, timestamp y
eventos fuente. `findings_to_proposals` lo genera deterministamente; el digest
separa atribuidos, legacy sin atribucion e invalidos y publica embudo/estado de
utilidad sin inferir autores historicos. No cambia trading, autonomia ni apply.

### P-L27DR - Semantica de sesiones posteriores de cohorte RR. **HECHO (v0.4.156).**
P-L27D incluia por error la sesion de la senal al calcular la decima sesion.
El calendario v2 usa ahora sesiones XNYS estrictamente posteriores, como el
productor de outcomes: una senal del 13-jul solo puede madurar tras el cierre
del 27-jul. El informe separa sesiones completas de recogida, sesiones
posteriores por senal, primera madurez posible y evaluabilidad de cohorte. Esta
ultima sigue `unavailable` hasta cumplir todos los requisitos de muestra,
clusters, ventanas, concentracion, linaje y control; no hay cambio de contrato
estadistico, captura, trading ni historicos.

### P-L27D - Cohorte prospectiva observacional reward/risk. **HECHO (v0.4.155).**
Se registra, exclusivamente en `learning_observations.features`, la cohorte
pre-registrada `pl27d_rr_1_1_5_vs_1_5_2`: senales long con geometria valida y
linaje/ciclo verificados, arm A [1, 1.5) frente a arm B [1.5, 2). La captura
empieza el primer XNYS completo posterior al despliegue, **2026-07-13**, y solo
evalua retornos forward 10d maduros. El informe `rr-cohort-report` separa
inelegibles, inmaduros, muestra, clusters, concentracion y controles
comparables; no calcula P&L, costes, alpha ni SPY y no cambia trading, gates,
ordenes, estrategia ni historicos. La integracion post-market es tolerante a
fallos y conserva la cadencia existente.

### P-L27BR - Correccion dimensional, conteos y pruebas MFE/MAE. **HECHO (v0.4.154).**
P-L27B queda corregido antes de aceptacion: `mfe_10d` y `mae_10d` son
fracciones sobre el precio de entrada, por lo que los multiplos R se normalizan
por `stop_distance_pct`, nunca por una distancia monetaria. El schema v2 separa
filas fuente de observaciones fila×horizonte, clasifica `short`, ausente e
invalida por separado, y etiqueta toda excursion como 10d. Los retornos 1d/3d/5d
son vistas auxiliares con horizonte no coincidente. Las metricas R de v1 son
dimensionalmente invalidas y no comparables. No cambia trading ni historicos.

### P-L27B - Auditoria MFE/MAE y geometria stop/take. **CORREGIDO Y ACEPTADO mediante P-L27BR (v0.4.154).**
Se incorpora `excursion-quality-report`, una lectura observacional y
determinista de `signal_outcomes`. Calcula MFE/MAE forward, consumo del stop,
alcance del objetivo y reward/risk por horizonte y cohortes, con muestra minima,
madurez, exclusiones, cobertura, concentracion y estado de linaje. No imputa
datos ni calcula alpha, SPY, causalidad o drawdown de cartera; las excursiones
disponibles son las fracciones decimales de 10d producidas por
`signal_learning.py`. Sus metricas normalizadas v1 quedan explicitamente invalidadas por el error dimensional y no son comparables con v2. La vista historica se activa explicitamente con
`--historical`; no reescribe registros ni cambia trading, gates, ordenes o
cadencia operativa. La hipotesis siguiente queda fuera de este lote.

### P-L26B - Contrato ejecutable desde hallazgos medidos. **HECHO (v0.4.152).**
Los hallazgos medidos conservan una tarjeta inmutable y se convierten en
propuestas solo cuando contienen clase, hipotesis, evidencia verificable,
metrica coherente, baseline, target, ventana, muestra minima, rutas y rollback.
`proposal_contract.py` sigue siendo la fuente unica de validacion. Los rechazos
son deterministas y previos a LLM/codegen; no consumen admision ni WIP. El
digest separa experimentos de evidencia, comprobaciones operativas, fallos,
legacy inevaluable y deuda WIP historica. Se mantienen dos admisiones diarias,
WIP nuevo dos, un codegen nocturno y apply exclusivamente humano. No cambia
trading ni se completan historicos con supuestos.

### P-L24R3 - Integracion real y eliminacion de duplicacion temporal. **HECHO (v0.4.151).**
`optional_measure` conserva una sola rama de produccion al envolver cada llamada
instrumentada o un `nullcontext` cuando no hay registrador. Las pruebas de
integracion ejecutan `_auto_paper_trade` con dependencias aisladas y verifican
la atribucion real de recomendaciones, gates, persistencia, estado de ejecucion
e informe shadow; el broker permanece fuera de las etapas. No cambian paper
trading, decisiones, gates, ordenes, mensajes, payloads ni su orden.

### P-L24R - Precision y aislamiento de la instrumentacion temporal. **HECHO (v0.4.149).**
Se restaura `scheduler.py` al comportamiento y mensajes de P-L23R, con hooks
minimos de timing. La medicion expone segmentos y separa la recomendacion LLM
estructurada de revisiones deterministas; incorpora duracion trazada y no
atribuida, sin contar dos veces intervalos. No cambia trading ni se infieren
duraciones historicas.

### P-L24R2 - Segmentos reales de decision, gates, persistencia e informes. **HECHO (v0.4.150).**
La instrumentacion conserva el scheduler restaurado y mide segmentos concretos: razonamiento CrewAI y recomendacion estructurada; revision, adversarial, entry-quality, backtest, planes y limites; y las escrituras de recomendaciones, decisiones y planes. La duracion trazada se calcula por la union de intervalos, publica `segment_overlap_count` y declara la no atribuida sin valores negativos. No cambia decisiones, gates, ordenes ni datos; el fin de semana mantiene la muestra real como `unavailable` cuando no hay ciclo instrumentado.

### P-L24 - Trazabilidad de duracion del ciclo de mercado. **HECHO (v0.4.148).**
Cada `market_cycle` publica un reporte JSON con ciclo, inicio, fin, duracion,
estado, version y seis etapas: datos, analisis tecnico, decision LLM, gates,
persistencia e informes. Cada etapa registra estado, timestamps, duracion y
error/motivo solo si existe. El reporte se conserva aun si una etapa posterior
falla; las etapas omitidas se declaran `skipped` y los historicos sin desglose
quedan `unavailable`. `production-health` resume hasta 20 muestras (p50/p95/max,
excesos de 600s, etapa dominante y cobertura) y el digest muestra el resumen sin
recomendar optimizaciones. No cambian cadencia, paralelismo, timeouts, proveedor,
modelos, gates, seleccion ni ordenes.

### P-L23R - Prueba determinista de plan manual tras cierre XNYS. **HECHO (v0.4.147).**
La prueba de persistencia del plan manual dejaba de ser valida tras el cierre de
XNYS porque consultaba `pending_order_plans()`, cuya responsabilidad operativa
es expirar correctamente planes por TTL de fin de sesion. Ahora verifica el
registro almacenado directamente con `order_plans(statuses=[PENDING])`, y exige
simbolo, `plan_id` y estado `PENDING`; no depende del reloj real ni cambia
`web_app.py`, `storage.py` o la politica TTL. La expiracion conserva sus pruebas
independientes con hora explicita en `test_order_plan_expiration.py`.

### P-L23 - Diagnostico accionable de calidad de datos de mercado. **HECHO (v0.4.146).**
`market-data-quality` deja de limitarse a contadores agregados: cada anomalia
identifica simbolo, fecha, campos invalidos, clase, proveedor, procedencia de
cache e impacto declarado sobre el escaneo. Las reglas conservadoras son
explicitas: OHLC invalido en la ultima fecha observada es bloqueante diagnostico;
OHLC historico o volumen invalido son advertencias; gaps extremos son
informativos. Los avisos legacy sin fila verificable se marcan `unavailable`,
sin inventar causa. La identidad estable de barra evita duplicados de cache. El
digest incorpora cobertura, bloqueos diagnosticos, anomalias unicas y accion.
No se modifican barras, proveedor, gates, ranking, ordenes ni politica de
bloqueo. La evidencia inicial del cache `600f58bc83572a79` (yfinance, no cache
hit) mantiene cobertura 500/500 y bloqueos de cobertura 0, y concreta 25 OHLC
invalidos de 2026-07-10 que afectan al escaneo; requiere revision antes del
siguiente escaneo, sin aplicar correccion automatica.

### P-L22 - Verdad del fallback LLM. **HECHO (v0.4.145).**
Se publica `latest_llm_decision_quality.json`, que separa recomendaciones LLM
reales, fallback tras fallo de LLM, relleno determinista de capacidad tras LLM
correcto y datos legacy sin causa verificable. `production-health` conserva sus
campos de compatibilidad y anade desglose por motivo; el digest muestra los cuatro
contadores. La medicion no altera proveedor, prompt, routing, gates ni ordenes.
La fotografia inicial fue 302 decisiones: 118 LLM reales, 184 deterministas, de
las que 167 eran `capacity_fill_after_llm_ok`, 7 fallos por respuesta/esquema y
10 sin evidencia historica suficiente (`unknown`).

### P-L21 - Diagnostico fiable del stack. **HECHO (v0.4.144).**
`scripts/check_services.ps1` deja de encadenar directamente un bloque `foreach`
a `Format-Table`, sintaxis que Windows PowerShell 5.1 rechazaba con
`EmptyPipeElement`. El script materializa primero las filas y luego las formatea.
Una prueba de regresion usa el parser real de PowerShell y exige esta estructura,
evitando que el diagnostico vuelva a romperse. No cambia procesos, trading ni
politica; solo restaura la herramienta de verificacion operativa.

### P-L20 - Operacion autonoma, health y agenda diaria. **HECHO (v0.4.143).**
El job postmercado ejecuta y publica una cadena unica: reconciliacion, outcomes y
observaciones maduras, linaje, scoreboard v2, investigacion observacional y
digest. Los viernes a las 23:15 Europe/Madrid se repite como revision semanal
idempotente. El digest abre con resultados, coberturas, bloqueos, hipotesis y una
sola decision solicitada. `production-health` incorpora TTL 26h de calidad de
datos, coherencia PID/lock/heartbeat, ratio LLM real/fallback de 7d, duracion y
solapes postmercado. La investigacion diaria separa estrategia, decision_source,
low-sample, gates, MFE/MAE/salidas y setup/regimen; dimensiones sin datos quedan
`unavailable`. Pullback sigue en sombra y su gate exige todas las condiciones
pre-registradas. No se modifica politica ni limites hasta el 1-sep.

### P-L19 - Fabrica de evidencia y diffs no rancios. **HECHO (v0.4.142).**
Toda propuesta nueva necesita contrato con clase, hipotesis, evidencia, metrica,
baseline, target, ventana, muestra, rutas y rollback. El gate previo a codegen
rechaza contratos incompletos, rutas inexistentes/fuera de allowlist, evidencia
rancia, objetivos vagos y peticiones de relajar seguridad. La lectura historica
separa `evidence_experiments`, `operational_checks` y `failed_runs` sin reescribir
las 483 filas. Los diffs llevan commit/version base, hashes de targets y fecha,
caducan a las 24h y solo admiten una regeneracion. Se limita la admision a dos
propuestas con WIP dos y el codegen a uno por noche. Docs/tests/digest no
promocionan autonomia; solo impacto post-aplicacion `PASSED` de trading,
fiabilidad u observabilidad. El apply continua exclusivamente humano.

### P-L18 - Linaje verificable y control comparable. **HECHO (v0.4.141).**
Cada recomendacion nueva recibe un `decision_lineage` estable con signal/cycle,
version de politica, estrategia, origen LLM/determinista/capacity-fill, cohorte,
low-sample y ranking. El mismo objeto viaja en plan y payload de broker sin tocar
los modulos protegidos. Las ordenes anteriores permanecen `legacy_unverified` y
no se les inventa estrategia. El scoreboard usa como control primario solo
candidatos del mismo ciclo aprobados por gates y excluidos por cupo; bloqueados,
SPY y pool por regimen se informan aparte. Los controles ausentes se declaran
`unavailable`, sin sustitucion oportunista.

### P-L14 - UI panel: fila de `Valor de cartera` con P/L de hoy. **HECHO (v0.4.137).**
Se sustituye en `web_app.py` la tarjeta `P/L ultimos 7d` por `P/L hoy (desde
cierre de ayer)` y se la alimenta exactamente desde la misma fuente que la
tarjeta hero (`_latest_daily_equity_change` + capital `exposure`). Ambos sitios
comparten ahora el helper `_today_pl_metric_payload`, de modo que importe y
porcentaje sobre invertido salen del mismo payload y permanecen sincronizados.
La fila queda en tres tarjetas: `P/L desde abril`, `P/L hoy (desde cierre de
ayer)` y `P/L abierto`. Verificacion: tests unitarios de consistencia, panel
real reiniciado con captura y suite/lint/gates completos.

### P-L13 - UI panel: P/L del dia sobre invertido y sin tarjeta realizado. **HECHO (v0.4.136).**
Se ajusta solo la presentacion del panel en `web_app.py` para que la tarjeta
`P/L hoy` muestre de forma prominente el porcentaje sobre capital realmente
invertido (`P/L dia / exposure`) usando la misma fuente de datos ya visible en
`Invertido`, con subtitulo `sobre invertido ($...)` y una referencia secundaria
pequena sobre equity total. Si `invertido=0`, el porcentaje principal pasa a
`n/d` sin division por cero. Tambien se elimina de la fila compacta bajo `Valor
de cartera` la tarjeta `P/L realizado`, quedando solo `P/L desde abril`,
`P/L ultimos 7d` y `P/L abierto`. Verificacion: tests unitarios del helper de
formato (normal, invertido=0, negativo), panel real HTTP 200 con captura y
suite/lint/gates completos.

### P-L12 - Salud operativa periodica + diagnostico backtest + cadena learning. **HECHO (v0.4.135).**
Se anade un job residente `operational_health_refresh` al scheduler: corre al
arrancar y cada 45 minutos, queda visible en `schedule-status` y regenera
`data/reports/latest_operational_health.json` sin reintroducir bloqueo por
informe rancio; si la regeneracion falla, el kill switch por stale report sigue
en fail-open. Se corrige un `UnboundLocalError` real (`cannot access local
variable 'backtest'`) localizado en `tools/signal_learning.py` para ramas
`hold/no-buy`, con evidencia en `system.log` y `orchestrator.jsonl` y test de
regresion. Tambien se recompone la cadena de aprendizaje de los fills reales de
2026-07-08: el digest ya reconoce AIZ/CRWD/ALL via `cohort=learning_experiment`
en ordenes/planes aunque `recommendation.source` sea `deterministic_*`, muestra
`trades=3`, `pnl.open=5.99`, snapshot por simbolo/bracket y reutiliza las
lecciones operativas aunque el reporte legacy no traiga `session_date`.
Verificacion: tests focales del scheduler, digest y regresion; regeneracion real
de `learning-digest` y `operational-health`; validacion completa `pytest`,
`ruff`, `status`, `validate-agent-config` y `run-once --skip-crew`.

### P-L11 - Hotfix restart_services por variable automatica `$PID`. **HECHO (v0.4.134).**
Se corrige la regresion introducida en `scripts/restart_services.ps1`: el helper
`Invoke-TaskKill` declaraba un parametro `$Pid`, que colisiona con la variable
automatica y de solo lectura `$PID` en Windows PowerShell 5.1. Se renombra a
`$TargetPid`, se actualizan sus call sites y se auditan todos los `.ps1` del repo
en busca de parametros/variables que usen nombres de automaticas conflictivas
(`Pid`, `Host`, `Input`, `Args`, `Error`); no se detectan mas casos invalidos.
Se anade test especifico que parsea el script en PowerShell y falla si reaparece
`param([int]$Pid)`. Verificacion operativa requerida: restart completo en
`powershell.exe`, sin errores y con 7/7 servicios en estado `CORRIENDO`.

### P-L10 - Excepcion low-sample en learning mode (max 1/dia). **HECHO (v0.4.133).**
Se autoriza, solo dentro de `learning_mode` activo y con `human_gated=true`, una
excepcion de backtest para senales cuyo unico fallo es `trades < minimo`. La
senal solo pasa si el resto de metricas sigue dentro de near-miss/umbral; si
ademas falla hit-rate, profit-factor, alpha o regimens, sigue bloqueada. El cupo
queda gobernado por `data/config/learning_mode.json` con
`low_sample_daily_quota` (default de codigo seguro `0`, valor operativo actual
`1`, autorizado por Antonio 2026-07-08), persistido por dia de mercado en
SQLite. La orden y su `signal_outcome` se etiquetan `low_sample_exploration`,
visible en `signal_outcomes.features`, en el `cycle-funnel` y en el digest del
lab (`low_sample: usado/quota hoy`). Verificado con tests de paso, bloqueo por
hit-rate, segunda del dia, quota=0 y propagacion de feature, ademas de embudo y
digest.

### P34 - Hardening pre-activacion de manga core y paridad diaria. **HECHO (v0.4.113).**
Se endurece `core_sleeve` antes de cualquier orden real: reserva atomica por
`data_date`, `client_order_id` estable `core-sleeve-YYYYMMDD`, preview sin envio,
guardas testeadas y tope absoluto `CORE_SLEEVE_MAX_ORDER_NOTIONAL` por `os.getenv`
con default finito. El one-shot diario ejecuta la manga y despues escribe el
parity check en `data/research/core_sleeve/parity_<fecha>.md`; el supervisor queda
por defecto a las 22:15 CEST y respeta `enabled/dry_run` del JSON. No se cambia la
matematica del vol-target ni se arranca/reinicia nada.

### P31 - Busqueda web trazable para evidencia y sentimiento. **HECHO (v0.4.110).**
Se integra una capa shadow de busqueda web con Tavily/Brave (`WEB_SEARCH_*`,
`TAVILY_*`, `BRAVE_*`) sin dar navegacion libre al LLM. `web_research_agent`
expone `web-research`, `news_sentiment` combina yfinance + web deduplicado y
`research_evidence` persiste provider/URL/frescura/evidence_id sobre la tabla
existente. No cambia gates ni ordenes: solo aporta evidencia trazable y flags.
Verificacion: tests unitarios sin red para normalizacion, fallback, evidencia,
sentimiento y CLI; lint y gates operativos.

### P32 - Gobernador de cuota y cache TTL para web search. **HECHO (v0.4.111).**
Se anade `tools/web_research_budget.py` como capa comun para Tavily/Brave:
contador mensual persistente, cap duro `WEB_SEARCH_MONTHLY_BUDGET` por `os.getenv`,
cache TTL por simbolo/macro y reporte `data/reports/latest_web_search_budget.json`.
La busqueda web pasa a ser fallback dirigido en sentimiento/evidencia: solo se
llama si la evidencia local esta ausente o vieja, salvo probes explicitos.
`WEB_SEARCH_FRESHNESS_V2` queda apagado por defecto; `research_evidence` calcula
el delta shadow de simbolos `unknown -> fresh` y si desbloquearia el gate, sin
cambiar compras vivas con el flag apagado. Verificacion: tests sinteticos sin red
para contador, cap, cache, TTL y parsing de frescura.

### P33 - Reparto Tavily/Brave, anti-falso-veto y A/B shadow. **HECHO (v0.4.112).**
Se reparte `WEB_SEARCH_PROVIDER=auto` por menor uso mensual entre Tavily y Brave,
con presupuesto independiente `WEB_SEARCH_BUDGET_TAVILY` y
`WEB_SEARCH_BUDGET_BRAVE` por `os.getenv`. `WEB_SEARCH_MERGE_PROVIDERS` permite
consultar ambos proveedores y fusionar/deduplicar evidencia. `MATERIAL_RISK_V2`
queda default OFF y calcula delta shadow para falsos vetos: exige coocurrencia
termino negativo + simbolo/empresa y elimina `competitor/rival` como veto por si
solos. `research_evidence` puntua fiabilidad por dominio curado y guarda delta de
scoring en payload. Se crea `data/research/web_ab/web_evidence_ab.jsonl` y CLI
`web-evidence-ab` para medir valor A/B sin llamadas extra. Verificacion: tests
sinteticos sin red para reparto/cap, merge+dedup, riesgo material V2, scoring de
dominio y A/B shadow.

### P30 - Arranque idempotente y stack-status. **HECHO (v0.4.109).**
Se añaden locks `data/run/<servicio>.pid` a los cinco supervisores residentes,
`scripts/stack_status.ps1`, `scripts/stack_up.ps1`, `scripts/stack_down.ps1` y
runbook operativo. El panel web ahora comprueba `127.0.0.1:8501` antes de lanzar
Streamlit y no crea una instancia duplicada si ya responde. Se reemplazaron los
usos deprecados de `use_container_width` por `width="stretch"` en `web_app.py`.
Verificado con `stack_status` antes/despues, `stack_up` idempotente, smoke web,
tests/lint/gates. Informe: `docs/informe_codex_p30_stack_2026-07-04.md`.

### P22 - Muralla `lab_book` para consumidores de `signal_outcomes`. **HECHO (v0.4.103).**
Auditoria completa de lectores de `signal_outcomes` antes de habilitar el lab book.
`Store.signal_outcomes` excluye `source='lab_book'` por defecto; la maduracion de
outcomes es la unica excepcion explicita con `include_lab_book=True`. Se filtraron
matching de ejecucion, edge/setup, C2 shadow, scoreboards, readiness, UI/contextos y
scripts de estudio, con test candado global en `tests/test_lab_book_wall.py`.
Veredicto: **SEGURO habilitar lab book log-only**, pero no se habilita en esta
entrega. Informe: `docs/informe_codex_p22_muralla_lab_book_2026-07-03.md`.

### P20 - Codegen con modo fichero-completo para targets medianos. **HECHO (v0.4.101).**
Post-mortem de los fallos `old block` de P15: 0/7 bloques de `digest.py` coincidian
exactamente o por whitespace; eran lineas parafraseadas o bloques inexistentes.
Se sube el limite de contexto/contenido completo de codegen a 900 lineas y se
actualizan los prompts para usar la constante, permitiendo que targets como
`digest.py` se entreguen como `{path, content}` y que git compute el diff. Validado
con tests focales y `gen-diff --demo --json`: `READY_FOR_HUMAN_REVIEW`,
`applied=false`, sin aprobar el diff. Informe:
`docs/informe_codex_p20_codegen_oldblock_2026-07-02.md`.

### P21 - Anomalia ORCL del radar Telegram verificada. **HECHO (v0.4.102).**
Se reviso el post Telegram `5014` del 2026-06-29 y se recalcularon los tecnicos
de ORCL contra cache local y descarga yfinance aislada. El dato `ext_sma20=-23.35%`
y `rsi=11.25` se reproduce exactamente; GOOGL y META del mismo post muestran
extensiones normales. Veredicto: dato real, sin simbolo mal extraido, precio
cruzado ni split corrupto. No se purga scorecard ni se cambia logica. Informe:
`docs/informe_codex_p21_orcl_anomalia_2026-07-02.md`.

### B3 â€” Estrategia `builtin_pullback` en SHADOW. **HECHO (v0.4.50).**
Nueva estrategia builtin en `src/agente_bolsa/strategies/builtin_pullback.py`,
registrada por defecto como `SHADOW` en el registry. Reutiliza
`validate_symbol_technical_state` para construir candidatos long y filtra solo
pullbacks de calidad: tendencia mayor intacta (`close > sma_50 > sma_200`),
precio cerca de SMA20 sin extension toxica (`distance_sma20` entre `-5%` y `+8%`),
RSI moderado (`40-60`), retroceso reciente (`return_5d <= 2%`) y exclusion de
perfiles de breakout/evento. No cambia la conducta real de trading: los candidatos
van solo a `shadow_candidates` y sirven para medir edge antes de cualquier
promocion. Verificado con `tests/test_builtin_pullback.py`, `tests/test_strategy_registry.py`,
`ruff`, `pytest`, bump de version y reinicio operativo.
---

## 1. Vision y punto de vista

El objetivo no es "operar con un LLM", sino sostener un grupo de agentes que
investiga, detecta oportunidades, aprende de aciertos y errores, genera hipotesis
falsables, las prueba en sandbox y solo promueve cambios cuando hay evidencia.

Principios:

- **Autonomia alta** en investigacion, aprendizaje, paper trading y mejora continua.
- **Autonomia baja** en ejecucion real, credenciales, broker, sizing critico y live.
- No aceptar narrativas sin evidencia y trazabilidad.
- Promover por evidencia (champion/challenger, shadow) antes que por intuicion.
- Proteger siempre el nucleo (`broker.py`, `execution.py`, `risk.py`, `config.py`,
  kernel inmutable).

El sistema debe comportarse como un equipo buy-side disciplinado: investiga,
documenta, contrasta, prueba, aprende y solo entonces cambia.

---

## 2. Estado real a 2026-06-16 (contrastado con datos)

El plumbing esta vivo (scheduler corriendo, jobs completados, reportes generados),
pero **varias capas estan construidas pero inertes** y, sobre todo, **el sistema
lleva ~10 dias sin operar de verdad**. Resumen de evidencia:

- Equity paper ~70.676 USD, practicamente plano (variacion ~-21 USD en 14 dias).
- `executed_observations: 0` sobre 19.940 observaciones; `duplicate_ratio` 0,90.
- Solo 32 `broker_orders` en toda la historia, **todas en `PENDING_NEW`** (sin
  reconciliacion de estado final).
- `research_evidence`: **0 filas**; `latest_research_evidence.json` no existia.
- Laboratorio: **0 cambios de codigo aplicados**, 1.092 propuestas RECHAZADAS,
  1.203 validaciones PENDING, 0 reglas activas (13 en shadow), 0 strategy_versions,
  0 distilled_lessons. Las 677 decisiones de `promotion_gate` estan todas en
  `approved=0`.
- BD de estado: **6,9 GB** con freelist ~0 (no es espacio libre: es fragmentacion
  por UPDATEs repetidos; el contenido real es ~750 MB).

### 2.1 Diagnostico: por que NO entramos ni salimos en un dia alcista

Causa raiz encadenada (de mas a menos critica):

1. **El LLM de decision y el de sentimiento llevan caidos desde ~6-jun.** En
   `llm_usage` no hay una sola llamada de `trade_decision` ni `news_sentiment`
   despues del 6-jun. El proveedor primario se cambio a **MiMo**
   (`mimo-v2.5-pro`, xiaomimimo.com) y falla (262 `continuous_improvement_llm_failed`);
   el fallback local **qwen3.6-27b** (`127.0.0.1:8080`) tampoco responde. Resultado:
   el sistema opera en **fallback determinista silencioso**.
2. **El fallback determinista es muy estrecho:** propone un unico candidato "strong"
   (HSIC) cada 15 min, con la razon literal *"Fallback determinista por fallo del
   LLM"*. No evalua los lideres reales del dia (QQQ, XLK +8,8%, etc.). Ademas HSIC
   estaba sobrecomprado (RSI 82, volumen z -2,33).
3. **El backtest-gate rechaza ese unico candidato cada ciclo:** *"regimenes
   negativos 2 > maximo 1 con minimo 2 trades"*. Por tanto `approved_buys = []` y
   `rejected = 0` (ni siquiera llega a plan de orden).
4. **Sentimiento vacio:** los 24 simbolos quedan marcados `material_risk=true` con
   `sentiment_score: null` (el LLM de sentimiento no corre), restando soporte a
   cualquier compra.
5. **Politica de regimen defensiva:** `profile=neutral`, `size_multiplier=0.5`,
   `requires_micro_experiment=true`, que estrangula aun mas la operativa.

En una frase: **el grupo de agentes esta efectivamente sin cabeza** (LLMs caidos),
funcionando con un fallback minimo que los propios gates rechazan. Por eso un dia
alcista no produjo ninguna entrada ni salida.

---

## 3. Mejoras YA ejecutadas

### 3.1 Heredadas (anteriores a este plan) — TERMINADO

- Pipeline de aprendizaje real (signal_outcomes, memorias por setup/simbolo).
- Shadow rules y walk-forward presentes.
- Sandbox de codigo integrado y autonomia por niveles.
- Mejora continua con iniciativas/propuestas/validaciones.
- Dashboard amplio (Research Inbox, Learning Lab, Code Changes, Strategy Lab,
  Agent Roster, etc.).
- Tuning adaptativo funcional (`adaptive_config.json`; p.ej. endurecimiento de
  `LLM_EXIT_EXCEPTION_*` tras post-market review). **Esta es la unica
  auto-modificacion que hoy funciona end-to-end.**

### 3.2 Entregadas en esta iteracion (2026-06-16)

| # | Mejora | Artefacto | Estado | Verificacion |
|---|--------|-----------|--------|--------------|
| E1 | Subida de version 0.1.13 -> 0.2.0 | `src/agente_bolsa/__init__.py` | TERMINADO | Fuente unica; se ve en sidebar |
| E2 | Chequeo de salud del LLM (aborda causa raiz) | `scripts/llm_health_check.py` | TERMINADO | Ejecutado: detecta primario y fallback caidos |
| E3 | Mantenimiento de BD (retencion + VACUUM, dry-run por defecto) | `scripts/db_maintenance.py` | TERMINADO | Ejecutado dry-run contra BD real; logica validada |
| E4 | Informe semanal de mejora (markdown desde BD) | `scripts/weekly_improvement_report.py` | TERMINADO | Ejecutado end-to-end; genera informe correcto |
| E5 | Refresco de evidencia externa (poblar tabla + json) | `scripts/refresh_research_evidence.py` | HECHO, PENDIENTE EJECUCION en venv | Compila; requiere .venv del proyecto para correr |
| E6 | Reconciliacion de estado de broker_orders contra Alpaca | `scripts/reconcile_broker_orders.py` | HECHO, PENDIENTE EJECUCION en venv | Compila; requiere .venv + credenciales Alpaca |
| E7 | Este documento maestro + fuente de verdad | `docs/plan_mejoras_y_tareas.md` | TERMINADO | — |
| E8 | Punteros de fuente de verdad | `README.md`, `docs/versioning.md` | TERMINADO | — |

> Nota: E2–E6 son **scripts/herramientas** deliberadamente desacoplados del
> proceso del scheduler para NO arriesgar el sistema en marcha. La integracion de
> E5/E6 como jobs programados es una tarea siguiente (ver seccion 5, T3 y T5).

### 3.3 Entregadas en la iteracion 0.3.0 (2026-06-16) — resiliencia y oportunidades

Objetivo: que **el grupo de agentes funcione bien aunque el LLM falle** y que el
sistema vea **las mejores oportunidades** de forma determinista.

| # | Mejora | Artefacto | Estado | Verificacion |
|---|--------|-----------|--------|--------------|
| E9 | Motor determinista de ranking de oportunidades (RS vs benchmark, tendencia, momentum, extension, volumen; stop por ATR) | `src/agente_bolsa/tools/opportunity_ranker.py` | TERMINADO | 6 tests unitarios verdes + ejecutado sobre snapshot real |
| E10 | Watchdog de LLM degradado (detecta grupo "sin cabeza" desde la BD y emite alerta accionable) | `src/agente_bolsa/tools/llm_degraded_watchdog.py` | TERMINADO | 4 tests verdes + ejecutado: detecta CRITICAL (LLM caido 246h) |
| E11 | Runner combinado salud + oportunidades (escribe `latest_agents_healthcheck.json` y `latest_opportunities.json`) | `scripts/agents_healthcheck.py` | TERMINADO | Ejecutado end-to-end contra BD y snapshot vivos |
| E12 | Tests unitarios de E9 y E10 | `tests/test_opportunity_ranker.py`, `tests/test_llm_degraded_watchdog.py` | TERMINADO | 10/10 verdes en sandbox |
| E13 | Version 0.2.0 -> 0.3.0 | `src/agente_bolsa/__init__.py` | TERMINADO | Compila; visible en sidebar tras reinicio |

Diseno: el nucleo (E9/E10) son modulos **sin dependencias pesadas** (solo stdlib),
asi que el runtime del proyecto puede importarlos sin riesgo y son testables de
forma aislada. NO se ha editado `scheduler.py`/`cycle_runner.py` (codigo de
arranque del sistema vivo que no puede validarse en este entorno); la activacion
como job se entrega como hook listo en la seccion 4.1.

Hallazgo adicional al ejecutar E11: el `market_snapshot_*.json` solo cubre ~9
megacaps, no el universo amplio. Para que el ranking surta candidatos de verdad
hay que alimentarlo con el scan amplio (breakout_scan / closed_market_technical_study).
Queda como tarea T11.

### 4.1 Hook de integracion como job (listo para pegar)

Para activar la vigilancia automatica del grupo de agentes, anadir en
`scheduler.py` un job que llame al runner (import perezoso y envuelto en
try/except para no afectar al arranque):

```python
def agents_healthcheck_job(settings, store, reporter, run_id):
    """Vigila modo degradado del LLM y publica mejores oportunidades."""
    try:
        from agente_bolsa.tools.llm_degraded_watchdog import evaluate
        from agente_bolsa.tools.opportunity_ranker import rank_opportunities
        wd = evaluate(settings.database_path)
        if wd.get("degraded"):
            reporter.emit(
                "orchestrator", "llm_degraded_alert", run_id,
                "Grupo de agentes en modo degradado (LLM de decision no disponible).",
                wd,
            )
        # rank_opportunities(snapshot, top_n=15) -> publicar en data/reports
    except Exception as exc:  # noqa: BLE001 - la vigilancia nunca debe romper el ciclo
        reporter.emit("orchestrator", "agents_healthcheck_failed", run_id, str(exc), {})
```

Registrar con la cadencia deseada (p.ej. cada 30 min en mercado abierto). Mientras
no se integre, se puede ejecutar a mano o por el cron del SO:
`python scripts/agents_healthcheck.py`.

### 3.4 Entregadas en la iteracion 0.4.0 (2026-06-16) — integracion en el sistema

Incidente previo: al editar `scheduler.py` por una via insegura (lectura truncada
del mount) se corrompio el fichero y se perdieron cambios sin commitear de
`scheduler.py`; se restauro y Codex re-integro `overnight_learning_heartbeat`.
Leccion aplicada: los ficheros grandes del nucleo se editan SOLO con la
herramienta de ficheros (escritura segura), nunca leyendo+reescribiendo por bash.

| # | Mejora | Artefacto | Estado | Verificacion |
|---|--------|-----------|--------|--------------|
| E14 | **T1b**: job `agents_healthcheck` registrado en el scheduler (cada 30 min, configurable) que emite `llm_degraded_alert` y publica oportunidades | `tools/agents_healthcheck.py` (nuevo), `scheduler.py` (job + add_job), `config.py` (`AGENTS_HEALTHCHECK_INTERVAL_MINUTES`) | HECHO, pendiente test suite + reinicio | Modulo nuevo compila; ediciones de scheduler/config verificadas en disco; pendiente `pytest` en el entorno con deps |
| E15 | **T11**: ranking sobre el universo amplio (~500 simbolos) via adaptadores del estudio tecnico / breakout scan | `tools/opportunity_ranker.py` (`snapshot_from_technical_study`, `snapshot_from_breakout_scan`) | TERMINADO | Ejecutado: surge CCL, MGM, HPE, DAL/UAL con fuerte RS |
| E16 | **T2b**: el fallback determinista reordena candidatos por score de oportunidad (RS/momentum/tendencia), bajo flag **OFF por defecto** | `tools/opportunity_ranker.py` (`prioritize_candidates`), `trade_decision.py` (hook flag-gated), `config.py` (`OPPORTUNITY_RANKER_FALLBACK_ENABLED`) | HECHO, flag OFF; pendiente validacion shadow | 11/11 tests del motor verdes; hook verificado en disco; NO cambia conducta hasta activar el flag |
| E17 | Version 0.3.0 -> 0.4.0 | `src/agente_bolsa/__init__.py` | TERMINADO | Compila; visible en sidebar tras reinicio |

Cómo activar T2b (cuando se quiera, tras validar): poner en `.env`
`OPPORTUNITY_RANKER_FALLBACK_ENABLED=true` y reiniciar. Recomendado observarlo
primero en paper/shadow.

Pasos para dejarlo corriendo con estos cambios:

1. `pytest` en el entorno del proyecto (deben seguir verdes, incluidos los nuevos).
2. Reiniciar panel web + scheduler (seccion 7) para cargar el job y la v0.4.0.
3. Verificar en `schedule-status` que aparece `agents_healthcheck` y, si el LLM
   esta caido, que se emite `llm_degraded_alert` y se escribe
   `data/reports/latest_opportunities.json`.

---

## 4. Como ejecutar lo entregado (operativa)

Desde la raiz del proyecto, con el `.venv` del proyecto:

```powershell
# 1) Diagnostico de la causa raiz (LLM). Exit code 1 = ningun LLM de decision.
.\.venv\Scripts\python.exe scripts\llm_health_check.py

# 2) Mantenimiento de BD: primero dry-run (seguro con sistema arriba)
.\.venv\Scripts\python.exe scripts\db_maintenance.py --days 120
#    Compactar de verdad (PARAR el scheduler antes):
.\.venv\Scripts\python.exe scripts\db_maintenance.py --vacuum-only

# 3) Informe semanal de mejora
.\.venv\Scripts\python.exe scripts\weekly_improvement_report.py --days 7 --out data\reports\weekly_improvement.md

# 4) Poblar evidencia externa (deja latest_research_evidence.json)
.\.venv\Scripts\python.exe scripts\refresh_research_evidence.py

# 5) Reconciliar ordenes con Alpaca (dry-run; --apply para persistir)
.\.venv\Scripts\python.exe scripts\reconcile_broker_orders.py
```

---

## 5. Tareas siguientes (backlog priorizado)

Estado: PENDIENTE salvo indicacion. Marcar aqui al completarlas.

| # | Tarea | Por que | Riesgo | Estado |
|---|-------|---------|--------|--------|
| T0 | **Restaurar el stack LLM**. Validar con `llm_health_check.py`. | Es la causa nº1 de no operar. Sin LLM no hay comite ni sentimiento. | Bajo (operativo) | **HECHO** (commit `ddb950e`). Causa raiz real: NO era MiMo ni la clave, sino una dependencia rota (`jiter`) que tumbaba el import de `openai` y hacia que el router marcara todos los proveedores como caidos. Ver seccion 10. |
| T1 | **Alerta de modo degradado** cuando el grupo opera sin LLM. | Hoy la caida del LLM pasa desapercibida. | Bajo | **HECHO** (E10 watchdog + E11 runner). Falta solo registrar el job (hook 4.1) -> T1b |
| T1b | Registrar `agents_healthcheck_job` en el scheduler con cadencia (hook seccion 4.1). | Activar la vigilancia automatica. | Bajo (edita scheduler, requiere reinicio) | PENDIENTE (requiere reinicio del sistema) |
| T2 | **Motor de mejores oportunidades determinista** (varios lideres por RS/momentum/tendencia, no un unico nombre sobrecomprado). | El fallback evaluaba un solo nombre. | Medio | **HECHO** (E9 `opportunity_ranker` + tests). Falta conectarlo al fallback -> T2b |
| T2b | Conectar el ranking de E9 al `deterministic_trade_fallback_recommendations` para ampliar el slate de candidatos. | Que el motor alimente la decision real, no solo el reporte. | Medio (toca decision; validar en shadow) | PENDIENTE |
| T11 | Alimentar el ranking de oportunidades con el **universo amplio** (breakout_scan / closed_market_technical_study), no solo el snapshot de 9 megacaps. | El snapshot actual es muy estrecho y limita los candidatos. | Bajo-Medio | PENDIENTE |
| T3 | **Integrar `refresh_research_evidence` como job** (junto al daily_study o inicio de sesion) y conectar la evidencia a mas capas que `trade_decision`. | La capa de evidencia esta inerte. | Bajo-Medio | PENDIENTE |
| T4 | **Revisar calibracion del backtest-gate** para paper/micro-experimentos: permitir entradas SHADOW que no consuman el veto, con reporting. | Hoy el gate bloquea incluso el unico candidato. | Medio (toca gates) | PENDIENTE |
| T5 | **Integrar `reconcile_broker_orders` como job** post-sesion y enlazar fills con `signal_outcomes.executed_buy`. | Sin reconciliacion no se sabe que se ejecuto; el aprendizaje no ve ejecuciones. | Bajo-Medio | PENDIENTE |
| T6 | **Dedupe de ejecucion same-symbol** antes de generar el plan (no despues). | `duplicate_ratio` 0,90; HSIC repetido cada ciclo. | Bajo | HECHO v0.4.51: el plan ya tenia `duplicate_symbol_cycle_guard`; el duplicado real venia de `record_signal_candidates` grabando cada candidato en cada ciclo. Se cambio a `signal_id` estable por fuente+dia+estrategia+simbolo con UPSERT, preservando outcomes y separando SHADOW de decision por `source_run_id=:shadow`. El historico no se compacta automaticamente para no perder outcomes; ver `docs/informe_codex_2026-06-25.md`. |
| T7 | **Desatascar el embudo del laboratorio**: drenar 1.203 validaciones PENDING y definir gates de promocion que de hecho aprueben en paper. | 0 applied_changes, 0 reglas activas: la mejora continua no mejora nada. | Medio | PENDIENTE |
| T8 | **Champion/challenger end-to-end**: ventanas, metricas de promocion, rechazo y rollback automaticos para paper. | Cerrar el ciclo idea -> shadow -> promocion. | Medio-Alto | PENDIENTE |
| T9 | **Programar `weekly_improvement_report`** (cron semanal) y publicarlo en el dashboard. | Reporting de que cambio/mejoro/empeoro/revertido. | Bajo | PENDIENTE |
| T10 | **Mantenimiento de BD periodico**: VACUUM + retencion automatizados con el scheduler parado (ventana de mantenimiento). | Evitar que la BD vuelva a inflarse. | Bajo | HECHO 25-jun: apply+autovacuum INCREMENTAL (1.9->1.8GB, freelist ya 0), backup consistente, y tarea semanal `AgenteBolsaDBMaintenance` (dom 3am). |

---

## 6. Riesgos a vigilar

1. Sobreajuste disfrazado de aprendizaje si se promocionan reglas con poca muestra.
2. Dependencia de fuentes informales si no se endurece el scoring de fiabilidad.
3. Saturacion del laboratorio con propuestas medianas (ya visible: 1.092 rechazos).
4. Agentes dinamicos sin medicion de utilidad rica.
5. Mezclar narrativa de investigacion con edge estadistico sin criterio de peso.
6. **Degradacion silenciosa por caida de LLM** (causa del incidente actual): mitigar con T1.

---

## 7. Operativa del sistema "siempre levantado" y versionado

- El sistema **suele estar levantado** (panel web en `:8501`, scheduler en
  background, LLM local en `:8080`). Ver `docs/startup_runbook.md`.
- **Tras aplicar cambios de codigo, el sistema debe seguir levantado pero con los
  cambios cargados.** Un proceso Python ya en marcha NO recoge cambios en caliente:
  hay que **reiniciar** el scheduler y el panel web para que carguen el codigo nuevo.
  Secuencia autorizada (PowerShell, solo con XNYS cerrado y sin jobs activos):

  ```powershell
  cd C:\Antonio\Bref\agenteBolsa
  powershell -ExecutionPolicy Bypass -File scripts\stack_down.ps1 -IncludeScheduled
  powershell -ExecutionPolicy Bypass -File scripts\stack_up.ps1
  powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
  ```

  No iniciar servicios persistentes con `Start-Process` ni borrar el lock a
  ciegas. Tras el arranque se exigen HTTP 200, scheduler logico unico, PID/lock
  vivo y heartbeat fresco en dos comprobaciones separadas.

- **Versionado:** en cada entrega se sube `__version__` en
  `src/agente_bolsa/__init__.py` (fuente unica; `pyproject.toml` y el sidebar la
  leen de ahi). Tras reiniciar el panel, la nueva version debe verse en la barra
  lateral. Convencion: `MAJOR.MINOR.PATCH`.

---

## 8. Como gestionar futuras mejoras (proceso)

1. Anadir la mejora como nueva fila en la seccion 5 (backlog) con estado PENDIENTE.
2. Al ejecutarla: mover/duplicar la fila a la seccion 3.2 con su artefacto, marcar
   TERMINADO o HECHO-PENDIENTE-VALIDACION, y anotar como se verifico.
3. Subir la version (seccion 7) y reiniciar el sistema para que cargue los cambios.
4. Si la mejora toca decision/ejecucion/gates, validar primero en SHADOW/dry-run y
   documentar el resultado aqui antes de activarla.
5. Mantener este documento como indice vivo: lo terminado y lo pendiente siempre
   reflejan el estado real.

## 9. Dejar el sistema corriendo de forma persistente

Diagnostico (16-jun-2026): al lanzar el scheduler en background oculto, arrancaba,
hacia bootstrap y registraba `scheduler_started`, pero el proceso se cerraba. NO
es un bug: `run_scheduler_forever` bloquea correctamente con un bucle
`while True: time.sleep(1)`. El proceso moria por quedar colgado de una sesion
transitoria (la del agente que lo lanzaba); al cerrarse esa sesion, moria el hijo.

Solucion: ejecutar como **Tarea Programada de Windows** (sobrevive al cierre de
ventana y de sesion). Artefactos entregados:

- `scripts/install_scheduler_task.ps1` — registra y arranca la tarea
  `AgenteBolsaScheduler` (al iniciar sesion, reinicio ante fallo, sin limite de
  tiempo, una sola instancia).
- `scripts/install_web_task.ps1` — idem para el panel web (`AgenteBolsaWeb`).
- `scripts/run_scheduler.bat` — lanzador manual en ventana normal (alternativa
  simple; vive mientras la ventana este abierta).

Instalacion (PowerShell en sesion de usuario normal):

```powershell
cd C:\Antonio\Bref\agenteBolsa
powershell -ExecutionPolicy Bypass -File scripts\install_scheduler_task.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_web_task.ps1
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status   # debe listar agents_healthcheck
```

Desinstalar: `Unregister-ScheduledTask -TaskName "AgenteBolsaScheduler" -Confirm:$false`
(idem `AgenteBolsaWeb`).

## 10. T0 cerrado: causa raiz del modo degradado (jiter)

Fecha: 2026-06-16. Commit: `ddb950e`.

El sistema llevaba ~10 dias sin llamadas LLM reales de decision/sentimiento. La
causa **no** era la config de MiMo ni la clave (MiMo respondia por HTTP en el
health check directo), sino una **dependencia transitiva rota en el venv**:
`jiter` (parser JSON en Rust que usa internamente el cliente `openai`) impedia
`import openai`. Como el `llm_router` capturaba ese `ImportError`, marcaba TODOS
los endpoints como no disponibles y el grupo caia a fallback determinista en
silencio.

Resolucion y blindaje:

- Reinstalado `jiter==0.13.0` y **pineado** en `requirements.txt` y `pyproject.toml`
  (era transitiva sin pin; por eso una reinstalacion del venv lo rompio).
- `tests/test_openai_client_health.py`: test de regresion que importa/crea el
  cliente OpenAI (detecta este fallo en `pytest`).
- `llm_router.py` ahora distingue `llm_client_import_broken` de "proveedor caido",
  para que el modo degradado sea diagnosticable y no se confunda con un endpoint
  inaccesible.

Validacion: `pip check` limpio, `pytest -q` 650 verdes, `llm_health_check.py`
MiMo OK + CI OK, `agents_healthcheck.py` `[OK]`, `schedule-status` lista
`agents_healthcheck`, panel 200, scheduler vivo tras 10 min.

Pendiente operativo (no de codigo): registrar las tareas programadas
(`install_scheduler_task.ps1` / `install_web_task.ps1`) desde una PowerShell con
permisos suficientes; desde el contexto del agente Windows devolvia "Acceso
denegado". Mientras tanto, scheduler y panel quedan arrancados en sesion.

Leccion: un fallo de import de dependencia puede disfrazarse de "LLM caido". El
watchdog `agents_healthcheck` (E10) fue precisamente lo que hizo visible que el
grupo llevaba dias sin LLM real; conviene mantenerlo y vigilar su alerta.

## 11. Fase edge: que el grupo gane, no que opere mas

Objetivo: subir la **expectativa real medida por setup**, no el volumen de
operaciones. Todo en paper, cambios sensibles en SHADOW y detras de flags; no
tocar `risk.py`/kernel ni `ALLOW_LIVE_TRADING`.

### 11.1 Diagnostico medido (bloques 0-1, commit `1cd7773`) — HECHO

Instrumentacion entregada por Codex: `tools/broker_reconciliation.py`,
`scripts/trading_block_metrics.py`, `scripts/reconcile_broker_orders.py`, job
`broker_reconciliation` en el scheduler.

Datos (ultimos 7 dias):

- 99 recomendaciones de compra -> **1 orden enviada**. Cuello de botella claro.
- Vetos por gate: `backtest_gate` **103**, `deterministic_review` 1. (Ni entry
  quality ni risk manager son el problema.)
- Top razones del `backtest_gate`: regimenes negativos 2>max1 (33); hit-rate
  43,75%<45% (15) y 44,44%<45% (14); profit-factor 1,01<1,05 (9); trade-window
  alpha −0,25%<0% (9). **Casi todos los vetos son "por poco".**

Reconciliacion (bloque 1): las 32 ordenes pasaron de `PENDING_NEW` a `filled`
(17 buy / 15 sell). `signal_executed_observations`=320. **P&L realizado FIFO =
−782,18** en 16 lotes cerrados; equity paper ~70.676 (plano), Sharpe60 negativo.

**Conclusion clave:** el edge actual es marginal/negativo. Relajar el gate a
secas haria operar mas setups perdedores. El trabajo es **mejorar y medir el
edge por setup**, ahora posible porque la ejecucion ya se reconcilia.

### 11.2 Backlog "Fase edge" (PENDIENTE salvo indicacion)

| # | Tarea | Criterio de exito | Estado |
|---|-------|-------------------|--------|
| F2b | Edge por setup/estrategia con las 320 ejecuciones + outcomes: expectativa, hit-rate, PF, alpha por `setup_quality`/tag/regimen. Subir prioridad/sizing a edge+ y mandar a shadow/vetar edge−. | Tabla de edge por setup; identificados pockets ganadores/perdedores. | PENDIENTE |
| F2 | Shadow A/B del `backtest_gate` con criterio de **expectativa forward** (1/3/5/10d) del cohorte vetado, por razon de veto. Relajar SOLO los umbrales cuyo cohorte demuestre expectativa positiva. | Recalibracion umbral a umbral basada en evidencia; nada se relaja sin expectativa+. | PENDIENTE |
| F5 | Disciplina de salida: analizar por que el realized P&L es negativo; revisar `exit_policy_v2`, stops/take-profit/trailing, holding y drawdown por trade. | Cortar perdidas y realizar ganadores; P&L realizado mejora. | PENDIENTE |
| F3 | A/B `opportunity_ranker` (lideres RS/momentum) vs scanner actual en paper (`OPPORTUNITY_RANKER_FALLBACK_ENABLED=true`). | Comparativa de forward returns; se queda si mejora, se revierte si no. | PENDIENTE |
| F6 | Cerrar embudo lab: drenar validaciones `PENDING` y promocion champion/challenger que apruebe con expectativa forward+ y estabilidad por regimen. | Reglas con edge pasan de shadow a active; `applied_changes`>0 con criterio. | PENDIENTE |
| F7 | Scoreboard de rentabilidad (equity, P&L, hit-rate, PF, expectancy, maxDD, alpha vs SPY por setup y regimen). | Panel/reporte para guiar y medir "mas listo". | PENDIENTE |

Orden recomendado: **F2b → F2 → F5 → F3 → F6/F7**. Empezar por el edge por setup:
dira si algun setup gana de verdad antes de tocar el gate.

### 11.3 Resultados F2b/F2 (commit `eaee6b0`, v0.4.2) — HECHO

Entregado: `tools/edge_analysis.py`, `tools/execution_linking.py`,
`scripts/edge_shadow_analysis.py` (`--since-date`), y un **fix serio**: la
reconciliacion propagaba el fill por `symbol` a señales recientes equivocadas;
ahora enlaza con la señal previa correcta por fecha/hora. `pytest` 654 verdes.

Edge por setup (muestras pequeñas, direccional):
- **Malo y accionable**: `confirmed_pattern` n=8, expectancy_5d **−5,25%**, hit 14%,
  PF 0,07. Tags débiles: `volume_z:lt0` −4,72%, `sma20_dist:0_6pct` −6,74%,
  `rsi:60_75` −3,86%.
- **Prometedor pero muestra corta**: `orderly_breakout` +4,89% (n=1),
  `volume_z:gt1` +4,89% (n=2), `sma20_dist:6_12pct` +1,17% PF 3,57 (n=3).

Cohortes vetados por `backtest_gate`: **no hay base para relajar en bloque**.
- Mantener/endurecer: `trades 0<10` (−40,76%), alpha negativos, `PF 0,73`.
- Prometedores pero inmaduros: `alpha −0,15%<0` (+2,70%, n=9), `hit 44%<45%`
  (+2,64%, n=7), `trades 8<10` (+0,90%, n=16).
- Near-miss sin muestra madura aún: `43,75%`, `44,44%`, `PF 1,0147`,
  `regimenes negativos 2>1` (solo 1d maduro).

Decision operativa (disciplinada, asimetrica): **no relajar nada en paper hoy**;
reducir exposicion a lo probadamente malo y NO añadir a lo "bueno" todavia (n
insuficiente). Abrir shadow solo para 3 near-miss: `hit 44%<45%`,
`alpha −0,15%<0`, `trades 8<10`.

Limites de dato detectados (a corregir antes de F6/F7):
- `alpha vs SPY` no computa: falta benchmark SPY en cache local para el script.
- `regime` sale `unknown`: el ledger no persiste `market_regime` en la señal.

### 11.4 Backlog actualizado (siguiente)

| # | Tarea | Estado |
|---|-------|--------|
| F5 | **Disciplina de salida** (shadow `stale_guard_v2`). | **HECHO** (commit `7d9a178`, OFF) |
| F2b-act | **Routing por setup** (penalización reversible de pockets malos) + fix de cableado de `Settings`. | **HECHO** (commit `1d43511`) |
| F-infra | Persistir `market_regime` + benchmark SPY en el analizador. | **HECHO** (commit `2a5c364`) |
| F2-shadow | Shadow de los 3 near-miss con expectativa+. | **HECHO** (commit `dc5ed0e`) |
| F3 | A/B `opportunity_ranker` (líderes RS/momentum) vs scanner; flag activado en fallback. | **HECHO** (commit `696549e`) |
| F6 | Evaluador champion/challenger estricto (solo-propuesta) + guardas anti-sobreajuste. | **HECHO** (commit `7a8660c`) |
| F7 | Scoreboard de rentabilidad en dashboard + CLI. | **HECHO** (commit `7a8660c`) |
| F8 | Consolidación: drenar backlog CI (94 cierres TTL), democión automática de pockets probadamente malos con evidencia, review semanal con scoreboard. Acumular muestra. | PENDIENTE (siguiente) |

### 11.5 Resultados F5 + F2b-act (commits `7d9a178`, `1d43511`) — HECHO

**F5 — salidas** (`exit_shadow_analysis.py`, `stale_guard_v2` OFF por defecto):
- `stop_loss`: 3 trades, hold **21d**, ret −5,06%, MFE −3,22%, MAE −10,43%.
- `take_profit`: 2 trades, hold 9,5d, ret **+13,21%**.
- `time_stop_v2`: 2 trades, hold 5d, ret −3,70%.
- Lectura: el daño no es vender pronto, sino **perdedores que se eternizan hasta el stop completo** (WELL, SBUX). El shadow `stale_guard` mejora hit (28,6%→42,9%) y PF (1,17→1,34); expectancy similar. Muestra corta → dejar OFF y seguir midiendo.

**F2b-act — routing de pockets negativos** (penalización reversible por flag):
- Aparta de la parte alta: `confirmed_pattern`, `volume_z<0`, `rsi:60_75`, `sma20_dist:0_6pct`. Top-4: `rsi:60_75` baja de 3→1.
- **Fix de cableado importante**: varios flujos (`scheduler`, `main`, `opportunities`, `trade_decision`) reconstruían `Settings(DATA_DIR=...)` y **perdían flags efectivos** de selección. Corregido: ahora la config runtime llega igual a scheduler, CLI y snapshot.
- Hallazgo: el routing ayuda al margen, pero **el universo sigue dominado por setups flojos** → la mejora de fondo es la calidad de candidatos (F3).

Pendiente: F-infra (alpha + régimen) y F2-shadow. Tests: 656 verdes.

### 11.6 Resultados F-infra + F2-shadow + F3 (commits `2a5c364`, `dc5ed0e`, `696549e`) — HECHO

**F-infra**: `edge_shadow_analysis.py` ya calcula **alpha vs SPY** y desglose por
**régimen**. Se persiste `market_regime`/`volatility_regime`/`risk_posture` en
`signal_outcomes.features` para señales nuevas; el histórico infiere régimen
desde tendencia de SPY. Edge con alpha: `orderly_breakout` alpha_10d **+16,9%**
(n=1); `confirmed_pattern` negativo en todos los horizontes; régimen `neutral`
n=9 negativo.

**F2-shadow**: logging shadow (sin cambiar conducta) en
`gate["backtest_near_miss_shadow"]` (`mode=shadow_only`) para `hit 44%<45%`,
`alpha −0,15%<0`, `trades 8<10`. Excluidos `43,75%`, `44,44%`, `PF 1,0147`,
`regímenes negativos 2>1`.

**F3**: `OPPORTUNITY_RANKER_FALLBACK_ENABLED=true` por defecto (solo fallback,
reversible). A/B (`opportunity_ranker_ab.py`):
- Ranker top: alpha_1d **+0,72%**, 3d −0,68%, 5d −0,74%, 10d **+3,94%**.
- Scanner top: alpha_1d +0,21%, 3d +0,51%, 5d −1,30%, 10d −0,00%.
- Ranker mete líderes (CCL, DAL, DDOG, DELL, CRWD). Mejora clara a 1d y 10d,
  peor a 3d/5d → activado solo en fallback, sin subir agresividad global aún.
- Lectura: confirma que los líderes por RS tienen mejor edge a 10d; conviene
  alinear el horizonte de salida con donde está el edge (ver F6/exits).

Tests: 660 verdes.

**Setup-edge bias (commit `d7dba99`, v0.4.27)**:
- `tools/setup_edge.py` queda como fuente comun para clasificar setups y
  calcular `edge_table` desde `signal_outcomes` con ventana train walk-forward.
- `trade_decision.py` lo cablea al fallback solo detras de
  `SETUP_EDGE_BIAS_ENABLED` (default **OFF**); al activarlo reordena el slate y
  deja comparativa shadow en `data/reports/latest_setup_edge_shadow.json`.
- `entry_quality` no se relaja en real: solo registra en shadow que rutas se
  desbloquearian al retirar el requisito duro de `confirmed_pattern`.
- Telemetria: `signal_learning` persiste `market_regime` y
  `volatility_regime` desde el reporte o el candidato para evitar cobertura
  cero por regimen.
- Config registrada: `SETUP_EDGE_BIAS_ENABLED=false`,
  `SETUP_EDGE_BIAS_TRAIN_WINDOW_DAYS=120`,
  `SETUP_EDGE_BIAS_MIN_SAMPLES=20`.

### 11.7 Siguiente: F6 (sistema de mejora sólido) + F7 (scoreboard)

Ahora que hay alpha y régimen, toca cerrar el lazo de mejora con **guardas
anti-sobreajuste** (muestras aún pequeñas, n=1/8/9): promoción champion/challenger
solo con muestra mínima, expectativa/alpha forward positivos, estabilidad por
régimen y validación out-of-sample; democión/retiro de lo que no rinde. Y un
scoreboard de rentabilidad para dirigir por datos.

### 11.8 Resultados F6 + F7 (commit `7a8660c`, v0.4.8) — HECHO

Entregado: `tools/profitability_scoreboard.py` + `scripts/profitability_scoreboard.py`,
`continuous_improvement/promotion_readiness.py` + `scripts/promotion_readiness.py`,
ambos expuestos en el dashboard (Profitability Scoreboard + readiness en Strategy
Lab). Política F6 **solo-propuesta** (no auto-aplica conducta). Tests 664 verdes.

Estado medido: equity 70.676 (plano), 9 fills enlazados, SPY 136 puntos.
- Promociones: **0** (bloqueadas correctamente por muestra/estabilidad).
- Demociones propuestas (no aplicadas): `confirmed_pattern` (alpha5d −6,21%, PF 0,07),
  `rsi:60_75` (−4,61%, PF 0,25), `volume_z:lt0` (−5,78%, PF 0,09).
- Backlog CI: 1.297 pendientes, 94 cierres por TTL recomendados.

**Inflexión honesta:** la maquinaria de mejora ya está completa y es correcta.
El limitante ahora es **muestra** (9 fills): no hay con qué promover todavía. Las
ganancias de P&L vendrán de (1) cortar ya los pockets probadamente malos,
(2) los mejores candidatos del ranker RS, y (3) **dejar correr el sistema** para
acumular muestra y poder promover ganadores. No hay atajo: es disciplina + tiempo.

### 11.9 F8 — Consolidación (siguiente)

- Drenar el backlog CI: aplicar los 94 cierres por TTL; criterio de cierre para
  que no se reacumule.
- Democión automática (no solo propuesta) de pockets con evidencia negativa
  suficiente (`confirmed_pattern` ya penalizado por F2b-act); promoción sigue
  manual/estricta.
- Review semanal automatizada con el scoreboard (cron) para decidir promociones a
  medida que madura la muestra.
- Mantener el sistema corriendo de forma persistente (tareas programadas) para
  acumular muestra.

## 12. Plan consolidado tras el estudio semanal (semana 23-jun-2026)

Lectura del estudio (`docs/weekly_study_2026-06-19.md`): la semana estuvo dominada
por fallos de infraestructura (crew sin deps 11-15, cuotas LLM y sentimiento
caido), no por la estrategia. Direccion correcta, resultados pendientes de una
semana limpia. Objetivo permanente: mas listo, mas autonomo, mas rentable.

Hallazgo clave de estrategia: **el edge aparece a 5-10 dias; el sistema evalua/sale
a 1-3 dias** (donde domina el ruido). Alinear el horizonte es probablemente la
mayor palanca de rentabilidad.

### Capa 1 — Estabilidad (bloqueante; sin esto el sistema opera ciego)
- **C1.1** Arreglar dependencias pip del scheduler (causa del 100% fallback 11-15 jun). Pinear/`pip install -r requirements.txt` en el venv del scheduler y verificar que el crew arranca. Idealmente, freeze de versiones para que no se rompa al reinstalar.
- **C1.2** LLM continuo: kimi-k2.6 (opencode-go) como primario de DECISION y SENTIMIENTO, con fallback configurado; respetar Retry-After/backoff ante 429/403. Validar con `scripts/llm_health_check.py` antes de apertura.
- **C1.3** Restaurar la capa de sentimiento (cuota). Fue el bloqueo nº1 de compras (vetó las 3 de APH y ~120 ciclos).

#### Resultado Capa 1 (20-jun-2026, v0.4.15)

- **C1.1 HECHO**: `pip install -r requirements.txt` ejecutado sobre el venv;
  `pip check` sin dependencias rotas. Smoke real: `build_crew()` crea 6 agentes
  y 6 tareas sin el error `Instala dependencias...`. Se añade
  `requirements.lock` con todas las dependencias transitivas fijadas
  (`crewai==1.14.7`, `crewai-tools==1.14.7`, `openai==2.41.1`,
  `jiter==0.13.0`).
- **C1.2 HECHO**: decision y sentimiento quedan fijados como roles separados a
  `kimi-k2.6` en `https://opencode.ai/zen/go/v1`, con fallback local configurado.
  El router respeta `Retry-After` y aplica backoff exponencial acotado ante
  HTTP 429/403. `llm_health_check.py`: decision OK, sentiment OK, mejora
  continua OK; el fallback local esta configurado pero apagado.
- **C1.3 HECHO**: ciclo real de sentimiento AAPL con 3 noticias, score `-1`,
  confianza `0.6`, sin warnings y `sentiment_failed=false`. Se eleva el limite
  del rol a 4.000 tokens porque Kimi consumia 1.200 en razonamiento y devolvia
  `{}`; ahora una respuesta incompleta se rechaza explic
### 12.1 Capa 2 — HECHA (medicion + shadow, commits ee51f8e/0411ce0/fb0d927/efcf8ee)

- Alpha vs SPY numerico (1d +0,80% / 3d -1,01% / 5d -0,45% / 10d +4,33%); cobertura SPY 7/7.
- Regimen real persistido (ej. AAPL -> bullish); ya no "unknown".
- **Hallazgo clave confirmado (horizonte):** salida actual 1-3d expectativa -1,78% (PF 0,25) vs shadow 5-10d +1,18% (PF 1,34). Mejora pareada +2,95% retorno / +1,54% alpha. NO promovido (n=4).
- stale_guard y shadow-penalty confirmed_pattern: OFF, midiendo en el informe semanal.

### 12.2 Decisiones a tomar el viernes 26-jun (con mas muestra)

1. **Activar horizonte de salida 5-10d** si la ventaja se mantiene con n>=20 (palanca nº1 de rentabilidad).
2. Valorar activar `stale_guard` si corta perdedores sin dañar ganadores.
3. Formalizar/activar penalizacion de `confirmed_pattern` si sigue con edge negativo y muestra alta.
4. Comparar calidad de decision kimi vs etapa MiMo (primera semana limpia con kimi).

Hasta el viernes: NO tocar nada; dejar acumular muestra con Capa 1 estable + Capa 2 en shadow.
unknown").

#### Resultado C2.4-C2.5 (20-jun-2026, v0.4.16)

- **C2.4 HECHO**: el fetcher de SPY usa el cache de mercado y amplía el rango
  para cubrir retornos forward y tendencia de régimen. `edge_shadow_analysis`
  obtiene 932 puntos benchmark; alpha a 1/3/5/10d: `+0,80%`, `-1,01%`,
  `-0,45%`, `+4,33%`. El scoreboard rellena SPY sin convertir ausencias en
  cero: cobertura 7/7 y alpha acumulado `-1,6839%`.
- **C2.5 HECHO**: el ciclo real ya copia `market_state` al ledger. El lote
  `opp_80c74db42155`, creado el 19-jun sobre la última sesión disponible
  (17-jun), persiste `market_regime=bullish`. Para históricos sin régimen, el
  analizador usa tendencia SPY con 300 días de contexto y declara el origen;
  cobertura actual de compras enlazadas: 4/4, todas `bullish`.

#### Resultado C2.1 (20-jun-2026, v0.4.17)

- Se incorpora una comparación contrafactual sobre compras paper reconciliadas:
  último outcome maduro de la ventana actual 1-3d frente al último de 5-10d.
  Reporta expectativa, hit-rate, profit-factor, alpha y delta pareada.
- Es análisis `SHADOW` puro (`changes_trading_behavior=false`) y nunca promociona
  la política automáticamente; requiere ampliar la muestra paper madura.

#### Resultado C2.2-C2.3 (20-jun-2026, v0.4.18)

- `stale_guard` permanece con conducta OFF y se calcula contrafactualmente en
  el informe semanal, con elegibles, disparos y métricas actual vs shadow.
- La penalización de `confirmed_pattern` queda formalmente en shadow: el flag de
  conducta pasa a OFF por defecto; el routing calcula y persiste la penalización
  que habría aplicado, pero no la resta del score. El informe semanal muestra
  muestra madura y edge por 1/3/5/10d.
- El informe semanal integra scoreboard, alpha SPY, régimen y comparación de
  horizonte. Ningún cálculo de esta sección modifica compras o ventas.

### Capa 3 — Mas autonomo
- **C3.1** Promocion/democion automatica del lab con guardas (champion/challenger) cuando haya muestra y expectativa+.
- **C3.2** El watchdog (`agents_healthcheck`) debe ALERTAR de forma visible si el grupo vuelve a quedarse en fallback varios ciclos (lo de 11-15 paso desapercibido).

Orden: Capa 1 (antes del lunes) -> Capa 2 (durante la semana, shadow + medir) ->
Capa 3 (cuando 1 y 2 esten estables). Nada que cambie compras/ventas reales sin
shadow + evidencia; no tocar risk.py/kernel ni ALLOW_LIVE_TRADING.

### 11.10 Publicacion manual en LLM Trading Leaderboard (21-jun-2026, v0.4.34) — HECHO

- El dashboard publica manualmente `model=AMR` y `gain_pct` usando el P/L porcentual
  de referencia calculado desde el 1 de abril (`DEFAULT_START_DATE=2026-04-01`).
- El ultimo envio confirmado queda trazado en `agent_events` y visible junto al boton.
- La eliminacion remota mediante `DELETE /api/data` exige casilla de advertencia y
  escribir exactamente `BORRAR TODO`; exitos y errores tambien quedan auditados.
- Rutas verificadas contra OpenAPI: `POST /api/submit` y `DELETE /api/data`;
  host configurable con `LEADERBOARD_API_BASE_URL`. Verificacion: tests unitarios de
  POST, DELETE y recuperacion del ultimo envio, sin llamadas reales a red.

### 11.11 Correccion de regresiones de decision y reconciliacion (22-jun-2026, v0.4.37) — HECHO

- El error medio del prior deja de ser un veto duro de entrada. El digest vigente
  contiene 19.930 observaciones, 0 compras ejecutadas y 90,03 % de duplicados: la
  metrica sirve como senal auxiliar, pero no justifica bloquear compras. Se conserva
  la penalizacion existente en ranking y sizing (20 % al superar 0,04) y se expone
  `prior_error_advisory` en la trazabilidad del gate.
- Los tests de entry-quality que no prueban aprendizaje quedan aislados de los
  reportes operativos de `data/`, evitando resultados dependientes de la maquina.
- El fixture de reconciliacion incluye la fecha real del plan, respetando el guard
  de antiguedad maxima de cinco dias que evita asociar fills a senales historicas.
- Verificacion: tests dirigidos, suite completa, Ruff y smokes operativos.

## 12. Plan de mejora 24-jun — desatascar la entrada (el dinero)

Contexto: tras arreglar el LLM (deepseek), los ciclos completan y el gate trabaja
con criterio, pero siguen 0 compras. Dos causas reales:
1. **El `market_state` sale PARTIAL / regime=unknown CADA ciclo** -> fuerza modo
   defensivo (`requires_micro_experiment`, size 0.5x, soft-override OFF) y NUNCA
   puede clasificar bullish, aunque la amplitud sea 95-100% positiva. Es un BUG de
   datos: el benchmark (SPY) no trae `close/sma_50/sma_200/atr` poblados
   (`benchmark_return_20d=0.0`), y `_quality_status` queda en PARTIAL por falta de
   earnings/macro/cobertura (FMP).
2. **El universo de candidatos es 100% `confirmed_pattern`** (lideres extendidos
   que el gate rechaza con razon); el edge validado OOS esta en `sin_patron|strong`
   y no se surfacea ni opera.

### A1 — Arreglar dato de benchmark + quality del market_state (BUG, max prioridad)
Poblar tecnicas de SPY en `build_market_snapshot`/`build_market_state` y revisar por
que `quality_status=PARTIAL`. Es arreglo de datos (no cambia conducta), de altisimo
impacto: destraba el modo defensivo y re-habilita el soft-override. Con test.
Estado: **HECHO (v0.4.38, A1a).** Bug encontrado y corregido: `build_market_snapshot`
descargaba el benchmark (SPY) pero el bucle iteraba solo `symbols` (candidatos), asi
que SPY NUNCA entraba en `snapshot["symbols"]` -> regime="unknown" + `benchmark_return_20d=0`
+ fuerza relativa rota. Fix: iterar `unique_symbols`. Test `test_market_snapshot_benchmark.py`.
- **A1b (decision tomada): NO conectar FMP por ahora.** El plan gratuito de FMP NO
  incluye calendario de earnings (es de pago), asi que no arreglaria `has_earnings`.
  Ademas PARTIAL **no bloquea** comprar (solo baja size a 0.5x y apaga soft-override):
  no es la causa de los 0 trades. Se aparca FMP hasta ver el sistema operar y tener
  evidencia de que earnings/macro mejoran decisiones en paper.

### A2 — Surfacear setups con edge + promocionar el sesgo (shadow->active)
- Verificar si la SELECCION surfacea `sin_patron|strong` (en logs eran 100%
  confirmed_pattern -> posible cuello aguas arriba).
- `SETUP_EDGE_BIAS_SHADOW_ENABLED=true` (mide en vivo sin tocar conducta) varias
  sesiones; si confirma OOS, `SETUP_EDGE_BIAS_ENABLED=true` (guarded). Relajar el
  requisito duro de `confirmed_pattern` (M2) tras flag, medido. Neto de costes.
Estado: **EN CURSO (v0.4.39, shadow por ciclo implementado).** Estudio del funnel:
el ranker (`opportunity_ranker`) NO prefiere confirmed_pattern; el selector
(`_selection_score_for_candidate`) tiene perfiles que SI exigen patron confirmado
(high_conviction, leader_momentum, top_long_alignment) y otros que NO (emerging/parabolic
leader), asi que sin_patron PUEDE pasar pero los perfiles de patron dominan. El
shadow del sesgo ya existia pero **solo corria en el fallback del LLM**. Nueva funcion
`record_setup_edge_cycle_shadow` (en `trade_decision.py`, llamada desde `cycle_runner`)
mide en CADA ciclo, tras `SETUP_EDGE_BIAS_SHADOW_ENABLED=true`, el funnel de
setup-quality (cuantos `sin_patron|strong` aparecen), el reorden baseline-vs-sesgo y
si las claves casan con la `edge_table`; escribe `latest_setup_edge_cycle_shadow.json`.
Pura observabilidad, sin tocar la seleccion. Test `test_setup_edge_cycle_shadow.py`.
Pendiente: encender el flag, recoger varias sesiones, y decidir promover (o arreglar
el etiquetado de `setup_quality` si las claves no casan).

**Hallazgo 24-jun (primer shadow en vivo, `mkt_6305f7697897`):** el shadow funciona y
revelo dos cosas. (1) BUG de etiquetado: los candidatos en vivo daban la clave
`confirmed_pattern` (sin calidad, por el short-circuit de `setup_name` en
`setup_quality_key`) mientras la `edge_table` usa `confirmed_pattern|strong` etc. ->
no casaban -> `setup_edge_bias=0` en todo, mecanismo INERTE. Corregido en **v0.4.41**
(la clave ahora es siempre `{base}|{quality}`, ignorando setup_name). (2) ESTRUCTURAL:
la seleccion surfacea 24/24 `confirmed_pattern` y **0 `sin_patron`**; los grupos de
edge positivo (sin_patron|mixed +0.49%, confirmed_pattern|watchlist +0.21%) no aparecen,
y el grupo que si aparece (confirmed_pattern|strong) tiene edge medido -0.15%. Bonus: A1
confirmado (benchmark_return_20d=-0.0178, ya poblado, no 0). Siguiente: validar que tras
v0.4.41 `keys_without_edge_match` se vacia, y luego atacar el surfaceo de `sin_patron`
(cuello estructural en la seleccion).

**Estudio 24-jun (`docs/estudio_universo_y_seleccion_2026-06-24.md`):** el universo
NO es el cuello (es S&P500 ~500; el `default_universe` de 9 no se usa en el ciclo).
`builtin_breakout` genera un candidato por CADA simbolo (incluidos `sin_patron`), pero
el corte **top-N por `score`** + la seleccion premian `confirmed_pattern|strong` y
dejan fuera `sin_patron|mixed` (edge +). El sesgo de A2 solo actua en el fallback y el
shadow, NO en el ranking del scan. Mejora propuesta: aplicar el sesgo de edge sobre
`all_candidates` ANTES del corte, primero en shadow (medir que `sin_patron|mixed`
entrarian), luego guarded, luego active. Disciplina shadow->guarded->active.

#### A2.S — Surfacear setups con edge positivo (sin_patron|mixed). Pasos:
- **Paso 1 — Shadow sobre `all_candidates` (observabilidad).** Extender
  `record_setup_edge_cycle_shadow` para analizar TODOS los candidatos (~500) del
  `latest_closed_market_technical_study.json`, no solo los 24 finalistas: distribucion
  completa de `setup_quality`, y listar los mejores candidatos (por `score`) de las
  claves con edge positivo medido (`sin_patron|mixed`, `confirmed_pattern|watchlist`,
  `sin_patron|weak`) que el corte top-N deja fuera. Sin tocar la seleccion real.
  Estado: **HECHO (v0.4.42).**
- **Paso 2 — Guarded.** Estado: **DESCARTADO con evidencia.** El shadow sobre los 343
  candidatos mostro que `sin_patron|mixed` son solo 2 nombres en todo el S&P 500
  (score 7 vs 16-18) y que el 87% cae en `confirmed_pattern|strong` (taxonomia
  degenerada). Promoverlo seria perseguir ruido. Ver
  `docs/estudio_universo_y_seleccion_2026-06-24.md` seccion 6.
- **Paso 3 — Active/promote.** Estado: DESCARTADO (dependia del Paso 2).

#### A2.E — Buscar el edge donde SI discrimina (redireccion 24-jun)
Como `setup_quality` es degenerada, medir el edge por dimensiones que varian. Script
`scripts/study_edge_by_score.py` (read-only): forward return_5d neto de costes por
bucket de `score`, por `setup_quality` y por extension `return_20d`. Estado: **HECHO
y CONCLUIDO.** Resultado: el "edge" (extension toxica / pullbacks ganan) **NO es
robusto** — `signal_outcomes` solo cubre 2026-05-06 a 2026-06-24 (7 semanas, 2 meses) y
el efecto lo dispara el selloff de junio (en mayo la extension OUTPERFORMO). Lo unico
consistente ambos meses: score medio 8-16 ~+0.87% a 10d (modesto). **DECISION: NO
cambiar la seleccion** (habria sido overfit a junio); seguir midiendo y revisar con
varios meses/regimenes. Ver `docs/estudio_universo_y_seleccion_2026-06-24.md` sec. 8.

#### A2.C — Clasificador degenerado (tarea derivada)
Revisar `technical_state_validator.py:322-332`: umbral `setup_quality="strong"` en
score>=7 (bajo) y detector de patrones que marca "confirmado" en casi todo -> 87% en
un solo cajon. Solo tras ver el estudio de edge por score. Estado: PENDIENTE.

### BUG material_risk (review determinista) — ARREGLADO (v0.4.45)
`deterministic_reviewer` evaluaba `bool(sentiment_row["material_risk"])`, pero ese
campo es un DICT (siempre truthy) -> bloqueaba TODA compra con reason="material_risk".
Detectado con `cycle-funnel --history` (8/8 recomendaciones bloqueadas). Fix: leer el
booleano interno `.material` (`_material_flag`). Test `test_deterministic_reviewer_material.py`.
Consecuencia: ahora solo bloquea con riesgo material real; quedan 2 blockers visibles en
el embudo (entry_quality reward_risk, y plan market_state_partial_missing_macro). Vigilar
con `cycle-funnel` si empiezan a entrar trades paper.

### B1 — A/B de modelo en decision (flash vs deepseek-pro vs glm), midiendo edge. PENDIENTE.
### B2 — Report del embudo (candidatos->gates->decision->fill). **HECHO (v0.4.43).**
Lector `tools/cycle_funnel.py` + comando `cycle-funnel` (y `--json`): ensambla el
embudo del ultimo `market_cycle` desde el evento `paper_auto_trade_completed` + el
estudio tecnico, con conteos por etapa, motivos de rechazo y deteccion del CUELLO
("por que no se compro"). Solo lectura, no toca el ciclo. Pendiente opcional: seccion
en el panel web (el com
---

## 13. Sesión autónoma 25-jun (mañana, mercado cerrado)

Avances sin tocar conducta de trading (todo read-only / docs / scripts; los cambios de
código que cambian conducta quedan DISEÑADOS, pendientes de pytest + 15:30):

- **material_risk (BUG)** → ARREGLADO y desplegado (v0.4.45). `deterministic_reviewer`
  evaluaba `bool(dict)` (siempre True) y bloqueaba toda compra. Detectado con
  `cycle-funnel --history`.
- **Mantenimiento de BD (T10)** → HECHO: apply + autovacuum INCREMENTAL + tarea semanal
  `AgenteBolsaDBMaintenance`. La BD (1.8GB) es dato real, no bloat.
- **Lab de mejora continua** → DIAGNOSTICADO (no está roto, es conservador por diseño):
  `docs/diagnostico_lab_mejora_continua_2026-06-25.md`. Aplica 0 cambios por
  `ALLOW_AUTO_APPLY=false` (seguridad) + validaciones que no llegan a READY_TO_APPLY por
  falta de datos maduros. Palanca: revisar propuestas READY_TO_APPLY a mano
---

## 14. Estado fin de jornada 25-jun (mercado abierto)

**Implementado y desplegado hoy (todo paper, pytest verde, commiteado):**
- **3 paredes de datos abajo:** material_risk (bug, v0.4.45), market_state_partial (§2, v0.4.46),
  research_guard (§3 flag, v0.4.48). Ver `docs/plan_desbloqueo_embudo_2026-06-25.md`.
- **§1 — construir take a R:R minimo (v0.4.49):** `_construct_min_reward_risk` en compras paper
  con buen setup pero take conservador (sube el take a 1.5R, nunca empeora). Experimento
  reversible (git revert). Validado en vivo: el blocker `reward_risk_bajo` **desaparecio** del
  embudo. Test `tests/test_entry_rr_construction.py`.
- **builtin_pullback en SHADOW (v0.4.50, B3):** estrategia de candidatos de pullback, mide sin
  tocar conducta. Registry: breakout=ACTIVE, pullback=SHADOW.
- **BD:** mantenimiento + autovacuum + tarea semanal. **Lab:** diagnosticado (conservador por
  diseno). **Duplicacion:** cuantificada (96.3%; `scripts/study_signal_duplication.py`).

**Resultado en vivo (embudo, mercado abierto):** las 3 paredes desaparecieron; §1 quito
`reward_risk_bajo`. Ahora **100% de rechazos son EXTENSION** (16-29% sobre SMA20). 0 trades =
**disciplina correcta**: el sistema genera momentum extendido (que pierde) y el gate lo rechaza
bien. El lever real es generar candidatos NO extendidos (pullback) — por eso builtin_pullback
en shadow, a validar con dias/regimenes.

**PENDIENTE (siguiente):**
1. Verificar que builtin_pullback genera candidatos no vacios y que sus outcomes se trackean.
2. **T6 — dedup de signal_outcomes por simbolo-dia** (96% duplicados arruinan la potencia de los
   estudios de edge). Cuidando el matching senal->outcome. Con test.
3. Medir (en dias) pullback-shadow vs breakout, y los forward outcomes de §1. Promover solo con
   evidencia OOS neta de costes.

## 15. Cierre 25-jun (tarde): cadena de medicion pullback verificada end-to-end

Tras pullback (B3) y T6, se cerro el riesgo de que la medicion del pullback fuese inutil dentro
de una semana. Tres entregas (Codex, paper-only, sin tocar ficheros bloqueados, suite verde):

- **Herramienta de medicion (v0.4.52):** `scripts/study_strategy_edge_compare.py`, read-only
  (`mode=ro`). Compara expectativa forward pullback(SHADOW) vs breakout(ACTIVE), por simbolo-dia,
  neta de costes (`--cost-bps`), horizontes 1/3/5/10. Dedup por `(signal_date, symbol, strategy)`.
  Hallazgo de esquema: `strategy/status/shadow` viven en `features_json`, returns en `outcome_json`.
  Estado 25-jun: 538 filas deduplicadas desde 2026-06-25 (42 pullback + 496 breakout), **0% maduro**
  (esperado; datos recien creados). Test sintetico cubre la matematica. `informe_codex_medicion_2026-06-25.md`.
- **Verificacion de maduracion (v0.4.53):** confirmado que `update_signal_outcomes` NO filtra por
  `source_run_id`/`decision`/`shadow_candidate` → las filas `:shadow` de pullback **si maduran**.
  No habia gap funcional; blindado con `test_update_signal_outcomes_matures_pullback_shadow_candidate`.
  Matiz: una llamada manual con `limit` bajo podria no cubrir filas; los jobs reales usan 200000/LEDGER_LIMIT.
  `informe_codex_maduracion_2026-06-25.md`.
- **Scoreboard de shadow (v0.4.54):** `cycle-funnel --shadow-scoreboard --history N`, read-only sobre
  reportes `closed_market_technical_study_*.json` (excluye manifests). Por ciclo/estrategia: nº de
  shadow_candidates + distribucion de `distance_sma20` y `rsi_14` (min/p50/max). 25-jun: pullback=42
  estable, dist -4.5%/0.7%/7.9%, RSI 40.4/53.0/58.6. Vigilar que varie dia a dia (no quede estancado).
  `informe_codex_scoreboard_2026-06-25.md`.

**Cadena verificada end-to-end:** genera (pullback 42) → trackea shadow (T6) → madura forward returns
(verificado) → mide (study_strategy_edge_compare). En ~1 semana el veredicto pullback-vs-breakout sera fiable.

**Recordatorio programado:** tarea `medicion-pullback-vs-breakout` para el **lun 6-jul 09:00 CEST**:
re-correr `study_strategy_edge_compare.py --since 2026-06-25 --horizons 1,3,5,10 --cost-bps 10` y analizar.

**PENDIENTE actualizado:**
1. (lun 6-jul) Leer la medicion pullback-vs-breakout con coverage maduro; promover a ACTIVE solo con
   evidencia OOS robusta, varios regimenes, neta de costes.
2. Vigilar con el scoreboard que el generador pullback sigue produciendo y varia dia a dia.
3. Backlog NO data-gated restante (riesgo/supervisar): migracion historica de T6 (320k filas 96%
   duplicadas, sin perder outcomes); C2 paralelizar sentimiento (cambio de conducta runtime).

### B4 - Regla constitucional anti-auto-sabotaje. **HECHO (v0.4.70).**
Regla deterministica en el laboratorio de mejora continua que rechaza propuestas
dirigidas a modificar controles de seguridad propios antes de llegar a
`READY_TO_APPLY`. Cubre auto-apply, aprobacion humana de cambios de codigo,
live trading, modo de trading, suelo de kernel, `autonomy.py` /
`code_autonomy_level`, `DETERMINISTIC_GATE` y umbrales de gates de riesgo
(`entry-quality`, `backtest_gate`, `risk_gate`). Ver informe:
`docs/informe_codex_constitucion_2026-06-30.md`.

### B5 - Constitucion v2: autogobierno y dedup anti-busywork. **HECHO (v0.4.71).**
Extension deterministica del lab para rechazar cambios de cadencia, WIP,
autonomia o supervision propios con `self_governance_modification_forbidden`, y
para bloquear re-propuestas recientemente rechazadas con
`recently_rejected_duplicate`. Los parametros de trading como
`trade_selection_top_n` no se prohiben por constitucion: quedan en cola humana y
requieren evidencia de edge. Ver informe:
`docs/informe_codex_constitucion_v2_2026-07-01.md`.

### B6 - Batch Fase 3: digest, auditoria constitucional y rollback demo. **HECHO (v0.4.72).**
Anadido `continuous-improvement-lab digest --days N` en modo solo lectura,
auditoria de cobertura constitucional contra `Settings.model_fields` con test
anti-huecos futuros, y rollback del cambio demo `docs/ci_codegen_demo.md` con
registro `ROLLED_BACK`. Ver informe:
`docs/informe_codex_batch_2026-07-01.md`.

### B7 - Estudio historico de politica por regimen. **HECHO (v0.4.73).**
Estudio read-only 2022-2026 con `strategy_edge_backtest.py`: caja,
buy&hold SPY, SPY solo en bull (`SPY > SMA200`) y top-selecciones solo en bull.
Incluye costes, Sharpe, max drawdown, peor semana y desglose por regimen. Ver
informe: `docs/informe_codex_regime_policy_2026-07-01.md`.

### B8 - Robustez de politica por regimen: beta, controles y costes. **HECHO (v0.4.74).**
Extension read-only del estudio de regimen con SMA150/200/250, sensibilidad
10/20/30 bps, control equal-weight de todo el universo, control random15 con seed
fija, residual beta-ajustado de top-picks y turnover semanal. Confirma etiquetas
de regimen causales (`SMA[t]` con datos `<= t`). Ver informe:
`docs/informe_codex_regime_policy_robustez_2026-07-01.md`.

### B9 - Turnover y estabilidad OOS del alpha beta-ajustado. **HECHO (v0.4.75).**
Extension read-only de `study_regime_policy.py` con sensibilidad de top-picks a
rebalanceo semanal/quincenal/mensual, min-hold e histeresis, coste por turnover
estimado y desglose OOS 2022/2023/2024/2025-26. El residual beta-ajustado sobrevive
mejor con menor turnover, pero 2023 muestra fragilidad. Ver informe:
`docs/informe_codex_regime_policy_turnover_oos_2026-07-01.md`.

### B10 - Walk-forward OOS honesto de politica por regimen. **HECHO (v0.4.76).**
Extension read-only de `study_regime_policy.py` con seleccion expansiva sobre una
rejilla pre-registrada (SMA150/200/250, cadencia 1/2/4w, min-hold e histeresis).
Cada bloque OOS usa parametros elegidos solo con datos pasados y cose el alpha
beta-ajustado. Resultado: alpha OOS cosido no confirma edge robusto y la seleccion
de parametros cambia en cada paso. Ver informe:
`docs/informe_codex_regime_policy_walk_forward_oos_2026-07-01.md`.

### B11 - Telegram radar Fase A: ingesta y extraccion read-only. **HECHO (v0.4.77).**
Nuevo paquete aislado `research/telegram_radar` para ingerir la vista publica de
Telegram sin login, cachear posts, extraer oportunidades/tickers con LLM o fallback
heuristico y marcar cobertura S&P 500 point-in-time. CLI `telegram-radar ingest`
y `telegram-radar list`. No cambia trading ni crea ordenes. Ver informe:
`docs/informe_codex_telegram_radar_faseA_2026-07-01.md`.

### B12 - Telegram radar Fase B: veredicto interno y scorecard honesto. **HECHO (v0.4.78).**
Extension read-only del paquete `research/telegram_radar` con `analysis.py` para
contrastar menciones in-universe contra regimen SPY>SMA200, extension SMA20, RSI,
R:R, 
---

## 18. Revision del responsable — lote 3 (3-jul-2026, manana)

- **P22 (muralla lab book) ACEPTADO. Veredicto: SEGURO.** Muralla central en
  `Store.signal_outcomes` (excluye `source=lab_book` por defecto), unica excepcion
  explicita para maduracion, filtros SQL directos en ~20 consumidores y
  test-candado global (`tests/test_lab_book_wall.py`). Protege tambien el
  veredicto pullback del 6-jul. (v0.4.103, commit 3da63043)
- **P23 (orquestador-lite nightly) ACEPTADO.** CLI `codegen-nightly` con frenos
  duros: max 2 gen-diff/dia, presupuesto tokens, doble freno (si auto-apply no es
  false, se NIEGA a generar), cupos human-gated fuera del allowlist, exclusion de
  propuestas previamente rechazadas, nunca approve/apply. Limpieza ejecutada:
  demo P20 REJECTED/demo_cleanup; P15 coherente. Fix extra: el digest ya no pide
  aprobacion de propuestas en estado terminal. (v0.4.104, commit c7ff4ec3)
  **Cabo suelto: falta el script supervisor del nightly** (solo CLI) → P24 lunes.
- **AUTORIZACIONES del responsable (3-jul):** (1) lab book `enabled=true` en modo
  log_only ($200 fijos, cap 10/dia, solo long, sin ordenes) — empezara a registrar
  el lunes con mercado abierto; (2) nightly operativo por CLI manual hasta P24.
- Ambar en vigilancia: `overnight_learning_heartbeat` degradado 2-jul
  (`overnight_llm_response_invalid`); revisar si repite con el codigo nuevo.

### Agenda lunes 6-jul
1. P3 — veredicto pullback (prompt en `docs/prompts_codex_2026-07-02.md`).
2. Encargar P24: supervisor del nightly + revision del heartbeat nocturno si
   repite el warning.
3. Primera sesion de dry-run de manga + lab book con mercado abierto; paridad
   con `scripts/core_sleeve_parity_check.py`.
4. Revision de activacion de la manga: jueves 9-jul (5 sesiones) o miercoles 8
   si la paridad viene perfecta.

---

## 19. Revision del responsable — lote 4 (3-jul-2026, manana)

- **P24 ACEPTADO** (v0.4.105, c611b385): research-mode del lab (flag OFF) con
  exclusion dura de caminos de trading + supervisor del nightly entregado.
- **P25 ACEPTADO** (v0.4.106, f3262631): misterio de las 160 observaciones
  RESUELTO con evidencia (candidatos de closed_market_study con outcomes
  inmaduros, no cola ejecutable) → familia `observation_execution_*` rechazada
  entera con dedupe. Puente findings_to_proposals creado: 3 CODE_CHANGE
  elegibles sembradas para el nightly.
- **P26 ACEPTADO** (v0.4.107, 806485e1): auditoria de producto. Numeros clave:
  OrchestratorAgent 969 propuestas/4sem con 98% rechazo; 88.5% prosa reciente;
  decision LLM 7.09M tokens/2sem con 0 trades; overnight arreglado con fallback
  determinista.

**Decisiones del responsable (3-jul):**
1. AUTORIZO encender `ci_research_mode` (la firma piensa 24/7; fin de semana como
   ventana de prueba supervisada; kill-switch = flag off + reinicio).
2. AUTORIZO arrancar el supervisor del nightly (03:00); tiene 3 propuestas
   elegibles para esta noche.
3. Recomendacion 1 de P26 (default ALLOW_AUTO_APPLY→false en config.py): APARCADA
   como ticket de cambio de kernel (requiere kernel-seal + aprobacion explicita de
   Antonio; no urgente: .env=false + doble freno + tests de invariante).
4. Recomendaciones 2/5 (capar orquestador, re-instruir cast) y 4 (dieta de tokens
   de decision, solo medicion) → lote 5 (P27-P29).

### Agenda actualizada
- Sab/dom: research-mode + nightly corriendo; revisar digest 08:30 y cola de
  aprobacion si el nightly produce diffs.
- Lun 6-jul: P3 veredicto pullback; primera sesion lab book + manga dry-run.
- Jue 9-jul (o mie 8): revision activacion manga con parity check.
puestas, sin enforcement | Codex | Bajo (lab, no trading) | **HECHO (v0.4.83, commit 764965ae).** Destapo cola READY_TO_APPLY con propuestas de agresividad sin evidencia. Ver 16.2 |
| P3 | (lun 6-jul) Lectura pullback vs breakout con criterios de promocion pre-registrados | Codex | Nulo (read-only) | PROGRAMADO (prompt entregado) |
| P4 | Shadow del overlay vol-target 12% + gate de evidencia para agresividad + limpieza digest | Codex | Bajo | **HECHO (v0.4.84, commit 0d69b0f0).** Paridad backtest-vivo testeada; señal 1-jul: vol 18.3% → exposicion VT12 66%. Cola saneada: 3 rechazos por `aggressiveness_requires_edge_evidence`, 2 por self_safety, 1 por self_governance. "Peor mes" aclarado (calendario en ambas tablas). Pendiente menor: listar las 7 propuestas restantes en READY_TO_APPLY (encargado en P6) |
| P5 | **Manga core SPY vol-target 12% en paper** (flag OFF + dry-run; limites duros; config fuera de config.py) | Codex | Medio (mitigado) | **HECHO (v0.4.85, commit 056e83e9).** Revisado por el responsable: dry-run retorna antes del submit (verificado en codigo), config segura `enabled=false`, demo real would_submit SPY $13.914 = 70.653×0.30×0.6565 (matematica verificada). Decision: pasar a dry-run diario (enabled=true, dry_run=true) para acumular sesiones antes de activar |
| P6 | Primer cambio real de la firma end-to-end + fix CLI + listado cola | Codex | Bajo | **HECHO PARCIAL (v0.4.86, commits 0db8e130+89d7f500). HALLAZGO CRITICO: el codegen de la firma fallo 3/3** (`opencode-go/glm-5.2`: "LLM response without text content"; fallback local sin conexion). La firma NO puede entregar diffs = Fase 2 muerta en runtime. Digest+CLI entregados via fallback Codex. Cola READY_TO_APPLY listada con recomendaciones → P7b |
| P7 | **Reparar el programador de la firma** (codegen LLM) + reintento e2e + saneo de cola | Codex | Bajo-Medio (lab) | **HECHO (v0.4.87, commit c548004f).** Causa raiz confirmada con respuesta cruda: glm-5.2 quemaba hasta 57k chars en `reasoning_content` con `finish_reason=length` y cap de 4k. Fix: truncado diagnosticable, extraccion JSON de reasoning, codegen a 16k tokens con modelo propio (deepseek-v4-flash), health-check cubre rol codegen (`codegen_ok=true`). Cola READY_TO_APPLY = 0 (5 REJECTED con razon auditable, 4 a VALIDATING). Reintento e2e: intento 3 llego a sandbox pero `REJECTED_BY_TESTS` (bloque `old` no casaba) → el programador habla pero aun no entrega parches aplicables → P9 |
| P8 | Radar Telegram: dejar madurar scorecard ~2-3 semanas | — | — | EN ESPERA (supervisor unico vivo; primer informe diario 2-jul OK; vigilar anomalia ORCL ext -23%/RSI 11) |
| P9 | **Codegen que entrega parches aplicables** (autocorreccion acotada + contexto completo + artefactos de intento) | Codex | Bajo (lab, allowlist) | **HECHO (v0.4.88, commit 2a457e08).** Causa raiz adicional encontrada: `_context_files()` truncaba a 12k chars sin avisar (digest.py ya media 29.7k) → el modelo parcheaba un fichero que no veia entero. Fix: contexto completo <=800 lineas + 32k tokens + autocorreccion (aplicacion Y validacion). **Reintento e2e: EXITO al 3er intento** — `ci_artifact_259b18101111` en READY_FOR_HUMAN_REVIEW, 5 tests sandbox verdes, targets en allowlist. La autocorreccion arreglo sola un JSON invalido del intento 2. **HITO FASE 2 pendiente solo de: revision del diff por el responsable → approve de Antonio** |

### 16.6 Hito Fase 2 (2-jul): primer diff de la firma — RECHAZADO en revision humana

`ci_prop_p7_core_sleeve_digest` llego a `READY_FOR_HUMAN_REVIEW` con tests verdes,
pero el responsable RECHAZO el diff (`ci_artifact_259b18101111`) antes del approve:
**la firma invento el esquema del log** (leia `target_exposure`/`hypothetical_order`;
el productor real escribe `exposure`/`decision.order`) **y escribio tests que
validaban su propia invencion**. Con datos reales, la seccion mostraria None.
Leccion capital para la firma: tests sinteticos contra datos autofabricados no
prueban integracion con la realidad — es la version en codigo del sobreajuste.
Ademas el rail de arbol limpio funciono: el approve prematuro quedo BLOCKED.
Regeneracion con esquema real + muestra de datos reales en contexto de codegen: P10
(`docs/prompts_codex_2026-07-02_f.md`). El hito queda pendiente de un diff correcto.
Matiz de proceso: la reactivacion uso `P9ManualCodegenGate` (bootstrap manual);
cuando el orquestador de Fase 3 exista, este cauce debe ser suyo.

**Actualizacion (2-jul, tarde):** P10 regenero el diff CORRECTO (esquema real,
tests con lineas reales del log; contenido aprobado por el responsable), pero el
`approve` real fallo con `patch does not apply` en ambos targets pese a sandbox
verde → bug del CAMINO DE APPLY en Windows (hipotesis: EOL CRLF/LF + mojibake real
en `test_ci_phase3_digest.py`; el sandbox normaliza, el arbol real no). Los railes
respondieron bien: REJECTED_BY_TESTS limpio, sin estado a medias. Fix encargado en
P11 (`docs/prompts_codex_2026-07-02_g.md`): diagnostico byte a byte, apply robusto
(--3way / --ignore-whitespace / normalizacion simetrica), test CRLF sintetico,
regeneracion y reintento. El hito Fase 2 queda a un `approve` de distancia.

**Actualizacion 2 (2-jul, 15h):** P11 (v0.4.90, commit 14b61778) encontro la causa
raiz REAL (no era CRLF de ficheros: los helpers Git decodificaban la salida con
locale cp1252 y el artefacto se guardaba con mojibake; fix: UTF-8 explicito +
apply en 3 niveles) — buen trabajo de no asumir la hipotesis del responsable.
PERO el artefacto regenerado (`ci_artifact_9a6378dc448e`) fue RECHAZADO por el
responsable tras inspeccion directa en BD: toca solo digest.py SIN ningun test de
la funcion nueva; su sandbox solo corrio los 4 tests preexistentes → `tests_ok=true`
enganoso. Hueco sistemico destapado: el gate acepta codigo nuevo sin tests. P12
(`docs/prompts_codex_2026-07-02_h.md`): gate determinista `new_code_requires_tests`
+ restaurar el artefacto P10 (contenido ya aprobado) reparado con el nuevo apply.
Racha de hallazgos del e2e: transporte LLM → contexto truncado → esquema inventado
→ encoding del apply → gate sin exigencia de tests. Cada iteracion endurece la firma.

### 16.7 HITO FASE 2 CERRADO (2-jul, tarde) — primer cambio de la firma APLICADO

`APPROVE | status=APPLIED | commit=6816b05e | applied_change=ci_applied_022335b7740c`

Primer cambio de codigo generado por la firma (deepseek-v4-flash + autocorreccion),
validado en sandbox con suite completa, revisado por el responsable, aprobado por
Antonio y aplicado de forma reversible. La seccion "Core sleeve" del digest diario
es ahora codigo escrito por la propia firma.

Recuento de defectos reales destapados y arreglados por este UNICO e2e (P6→P14):
1. Transporte LLM roto (glm-5.2 truncaba en razonamiento; cap 4k) — P7.
2. Contexto truncado en silencio a 12k chars (el modelo parcheaba a ciegas) — P9.
3. Esquema inventado + tests autoreferenciales (rechazo humano) — P10.
4. Artefactos corrompidos por decode cp1252 (mojibake) — P11.
5. Gate aceptaba codigo nuevo sin tests — P12.
6. Approve con limit-before-filter (elegia el artefacto equivocado) — P13.
7. Approve sin evidencia del fallo + asimetria sandbox/approve (suites focalizadas
   vs suite completa) + politica de version no contemplada en artefactos — P14.
   Ironia instructiva: el test que tumbo el approve era `test_version_policy` — el
   propio control de la casa exigiendo bump de version al diff de la firma.

Todo con test de regresion. Cadencia de apply humano DEMOSTRADA end-to-end.
Pendiente estructural (Fase 3): los pasos manuales (`P9/P10/P11ManualCodegenGate`,
reactivaciones, resiembras) deben pasar al orquestador; y el digest debe traer la
cola de aprobacion al humano cada manana (ya lo hace).

**Post-hito (P15, v0.4.96, commits 0ea61f00/fa126d40/88bb854d):** el codigo aplicado
de la firma crasheo en su primera ejecucion real (`decision.order: null`, estado
`no_order` por `already_rebalanced_today` — el caso normal futuro de "hold"). La
firma fallo 3/3 al arreglar su propio bug (old-block otra vez) → hotfix directo de
Codex con tests del contrato COMPLETO de estados del productor. Dos lecciones: (a)
tests de parsers deben cubrir todos los estados que el productor emite, no los que
convenga; (b) el codegen sigue sin saber editar ficheros grandes → P20.

---

## 17. Direccion revisada del responsable (2-jul, tarde; aprobada por Antonio)

El beneficio viene de: exposicion al mercado, control de perdidas y edge — no de
fontaneria. Reordenacion por impacto:

1. **Capital desplegado** (palanca nº1): activar la manga tras paridad dry-run y
   escalar 30→50→70% por puertas pre-registradas (P17). Techo de honestidad: la
   beta bien cobrada + caidas controladas ya bate a la mayoria de minoristas.
2. **Horizonte de salida 5-10d**: unico hallazgo de edge propio con evidencia
   direccional positiva (jun: 1-3d −1,78% vs 5-10d +1,18%, n=4); releer con la
   muestra acumulada y criterios pre-registrados (P16).
3. **Dos libros**: core (beta+overlay, rotacion minima) + laboratorio (micro-size,
   log-only primero) para resolver el hambre de muestra sin sobre-operar (P18).
4. **KPI de mortalidad**: la firma se mide por hipotesis matadas honestamente por
   semana, no por actividad; agenda de investigacion en el digest (P19).
5. **Codegen ficheros grandes**: sin esto la firma no mantiene su propio codigo (P20).

Lote 2 encargado: P16-P21 en `docs/prompts_codex_2026-07-02_lote2.md`. Estado:
EN CURSO. Ninguna tarea cambia conducta real (read-only / flag OFF / human-gated).

| Tarea | Entrega | Artefacto | Estado |
|---|---|---|---|
| P16 | Relectura horizonte salida 1-3d vs 5-10d con muestra acumulada | `docs/informe_codex_p16_horizonte_salida_2026-07-02.md` | HECHO (v0.4.97, commit 09c27b07) |
| P17 | Parity check core sleeve + runbook de activacion/escalado | `scripts/core_sleeve_parity_check.py`, `docs/runbook_core_sleeve_activacion.md`, `docs/informe_codex_p17_parity_runbook_2026-07-02.md` | HECHO (v0.4.98) |
| P18 | Lab book log-only separado del libro real | `src/agente_bolsa/tools/lab_book.py`, `scripts/run_lab_book_daily.ps1`, `docs/informe_codex_p18_lab_book_2026-07-02.md` | HECHO (v0.4.99) |
| P19 | Agenda de investigacion y KPIs de hipotesis en digest | `data/research/research_agenda.json`, `src/agente_bolsa/continuous_improvement/research_agenda.py`, `docs/informe_codex_p19_agenda_investigacion_2026-07-02.md` | HECHO (v0.4.100) |
| P20-P21 | Pendiente, en orden | `docs/prompts_codex_2026-07-02_lote2.md` | PENDIENTE |

| P10-P14 | Regeneracion esquema real → fix encoding → gate tests → fix approve → simetria suite | Codex | Bajo | **HECHO** (v0.4.89-0.4.93, commits aa2d6b42, 14b61778, 621d364e, e9c7e992, 81cddbaa; apply final commit 6816b05e por approve de Antonio; version efectiva 0.4.94) |

### 16.5 Revision del responsable sobre P7 (2-jul, tarde)

Entrega modelo: diagnostico con evidencia cruda ANTES de arreglar. Estado de la
cadena del programador de la firma tras P7: transporte OK (habla), calidad KO (su
patch no aplica: `old` block mismatch, fallo clasico de search/replace). Correcto
no aplicar fallback esta vez: el fallo real es el dato que necesitabamos. La
propuesta `ci_prop_p7_core_sleeve_digest` paso ademas por el cauce normal de
validacion (matiz de P6 corregido). Dos payloads literales confirmaron que los
rechazos `duplicate_or_prose` eran correctos (ambos pedian auto-aplicacion en
prosa). Siguiente eslabon (P9): autocorreccion con el error de vuelta al modelo —
si tras eso el codegen sigue sin entregar, la decision sera cambiar el formato de
patch (p. ej. fichero completo en vez de search/replace para targets pequenos).

### 16.4 Revision del responsable sobre P5+P6 (2-jul, tarde)

- **P5 aceptado.** Verificaciones propias del responsable (no de palabra): config en
  disco `enabled=false/dry_run=true`; el guard dry-run retorna antes de cualquier
  submit; sizing de la demo cuadra a mano. Gobierno correcto: la firma no puede
  proponerse activar la manga (`core_sleeve.enabled/dry_run` human-gated).
- **P6: el valor esta en el fallo.** El experimento e2e destapo que el programador
  de la firma esta roto en runtime: 3/3 `gen-diff` con respuesta LLM sin contenido
  (glm-5.2 via opencode-go) y fallback local caido. Es el MISMO patron de fallos
  previos (C1.3: Kimi consumia tokens en razonamiento y devolvia vacio; B.1: fix de
  extraccion en telegram radar). Sin esto, el hito "la firma funciona" es imposible:
  arreglar el codegen pasa a maxima prioridad de la firma (P7). Leccion repetida del
  proyecto: la degradacion LLM silenciosa debe hacerse visible → el health-check
  debe cubrir el rol de codegen.
- Matiz de metodo anotado: Codex sembro la propuesta directamente en READY_TO_APPLY
  (bypass de validacion). Aceptable para el ejercicio; el reintento P7 debe pasar
  por el cauce normal de validacion.

### 16.3 Decision estrategica del responsable (2-jul, tarde; ratificada por Antonio)

El sistema pivota a **core + satelite en paper**: manga core de SPY gobernada por
vol-target 12% (unica palanca con evidencia OOS que CUMPLE criterios pre-registrados)
y el stock-picking como satelite en shadow hasta que demuestre edge (lectura pullback
6-jul). Despliegue: shadow (corriendo desde P4) → dry-run (P5) → activacion humana.
La activacion (`enabled=true, dry_run=false`) requiere: ~5 sesiones de paridad
shadow-vs-backtest sin divergencia, revision del responsable, y accion manual de
Antonio. La firma tiene prohibido proponerse a si misma activar o engordar la manga
(cubierto por aggressiveness_gate/human-gate en P5.4).

### 16.1 Revision del responsable sobre P1 (2-jul, tarde)

Veredicto aceptado como evidencia con estas cautelas anotadas:

- El test decisivo es el correcto: politica FIJA vol-target 12% sin seleccion a
  posteriori. El walk-forward selector es inestable (Codex lo reconoce) y NO se usa.
- Coste real de la proteccion: CAGR full-period 8.43%→6.09% a 20 bps. El criterio
  pre-registrado aceptaba ese trade-off (Sortino y colas mandan), pero debe quedar
  explicito ante cualquier decision de adopcion.
- Calidad de datos: 28 dias con desviacion >1% SPY vs ^GSPC, concentrados en
  2000 y 2008 (p.ej. 2000-01-07: +5.81% vs +2.71%). Los episodios dot-com son los
  menos fiables; 2008/2020/2022 tienen margen de sobra aunque el dato tenga ruido.
- Inconsistencia menor detectada: "peor mes" usa ventana distinta en la tabla de
  episodios (parece rolling) vs la tabla de criterios (calendario). Pedir
  harmonizacion/definicion explicita en P4.
- Scope creep menor: el commit toca 3 scripts ajenos (orden de imports por ruff).
  Inocuo, pero en adelante arreglos de lint ajenos van en commit separado.
- Recuperaciones: vol-target tarda MAS en recuperar en varios episodios (dot-com
  1139 vs 1020 dias). La proteccion es de profundidad de caida, no de velocidad.

**Implicacion estrategica (decision de Antonio, sin prisa):** el overlay solo
sirve si el portfolio tiene exposicion de mercado, y hoy el book paper esta
practicamente plano. La evidencia acumulada (picking sin alpha + overlay que
CUMPLE) apunta al pivote honesto: una manga core de SPY en paper gobernada por
vol-target 12%, con el picking como satelite en shadow. Es un cambio de
estrategia, no de parametro: requiere decision humana explicita. Paso previo
obligatorio en cualquier caso: shadow del overlay en vivo (P4) para verificar que
la senal diaria replica el backtest.

### 16.2 Revision del responsable sobre P2 (2-jul, tarde)

El digest funciona y ya paga: destapo la cola. Hallazgos:

- **La constitucion muerde** (rechazos 24h: self_safety=5, self_governance=6),
  y la firma sigue intentando encender auto-apply — bien bloqueado.
- **RED FLAG — cola READY_TO_APPLY (13):** contiene subidas de agresividad de
  trading SIN evidencia de edge (`max_daily_buy_orders`, `max_orders_per_cycle`)
  justificadas con "mas trades → mas outcomes" — exactamente la falacia de
  sobre-operacion que este proyecto combate. Tambien `deterministic_gate_error_severity`
  (relajar severidad del gate, 2 propuestas) llego a READY_TO_APPLY: revisar por
  que la constitucion v2 no lo cubre. Decision del responsable: **rechazar en
  bloque** las de agresividad sin evidencia y anadir regla de gate (P4) para que
  no vuelvan a llegar a la cola humana sin experimento adjunto.
- Digest re-lista en PIDE APROBACION la demo codegen ya aplicada y revertida
  (`ci_prop_codegen_demo_...`): debe excluirse lo ya APPLIED/ROLLED_BACK (P4).
- KPI: semana 29-jun Applied=1 pero %exp→aplicado=0.00% (definicion no casa);
  harmonizar (P4). El clasificador 68% "ejecutable" esta inflado (payloads de
  metricas cuentan como spec): valido para medir tendencia, NO para enforcement.

**Criterios pre-registrados (fijados HOY, antes de mirar los datos):**
- P1 / vol-target 12% fijo (sin seleccion): en cada bloque OOS anual, neto 20 bps,
  debe reducir max DD y peor mes vs buy&hold en los años de drawdown grande
  (>15% en SPY), mantener Sortino global >= buy&hold, y hacerlo en >=80% de los
  bloques con drawdown. Si falla → se archiva la palanca honestamente.
- P3 / pullback → ACTIVE solo si: expectancy 5d y 10d positiva neta de 10 bps,
  alpha vs SPY positivo, n>=30 simbolo-dias maduros, y el resultado no depende de
  un solo dia ni de un solo sector. Si no, sigue SHADOW acumulando.

**Que NO se hace:** no relajar gates; no promover vol-target ni pullback sin sus
criterios; no ampliar autonomia ni auto-apply; no Fase 4 hasta que la Fase 3
minima este corriendo y medida.

---

## 20. Revision del responsable — 4-jul-2026 (sabado)

- **P30 ACEPTADO (v0.4.109, commit da001ccd)** y validado en combate el mismo
  dia: `stack_status` detecto 5 supervisores duplicados que el filtro crudo por
  CommandLine NO puede ver (lanzamientos con ruta relativa no contienen
  "agenteBolsa"). Limpieza ejecutada; estado final 7/7 CORRIENDO sin duplicados.
  Matiz al informe de Codex: SI habia duplicados logicos (su propia stack_up los
  creo contra los viejos invisibles); la herramienta corregida los destapo.
  Reglas de oro anadidas a `docs/runbook_stack.md`.
- **Primer run 100% autonomo del nightly** (ci_codegen_nightly_6f75d401179a):
  selecciono 2 propuestas de P25, gasto 64k tokens, genero diffs con
  autocorreccion y los rechazo honestamente. Post-mortem con evidencia:
  1. `ci_prop_82a01dd92356`: su test generado fallo (proposal_test_1).
  2. `ci_prop_0327e166f163`, cascada de 3 intentos: test generado mal →
     autocorrige → **FAILED test_version_policy** (el diff no bumpeaba version)
     → intenta bumpear `__init__.py` a ciegas → "No se encontro bloque old"
     (invento el contenido: el fichero no estaba en su contexto).
  Causas mecanicas → P31 (lunes): (a) el bump de `__version__` lo hace el
  PIPELINE deterministicamente tras aplicar el patch (el modelo tiene PROHIBIDO
  tocar `__init__.py`); (b) para propuestas de tests, incluir en contexto el
  MODULO BAJO TEST (hoy el modelo asertaba comportamientos que no habia visto);
  (c) relanzar las 2 propuestas fallidas con esos fixes.
- Digest sabado: Safety OK en produccion, agenda viva (5-10d matada), manga
  calculando ($14.028 hipoteticos), research-mode aun 0 ciclos (el scheduler
  con codigo research arranco 15:05 de hoy; primera madrugada util: domingo).
- Pendiente para el lunes: P3 (veredicto pullback) + P31 + primera sesion de
  manga dry-run + lab book con mercado abierto + paridad.

---

## 21. GIRO DE OBJETIVO — 7-jul-2026 (decision de Antonio, asumida por el lead)

**Objetivo corregido:** el sistema dinamico opera en paper para APRENDER de sus
propias operaciones y mejorar con el tiempo. Experimento de aprendizaje, no
producto de rentabilidad inmediata. Perder al principio es aceptable; la vara es
la TENDENCIA de mejora medida sin autoengano. La manga core SPY fue un desvio
(el indice ya lo cubre Antonio por su cuenta): APAGADA el 7-jul
(enabled=false, dry_run=true; commit 073b7659). El codigo y los estudios de
vol-target quedan archivados como activo reutilizable, no como rumbo.

**Plan del giro** (`docs/prompts_codex_giro_aprendizaje.md` +
`docs/prompts_codex_giro_lote_hoy.md`):
- P-L1 LLM vivo — **HECHO (v0.4.114)**: health check por rol sin falsos
  positivos (200-vacio ya no es OK), linea `LLM:` permanente en digest, llamada
  real de decision en llm_usage. Matiz del lead: el fallo de suite que el
  informe llamo "ajeno" es BLOQUEANTE (gate de approve/nightly) → G0.
- G0 suite verde (bomba de fechas hardcodeadas en test_lab_book_wall) →
- G1/P-L2 learning_mode: budget 3 ordenes/dia x $1000, near-miss soft,
  market_state PARTIAL no estrangula, pullback ACTIVE en el modo, cohorte
  `learning_experiment` con muralla, shadow_first → flip humano.
- G2/P-L3 bucle fill→outcome→review→leccion→ajuste verificado eslabon a eslabon
  + digest "Aprendizaje de ayer".
- G3/P-L4 scoreboard con criterio PRE-REGISTRADO: aprende si expectancy neta de
  semanas 5-8 > semanas 1-4, pendiente positiva, y bate al contrafactual
  (candidatos rechazados / seleccion aleatoria). A las 8 semanas, veredicto en
  rojo o verde, sin autoengano.
- G4/P31 nightly: bump por pipeline, contexto de modulo bajo test, relanzar.

**Lo que NO cambia:** paper-only sellado, suelo de kernel, constitucion,
auto-apply OFF, apply humano, mediciones pre-registradas.

## P-L43B — time-stop XNYS en observación shadow (15-jul-2026)

- P-L43A confirmó un `semantic_mismatch` de severidad high: el horizonte
  legacy se medía por días naturales.
- P-L43B implementa `p-l43b.time-stop-xnys.v1`: cinco sesiones XNYS cerradas
  estrictamente posteriores al fill, con comparación legacy descriptiva.
  `legacy_calendar_days` continúa siendo la única política activa y XNYS
  permanece `shadow_only=true`.
- P-L43BR1 restauró explícitamente shadow/paridad. P-L43BR2 hizo histórica y
  auditable la evidencia mediante eventos append-only por posición; `runtime_state`
  es sólo `latest_view`.
- P-L43BR4 desplegó el candidato `0.4.173` en producción mediante merge no
  destructivo. La política `legacy_calendar_days` sigue activa y XNYS es
  exclusivamente `shadow_only=true`. El estado prospectivo continúa
  `collecting` hasta observar posiciones reales; su activación requiere
  autorización humana y otro lote separado (`guarded_active`).
- No se interpretan los casos históricos como rentabilidad ni como autorización
  para cambiar stops, takes, trailing, exposición, límites o trading.
## P-L45B1 — fiabilidad del postmarket (desplegado en 0.4.174)

- **Desplegado y operativo:** coordinación única por sesión, exclusión
  entre postmarket y reconciliación, terminales duraderos
  `completed|failed|skipped` y una sola actualización de `signal_outcomes` por
  ejecución efectiva.
- Los eventos nuevos usan `p-l45b1.postmarket-run.v1`, son append-only,
  idempotentes y conflict-safe sobre `agent_events`; `runtime_state` queda como
  vista operativa del lease.
- `build_learning_daily_run(update_result=...)` reutiliza el resultado de
  outcomes; los llamadores sin argumento conservan compatibilidad legacy.
- **P-L45B2 desplegado en 0.4.176:** batching y reducción de duración de los
  upserts de observaciones; chunk=250, sin cambio funcional de trading.
- **P-L44B en ensayo shadow:** candidato `0.4.177`; `legacy_double_application`
  sigue activa y `single_application` no tiene autoridad sobre trading.
- La mejora de duración no se interpretará hasta disponer de cinco sesiones
  reales posteriores; no se modifica trading ni la política legacy activa de
  P-L43B.
- **P-L45B1-QA:** el ensayo adversarial corrigió la fixture temporal de
  `test_insufficient_evidence_extends_window`, añadió identidad de proceso al
  lease para PID reutilizado y persistencia durable de `max_instances`/`missed`
  de APScheduler; además, `post_market_review_last_session` solo avanza de
  forma monotónica tras `completed`. No cambian horarios, `max_instances`,
  `coalesce` ni trading; P-L45B2 sigue reservado para batching.

## P-L45B1-D desplegado (16-jul-2026)

Merge productivo `2dbd02a8`, versión `0.4.174`, tree `a3dba615`, suite
`1395 passed` y gates operativos verdes. El stack quedó con scheduler único,
lock/PID y heartbeat frescos, HTTP 200, paper activo, live y auto-apply
desactivados. El bootstrap posterior publicó un único skip durable
`market_not_ready` sin reprocesar la sesión del `2026-07-15`, sin segunda
actualización de outcomes ni bloqueo SQLite.

P-L45B2 (batching) está integrado en producción dentro de 0.4.176; la mejora de
duración requiere cinco sesiones reales posteriores antes de interpretarse.
P-L44B sigue en ensayo shadow como `0.4.177`; no se ha desplegado.

## P-L45B2-W - escrituras batch de learning_observations (candidato 0.4.175)

En `codex/pl45b2-batch-impl` se implementa una API de `Store` con chunks de
250 filas por defecto, `BEGIN IMMEDIATE` y un commit por chunk. El upsert
individual y el batch comparten el mismo SQL y normalizacion: se conservan
`ON CONFLICT(observation_id) DO UPDATE`, overwrite de JSON, `updated_at`,
conflictos por indice natural y la serializacion legacy de `NaN`/`Infinity`.

`daily_learning` y la sincronizacion RR reutilizan la API sin cambiar
observaciones, orden, payloads, cohortes ni decisiones. El resultado expone
filas recibidas/escritas, chunks, duracion y valores JSON no estrictos; un
fallo hace rollback del chunk actual, conserva commits anteriores y detiene la
fase para retry explicito. No se crean tablas ni migraciones.

La caracterizacion de 33.336 filas reduce estructuralmente 33.336 commits a
134 con chunk=250. Se recomienda validar 250 como tamano inicial conservador.
Quedan como deuda separada la perdida potencial de ramas JSON, JSON no estricto
y el `updated_at` que cambia al reintentar. P-L44B queda reservado para
`0.4.177`.
## P-L43BR5-W - autoridad verificable del fill en time-stop shadow (desplegado en 0.4.176)

- La auditoría read-only identificó que las posiciones reales exponen
  `PositionSide.LONG`, mientras la autoridad de la orden y del fill se conserva
  en `broker_order_id`, `OrderSide.BUY`, estado `filled` y
  `execution_quality_snapshot.timestamps.first_fill_at`.
- El candidato normaliza únicamente variantes deterministas de compra
  (`buy`, `BUY`, `OrderSide.BUY` y enums con valor `buy`); no trata `long` como
  lado de orden. Exige orden rellenada, cantidad válida, identidad de broker y
  `first_fill_at` para parciales; `filled_at` agregado sólo es válido cuando no
  hay evidencia de parcialidad.
- La identidad canónica de lote no cambia: el hash sigue dependiendo de las
  referencias de orden/plan, cantidad y fill. Las cinco observaciones históricas
  `unavailable` no se reescriben; una evaluación verificable futura sólo añade
  una transición append-only idempotente.
- `legacy_calendar_days` continúa siendo la única política activa y XNYS sigue
  `shadow_only=true`; no se generan órdenes ni se alteran stops, takes, trailing,
  cantidades, gates, ranking, exposición, límites o historial. P-L45B2 y P-L44
  permanecen fuera de alcance. P-L44B queda reservado para la futura version
  `0.4.177`.

Despliegue confirmado mediante merge productivo `6e29fd6d`, árbol funcional
`20d11916`, suite `1463 passed` y gates de configuración/kernel verdes. La
evidencia XNYS permanece shadow/collecting y no se interpreta como resultado de
rentabilidad.

## P-L44B-W2 - penalizacion de aprendizaje en shadow (15-jul-2026)

- El candidato `0.4.177` integra sobre la base P-L43BR5 el comparador
  `p-l44b.learning-penalty-cycle-shadow.v1`.
- `legacy_double_application` sigue siendo la unica politica activa; el
  resultado `single_application` es telemetria sin autoridad sobre ranking,
  gates, seleccion, sizing, planes u ordenes.
- P-L44BR3 desplegó en producción mediante merge `23e4bf4d` sobre el commit
  `f303d351`. La versión final es `0.4.177`; `legacy_double_application` sigue
  activa y `single_application` es exclusivamente shadow.
- Cada ciclo captura los BUY ya rankeados en memoria y persiste un unico evento
  acotado en `agent_events`; las repeticiones son no-op y los conflictos no
  sobrescriben el original. El detalle se limita a la union de los top-20
  legacy/shadow, seleccionados y controles.
- Sin eventos el digest/health/CLI publican `collecting` con denominadores
  `null`; no hay backfill. El CLI es `learning-penalty-shadow-report --json`.
- El historial prospectivo permanece `collecting`; no hay evidencia suficiente
  para activar la penalización única ni influencia sobre trading.
## P-L47B1 — leases terminales y ownership del scheduler (desplegado 0.4.180)

En un worktree aislado se corrige la recuperación durable de leases de
postmarket/reconciliación y la propiedad del lock del scheduler. `runtime_state`
continúa siendo una vista mutable; `agent_events` conserva adquisiciones,
liberaciones, recuperaciones, conflictos y fallos de liberación append-only.
La autoridad del scheduler es el proceso Python real de APScheduler, con PID,
token estable de creación y payload versionado; wrappers, locks legacy,
propietarios muertos y PID reutilizado se diagnostican sin robar un proceso
vivo. No se crean tablas, migraciones, procesos ni schedulers nuevos y no se
tocan decisiones de trading.

El despliegue cerrado del 18-jul-2026 integra el merge `f60a3d82` desde la base
`39da7c8c`. La topología Windows se confirmó como un scheduler lógico
wrapper → launcher `.venv` → runtime Python. El lock v1 quedó asociado al
runtime y el bootstrap recuperó `brkrec_eb45e5acbd6b` como lease terminal
residual, conservando su terminal durable y sin reprocesar postmarket,
reconciliación ni outcomes. P-L43BR6 conserva el slot futuro `0.4.181` y
P-L44BR3 el `0.4.182`; ninguno se integra en este lote.

## P-L44BR3 - contrato lector y denominadores shadow (candidato 0.4.181)

- La auditoría confirmó un `reader_contract_gap`: la identidad se evaluaba
  después de exigir inputs de scoring y los candidatos raw quedaban contados
  erróneamente como `identity_unavailable`.
- El lector corregido evalúa primero `signal_capture_id` y `signal_id`; los
  identificados sin prior/rank permanecen en el denominador como
  `shadow_inputs_unavailable`, sin score inventado. `candidate_id` aislado no
  sustituye identidad canónica y no se usa símbolo/fecha como fallback.
- Digest, health y CLI aceptan sólo eventos canónicos con schema, ciclo, id y
  hash válidos; deduplican por `cycle_id`, ignoran filas genéricas del
  reporter y exponen conflictos sin reemplazar el original.
- Los denominadores anteriores quedan invalidados para interpretación; no hay
  backfill. Sin eventos el estado es `collecting` con denominadores `null`;
  con identidad válida pero inputs ausentes es `partial`.
- `legacy_double_application` sigue siendo la política activa y
  `single_application` exclusivamente shadow. No existe evidencia para
  activarla. P-L43BR6 conserva prioridad de integración como `0.4.180` y
  P-L44BR3 deja el ensayo en `0.4.182`; ambos permanecen exclusivamente shadow.

## Secuencia post-P-L47B1 del ensayo

- 0.4.180: P-L47B1 desplegado.
- 0.4.181: P-L43BR6 integrado primero en este ensayo.
- 0.4.182: P-L44BR3 integrado después; versión final del ensayo.
- Ambos lotes continúan exclusivamente shadow y no modifican trading.

## Despliegue secuenciado P-L43BR6 + P-L44BR3 (18-jul-2026)

- Merge productivo: `7cc432aee3f594d946f5a65d1f86f3e49fa82e4`.
- Tree funcional: `bc2d15ffd0d43f10359761b61efc07b0384c5072`.
- Versión final: `0.4.182`.
- Secuencia: P-L47B1 `0.4.180` desplegado; P-L43BR6 `0.4.181` desplegado;
  P-L44BR3 `0.4.182` desplegado.
- P-L43BR6 conserva `legacy_calendar_days` activa y XNYS `shadow_only=true`.
- P-L44BR3 conserva `legacy_double_application` activa y
  `single_application` exclusivamente shadow.
- Ambos shadows siguen `collecting`/`partial`; no hay backfill ni autoridad
  sobre trading.

## P-L43C-W - carrier shadow de autoridad causal time-stop (candidato 0.4.192)

- Implementacion aislada en el worktree P-L43C-W desde la base de
  caracterizacion e0ba03ff; `legacy_calendar_days` sigue activa y XNYS sigue
  shadow-only.
- La captura predecisional se conserva en memoria antes del envio y los
  eventos decision/link se persisten despues, en una transaccion append-only
  fail-open. No se toca `execution.py` ni la llamada `close_position`.
- La identidad exige cycle/watch, position_identity, plan y BUY broker order
  exactos; multilote, recompra ambigua, fill no autorizado y version de
  politica ausente quedan unavailable/ambiguous. No hay join por simbolo/fecha.
- QA del worktree: P-L43C-T 29, P-L43C-W 40, focales relacionadas 178; Ruff,
  NUL, diff y validate-agent-config verdes. No desplegado. Siguiente paso:
  validacion cerrada integrada.

### P-L43C-R1 - prioridad durable de la orden local (candidato 0.4.192)

- Reproduccion contra la base P-L43C-W: `submit` persistia P-L43C antes de
  `save_broker_order`.
- Correccion aislada: `submit activo -> save_broker_order local -> P-L43C
  decision/link fail-open -> reconciliacion`; no cambia request, resultado,
  excepciones, politica, plan, orden ni reconciliacion.
- QA focal: 44 pruebas P-L43C/R1 verdes; no se ejecutan suite completa, smoke
  ni validacion cerrada con XNYS abierto. Produccion intacta y sin despliegue.
- Siguiente paso unico: validacion cerrada integrada del candidato exacto.

## P-L48B-W - telemetria canonica de operaciones (candidato 0.4.184)

- Implementado en shadow un productor unico `p-l48b.canonical-operation-telemetry.v1`.
- La unidad canonica es `broker_order_id`; fragmentos, senales, candidatos,
  recomendaciones y planes conservan denominadores separados.
- Persistencia append-only por sesion, hash estable fuera de `captured_at`,
  idempotencia y conflictos auditables. No hay tablas, migraciones ni backfill.
- `performance_daily`, digest, health y CLI consumen exclusivamente el evento
  canonico ya construido. La ruta activa de trading, P-L43, P-L44, P-L45 y
  P-L47 no cambia.

## P-L48BR1 - QA adversarial y ensayo de integracion de P-L48B (0.4.185)

- Ensayo en worktree dedicado desde `acc6e29a` con merge `--no-ff` del
  candidato exacto `40c05a2d`; commits QA separados (`b3155389`, `919f58b6`,
  `77d2e743`); produccion intacta y sin despliegue.
- Verificados con contadores: fuente unica (1 construccion/1 persistencia por
  PMR), orden postmarket P-L47, fail-open completo, idempotencia append-only,
  unidad canonica adversarial, atribucion ANET y matriz de salidas,
  denominadores separados en `performance_daily`, reconciliacion, freshness
  en segundos (8604,54 s ≈ 143,4 min) sin gates, volumen (1.000 senales /
  100 operaciones / 2 sesiones), lectores y estados, y paridad
  P-L43/P-L44/P-L45/P-L47.
- Defectos del candidato corregidos en el ensayo con commit QA separado:
  centinela `_MISSING` truthy en identidad/fallbacks (D1), digest global que
  ocultaba el snapshot valido tras conflicto (D2) y `candidate_count`
  excesivamente estricto (D3). Defecto preexistente de
  `profitability_scoreboard` con `pnl_pct` NULL documentado para el backlog
  (reproducido contra `acc6e29a`; no lo causa P-L48B).
- Suite 1689 passed; Ruff, `check_no_nulls.py`, `git diff --check` y
  `validate-agent-config` en verde. Dictamen:
  `ready_for_closed_market_deployment`. Detalle en `docs/P-L48_informe.md`.
- Backlog: corregir `_max_drawdown_from_returns` para ignorar valores NULL
  (defecto preexistente de scoreboard); valorar en otro lote si
  `reconciliation_terminal_at` entra en el contrato v2 de telemetria.

## P-L48BD - despliegue cerrado de P-L48B en produccion (0.4.185). **HECHO**

- Auditoria previa P-L48BD-P (`single_logical_stack_launcher_runtime_chains`):
  una unica cadena logica por servicio, launcher venv → runtime Python base;
  el `scheduler.lock` v1 pertenece al runtime APScheduler hijo del launcher
  `.venv`, no al launcher. No se "normalizo" la topologia.
- Precondiciones verificadas con XNYS cerrado: 17-jul terminal `completed`;
  18/19-jul `skipped/market_not_ready` (historial); `post_market_coordination:active
  = None`; paper/live-off/auto-apply-off; kernel sellado; `validate-agent-config`
  `ok=true`; `adaptive_config.json` SHA-256 exacto; HTTP 200/200.
- `scripts\stack_down.ps1 -IncludeScheduled`; merge `--no-ff` de
  `266950a0fc363e87a8bda706d30fbe0239ee95b4` en produccion, commit
  `8cfa0db30ffeae7ae1da8a5dc818d29785b80d08`, tree funcional
  `4c3636be2b6a6c4921e57de3f81ef490cbebbbbf` identico al ensayo, sin conflictos,
  sin squash/rebase/amend. Commits del ensayo conservados.
- Validacion con stack detenido (sin tocar SQLite productiva): baterias
  P-L48BR1 + P-L48B-T/W (111 passed), focales scheduler/storage/postmarket/
  performance/reconciliation/execution/digest/health/CLI y P-L43/P-L44/P-L45/
  P-L47 (verdes), suite completa ≈1693 passed/0 fallos, Ruff limpio,
  `check_no_nulls.py` OK, `git diff --check` limpio, `validate-agent-config`
  `ok=true`, `kernel-status` sellado sin violaciones.
- `scripts\stack_up.ps1`; dos comprobaciones: HTTP 200/200, unico listener 8501,
  lock v1 PID 49096 token `134289557074352030` coincide con el runtime real,
  `post_market_coordination:active = None`, 0 ordenes desde el reinicio,
  0 `database is locked`, health `warning` con 0 alertas criticas.
- Bootstrap: `terminal:skipped` reason `market_not_ready` unico; no reprocesa
  17-jul, no repite reconciliacion/outcomes, no crea telemetria/ordenes ni lease.
- Estado P-L48B inicial sin backfill: CLI/digest/health `collecting`,
  denominadores `null`, 0 eventos canonico en SQLite, sin reconstruccion
  heuristica.
- P-L43 `legacy_calendar_days` activa; P-L44 `legacy_double_application` activa
  (`single_application` shadow); P-L45 batching 250 y outcomes unicos; P-L47
  lock/lease v1 con token coherente. Deuda `profitability_scoreboard` no
  corregida (backlog). Detalle en `docs/P-L48_informe.md`. Dictamen: `deployed`.

## P-L50BR1 - ensayo combinado secuenciado (pendiente de validacion cerrada)

Secuencia del worktree: P-L49B `0.4.186`, P-L46BR3 `0.4.187`, P-L50B
`0.4.188`. QA focal: 675 passed; interacción nueva: 10 passed. Ambos shadows
son fail-open, append-only e independientes. Suite completa, smoke y validación
de despliegue quedan pendientes con XNYS cerrado.

### Cierre QA P-L50BR1 (20-jul-2026)

- Base y aislamiento: `24537e81`; worktree `pl49_pl46_pl50_combined_rehearsal`;
  rama `codex/pl49-pl46-pl50-combined-rehearsal`.
- Merges `--no-ff`: `0f5a26a0` <- `753136fc`, `17b5fbc7` <- `a0ab7ce4`,
  `045288dd` <- `8ebac5f2`, en ese orden. QA: `c99cd318`.
- Baterías permitidas: 90 + 84 + 211 + 290 = **675 passed**. Ruff completo,
  `check_no_nulls.py` (405 archivos), `git diff --check` y
  `validate-agent-config --json` aislado (`ok=true`) verdes.
- P-L49/P-L50 no comparten identidad ni autoridad; los planes, controles,
  gates, cantidades, precios, stops/takes, órdenes, exposición y límites del
  camino activo permanecen sin mutación. P-L46BR3 es solo lectura.
- Suite completa, smoke, jobs reales, prueba histórica de 33.336 filas y
  despliegue quedan pendientes para mercado cerrado. Dictamen:
  `ready_for_closed_market_full_validation`.
## P-L57A - continuidad null-safe del cierre postmarket y scoreboard (0.4.193)

- Base exacta: producción `24537e813ff0905696cda0b3925a212045ee7b09`, tree
  `4747f27f3d5dc152410203bf089baee500440897`, versión `0.4.185`. Worktree
  aislado `pl57a_pmr_null_safety`, rama `codex/pl57a-pmr-null-safety`.
- La reproducción contra la base confirmó que `pmr_dbfa382016b8` del
  23-jul terminó en `stage_postmarket_report_failed` por
  `TypeError("'<' not supported between instances of 'NoneType' and 'int'")`:
  `profitability_scoreboard._performance_summary` pasaba `pnl_pct=NULL` a la
  reducción de drawdown. La fila incompleta no era una razón para abortar el
  terminal del PMR.
- El contrato corregido rechaza null, bool, strings no numéricos, NaN e
  infinitos en métricas numéricas; reduce solo observaciones válidas; cuando
  no hay valores devuelve `null` y cobertura `unavailable`, y cuando hay una
  parte devuelve cobertura `partial`. No rellena `previous_equity`, retorno,
  alpha, costes, flujos ni drawdown; tampoco reconstruye ni hace backfill del
  23-jul. `result_metrics` del payload no sustituye columnas SQL ausentes.
- `performance_daily`, `profitability_scoreboard`, `promotion_readiness`,
  digest semanal y la serie read-only de web conservan filas válidas y
  continúan con resultado parcial auditable. La ruta de trading, PMR activo,
  reconciliación, ranking, gates, sizing, planes, órdenes, exits, exposición
  y límites no cambia.
- Commits: `5d05092c` reproducción; `12684790` corrección; `6ddf93da`
  actualización de la expectativa de primera sesión; `ee9afee6` documentación.
  La suite cerrada terminó `1698 passed, 1 skipped`; el único skip es el test
  legado `test_score_study_regression_current_sqlite`, que requiere la SQLite
  local ausente del worktree. Ruff, NUL, diff, configuración y version policy
  pasan. El dictamen es `ready_for_integration_rehearsal`.
- Siguiente paso único: ensayo de integración aislado P-L57A; no desplegar ni
  hacer backfill hasta validar el candidato con las precondiciones de mercado
  cerrado.

## P-L46B - orden cronologico de Cartera abierta (desplegado 0.4.178)

- El orden anterior mostraba primero las posiciones con mayor valor absoluto de
  P/L en dolares, mezclando ganadoras y perdedoras.
- El candidato ordena por el ultimo fill de compra verificable, de mas reciente
  a mas antiguo, y muestra su fecha y hora en la zona local configurada.
- Las posiciones sin un fill de compra verificable quedan al final como
  `Fecha de compra no disponible`; no se usa la fecha de creacion de una orden como sustituto.
- Es un cambio exclusivamente visual. No altera posiciones, trading, ranking,
  gates, stops, takes, cantidades ni ordenes.
- P-L50T (20-jul, caracterizacion aislada): worktree sobre produccion 0.4.185,
  solo fixtures/pruebas e informe, sin cambios en `src/` ni politicas activas.
- Dictamen tecnico: `mixed_contract_gap`; P-L44 fase A recibe un contexto sin
  IDs mientras la ruta de recomendacion los completa despues, con scores/prior
  y controles no uniformes.
- P-L50B queda reservado como shadow-only, minimo 0.4.188; P-L50T no cambia
  version ni autoriza activacion de aprendizaje.
- P-L50B implementado en candidato `0.4.188`: la identidad se prepara antes de
  ranking y la fase A consume una proyección inmutable del mismo contexto
  enriquecido. El contrato P-L44 v2 separa identidad, inputs, decisiones,
  controles, rechazos y freshness sin modificar el camino activo. Estado:
  `ready_for_integration_rehearsal`; queda pendiente la validación completa fuera
  de mercado. P-L49B conserva `0.4.186` y P-L46BR3 conserva `0.4.187`.
- Secuencia desplegada: P-L45B2 `0.4.175`, P-L43BR5 `0.4.176`, P-L44B
  `0.4.177` y este cambio UI `0.4.178`. El merge productivo es `4158ac5f`;
  la verificación visual confirmó la versión y el orden descendente.

## P-L49BR1 — estado del ensayo (0.4.186)

- Ensayo aislado fusionado desde `24537e81` con candidato `938580b7`:
  merge `2ea57983`; QA adicional `b8aee78a` y `db6577b2`.
- La captura de calidad sigue siendo observabilidad shadow. Sin provenance OHLC
  exacta en el objeto que alimentó features, los candidatos identificados se
  clasifican `unavailable_temporal`/`partial`; no se aplican informes
  posteriores ni bloqueos retroactivos.
- Pendiente: suite completa, smoke y validación de 33.336 observaciones con
  XNYS cerrado. No habilitar gates ni iniciar P-L48C.
## P-L46BR3 - resultado de cartera coherente con el rango visible (candidato 0.4.187)

- Causa: la tarjeta `P/L desde abril` procedia del historial de operaciones,
  mientras la grafica representa equity de cuenta. La mezcla podia publicar
  una ganancia positiva sobre una curva descendente.
- La tarjeta pasa a llamarse `Resultado del periodo` y se calcula como ultimo
  equity menos primer equity del rango seleccionado; muestra porcentaje y
  fechas de ambos extremos. `Desde inicio` solicita todo el historial
  disponible y conserva el corte operativo del 28-abr-2026.
- Se elimina de este bloque el duplicado `P/L hoy`; permanece en la cabecera.
  El segundo y unico KPI del bloque es `P/L abierto`, sumado desde las
  posiciones actuales ya cargadas, sin otra consulta al broker.
- La cabecera `Cuenta · desde inicio` y el control externo usan la misma
  variacion de equity completa. Sin datos suficientes se muestra `-`, nunca
  un cero inventado.
- Cambio exclusivamente de presentacion y lectura. No altera trading,
  ranking, gates, sizing, planes, ordenes, stops, takes, exposicion, SQLite ni
  runtime state. P-L49 conserva `0.4.186`; este lote reserva `0.4.187`.

## P-L51C-W - carrier futuro BUY -> SELL (candidato 0.4.189)

- Implementada en worktree aislado la frontera `P-L43BR6 open lots -> order_plan
  metadata -> broker_order local -> reconciliation -> P-L48/P-L51`.
- El carrier `p-l51c.exit-lot-provenance.v1` usa solo IDs y cantidades exactas,
  es append-only/idempotente/conflict-safe y fail-open; no entra en el request
  del broker ni en autoridad de riesgo o ejecucion.
- Evidencia Store temporal: BUY/SELL exactos, un lote cerrado, atribucion 1,
  gross 100.0 y net 98.5 con costes completos; costes parciales dejan net
  null; historicos sin carrier permanecen unavailable.
- Commits separados: `c86917ee` funcional y `5c0077d9` pruebas. La
  documentacion de este estado queda en `docs/P-L51_informe.md` y en este
  plan; la validacion completa, suite, smoke y despliegue esperan XNYS cerrado.
## P-L51CV2 - validacion completa nocturna del candidato 0.4.189 (21-jul-2026)

- Con XNYS cerrado, PMR `pmr_7a4f5b7f8f4b` terminal y lease vacio, la suite
  completa paso `1864 passed, 1 skipped` y las focales/regresiones pasaron
  `364 passed`. P-L45B2 de 33.336 filas paso `1 passed`.
- Ruff, NUL, diff y `validate-agent-config --json` temporal quedaron verdes.
  El smoke real `run-once` queda `smoke_unavailable_by_safety`; el sustituto
  aislado paso 8 pruebas. No se anadio skip/xfail.
- Dictamen: `ready_for_closed_market_deployment`. No hubo despliegue ni push;
  la promocion requiere una tarea separada y autorizacion operativa.
## P-L52B-T — snapshot EOD contable y benchmark comparable (21-jul-2026)

- Worktree de tests: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52b_eod_snapshot_tests`,
  rama `codex/pl52b-eod-snapshot-tests`, base P-L51CV2
  `7638149610060153dfe8a8edf2037ad9dab028a3`.
- Contrato caracterizado: `p-l52b.canonical-eod-account-snapshot.v1`.
  Separa equity, flujos, realized neto, open P/L, costes, exposición, cash,
  benchmark SPY comparable y residual; missing permanece null/unavailable.
- Tests P-L52B-T `21 passed`; focales `248 passed`; Ruff/NUL/diff/configuración
  verdes. Sin cambios en `src` ni bump de versión.
- Dictamen: `ready_for_p52b_implementation`. Siguiente lote mínimo: productor
  shadow fail-open del snapshot con ledger de flujos y benchmark autorizados;
  no cambiar trading, política, UI ni producción.

## P-L52B-W — implementación shadow EOD contable (candidato 0.4.190)

- Worktree aislado: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52b_eod_snapshot_impl`;
  rama `codex/pl52b-eod-snapshot-impl`; base P-L52B-T `609183e1`.
- Implementados el módulo `canonical_eod_account_snapshot`, evento
  `canonical_eod_account_snapshot:<session_date>`, persistencia append-only,
  lector/digest/health/CLI y stage PMR después de P-L48/P-L51 y antes de
  performance. La ruta activa y los archivos protegidos permanecen intactos.
- Commits: `57ec7b7f` feature, `eb17d582` tests, `4e868109` QA de freshness.
  Las 32 pruebas del lote pasan y Ruff/diff también.
- Dictamen: `ready_for_integration_rehearsal`. Antes de cualquier promoción
  deben verificarse con XNYS cerrado el PMR terminal, suite completa, P-L45B2,
  smoke aislado seguro, configuración/kernel y paridad final. No cambiar
  thresholds, sizing, ranking, gates, stops, política ni producción.

## P-L52BR1 — ensayo integrado P-L51C + P-L52B (candidato 0.4.190)

- Worktree/rama: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52br1_integration_rehearsal`,
  `codex/pl52br1-integration-rehearsal`, base `76381496`.
- Merge `--no-ff` P-L52B-W: `36bdd366`; correccion QA separada: `932c648a`.
- Se verifico reconciliation -> P-L48 -> P-L51 -> P-L52 -> performance ->
  measurement -> thesis -> terminal, con una sola construccion/persistencia y
  reutilizacion del objeto P-L52.
- La QA E2E corrigio la perdida de allocations exactas P-L51 en P-L52. El fix
  conserva IDs de lote y deja null cualquier importe que no sea explicito;
  multi-lote no se prorratea. No cambia trading ni request broker.
- Resultado: `1899 passed, 1 skipped, 1 warning`; P-L45B2 33.336 incluido y
  pasado; QA nueva 3 y volumen 100 sesiones/1000 operaciones sin locks. Ruff,
  NUL, diff y config verdes. Smoke CLI queda `smoke_unavailable_by_safety`;
  sustituto PMR aislado verde.
- Dictamen: `ready_for_closed_market_deployment`, sin despliegue ni push. La
  promocion requiere tarea operativa separada, preflight nuevo y autorizacion
  humana; produccion/candidatos originales permanecen intactos.
## P-L51CR2 - correccion de regresiones temporales de provenance (22-jul-2026)

- Worktree aislado desde P-L52BR1: `pl51cr2_exact_provenance_fix`, rama
  `codex/pl51cr2-exact-provenance-fix`, base `134ec525`, version conservada
  `0.4.190` porque no hubo cambio en `src/`.
- Los tres fallos heredados compartian una fixture sin reloj congelado:
  `created_at` caia el 22-jul mientras la sesion consultada era 21-jul. El
  productor P-L48 filtraba correctamente; no se perdio carrier en produccion.
- Commits separados: `9a7b46d2` caracterizacion y `494e6515` correccion de las
  fixtures. Los tres tests pasan; focales `239 passed`; suite segura
  `1900 passed, 1 deselected`.
- Ruff/NUL/diff/configuracion/kernel productivo y P-L45B2 verdes. No se
  modificaron archivos protegidos, produccion, servicios, SQLite productiva ni
  candidatos. No hubo despliegue ni push.
- Dictamen: `ready_for_reintegration`. Siguiente lote unico: reintentar
  P-L53BR1 sobre este fix como candidato posterior 0.4.192.

## P-L53B-W - ledger canónico shadow de selección por ciclo (candidato 0.4.191)

- Implementado en `pl53b_selection_ledger_impl`, rama
  `codex/pl53b-selection-ledger-impl`, desde la base exacta P-L53B-T
  `4ec81a0c`. Reserva funcional `0.4.191`.
- Captura el universo completo de fase A y los objetos exactos de
  recomendaciones, gates, planes y órdenes de fase B. `signal_capture_id`
  prevalece sobre `signal_id`; símbolo/fecha y `source_run_id + symbol` no son
  identidad.
- Persistencia append-only en `agent_events`, hash estable sin `captured_at`,
  `BEGIN IMMEDIATE` corto, idempotencia y conflictos separados. Fail-open y
  sin autoridad sobre trading.
- Commits: `e5ace319` feature y `eea3794a` tests/paridad. Documentación
  consolidada pendiente del commit documental P-L53B-W.
- QA focal P-L53B-T/W: 28 passed; suite completa y smoke quedan pendientes
  para mercado cerrado con precondiciones operativas verificadas. Siguiente
  lote único: ensayo integrado P-L53BR1 aislado.

## P-L53BR1 - ensayo integrado P-L53B-W sobre P-L52BR1 (22-jul-2026)

- Worktree `pl53br1_integration_rehearsal`, rama
  `codex/pl53br1-integration-rehearsal`, base exacta `134ec525`; merge
  `fc4eb767` con `--no-ff`, versión final `0.4.191`.
- Se comprobó la ruta de mercado P-L49/P-L50/P-L53 y el PMR P-L48/P-L51/P-L52.
  P-L53 reutiliza el contexto rankeado y finaliza después del envío activo,
  sin autoridad sobre trading ni entrada en el pipeline PMR.
- QA integrada y volumen 100x500 verdes; la suite segura final obtuvo
  `1928 passed, 4 deselected`. Las cuatro exclusiones son el test de SQLite
  productiva y tres fallos heredados reproducidos en el padre P-L52BR1; no se
  añadieron skips/xfails.
- Ruff, NUL, diff, versión, configuración y kernel productivo sellado verdes.
  Producción, SQLite productiva, servicios y candidatos originales intactos;
  no hubo despliegue ni push.
- Dictamen del ensayo: `needs_fix` por la deuda heredada P-L51/P-L51C.

## P-L53BR2 - reensayo limpio de P-L53 sobre P-L51CR2 (22-jul-2026)

- Base `2da5ccda`, tree `cdf34263`; merge `--no-ff` `3b2ae0bf` desde P-L53BR1.
  Worktree `pl53br2_integration_rehearsal`, rama
  `codex/pl53br2-integration-rehearsal`, version final `0.4.191`.
- Gate de las tres fixtures temporales: `3 passed`. QA adicional
  `2bb92a4b`/`165ad748`; fixture concurrente estabilizada en `ff6267a0`, sin
  cambio en src.
- P-L53 conserva la ruta shadow y queda fuera del PMR; identidades, cap,
  truncation/maturity, fail-open y paridad verificados.
- BR2: 100x500 mas escalas 250/500/1000; 109 eventos/conexiones/transacciones,
  uno por ciclo; evento p50/max `757177`, memoria pico `17066653`, WAL `0`,
  shadow p50 `511.6280 ms`. Riesgo `medium` por tamano/latencia, con
  persistencia despues del envio y sin locks.
- Suite final: `1933 passed, 1 deselected, 1 warning` en 753.78 s, incluyendo
  P-L45 de 33.336 filas. Unico deselect:
  `tests/test_pre_earnings.py::test_score_study_regression_current_sqlite`,
  que abre SQLite productiva; no se anadieron skips/xfails.
- Smoke real queda `smoke_unavailable_by_safety`. Sin produccion, SQLite
  productiva, servicios, reinicio, despliegue ni push.
- Dictamen: `ready_for_closed_market_deployment` como candidato no desplegado;
  siguiente paso unico: preflight operativo y autorizacion humana.
  Siguiente lote único: corregir esos tres focales y repetir la suite cerrada;
  P-L53 permanece shadow y no se cambia política de trading.

## P-L54B-W - embudo shadow de despliegue de capital

- Candidato aislado 0.4.194 desde `20e8be04`; productor fail-open con evento
  `capital_deployment_funnel_shadow:<cycle_id>` y persistencia append-only.
- Observa la ruta activa sin recalcular selección, gates, capacity, sizing,
  RiskManager, planes u órdenes. Identidad exacta por ciclo/señal/acción; no
  joins por símbolo/fecha.
- Denominadores y notional conservan cobertura, `null/unavailable`, razones
  primarias exclusivas y estado de truncation. Target exposure queda
  unavailable sin autoridad estructurada.
- Focales P-L54B-T/R1/W: 33 passed; suite completa, smoke y prueba larga quedan
  pendientes del ensayo integrado cerrado P-L54BR1.

## P-L54B-R1 - correccion de identidad de decision (0.4.194)

- La colision `cycle + signal + action` se reprodujo contra P-L54B-W y se
  corrigio incorporando `recommendation_id` cuando existe.
- Decision parcial, ambigua, conflicto de contenido y ciclo inconsistente
  quedan separados de stages/notional evaluables; no se usa `candidate_id` ni
  symbol/date como sustituto.
- Worktree `pl54br1_decision_identity`, rama
  `codex/pl54br1-decision-identity`; commits `de08b9fd`, `8d814934` y
  `3f85071f`; version `0.4.194`.
- QA focal verde; suite completa, smoke y ensayo P-L54BR1 quedan pendientes con
  XNYS cerrado y precondiciones operativas comprobadas. No desplegar.

## P-L54BR1-Retry - estado del ensayo integrado (27-jul-2026)

- Merge aislado `8574a227` sobre P-L58R1, version final `0.4.194`, tree
  `ff42c750`; produccion permanece en `0.4.185`.
- XNYS estaba abierto al iniciar la QA; se ejecutaron solo focales y gates
  estaticos: `330 passed`, Ruff/NUL/diff/configuracion verdes.
- La ruta, identidades, fail-open y denominadores P-L54 se mantienen; target
  exposure/undeployed notional siguen unavailable.
- Suite completa, P-L45 33336, smoke y benchmark combinado quedan pendientes
  para mercado cerrado. Dictamen: `ready_for_closed_market_full_validation`.
## P-L46BR4 - filtro calendario del grafico de cartera (candidato 0.4.195)

- Corregido el filtro para usar limites de fecha y no cantidad de filas; las
  sesiones XNYS pueden dejar menos puntos que dias naturales.
- Ventanas disponibles: 7, 15, 30, 90 y `Desde inicio`. La serie filtrada es
  la unica fuente de grafica, Resultado del periodo, porcentaje y fechas.
- Reproduccion y fix en worktree aislado; 75 pruebas UI verdes. Suite completa,
  smoke y validacion cerrada siguen pendientes con XNYS abierto.
- No cambia trading, riesgo, broker, persistencia ni consultas adicionales.

## P-L60R1 - ensayo integrado UI sobre P-L54BR1 (27-jul-2026)

- Merge aislado `489b229f` en `pl60r1_ui_measurement_integration`, version
  final `0.4.195`, tree `5f3afdc7`. P-L46BR3 ya estaba en la base y no se
  duplicaron helpers ni widgets.
- El selector unico ofrece 7/15/30/90/`Desde inicio`; la serie calendario
  filtrada se reutiliza para grafica, Resultado del periodo, porcentaje y
  fechas. P/L abierto mantiene las posiciones cargadas y no hay broker extra.
- QA: `83 passed` UI/version y `159 passed, 1 warning` relacionados. Ruff,
  NUL, diff, py_compile y configuracion temporal verdes. XNYS abierto impide
  suite completa, smoke y validacion cerrada; sin cambios de trading ni
  despliegue. Se conserva `unconfirmed_sqlite_mutation` como incertidumbre.

## P-L59B-T-R5 (final) - caracterizacion cerrada (27-jul-2026)

- Dictamen: **`needs_fix`**. XNYS abierto. Hora real: 19:43 CEST. HEAD: `a48113fe`.
- 27 tests P-L59 + 5 integracion (32 total). Ruff/NUL/diff verdes.
- Stage order: rama 2399/2412 (con submit). plan_id nace en plan_records, no
  en OrderPlan (modelo real). Identidades: symbol+side+decision_lineage.
  Sin object.__setattr__ ni campos inventados.
- Seccion stale 2255/2266 eliminada del informe. Caracterizacion cerrada.
- Siguiente: P-L59C (no iniciado).

## P-L59C-R6 - autoridad prospectiva estructurada de llm_selected (27-jul-2026)

- Dictamen: **`ready_for_integration_rehearsal`** (R6 corregido). XNYS abierto, 20:30 CEST.
- R6: list branch inside_dcs=False (items nested conservan hashes). Test unitario listas.
  Docs con hashes R5 (`4b1c1982`, `c50f23ae`). R2 baseline 278. R6: 15 integration.
  Ruff/NUL/diff verdes.
- Brecha P-L53 recommendation_id sigue abierta.
- Siguiente: P-L59D rehearsal de integracion.

## P-L59D - rehearsal de integracion (27-jul-2026)

- Dictamen: **`ready_for_closed_market_full_validation`**. XNYS abierto, ~21:32 CEST.
- Merge `--no-ff` de P-L59C-R6D (`30b6b76b`, v0.4.196) sobre P-L60R1 (`70de3401`, v0.4.195).
  Sin conflictos. HEAD final `4524cbe3` (tree `661216b3`); merge `9009c7f2` (tree `ad69264e`, identico a P-L59C-R6D).
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59d_llm_selected_rehearsal`,
  rama `codex/pl59d-llm-selected-rehearsal`.
- 5 protegidos versionados identicos contra base y produccion; .env no modificado (hash unavailable). Ruta activa P-L60R1 intacta.
- QA focal: 300 passed (10 archivos) en 65.53s. Ruff/NUL/diff/py_compile/validate-config verdes.
- Brecha P-L53 recommendation_id sigue abierta.
- Gates omitidos (XNYS abierto): suite, smoke, benchmark, P-L45 33.336, kernel.
- Siguiente: P-L59E validacion cerrada completa (requiere XNYS cerrado).

## P-L59F-T-R3 — caracterizacion final, contrato cerrado (27-jul-2026)

- Dictamen: **`ready_for_implementation`**. XNYS cerrado (22:00 CEST),
  pero postmarket no terminal y continuous_improvement running.
  P-L59E bloqueado; no operacion cerrada.
- Base: P-L59D-D `520559c6` (tree `e3c80ba`, v0.4.196).
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59ft_recommendation_identity_design`,
  rama `codex/pl59ft-recommendation-identity-design`.
- HEAD tests R3: `e14caa1e`. Solo tests/docs, sin cambios en src.
- R3: lineage literal identico en rec1/rec2, adjuntos P-L53 (plans/plan_records)
  y P-L54 (recommendations/plans) con IDs coherentes, stage P-L53<P-L54 explicito,
  `_denominators` real en expansion con raw_count=1.
- 17 tests pasan (0.90s). Ruff/NUL/diff verdes.
- Contrato de implementacion completo en informe.
- Siguiente: P-L59F-I (requiere verificar precondiciones XNYS antes de iniciar).

## P-L59F-T-R4 — cierre de diseño. HECHO.

- Dictamen de direccion: `ready_for_implementation`.
- HEAD `224b4958`, tree `135df124`, v0.4.196, limpio.
- 17 tests verdes. Contrato decision_rows completo en informe único.
- P-L59E sigue bloqueado por precondiciones.

## P-L59F-I-R1 — implementacion decision_rows v2 corregida. HECHO (v0.4.197).

- El candidato inicial `305b56ee` quedo `needs_fix`; el worker fue
  interrumpido durante R1 y sus cambios parciales se revisaron antes de
  continuar.
- Dictamen corregido: `ready_for_integration_rehearsal`.
- Worktree/rama: `pl59fi_decision_rows`, `codex/pl59fi-decision-rows`.
- Base `224b4958`, tree `135df124`, version `0.4.196`.
- Candidato version `0.4.197`; correccion funcional/QA `1ce3c155`, tree
  `ed1e6879`.
- Solo `canonical_selection_ledger.py` (+449/-43) y `__init__.py`.
  Sin cambios en cycle_runner, storage, protegidos, config, politica.
- SCHEMA_VERSION `p-l53b.canonical-selection-ledger.v2`. candidate_rows
  summary 8 estados. decision_rows por identidad exacta. Bounded 600.
  Denominadores v2. Reader backward-compatible v1.
- 169 passed en la bateria focal disjunta; Ruff completo, NUL y diff verdes.
- Se separan conflictos de duplicados idempotentes, se cuentan denominadores
  pre-truncado y se exigen candidato/linaje exactos para recomendaciones y
  adjuntos.
- Brecha P-L53 recommendation_id: CERRADA.
- Gates omitidos: suite, smoke, benchmark, P-L45, kernel (precondiciones).
- Siguiente: P-L59F-D rehearsal `--no-ff` y validacion cerrada completa; sin
  despliegue automatico.

## P-L59F-D — ensayo integrado cerrado. HECHO (v0.4.197).

- Merge `--no-ff` `f535923f` sobre P-L59D-D; QA `e0290762` y `2f156eb8`;
  tree funcional `f8193f6d`.
- Suite completa: 2184 passed, 1 skip y 1 warning preexistentes. Ruff, NUL,
  diff y configuracion verdes; kernel productivo sellado y protegidos iguales.
- Benchmark v2: 500 candidatos, p95 total 649.32 ms, 840,943 bytes/evento,
  memoria pico 17.2 MB. Riesgo de volumen medio; shadow/fail-open.
- Dictamen: `ready_for_closed_market_deployment`, pero el despliegue no esta
  autorizado. Smoke real omitido por seguridad al no existir proveedor
  sintetico CLI garantizado.

## P-L63 - baseline de equity desde el 1 de abril. HECHO (v0.4.198)

- Base `8c66f966`, worktree `pl63_portfolio_april_baseline`, rama
  `codex/pl63-portfolio-april-baseline`. Reproduccion `2d17df99`, pruebas de
  aceptacion `0728a113`, fix `cad229af`.
- Se elimina la divergencia 28-abr frente a `DEFAULT_START_DATE=2026-04-01`.
  La unica llamada de portfolio history usa `period="all"`; Cuenta, grafica y
  Resultado usan equity real, primer/ultimo punto, porcentaje, fechas, source
  y coverage coherentes. No se reconstruye desde realized/unrealized trades.
- Falta el punto del 1-abr: `partial` con primera fecha real o `unavailable`.
  P/L hoy y P/L abierto siguen separados del baseline historico.
- QA focal `101 passed`; Ruff/NUL/diff/py_compile/config temporal verdes.
  Suite completa, smoke y validacion cerrada quedan pendientes fuera de esta
  ventana. No cambiar trading ni desplegar.

### P-L63 — semántica UX de equity y ventana desde junio (28-jul-2026)

- Se reprodujo la segunda manifestación: equity `71.550 -> 70.700` junto a
  `trade_history.total_pl=+106,83` producía una tarjeta verde incorrecta.
  El resultado visible ahora es `-850,00`, aproximadamente `-1,19%` sobre el
  primer equity, y el tono depende solo de ese signo.
- La tarjeta y la cabecera usan `Resultado del periodo`/`Variación de equity`,
  las fechas reales y la misma serie filtrada que la gráfica. P/L hoy y P/L
  abierto permanecen fuera del baseline histórico. Se añadió la ventana
  explícita `Desde 01/06/2026`; no se infiere “desde junio” desde trades.
- Commits del incremento: `50976dfe` y `22609ba3`; versión permanece
  `0.4.198`. QA focal `103 passed`; Ruff, NUL, diff, py_compile y config
  temporal verdes. Suite completa, smoke y validación cerrada pendientes por
  premarket/XNYS. Sin cambio de trading ni despliegue.

### P-L63R1 — corrección diaria y tooltip del gráfico (28-jul-2026)

- El porcentaje 2,10% sobre exposición (190,42 / 9.078,06) se eliminó
  como métrica principal. La cuenta publica la variación diaria de equity
  sobre el cierre anterior (0,27% en la evidencia), independiente de la
  exposición. Sin equity previo queda n/d; no se reconstruye con exposición.
- El copy es Variación de equity hoy y variación de equity desde el cierre
  anterior; no se afirma rentabilidad desde apertura ni se presenta la serie
  diaria como intradía. P/L abierto y resultado histórico siguen separados.
- El tooltip del baseline Sistema/SP500 está explícito en línea y puntos:
  Fecha, % ganancias, Serie, mismo campo retorno_acumulado y formato +.2%.
  No cambia el eje, los valores, la fuente ni los indicadores.
- QA focal 106 passed; Ruff, NUL, diff, py_compile y config temporal verdes.
  Suite completa, smoke y benchmark largo quedan pendientes por XNYS abierto.
  Versión 0.4.198; commits 12a6cb11, bef256d6, 031597c7, 89adde7f
  y fb2c47a7. Sin cambios de trading ni despliegue.

### P-L65B — UI coherente Sistema vs SP500 (28-jul-2026)

- Candidato aislado `0.4.200` sobre P-L65A-R1 `53b49f71`.
- Implementa una fila diaria canónica desde `performance_benchmark`, con
  equity primaria, SPY de dos cierres, source/basis/as_of/freshness y estados
  pending/unavailable. El selector 7/15/30/90/Desde inicio recorta un único
  rowset de sesiones para tabla, contadores y gráfico.
- El 2,39% sobre exposición queda descriptivo; no decide el ganador. Sin
  ledger de flujos el copy es variación de equity.
- QA focal `129 passed`; no se ejecutaron suite completa, smoke o benchmark
  largo por XNYS abierto. Sin producción, broker, red, SQLite productiva,
  despliegue o push.
- Dictamen provisional: `ready_for_integration_rehearsal`. Siguiente trabajo:
  ensayo combinado aislado P-L63/P-L65B, con P-L66 fuera de este lote.
## P-L66 - Telegram (candidato 0.4.201)

- Resumen diario 22:05 Europe/Madrid y fallback postmarket, ambos idempotentes.
- Avisos de BUY/SELL al fill reconciliado; P/L SELL solo con `source_plan_id`
  exacto. Pendiente ensayo integrado y despliegue autorizado con XNYS cerrado.

## P-L68 - gráfica Sistema vs SP500 visible y comparable (v0.4.202)

- Causa raíz: yfinance usaba `auto_adjust=True` sin persistir la base de
  precio; el lector invertía la latencia de una barra diaria y descartaba
  todos los valores cuando las filas eran `pending`.
- Las nuevas capturas declaran `adjusted_ohlc`; `as_of` diferencia precisión
  diaria e instantánea. Los históricos incompletos se dibujan como
  provisionales, pero no deciden ganadores.
- El acumulado compone retornos diarios en lugar de sumarlos.
- Suite completa: 2249 passed, 1 skip y 1 warning preexistentes; estáticos,
  configuración y kernel verdes.
- Dictamen: `ready_for_integration_rehearsal`. Sin despliegue.

## P-L69 - avisos Telegram de fills durante mercado abierto. EN COLA

- P-L66 actual avisa cuando la reconciliación detecta `filled`; no garantiza
  el instante real del fill.
- Diseñar un detector canónico durante sesión que persista primero el fill y
  publique después, fail-open e idempotente por `broker_order_id`.
- No enviar al mero submit. BUY incluye entrada real; SELL exige
  `source_plan_id` exacto para entrada, salida y P/L bruto.
- Lote separado, con revisión de paridad y de protegidos si toca
  broker/execution. Sin cambio de política.

## P-L68 - desplegado (28-jul-2026)

- Producción `0.4.202`, merge `18add124`, árbol funcional `68a7b4c5`.
- La gráfica Sistema vs SP500 muestra los valores históricos incompletos como
  provisionales discontinuos; solo datos comparables deciden ganadores.
- Nuevas capturas yfinance persisten `adjusted_ohlc`; no hubo backfill.
- Validación productiva: 2250 passed; Ruff, NUL, diff, configuración y kernel
  verdes; HTTP 200/200 en dos comprobaciones.
- Siguiente lote funcional: P-L69, separado y sin cambio de política activa.

## P-L67R1 - ensayo final P-L65B/P-L63 + P-L62 + P-L66

- Ensayo aislado `pl67_p65_p62_p66_deployment_rehearsal`, merge `d3a75c98`,
  HEAD final `62de5525`, versión 0.4.201.
- P-L62 fue preservado campo a campo; el panel dirty P-L61 no se copió porque
  P-L65B lo sustituye por el rowset canónico Sistema/SP500. Producción dirty
  permanece intacta y los untracked quedan fuera.
- Suite final: 2242 passed, 1 skip preexistente en
  `tests/test_pre_earnings.py:1041`; Ruff/NUL/diff/compile/config verdes.
  Smoke CLI real queda `smoke_unavailable_by_safety`; sustituto aislado verde.
- Dictamen `ready_for_deployment` sin autorización de despliegue en este lote.

## P-L72 - rendimiento apertura a apertura (29-jul-2026)

- Candidato `0.4.206` listo para despliegue cerrado.
- Sustituye el panel provisional P-L65/P-L68 por intervalos exactos:
  apertura XNYS T → apertura siguiente; sesión vigente → ahora.
- Cabecera, gráfica, contadores, tabla y Telegram comparten ventana y
  denominadores. La tabla queda ordenada de más reciente a más antigua y no
  muestra filas vacías o pendientes.
- Evidencia real: 27→28 cuenta +0,1569% frente a SPY -0,7679%; 28→preapertura
  29 cuenta aproximadamente -0,043% frente a SPY +0,2259%.
- Suite completa `2283 passed, 1 skipped`; Ruff/NUL/diff/config verdes.
- No cambia política ni rutas de trading. Pendiente despliegue autorizado y
  doble comprobación operativa.

### Estado final P-L72

- Desplegado en producción `0.4.206` mediante merge `50d959d7`, árbol funcional
  `b7eb971f`.
- Suite productiva `2284 passed`; Ruff/NUL/diff/config/kernel/smoke verdes.
- UI comprobada con siete valores visibles completos, tabla descendente y una
  única sesión vigente etiquetada `En curso`.
- Stack sano en dos comprobaciones; cero órdenes inesperadas y cero locks de
  SQLite. P-L72 queda cerrado.

## P-L73 - P/L total y diario en cartera abierta

- Candidato `0.4.207` en worktree aislado.
- La tabla muestra por posición `P/L total` y `P/L día`, cada uno en USD y
  porcentaje.
- Los cuatro valores proceden del mismo `PositionSnapshot` de Alpaca ya cargado;
  no hay segunda lectura de posiciones ni reconstrucción por símbolo.
- Missing intradía permanece `n/d`. El P/L diario de Alpaca no se confunde con
  el contrato apertura a apertura de P-L72.
- Focales relacionados: `129 passed`.
- Suite completa `2289 passed, 1 skipped`; Ruff, NUL, diff y configuración
  temporal verdes. Smoke sustituto aislado verde; CLI real no ejecutado por
  seguridad de proveedores.
- Dictamen: `ready_for_integration_rehearsal`; sin despliegue.

## P-L74 - autoridad de apertura SPY (candidato 0.4.208)

- Implementacion aislada: apertura incompatible = `conflict`; el current
  mutable usa la observacion valida mas fresca con provenance compatible.
- Productor dedicado fuera de UI, al final fail-open de `market_cycle_job`.
  Estados terminales: `inserted`, `available`, `idempotent`, `recovered`.
  Metadata sin `.pkl` legible sigue reintentable.
- Focales 17/17 y regresiones 131/131 verdes; suite completa y smoke quedan
  pendientes porque XNYS estaba abierto. No desplegar hasta ensayo cerrado.

## P-L69-W - avisos intradia de fills confirmados (candidato 0.4.209)

- Worktree `pl69_fill_watch_impl`, rama `codex/pl69-fill-watch-impl`, sobre
  P-L75 `08e8f8fa`/arbol `86a8b4d7`.
- Contrato provider-neutral: snapshot remoto por `broker_order_id` exacto,
  commit local `filled` y despues Telegram fail-open con claim/receipt
  append-only. El adaptador especifico queda confinado en `fill_provider.py`.
- Job separado `trade_fill_watch`, desactivado por defecto, cap 25, cadence 30
  s y backoff 30->300 s. No bloquea market_cycle/portfolio_watch ni cambia
  trading. Rejected/partial/pending no notifican; BUY/SELL exigen identidad y
  provenance exactas.
- Caracterizacion `581f6bfc`, implementacion `6bffedf2`, QA `9a689153` y fixes
  QA `fc9f7206`/`8e8da2c1`.
  Focales P-L69/Telegram/reconciliacion/scheduler/storage/P-L72-P-L75:
  115 pruebas verdes acumuladas. Suite completa y smoke quedan pendientes por
  XNYS abierto; no hubo broker, red, SQLite productiva ni mensaje real.
- Dictamen: `ready_for_closed_market_full_validation`. Siguiente paso: ensayo
  cerrado aislado y revision de paridad antes de cualquier integracion.

## P-L75 - ensayo combinado P-L73 + P-L74

- Merge `--no-ff` de P-L73 y P-L74 sobre producción 0.4.206, versión final
  0.4.208. Conflictos solo en versión/documentación, resueltos campo a campo.
- QA focal combinada verde; suite completa y smoke pendientes por XNYS abierto.
- Dictamen: `ready_for_closed_market_full_validation`. No desplegar todavía.

## P-L69-R1 - finalización downstream tras fill intradía (0.4.209)

- Reproducción contra `ca691275`: el watcher dejaba BUY terminal `filled` fuera
  de `_pending_orders`, por lo que PMR no aplicaba signal/learning ni attach de
  execution quality. El recibo Telegram no sustituye esa finalización.
- Fix `584575c1`: marcador durable `reconciliation_finalization` junto al
  snapshot local; terminales watcher pendientes se finalizan en PMR con
  `pending -> processing -> applied`, transacción corta e idempotencia frente a
  retry/restart/carrera. No se reabre el terminal ni se consulta otra transición
  remota.
- Tests R1 `31560cfb`, `0c121836`, `86b653ce`, `0909ea4b`; focales `133 passed`
  y R1 ampliado `18 passed`. Ruff/NUL/diff/py_compile/config aislado verdes.
- XNYS abierto: no suite completa, smoke, proveedor/red/Telegram real ni
  despliegue. Dictamen: `ready_for_closed_market_full_validation`.

## P-L69-R2 - endpoint proveedor y rollback de finalización (0.4.209)

- Reproducido contra `ce6f86af`: el SDK real entregaba enum
  `BaseURL.TRADING_PAPER` y el adaptador construía una URL inválida por usar
  `str(enum)` en vez de `.value`.
- Fix `de8b250e`: normalización y validación HTTP(S), preservando paper/live,
  timeout, headers, fallback por `client_order_id` y frontera provider-neutral.
- QA `f6c82f85`/`b819c540`: endpoint inválido fail-open sin transición ni
  Telegram; rollback de `processing` a `pending`; GET, fallback y live reales
  con sesión stub. Batería final `138 passed`; gates estáticos verdes.
- XNYS abierto: suite completa/smoke/operación real omitidos. Dictamen:
  `ready_for_closed_market_full_validation`.

## P-L76-CLOSE - despliegue validado

- Merge productivo `49d33e17`, árbol funcional `3f2b859b`, versión `0.4.210`.
- Suite merged `2340 passed`, 1 warning; focales `107 passed`; Ruff/NUL/
  compile/diff/config/kernel/smoke aislado verdes.
- XNYS cerrado, PMR 2026-07-31 terminal completed y lease activo ausente.
- `.env` solo recibió las seis claves TRADE_FILL_WATCH autorizadas; hash
  posterior `99907AA6E778F21FD535553845BA1BEF0607BB91E17F530E50951F2EC849AA58`.
- Health doble 200/200 separada por más de 75 s; watcher registrado y normal
  `skipped` por mercado cerrado; cero órdenes inesperadas y cero críticos.
- Estado: `deployed`. No push ni tareas nuevas.

## P-L76R1 - corrección del gate P-L54 y suite cerrada

- Fix mínimo `00015af6`: el lector de conflictos P-L54 ya no mezcla estados de
  broker ni accede a una columna inexistente. Versión `0.4.210`.
- QA de expectativas históricas actualizadas: `1f4b4a79` y `2b2a21d0`.
- Suite final `2339 passed`, `1 skipped` preexistente, `1 warning`,
  `816.43 s`; focales finales `107 passed`; Ruff/NUL/compile/diff/config OK y
  smoke de entrypoint temporal aislado OK.
- Estado: listo para revalidación productiva cerrada y despliegue autorizado,
  aún no desplegado. Siguiente paso único: ejecutar P-L76-CLOSE con preflight
  read-only y sin reparar más código.

## P-L76-PRECLOSE - ensayo previo de P-L69-R2 sobre P-L75

- Worktree aislado `pl76_p69_predeployment_rehearsal`, rama
  `codex/pl76-p69-predeployment-rehearsal`.
- Merge único `--no-ff` `faccc5de42064211276b449d3cc78ebb6c022212` desde la base
  productiva exacta y P-L69-R2; tree `f2b5a772` coincide con el candidato y la
  versión final es `0.4.209`.
- P-L73/P-L74/P-L69/R1/R2 conservan sus fronteras: snapshot provider-neutral,
  commit local, Telegram fail-open y finalización postmarket idempotente.
- QA focal `145 passed` + QA P-L76 `2 passed`; Ruff, NUL, py_compile,
  diff-check y configuración temporal verdes. XNYS abierto: suite completa,
  smoke y validación operativa pendientes.
- Dictamen: `ready_for_closed_market_full_validation`, sin despliegue ni
  cambios en producción. Siguiente paso mínimo: preflight cerrado y ejecutar
  la matriz de `P-L69_informe.md` antes de cualquier promoción.

## P-L77B1 - autoridad fail-closed de overrides adaptativos (0.4.211)

- Candidato aislado `pl77b1_adaptive_override_authority`, rama
  `codex/pl77b1-adaptive-override-authority`, sobre producción `ba9d60d4`.
- Reproducción: el loader legacy aplicaba `MAX_ORDERS_PER_CYCLE=2` con
  autorización global falsa, aunque la base es 4.
- Fix: global literal True + autorización individual canónica + expiración por
  sesiones XNYS evaluable; registros legacy, ambiguos, vencidos o no evaluables
  quedan sin autoridad. No se toca `config.py` ni el fichero productivo.
- Focales `49 passed`; suite `2361 passed`, `1 skipped` preexistente y
  `1 warning`; Ruff/NUL/py_compile/diff/config/kernel aislado y smoke temporal
  verdes. El merge productivo `7682901a` dejó producción en `0.4.211`, con
  dos checks post-arranque HTTP `200/200`, kernel `sealed/ok`, scheduler con
  token válido, `MAX_ORDERS_PER_CYCLE=4`, cero órdenes abiertas y cero
  críticos. Dictamen: `deployed`; el warning de inventario legacy permanece
  observacional y sin autoridad.

## P-L79H - cierre productivo intentado y revertido

- Preflight cerrado del 02-ago-2026: XNYS cerrado, PMR 2026-07-31
  `completed/pipeline_completed`, lease vacio, kernel `ok` tras el sellado
  manual autorizado y stack sano.
- Se integro el candidato exacto `222d2371` mediante merge `--no-ff`
  `d05ce134`, con arbol funcional `205964d4` y version `0.4.214`.
- El gate de suite completa termino en `1678 passed, 1 failed, 1 warning`
  tras 751.99 s. Fallo reproducible:
  `tests/test_p69_fill_watch_implementation.py::test_configuration_is_disabled_and_provider_timeout_is_neutral`,
  que espera el watcher desactivado mientras la configuracion productiva
  autorizada de P-L76 lo tiene activo.
- No se modifico `.env`, manifest ni codigo para ocultar el fallo. Se ejecuto
  rollback auditable `6c36c062`; produccion queda en version `0.4.211`, arbol
  `6938d157`, stack levantado y health doble `200/200` separado por mas de 75 s.
- Dictamen: `needs_fix`. Siguiente paso unico: corregir el aislamiento o
  contrato de esa prueba sin cambiar la activacion productiva del watcher y
  repetir la validacion cerrada; no reintentar el despliegue antes de suite
  verde.
## P-L78B - default global DeepSeek V4 Flash (0.4.212)

- Candidato aislado `pl78b_deepseek_default`, rama
  `codex/pl78b-deepseek-default`, sobre la base productiva `ba7d488d`.
- Reproducción: Settings, roles y codegen heredaban Kimi por defaults de código
  aunque parte de la ruta productiva ya seleccionaba OpenCode Go/DeepSeek;
  mejora continua conservaba GLM como default activo.
- Fix: defaults globales y `.env.example` pasan a
  `opencode-go/deepseek-v4-flash`; Qwen sigue siendo fallback técnico y los
  overrides explícitos compatibles se conservan. La identidad efectiva de
  telemetría sale del endpoint/respuesta real, no de `settings.openai_model`.
- Focales `317 passed`; suite aislada `2370 passed`, 1 skip preexistente y
  1 warning externo; Ruff/NUL/compile/diff/config/kernel/smoke temporal verdes.
- Producción, `.env`, datos, stack y archivos protegidos no se modificaron. El
  candidato queda pendiente de integración y despliegue cerrado; no se
  reescriben eventos históricos GLM/Kimi.

## P-L78C - `schedule-status` read-only (0.4.213)

- La caracterización contra P-L78B reprodujo que `schedule-status` llamaba
  `Store.ensure_schema()` y creaba o migraba SQLite en una `DATA_DIR` ausente.
- Candidato aislado `pl78c_schedule_status_readonly`, rama
  `codex/pl78c-schedule-status-readonly`, usa exclusivamente la lectura
  `Store.read_connection`/`read_runtime_values` y nunca ejecuta migraciones.
- DB ausente, schema incompatible, acceso denegado, payload inválido y WAL o
  sidecar con riesgo de mutación se expresan como runtime unavailable con
  razones estables; calendario/jobs estáticos permanecen disponibles.
- Acepta `schedule-status --json` sin cambiar la salida JSON existente ni el
  scheduling efectivo. La deriva `.env`/kernel de P-L78B sigue sin resolverse y
  bloquea cualquier despliegue, fuera del alcance P-L78C.
- Suite final aislada: `2380 passed, 1 skipped` preexistente
  (`test_score_study_regression_current_sqlite`, sin SQLite histórica local) y
  `1 warning` externo; focales P-L78C `10 passed`; Ruff/NUL/compilación/diff/
  config/kernel temporal y smoke fake aislado verdes.
- `schedule-status --json` real con DB ausente devuelve `database_missing` sin
  crear `DATA_DIR` ni artefactos de logging.
- Dictamen del candidato: `ready_for_pl78c_closed_market_integration`. El
  siguiente paso único sigue siendo resolver la procedencia de `.env`/kernel y
  realizar un ensayo combinado separado; P-L78C no autoriza despliegue.

## P-L78D - ensayo combinado P-L78B + P-L78C

- Merge `--no-ff` `304a61ab` desde producción exacta hacia el candidato
  P-L78C; primer/segundo padres `ba7d488d`/`1bab847a`.
- El árbol funcional mergeado coincide exactamente con `308baa64`, versión
  0.4.213; no hubo conflictos ni deltas inesperados.
- Focales combinados `174 passed`; suite `2380 passed`, un skip histórico
  preexistente y una warning externa; Ruff/NUL/compile/diff/config/kernel
  aislado y smoke fake verdes.
- `config.py` conserva únicamente el delta de defaults de P-L78B; kernel,
  broker, execution y risk son idénticos a producción. El bloqueo `.env`/
  kernel productivo no fue tocado.
- Dictamen: `ready_for_pl78_combined_closed_market_deployment_after_env_authority`;
  no desplegar hasta resolver la autoridad `.env` y repetir el cierre.

## P-L79 - tabla de configuración Streamlit segura para PyArrow (0.4.214)

- Candidato aislado `pl79_arrow_safe_config_table`, rama
  `codex/pl79-arrow-safe-config-table`, sobre el HEAD documental final de
  P-L78D `5e0f41e2`/tree `d00abe9c`.
- Caracterización: `page_config()` entregaba una columna `valor` heterogénea
  (`str`/`bool`/números/`Path`/`None`) y PyArrow fallaba antes del fallback
  interno de Streamlit.
- Corrección: frontera `_config_display_dataframe()` exclusivamente textual,
  con `true`/`false`, representación numérica estable, `n/d` explícito para
  missing y preservación de orden/claves/copy. No cambia Settings ni trading.
- QA final: suite `2385 passed, 1 skipped` preexistente y `1 warning` externa;
  Ruff/NUL/compilación/diff/config/kernel temporal y focales verdes. El smoke
  CLI real no se ejecutó para no adquirir datos externos; el flujo de ciclo con
  dobles quedó cubierto (`22 passed`).
- Dictamen del candidato: `ready_for_pl79_closed_market_integration`.
  Siguiente paso único: ensayo `--no-ff` separado. El bloqueo `.env`/kernel de
  P-L78 sigue fuera de este lote.

## P-L79I - aislamiento de tests P-L69 respecto del entorno

- Reproducción contra `222d2371`: con `TRADE_FILL_WATCH_ENABLED=true` en el
  entorno temporal, `Settings(DATA_DIR=tmp_path)` leyó la variable externa y
  falló la expectativa de watcher desactivado.
- Corrección exclusivamente en tests: `_env_file=None`, `DATA_DIR` temporal y
  saneamiento de las seis variables `TRADE_FILL_WATCH_*` mediante
  `monkeypatch`. También se aisló la aserción equivalente de P-L76.
- Focales bajo entorno externo activo: `159 passed, 1 warning`; subconjunto
  limpio: `3 passed`. Ruff, NUL y `git diff --check` verdes.
- Dictamen del candidato: `ready_for_closed_market_redeployment_rehearsal`.
  Suite completa y gates de integración quedan pendientes del siguiente
  ensayo cerrado; no se modifica el watcher productivo ni `.env`.
## P-L79L - cierre productivo v0.4.214

- Dictamen: deployed el 02-ago-2026 con XNYS cerrado.
- Merge productivo 9b6c4a7b (1b88ae4a + 6c91279f), tree funcional 8a0622ce,
  version 0.4.214; sin conflictos ni deltas funcionales inesperados. PMR
  2026-07-31 completed/pipeline_completed y sin lease activo.
- Suite completa 2387 passed y 1 warning en 880.33 s; focales de la cadena
  bajo entorno activo y limpio 168 passed por ejecucion. Ruff, NUL,
  compilacion, diff, config, kernel y smoke aislado verdes.
- Dos comprobaciones posteriores separadas 101 s confirmaron HTTP raiz y
  /health 200/200, scheduler/listener unicos, kernel sellado/ok y .env
  autorizado sin cambios (86a8420f...dfc35afb).
- Warning externo websockets.legacy; no jobs manuales, broker/red/LLM real,
  reconciliacion, postmarket, kernel-seal, edicion de secretos ni push.

## P-L80 - auditoría del embudo de aprendizaje (P-L80A auditado)

- P-L80A es únicamente auditoría read-only sobre producción `0.4.214`:
  cuantificó el embudo señal → observación → recomendación → plan → orden →
  outcome → aprendizaje → gobierno y reprodujo 0/43 controles same-cycle.
- Causa verificada: las 43 ejecuciones llegan como `executed_buy` con
  `gate.execution={}`; sí existen controles de la misma fecha y
  `source_run_ids`, pero ninguno alcanza la decisión/razón allowlisted del
  matcher. Los 7 linajes legacy no verificados son una deuda separada.
- La actividad de CI no equivale a evidencia: 199/200 propuestas recientes
  son prosa, el digest vigente admite 0 experimentos de evidencia y las
  anomalías de market-data (37 en un artefacto stale) quedan `unavailable`
  para el estado actual.
- P-L80A no está hecho funcionalmente, no cambia código/política, no reserva
  versión y no autoriza auto-apply. Informe único:
  `docs/informe_p_l80_aprendizaje_evidencia.md`.

Cola provisional, dependiente y no autorizada: P-L80B cierre del carrier de
control same-cycle; P-L80C linaje de los 7 legacy; P-L80D contrato
finding→proposal; P-L80E admisión de experimentos/evaluación post-apply;
P-L80F freshness y autoridad de market-data; P-L80G reconciliación de
duplicate ratio/retención. El único siguiente lote recomendado es P-L80B.

P-L80B debe conservar el matcher exacto, usar IDs/source runs canónicos,
mantener la paridad de candidatos/ranks/gates/sizing/planes/órdenes/exposición
y detenerse si exige tocar trading, riesgo o ejecución. La validación completa
requiere XNYS cerrado, PMR terminal, lease vacío y fixtures temporales; no se
promueven propuestas ni se cierra TTL durante esta auditoría.
## P-L80B - cierre prospectivo del carrier same-cycle (candidato 0.4.215)

Estado: `ready_for_integration_rehearsal`; no desplegado ni integrado en
producción. Sobre P-L80A se corrigió únicamente la propagación observacional
de identidad y capacidad: `decision_lineage.signal_id` y `source_run_id`
viajan desde `run_observable_cycle` hasta `signal_outcomes.gate_json` y
`learning_observations.gate_json`. El matcher
`same_cycle_eligible_next_best` no cambia.

La ruta exacta usa `signal_id` + `source_run_id`; la ruta por símbolo queda
solo como compatibilidad para callers legacy sin carrier. Missing/conflict no
se convierte en control. Reintentos iguales son no-op y contenido distinto
conserva el original con evento de conflicto append-only. No hay backfill de
las 43 ejecuciones de P-L80A ni cambios de trading, riesgo o ejecución.

Worktree `pl80b_same_cycle_control_carrier`, rama
`codex/p-l80b-same-cycle-control-carrier`, base `b89bef47`. Commits:
`39ac28c6` caracterización, `e089f7f3` implementación/bump y `a57c0f67`
corrección QA de versión. La suite cerrada queda en 2392 passed, 1 skip
preexistente y 1 warning externo; el siguiente paso único es el ensayo
`merge --no-ff` en un worktree separado, no un despliegue directo.

Cutoff prospectivo pendiente de integración: `deployment_activation_at` UTC
y cinco sesiones XNYS completadas posteriores, sin usar filas históricas.
P-L80C-G continúan como cola provisional y no se inician en paralelo.

## P-L80BR - ensayo aislado de integración

El ensayo `codex/pl80br-integration-rehearsal` fusionó con `--no-ff` el
candidato P-L80B `b0ff0d94` sobre producción `eb662c07`. El merge
`5d7ea285`, versión `0.4.215`, produce exactamente el tree del candidato y
conserva la paridad de trading/riesgo/ejecución. Hubo 110 focales verdes;
la suite previa de 2395 passed se reutiliza por identidad exacta de tree.
Estado: `ready_for_closed_market_deployment`, sin despliegue. La siguiente
acción única es la validación cerrada y despliegue autorizado; P-L80C-G sigue
fuera de alcance.

## P-L80H2 - health canónico OpenCode Go / DeepSeek V4 Flash

- Se implementó en worktree aislado `codex/pl80h2-opencode-go-health` la
  comprobación de una sola llamada al endpoint oficial
  `opencode-go/deepseek-v4-flash`, sin reintentos, fallback, SQLite ni runtime
  operativo. Versión candidata: 0.4.216.
- La probe real autorizada devolvió HTTP 403 `region_forbidden`; no se modificó
  proveedor, modelo, endpoint, `.env` ni política. El bloqueo es externo y no
  se marca como defecto de routing del proyecto.
- Focales del script/routing/CI/overnight: 288 passed; suite completa omitida
  porque el script no es importado por runtime y una segunda llamada real está
  prohibida. El healthcheck antiguo de cinco roles no sustituye este contrato.
- Estado: `blocked_external_provider`. Siguiente acción única: opt-in regional
  oficial de OpenCode Go y una nueva ejecución aislada del script; no cambiar a
  GLM/Kimi ni alterar fallback/política.

## P-L80H4 - correccion del gate de version del candidato

P-L80H3 fue revertido de forma auditable porque la suite encontro una
expectativa stale de `0.4.215` en el candidato `0.4.216`. La base
`0.4.214` pasa su expectativa `0.4.214`; el candidato fallaba. P-L80H4
corrige solo esa asercion en `tests/test_p59c_llm_selected_authority.py`.

El candidato queda `ready_for_closed_market_redeployment`: commit funcional
`338d0cc0`, version `0.4.216`, focales 70 passed y suite 2410 passed, 1 skip
preexistente y 1 warning externo. No hay cambios de trading, riesgo,
ejecucion, proveedor, modelo, endpoint ni credenciales. Siguiente lote unico:
revalidacion cerrada y redeploy secuenciado con todos los gates verdes.

## P-L80H5 - redespliegue final v0.4.216

Estado: `deployed` tras revert auditable del rollback (`97af2f24`) y merge
`--no-ff` del candidato `f4b4bc58`, con tree funcional `59097b81` y version
0.4.216. Suite cerrada: 2410 passed, 1 skip preexistente, 1 warning externa;
focales 70 passed y gates restantes verdes. No hubo cambios de trading,
riesgo, ejecucion, proveedor, credenciales o politica.

Cutoff prospectivo: `2026-08-02T15:51:41.5484478Z`. La ventana de medicion
empieza solo en sesiones XNYS completamente posteriores y requiere cinco
sesiones completadas; no se hace backfill historico. P-L80B queda desplegado
como carrier prospectivo: el matcher no cambia y missing/conflict no forma
controles. La siguiente decision se toma despues de esa cohorte, sin iniciar
P-L80C-G en paralelo.
## P-L81 - resultado del cierre productivo

Estado: `needs_fix`. El candidato v0.4.217 paso suite y gates, pero el merge
produjo `kernel-status=violation` porque el carry read-only de `account.last_equity`
modifica el hash protegido de `broker.py`. El merge fue revertido auditably con
`6f86f260`; produccion queda segura en v0.4.216. Siguiente paso unico: autoridad
explicita para el sello del hash exacto o rediseño de la frontera protegida; no
abrir P-L82/P-L83.
## P-L81 - coherencia de ganancia global diaria y continuidad UI

Estado: `ready_for_next_closed_market_deployment`. La definicion general de hoy es `current_equity - previous_close_equity` sobre `account.last_equity`, con porcentaje sobre el cierre anterior. El carrier se propaga a `PortfolioSnapshot`; el helper canonico es reutilizable y la tarjeta ya no presenta apertura-to-now como hoy. La grafica conecta el tramo `En curso` y conserva `session_date`/intervalo exactos en tooltip.

QA focal: 168 passed y 1 warning externo. Produccion sigue en v0.4.216, sin cambios de stack ni politica. No se modificaron skills/runbooks: no habia contradiccion reproducible. Siguiente paso unico: gates cerrados y despliegue en una ventana con margen seguro; sin backfill P-L80 ni cambios de trading.
## P-L81 - cierre seguro tras reinicio

El primer intento de suite completa encontro solo una expectativa stale de version (`1555 passed, 1 failed, 1 warning`); `365d855f` la corrigio a `0.4.217` y el test aislado pasa. El segundo intento quedo interrumpido por reinicio sin terminal/artefacto recuperable y permanece pendiente. Gates breves verdes: Ruff, NUL, diff-check y version policy.

Dictamen: `ready_for_next_closed_market_deployment`. No iniciar stack_down ni merge preapertura; siguiente precondicion unica: repetir la suite completa aislada y cerrar los gates restantes con XNYS cerrado y margen operativo.

## P-L81A - reaplicacion auditable

Estado provisional: `ready_for_closed_market_full_validation`. El contenido
funcional validado se reaplica mediante revert-of-revert de `6f86f260`, sin
fusionar directamente el merge revertido. Version prevista: 0.4.217. Faltan
suite fresca, gates cerrados, sello canonico y despliegue; no abrir P-L82/P-L83.

## P-L81A - cierre productivo (04-ago-2026)

Dictamen: `deployed`. El contenido P-L81A quedo integrado mediante merge
`32c4025b4d148a9a6e54296e409639339c8f04cc` sobre `91ad200b`, con segundo
padre `dc5df89e`, tree `0619f5b6ab5ed7bd9e5b0dd5f4cad42a6c0d0036` y version
`0.4.217`. El carry de `account.last_equity` sigue siendo read-only y no
modifica trading, riesgo, ejecucion ni politica.

Suite post-merge: `2422 passed, 1 skipped preexistente, 1 warning` en 975.02 s;
focales P-L81/UI: `109 passed`. Ruff, NUL, compile, diff, version policy,
configuracion aislada, kernel temporal y smoke fake verdes. El sello canonico
se ejecuto una vez y kernel productivo quedo `ok` sin violaciones. Dos saludos
200/200 separadas 123 s confirmaron scheduler/listener unicos, token coherente,
paper activo, live/auto-apply off y 0 criticos; los 3 warnings existentes se
conservan sin mezclar este lote.

El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` no cambia. No hay backfill ni
jobs manuales; la siguiente decision queda despues de la cohorte prospectiva
P-L80. No iniciar P-L82/P-L83 en este cierre.

## P-L82 - resolución autoritativa SPY y sesiones omitidas

Estado: `ready_for_closed_market_deployment`. Se reprodujo en la base que
`load_cached_spy_open_observations()` dependía de `group[0]`: un duplicado
genérico del mismo valor leído antes que la cache dedicada producía `conflict`,
mientras el orden inverso resolvía `available`. El fix de `0.4.218` resuelve la
autoridad a nivel de grupo `(price, price_basis)`, mantiene conflicto para
autoridades discordantes y no hace llamadas ni escrituras adicionales.

El contexto/UI expone ahora fecha, estado, motivo y cobertura de cada intervalo
omitido, sin inventar puntos ni conectar sobre huecos. Commits del candidato:
`e1538614` caracterización, `87919ee2` implementación/bump, `d5228ac4` QA y
`b938eaa9` version policy. Suite fresca: `2430 passed, 1 skipped preexistente,
1 warning`; focales: `193 passed, 1 warning`; Ruff/NUL/compile/diff/config y
kernel temporal sin violaciones verdes. El warning es la deprecación externa
de `websockets.legacy`.

No se cambian broker, kernel, execution, risk, config, `.env`, trading,
selección, gates, sizing, órdenes, exposición, límites ni la captura P-L80.
La siguiente acción única es preflight cerrado, ensayo `merge --no-ff` y
despliegue solo con margen suficiente; no iniciar P-L83 ni mezclar deuda ajena.

### P-L82 - cierre productivo

Estado: `deployed`. Merge final `df80dee8` sobre el estado seguro
`31b7367b`, con segundo padre de recuperacion `a0ac5eed`, tree funcional
`93d8a756` y version `0.4.218`. La tentativa accidental `098283bf` fue
revertida de forma auditable por `31b7367b` antes de la integracion final;
no deja delta funcional fuera de P-L82. Suite post-merge `2431 passed, 1
warning`; focales `193 passed, 1 warning`; doble salud 200/200 separada
`136.89s`, kernel `ok`, 0 criticos. Cutoff P-L80 preservado. No iniciar P-L83
en este cierre.

## P-L82R - continuidad y comparabilidad temporal Sistema vs SPY

Estado: `ready_for_closed_market_deployment` en candidato, todavía no
desplegado. La base exacta es `d73a8971` / tree `f966a725`, version `0.4.218`;
el candidato `codex/pl82r-spy-temporal-continuity` queda en version `0.4.219`,
HEAD `1fab7813`, tree `32506e65`. La caracterización reprodujo que la UI
conectaba filas finales sobre intervalos omitidos y que una observación SPY
stale podía clasificarse como comparable por el mero orden temporal.

El fix observacional segmenta por contigüidad XNYS (`end_session_date` de la
fila anterior igual a `session_date` de la siguiente) y exige igualdad exacta
de `system_end_at`/`spy_end_at` UTC para la comparación vigente, sin inventar
umbral de frescura. Sistema y SPY siguen visibles por separado cuando el
estado es `unavailable`, con razón, lag y cobertura; los ganadores y conectores
solo consumen filas finales comparables. Las omisiones y conflictos de P-L82
se conservan; no hay backfill ni llamadas adicionales.

Commits: `3668369f` caracterización, `914c715b` test de exclusión de ganador,
`0fce01a1` implementación/bump y `1fab7813` QA/version policy. Focales `6
passed`; regresiones UI/SPY/Telegram `200 passed, 1 warning`; suite completa
`2436 passed, 1 skipped preexistente, 1 warning` en `786.12s`; Ruff, NUL,
compile, diff-check, config aislada, kernel temporal sin violaciones y smoke
fake aislado verdes. Protegidos objeto-a-objeto iguales a la base y producción
sin cambios. Siguiente acción única: ensayo de integración y despliegue
cerrado solo si el preflight y el margen siguen verdes. P-L83 permanece fuera.

### P-L82R - cierre productivo

Dictamen: `deployed`. Merge productivo `b0a88b98` con primer padre `d73a8971`
y segundo padre `06152971`; tree final `cd75d3de`, version `0.4.219`, checkout
limpio. El ensayo previo tuvo tree idéntico y ningún conflicto. La suite
post-merge fue `2436 passed, 1 skipped preexistente, 1 warning` en `763.44s`;
Ruff, NUL, compile, diff, version policy, configuración, kernel y smoke fake
quedaron verdes. Salud 1 `11:07:20 CEST` y salud 2 `11:09:34 CEST` fueron
`200/200`, separadas `134.33s`, con scheduler/listener únicos, token coherente,
paper activo, live/auto-apply off, kernel `ok`, 0 críticos y 0 órdenes creadas
desde el merge. El cutoff P-L80 permanece intacto; no backfill, jobs manuales,
P-L83 ni push.

### P-L83D - cierre productivo

Estado: `deployed`. Merge `613aab87` sobre `5d53e24c`, segundo padre
`c3a5e671`, tree final `57780f1d`, version `0.4.220`. El fix normaliza
timestamps/buckets Alpaca por sesiones XNYS, separa el current provisional y
preserva la autoridad de P-L81 y la continuidad P-L82R.

La suite fresca fue `2444 passed, 1 skip preexistente, 1 warning`; los focales
post-merge `227 passed, 1 warning`; gates Ruff/NUL/compile/diff/version/config,
kernel y smoke fake quedaron verdes. Salud 1 `12:36:06 CEST` y salud 2
`12:37:58 CEST`, separadas `111.83s`, confirmaron HTTP 200/200, scheduler y
listener unicos, paper activo, live/auto-apply off, kernel ok, 0 criticos y
0 ordenes abiertas.

El cutoff P-L80 permanece intacto. Se congelan cambios funcionales hasta la
revision del 08/08; no iniciar lotes nuevos ni hacer backfill o jobs manuales.

## P-L83D - correccion temporal final del dashboard

P-L83D es el unico lote UI autorizado antes de la congelacion del 08/08. La
regresion se reprodujo en la base: epoch seconds se interpretaban como
nanoseconds y los buckets diarios se etiquetaban por fecha civil local en vez
de por la sesion XNYS de cierre; el current provisional tambien podia
sobrescribir un cierre. El candidato normaliza epoch seconds/milliseconds,
asigna cada bucket al ultimo cierre XNYS disponible, conserva `session_date` y
mantiene el current separado y marcado provisional. No cambia trading, riesgo,
ejecucion, P-L80, P-L82R ni hace llamadas adicionales al broker.

El candidato `codex/pl83d-dashboard-temporal-dates` esta en version `0.4.220`,
HEAD `d15eb37e`, tree `306a3dae`, limpio. Suite fresca: `2444 passed, 1 skip
preexistente, 1 warning`; focales y gates completos constan en el informe
`docs/informe_p_l83d_dashboard_temporal_dates.md`. Estado: listo para ensayo
`merge --no-ff`; no marcar desplegado hasta confirmar salud productiva doble.

Siguiente paso unico: ensayo aislado y, si XNYS cerrado y hay margen suficiente,
despliegue secuenciado. Si no hay margen, posponer al siguiente cierre. Tras
P-L83D quedan congelados los cambios funcionales hasta la revision del 08/08.

## P-L84 - evidencia y orquestacion de agentes (plan condicional)

Estado: `planned_conditional_after_p_l80_review`. Este bloque incorpora las
ideas utiles observadas en BQuant Agents sin adoptar sus afirmaciones
comerciales como evidencia. No reserva version, no autoriza implementacion y
no altera la congelacion funcional ni el cutoff P-L80
`2026-08-02T15:51:41.5484478Z`.

Referencia informativa consultada el 05/08/2026:
`https://bquantagents.com/` y `https://bquantfunds.info/mcp`.

### Tesis y limites

El valor de una cartera multi-agente no se demuestra por el numero de agentes,
herramientas, informes o votos. Debe demostrarse prospectivamente mediante
aportacion incremental, independencia de errores, calibracion, identidad
efectiva, control comparable y outcomes maduros. La decision de no operar es
una decision evaluable; el desacuerdo entre agentes es informacion, no una
orden ni un permiso.

P-L84 permanece subordinado a la revision de las cinco sesiones XNYS del
03-07 de agosto. Si los outcomes no estan maduros, el carrier P-L80B no tiene
cobertura suficiente o faltan controles same-cycle comparables, la decision
correcta es esperar. Ningun sublote puede cambiar seleccion, gates, sizing,
exits, riesgo, ejecucion, autoridad, modelo, politica activa o auto-apply.

### Secuencia estricta, un solo sublote activo

1. **P-L84A - auditoria del contrato efectivo de agentes.** Read-only y sin
   schema nuevo: inventariar productor -> evento -> consumidor para cada
   agente, reutilizando contratos existentes antes de proponer campos.
   Contrato minimo evaluado: `cycle_id`, identidad efectiva de agente/modelo,
   `as_of`, horizonte, prediccion/direccion, probabilidad o confianza
   interpretable, referencias de evidencia, latencia, estado y fallback.
   Metrica primaria: porcentaje de decisiones elegibles con contrato completo
   y trazable. Salida: `ready_for_implementation`, `wait_for_sample` o
   `not_needed`; nunca promocion.
2. **P-L84B - carrier prospectivo de creencias, solo si A demuestra un hueco.**
   Un unico cambio observacional append-only e idempotente, sin reconstruccion
   por simbolo/fecha y sin convertir missing en cero. Metrica primaria:
   cobertura exacta del contrato en decisiones elegibles posteriores al
   cutoff del despliegue. Paridad economica completa obligatoria.
3. **P-L84C - scoreboard de aportacion ortogonal.** Con muestra madura, medir
   calibracion con una proper scoring rule y comparar cada agente contra el
   control same-cycle y el ensemble sin ese agente. Metrica primaria: delta
   OOS de Brier frente al control preregistrado. Cobertura,
   correlacion de errores, latencia, fallos, fallback, P/L neto, drawdown,
   MAE/tail y concentracion son guardrails, no excusas para mezclar
   denominadores. El scoreboard no cambia pesos activos.
4. **P-L84D - debate auditado en shadow.** Tesis y esceptico deben emitir
   contratos estructurados con evidencia, objecion e invalidacion; un arbitro
   solo registra el desacuerdo y no adquiere autoridad de trading. Metrica
   primaria: tasa de falsos positivos de alta confianza frente al control
   comparable. Si no existe muestra/control suficiente, `wait_for_sample`.
5. **P-L84E - tres horizontes en shadow.** Evaluar diario/semanal/mensual con
   cortes temporales exactos; acuerdo y desacuerdo permanecen telemetria.
   Metrica primaria: expectativa neta madura frente al control same-cycle.
   No convertir alineamiento en gate antes de promocion human-gated.
6. **P-L84F - proveedor externo point-in-time, piloto opcional de research.**
   Solo si una carencia de datos prioritaria esta demostrada: adaptador
   postmarket/fail-open que entregue snapshots canonicos con `observed_at`,
   `effective_at`, `published_at`, vintage, proveedor y conflicto. Metrica
   primaria: porcentaje reproducible de observaciones con identidad y
   temporalidad completas. Verificar licencia, SLA, survivorship, revisiones,
   limites y coste antes de considerar BQuant MCP u otro proveedor. Nunca
   permitir seleccion dinamica de tools LLM en la ruta operativa.
7. **P-L84G - coste de transicion y crowding, solo despues de C.** Medir en
   shadow turnover, spread, slippage, comisiones y concentracion del cambio
   cartera actual -> objetivo. Metrica primaria: error absoluto del coste neto
   estimado frente al realizado. Correlacion de recomendaciones/exposiciones
   basta como diagnostico inicial; no introducir formalismos de transporte o
   sincronizacion sin valor incremental demostrado.
8. **P-L84H - routing por regimen, ultimo y human-gated.** Solo con regimenes
   preregistrados, datos point-in-time, potencia suficiente y un control sin
   router. Metrica primaria: expectativa neta OOS frente al control. Un mejor
   retorno con peor drawdown, MAE o cola queda rechazado.

### Exclusiones explicitas

- No crear mas agentes ni ampliar el catalogo de tools por actividad aparente.
- No usar SPY, un pool de regimen o promedios historicos como sustituto de un
  control causal same-cycle.
- No activar voto ponderado, pesos bayesianos o regime switching por prosa.
- No incorporar insiders, 13F, Congreso, consenso, macro o noticias sin lag de
  publicacion y vintage point-in-time verificables.
- No integrar BQuant MCP ni otro servicio en trading, broker, riesgo o gates;
  cualquier piloto es research-only, aislado y revocable.

### Primera decision permitida

Tras la revision P-L80 del 08/08 se seleccionara como maximo un lote minimo.
P-L84A es el candidato por defecto solo si la evidencia de esa revision no
identifica antes un defecto mas critico de captura, control, linaje, costes u
outcomes. P-L84B-H no se inician por inercia ni en paralelo.

## P-L85 - migracion condicionada Zen Free / Go

Estado: `ready_for_closed_market_deployment` en candidato aislado; produccion
continua en v0.4.220 con OpenCode Go como primario vigente hasta completar el
cierre autorizado. La caracterizacion inicial encontro una respuesta HTTP 200
con `finish_reason=length` y contenido final ausente usando el cap antiguo de
32; no se ignora ni se reclasifica como exito. La probe corregida uso un cap
alineado con los consumidores y valido cuatro llamadas Zen adicionales y una
health Go, agotando `10/10` llamadas reales autorizadas sin retry.

Contrato unico: Zen Free (`opencode-zen`, `deepseek-v4-flash-free`,
`https://opencode.ai/zen/v1`) es primario; Go
(`opencode-go`, `deepseek-v4-flash`, `https://opencode.ai/zen/go/v1`) es una
unica tentativa inmediata por peticion si Zen falla. Despues siguen los
fallbacks locales existentes. `length`, contenido ausente, identidad
incorrecta y respuesta invalida permanecen fail-closed. No cambia la politica
de trading, riesgo, ejecucion, gates, sizing, seleccion, autoridad ni el
cutoff P-L80.

QA candidata: suite `2456 passed, 1 skipped preexistente, 1 warning` en
`752.91s`; focales posteriores `106 passed`; Ruff, NUL, compilacion,
diff-check, configuracion aislada, kernel temporal sin violaciones y smoke fake
aislado verdes. El siguiente unico paso es preflight cerrado y despliegue
secuenciado; si falla cualquier gate, mantener Go sin mutar produccion.

### P-L85 - transición completada

P-L85 queda `deployed` en `0.4.221`: merge `78bb0758`, tree funcional
`8ea38dbb`, con Zen Free primario y Go como fallback inmediato de una tentativa.
El kernel fue sellado una sola vez tras el delta exacto de aliases `.env` y
quedó `ok`. Las dos saludes fueron 200/200, separadas `109.9286s`, con paper
activo, live/auto-apply off, scheduler/listener únicos y cero órdenes abiertas.
La activación prospectiva es `2026-08-05T23:14:15.6752134Z`; P-L80 mantiene su
cutoff y no hay backfill. No iniciar otro lote de routing antes de la revisión
P-L80 del 08/08.
