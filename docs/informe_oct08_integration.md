## QA local final .363 cerrada — 11-oct-2026

Fullsuite del árbol definitivo:2867 passed,1 skipped,0 failed,727.67s,exit0.
Skip preexistente de historia local unavailable. Focales64, Ruff,NUL555/0,
diff, configuración y smoke aislados pasan; Python proyecto,PYTHONPATH exacto,
DATA_DIR temporal,_env_file=None,PYTHON_DOTENV_DISABLED=1 y red externa bloqueada.
No repetir esta suite sin nueva causa. Snapshot fuentes/tests en EF99
release_oct11_0363_tested_tree_snapshot.json y journal
EF99/oct11_0363_final_full_v6.jsonl. Fuentes/tests congelados desde su inicio.
Paridad exacta de solicitudes y ARM preliminar combinado constan abajo.
Producción todavía .321; ARM final, recuperación y corte pendientes.

## Corrección de memoria .363 en validación — 11-oct-2026

El usuario autorizó «Corrígelo y despliega». Producción sigue .321; no corte,
reinicio, sellado ni cambio de estado realizado en este tramo. La imagen
.362 sí está construida en staging: los apartados anteriores que dicen
«no construida» describen el momento anterior y no el estado presente.

Nueva reserva .363: ready_for_human_approval_requests consume el cursor
SQLite de sólo lectura fila a fila en lugar de retener todos los content_text.
Conserva SELECT, límite, orden, criterios, errores JSON y salida; cierre explícito
de cursor y reader también al fallar. No cambio de riesgo, límites o broker.
64 focales pasan; Ruff y diff pasan. Paridad contra HEAD .362 exacto
226b28350c52f78f5c55d30ca3c5ddd97cc95d30:205 registros,limit200,
60 resultados idénticos. Dos tests nuevos verifican streaming y cierre ante error.

ARM diagnóstico .362:50k recomendaciones,200k outcomes,16 diffs de4MiB,
digest completo incluida serialización/report; con512MiB pico RSS284794880.
La mayor acumulación adicional ocurre antes de research_agenda, en la lectura
de solicitudes de aprobación. .363 preliminar se probó mediante montaje ro
únicamente del digest corregido sobre imagen .362: NO es imagen final .363.
Bajo256MiB, solo pico227864576 y combinado con18MiB residentes229724160;
ambos exit0,oom0,oom_kill0. cgroup memory.peak alcanza límite por caché de
fixture; no confundirlo con RSS ni certificar margen productivo universal.

Fullsuite final .363 en curso, journal EF99/oct11_0363_final_full_v6.jsonl;
no editar src/tests durante su ejecución. Pendientes: resultado fullsuite,
NUL/config/smoke, identidad y paquete final, construir imagen .363,
ARM final exacta, recuperación canónica del digest con failed conservado,
preflight inmediato, sellado intencional aprobado y despliegue con doble
salud>=75s y OOM600s. Mantener revisión12-oct sin cambios.


## Identidad de fuentes probadas .362

Commit funcional y de QA:b7d055ff1b226cf0f57466d647641a7f7abe1a7f.
Tree:dab188c5e7a1558245623e173cc0d3344e064783. Checkout limpio verificado
tras commit; fuentes/tests idénticos al snapshot de la fullsuite verde.
Los commits documentales posteriores no autorizan repetir suites idénticas.
La preparación.361 queda superseded. No imagen.362 construida ni desplegada.

Al cerrar commit, mantenimiento geométrico de Git encontró una referencia
ajena refs/codex/turn-diffs/captures/.../base con bad object. El commit,
HEAD/tree y estado limpio se verifican por separado. Incidencia de metadata
Codex; no reparar/eliminar refs ni ocultarla. No es fallo de tests ni prueba
de despliegue. Readiness, paquete y manifest final se registran en EF99.


## Resultado final local .362 — 11-oct-2026

Fullsuite definitiva:2865 passed,1 skipped,0 failed,739.68s,exit0.
Skip preexistente: historia SQLite local no disponible; no introducir datos
productivos en tests. Ruff, NUL539/0, diff, configuración y smoke aislados
pasan. PYTHON_DOTENV_DISABLED=1,_env_file=None,DATA_DIR temporal, Python
C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe y PYTHONPATH src exacto;
red externa bloqueada y proveedores locales. No se repite esta suite sin causa
nueva. Journal y receipt en EF99/oct11_0362_final_full_v6.jsonl y
release_oct11_0362_local_qa.json. Fuentes/tests conservan los hashes del
snapshot probado; sólo docs se actualizan después de QA.

Correcciones nuevas: fecha contractual fija20-jun en fixture setup-edge y
expectativa de versión. Reserva.362 obligatoria por política de cambios en
tests; no cambio de estrategia, proveedor, configuración ni límites. Frente
a1adc3cec, archivos protegidos diferentes sólo broker Enum.value y execution
partial_take_profit_v2 aprobado. No sellado canónico aún: QA ARM pendiente.

Capital5–9oct:180 recomendaciones/109 BUY.8 BUY enlazados por IDs exactos a
plan,orden y fill, con paridad de cantidades8/8; todos con multiplicador0.5 y
cap1000USD, después redondeo entero.53 BUY sólo rechazo position_adds_disabled;
8 rechazos de duplicados pertenecen a BUY con plan y no son oportunidades
adicionales.48 BUY sin frontera final atribuida; los carriers de backtest por
símbolo no conceden autoridad para unirlos.61 enlaces de rechazo contrastados
por cycle_id/candidate_id/signal_capture_id. Orígenes BUY58 fallback LLM
fallido,22 hold override,22 capacity fill,7 LLM. No convertirlos en beneficio
retrospectivo ni capacidad elegible sin gates completos.

Dictamen operativo:precondition_not_met,NO DEPLOY. Producción observada.321,
auxiliary unhealthy,ci_digest failed11-oct06:31:26UTC returncode-9,
cgroup256MiB con oom_kill4 acumulados y heartbeat fresco. El postmarket de
última sesión9-oct es terminal failed; skipped dominical no es el bloqueo
decisivo. No cambios productivos, reinicios, órdenes, límites ni estados.
Pendientes:QA ARM digest completo representativo y margen real, recuperación
canónica con evidencia conservada, sellado aprobado, preflight inmediato
completo, imagen/hashes activos,doble salud>=75s,OOM600s,5 sesiones posteriores.
La revisión12-oct10:00Madrid se mantiene sin cambios.


## Reserva final .362 — QA en curso

La política test_version_must_change_when_product_files_change incluye tests/:
por eso las dos correcciones QA exigen versión nueva. Se reserva0.4.362;
solo __init__.py cambia en src desde HEADfuncional.e1a0013b. Se mantienen
intactos los demás204/205 archivos funcionales y los parches aprobados.
No integrar nuevos cambios mientras corre la fullsuite final.
Tramo posterior no alcanzado en v6:107 passed12.89s tras la reserva; no se
suma a la fullsuite fallida. Nueva suite completa final tiene journal
EF99/oct11_0362_final_full_v6.jsonl y permanece pendiente.
Skip preexistente: test_score_study_regression_current_sqlite exige historia
SQLite local ausente en entorno aislado; no conectar ni copiar datos productivos
para eliminarlo. Registrar ese límite al dictaminar QA.
Ruff y diff finales pasan. Smoke .362, NUL y sellado/ARM quedan por verificar.
El ZIP .361 anterior queda superseded y no debe utilizarse para el corte.


## Precisión del gate postmarket en domingo

El plan actual exige postmarket terminal de la sesión bursátil pertinente;
no exige fabricar una sesión bursátil dominical. La coordinación9-oct consta
terminal failed/stage_postmarket_report_failed, finished10-oct03:29:55UTC.
El skipped/market_not_ready del11-oct no prueba por sí solo incumplimiento
para la última sesión XNYS. Se corrige la atribución anterior: el bloqueo
confirmado de este intento es auxiliary unhealthy/digest failed con OOM,
además de QA ARM y comprobaciones finales aún pendientes. No certificar
quietud solo con snapshots ni con WAL unavailable. Sin corte productivo.


## Capital: cobertura completa de carriers BUY y fallo auxiliar actual

Segunda extracción dirigida: 340 eventos desde5-oct, límite3000 no saturado.
Los210 rechazos transportados se reducen a61 observaciones por identidad exacta
cycle_id/candidate_id/signal_capture_id/stage/reason; todos tienen un único
recommendation_id por captura exacta. 53 position_adds_disabled y8
symbol_already_has_buy_plan_in_cycle. Esos8 también obtuvieron planes BUY:
son duplicados adicionales bloqueados, no8 oportunidades perdidas.
Cobertura final de109 BUY:8 con plan/orden/fill,53 solo con rechazo verificado,
48 sin frontera final atribuida. No calcular beneficios ejecutables ni
convertir repetición de carriers en oportunidades únicas. Universo y candidatos
entregados requieren el carrier symbol_coverage realmente desplegado.

Lectura auxiliar actual11-oct: ci_digest failed06:31:26UTC returncode=-9;
heartbeat supervisor fresco10:56:27UTC PID7. memory.max268435456,
memory.current18087936 al observar; memory.events max39172/oom63/oom_kill4.
Los contadores agregados no identifican por sí solos la fase que consume.
No declarar solucionado OOM por memoria actual baja ni por mejora sintética.
El código canónico conserva un fallo diario y no lo reintenta ese día;
no hay ruta de retry explícita en el supervisor. No borrar/reescribir estado,
forzar digest productivo ni reiniciar para certificar salud. precondition_not_met
por salud auxiliar; medir ARM y definir recuperación verificable siguen
pendientes antes de aceptar corte. Evidencia audit_oct11_auxiliary_readonly.json.


## Implementación del plan — evidencia nueva 11-oct

La dependencia de orden queda localizada tras test_p147_crew_session_headers:
CrewAI llama load_dotenv() al importarse; la búsqueda desde la dependencia
encuentra C:/Antonio/Bref/agenteBolsa/.env. _env_file=None no bloquea esa carga.
No se han inspeccionado ni publicado credenciales. El lanzador v6 establece
PYTHON_DOTENV_DISABLED=1 antes de importar dependencias. Reproducción conjunta
P-L147 + P-L78B: 13 passed en 3,34 s con red bloqueada. La suite completa v6
está en ejecución; todavía no se declara verde. La causa está en aislamiento
QA, no autoriza cambiar proveedor ni configuración productiva.

SELECT con Store.read_connection y query_only=1 confirma producción .321,
paper true, live/auto-apply false; max_position_exposure=0.05,
max_risk_per_trade=0.01, risk_budget_max_new_risk_per_day_pct=0.015,
trade_selection_top_n=24. Ventana desde 5-oct: 180 recomendaciones, 109 BUY,
8 planes BUY y 8 órdenes BUY filled. Los ocho enlaces se verifican por
recommendation_id y plan_id, sin unir por símbolo/fecha. No concluir que los
otros 101 BUY fueran elegibles: atribución de rechazos pendiente.

Los 8 planes tienen size_multiplier=0.5 y learning_mode_notional_cap=1000.
Ejemplo PANW plan_6459f2c1a7fb / rec_f262132f1131: equity 69883.12,
max_position_notional 3494.16, adjusted_target_notional 1747.08, cap1000,
whole_share_bracket qty2 x404.27 =808.54. El riesgo snapshot registra exposure0;
no lo usar como exposición real ni liberar límites. Los cambios aprobados
Enum.value deben corregir ese contrato antes de N3.

Gate de corte: precondition_not_met. Coordinación 11-oct terminal skipped,
reason market_not_ready, finalizada 10:43:51UTC; el plan exige completed/failed.
Auxiliar unhealthy también pendiente. No se ha desplegado, reiniciado,
forzado jobs ni borrado estados. QA ARM/digest completo, sellado final,
identidad limpia, doble salud y observación600s siguen pendientes.
Evidencia local ef99: audit_oct11_capital_exact_readonly.json,
audit_oct11_capital_exact_analysis.json, oct11_defaults_fixed_v6.jsonl,
validate_oct11_isolated_entry_v6.py. La revisión 12-oct permanece intacta.

# Ensayo conjunto de siete mejoras — 8-oct-2026

## Estado actualizado .361 y capital — 11-oct-2026

Candidato integrado HEAD e1a0013bb324b5d25dcadeed1dcd224c5c9fd380,
tree comprometido 2adc44379f0925a842448bddd13cd4760bc938b8, versión .361.
.359/.360 integrados en rehearsal: sustituyen el estado abierto de las notas
históricas inferiores. Pendiente commit del test de versión .352 -> .361;
status previo a esta nota: solo ese test modificado. No desplegado.
Fullsuite v5: 2.110 passed y 1 failed (defaults P-L78B opencode-go/zen),
742,80s. Focal del fallo pasa en base y candidato con objetos config/test
idénticos: dependencia de orden/entorno sospechada, causa no demostrada;
no clasificarlo como defecto de base reproducido ni cambiar proveedor.
Smoke .361 local y validate-agent-config passed; diff --check correcto.
Journal: ef99/docs/artifacts/oct11_0361_full_v5_journal.jsonl. No repetir
suite sin resolver una causa nueva. Kernel productivo, ARM y gates pendientes.

Producción comprobada hoy: imagen .321; scheduler/web healthy, auxiliary
unhealthy. Schedule-status 12:28:52 Madrid XNYS cerrado, próxima apertura
12-oct15:30; lock PID7/token coincidente. Runtime unavailable por WAL no
prueba ausencia de jobs. Sin despliegue, reinicio, órdenes ni cambios de riesgo.

Capital: captura 9-oct con 89,22% cash; 37 BUY de últimas80 recomendaciones
(límite saturado),35 con razón fallback;8 fills BUY entre638,88 y972,25USD.
No dividir8/37: ventanas y granularidad difieren. Diagnóstico/reproducción:
C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/docs/informe_oct11_capital_y_validacion.md.
Siguiente: resolver QA por orden; enlazar candidatos/recomendaciones/planes/
órdenes por IDs, atribuir notional rechazado y sizing; eliminar defectos
operativos conservando gates. Ajustar capital requiere evidencia de riesgo,
costes y OOS; no forzar compras por cash. Revisión12-oct intacta.


## Revisión final .359 todavía abierta — 10-oct, 11:56 Europe/Madrid

Entrega 0f181d8498a3ae89c4c1b884a0a784eda3d6dc2a/tree
3d8d5b78735c89d49bb4a99d1d3f414f1369e794 verificada limpia. Focales finales:
42 passed en3.65s, PID2556/exit0 según log v3 leído por root. Sustituye cualquier
atribución previa de28/8passed: aquellos ocho ensayos fueron inconclusive.
El worker acredita parada explícita de sus16PID tras comprobar pertenencia;
la comprobación root posterior sin procesos ocurrió después. La frase anterior
"No se mataron procesos" describía acciones root, no el conjunto del equipo.
No se detuvieron servicios ni procesos productivos.

Paridad no aceptada aún: comparación independiente root v2 contra ASTbase
exacta43325d cubre13casos,10iguales. Tres divergencias: controles parciales
escalares provocan fallo antes de leer outcomes (base los lee); controles
escalares verificados/parciales seguidos de recomendación inválida cambian
error prioritario (base list.get, candidato int not iterable). Se pide diferir
por etapa/orden los errores sin retener payloads/tracebacks grandes, añadir
regresión contra base y medición local de memoria requerida por el lote.
Evidencia docs/artifacts/oct10_comparable_root_errors_v2.{json,py}.
No merge .359 ni declaración OOM resuelto.

.360 ya asignado en bolsa-origin-memory-oct10, base limpia1a3333a4:
proyección/stream exclusivo de artifacts para origin_utility; lector íntegro
para aprobación humana intacto. Schedule-status real09:54:44UTC confirma
XNYS cerrado y próxima apertura12-oct15:30Madrid. Fullsuite única pendiente
para árbol integrado definitivo; producción .321 sin cambios.


## Integración digest y defectos de paridad — 10-oct, 11:53 Europe/Madrid

.358 integrado únicamente en rehearsal mediante merge --no-ff
1a3333a49db77898cecf1670813b4e23d445ac00,
tree 3d64164ce508958be64b86445dfbdc84ef79c076, limpio/version .358.
Se incorporó HEAD 3d6e4f8c197dfd3227fb6eefb67ade5d586d25fd (código/tests
idénticos a la entrega revisada 56a8b988; posteriores solo docs). Protegidos
idénticos a 01000f74. No es despliegue ni DoD completo; fullsuite final pendiente.
Antes de merge, CIM ya no devolvió pytest/smoke/bootstrap local activo.

.359 permanece needs_fix. Root ejecutó AST exacto de la base 43325d7b con
fakes en memoria, red/DNS bloqueados y Python/PYTHONPATH del proyecto: nueve
de diez casos conservaron resultados/errores/lecturas; verified_controls_scalar
(controls=1, status=verified) difirió: base TypeError "'int' object is not iterable",
candidato TypeError "object of type 'int' has no len()". Es diagnóstico de la
fuente en curso, no QA final de un árbol limpio: HEAD 83ec4b60 y SHA fuente
registrados en artefacto. Corrección y caracterización persistente asignadas al
worker. Las pruebas nuevo-vs-nuevo no certifican equivalencia con la base.
Evidencia: docs/artifacts/oct10_comparable_root_errors.json y su script.

La discrepancia de procesos se contrastó de nuevo: Get-Process no encontró los
16 PID de pytest previamente vistos por CIM; CIM posterior tampoco los mostró.
No se mataron procesos. Se exige al worker registrar handles/terminales/salidas
originales y corregir cualquier atribución al coordinador, que no lanzó esos
ensayos. No se afirma un cuelgue productivo ni QA pasada por inventario parcial.

Auditoría scheduler: el worker reconoce que el SELECT histórico de cinco
cycle_id (LIMIT 300) usó sqlite3.connect directo, no la envoltura Store.
No cumple el procedimiento de auditoría readonly exigido; corregir un helper
local después no valida retroactivamente la ejecución. Consulta histórica se
conserva como tal; no se repite. Procedencia: ef99/audit_oct10_remote_query_provenance.txt.
La conclusión de OOM memcg se sostiene por la evidencia independiente del kernel;
la causa por función sigue hipótesis. update_learning=False se retira como
optimización de paridad: puede dejar outcomes/capturas obsoletos si PMR falla.

Próximo lote N2 reservado .360: lectura proyectada/por lotes exclusiva de
artifacts para origin_utility del digest. Fuente actual solicita 50000 artifacts
con content_text completo, mientras ese consumidor solo usa proposal_id y
payload.status/tests_ok. La aprobación humana sigue usando su lector íntegro.
Mantener límite/orden/JSON/errores y métricas exactas; caracterizar contra base,
probar lifecycle/read-only y medir memoria local con diffs sintéticos grandes.
Sin cambios a aprobación, aprendizaje, trading, esquema, config ni protegidos.
Base prevista 1a3333a4; nuevo worktree bolsa-origin-memory-oct10 en preparación.
.361 reservado para la versión de integración final si se combinan .359/.360.
No afirmar OOM resuelto por esta reducción de ancho; salud/ARM/paridad/QA final
siguen gates antes de desplegar. Producción .321 y revisión 12-oct intactas.


## Revisión root del digest y auditoría del scheduler — 10-oct, 11:45 Europe/Madrid

Dictamen .358 `ready_for_integration_rehearsal`, con merge pendiente. Entrega
limpia verificada: HEAD 56a8b988bda1714b0ab78d5233744d6849275d46,
tree 921d9321fce9afb25a2aaf80f4127b71b1923f5a. Sustituye el rechazo de la
entrega anterior f52c055e; no borra su evidencia. QA del worker: 38 passed
(9.51 s), Ruff correcto y medición v3 del proceso propio con firma WinAPI
corregida. RSS Windows no prueba límites memcg Linux ni resolución del OOM.

Root ejecutó el despacho AST exacto de cb3d8805a9890fab0357b0ba3a3f7afaa8577586
contra el handler nuevo, con Python del proyecto, PYTHONPATH exacto .358/src,
DATA_DIR temporal, Settings(_env_file=None), reloj fijo y red/DNS bloqueados.
Ocho casos (vacío/fixture, texto/JSON, con/sin archivo) dieron igualdad exacta
sin normalización. También verificó identidad de la clase exportada
ContinuousImprovementOrchestrator. Dos ensayos previos fallaron únicamente
al limpiar SQLite temporal (WinError32); v3 cierra readers y ejecuta gc.collect
antes de limpiar, termina exit=0 y conserva resultado. No cambió Store ni
código productivo para corregir el lanzador.
Evidencia reproducible: docs/artifacts/oct10_digest_root_cb3_exact_parity.json
y docs/artifacts/oct10_digest_root_cb3_exact_parity.py. SHA256 del blob bruto
main.py cb3: 2bc7bbfa1a5eddee347094351cfb474ea6eb4e077a5cdd4435493bb296641fbe.
La huella d40daccc del worker corresponde a texto con normalización universal
de saltos de línea (subprocess text=True), no a bytes Git brutos. Son ámbitos
distintos; la comparación root usa el blob bruto y su AST ejecutable.

Auditoría scheduler readonly entregada en ef99/docs/informe_oct10_scheduler_memory.md:
OOM históricos confirmados, reconciliaciones largas y llamadas grandes de
aprendizaje repetidas entre reconciliación, PMR y medición. No demuestra qué
función es dueña de cada pico; un OOM coincide con crew/reintentos LLM y no
se atribuye a digest. Desactivar update_learning en reconciliación alteraría
cadencia/disponibilidad de outcomes; no se acepta como optimización de paridad
sin estudiar consumidores y PMR fallido. Auditoría de contratos adicional en curso.
El script fuente entregado muestra sqlite3.connect directo; root exige evidencia
de la envoltura Store.read_connection realmente ejecutada antes de certificar
la conformidad de esa consulta. No repetir la consulta para sustituir evidencia.

Schedule-status real 09:43:20 UTC confirma XNYS cerrado, próxima apertura
12-oct 15:30 Madrid. Sonda Store.read_connection query_only=1 de 09:43:52 UTC
consulta claves scheduler_job_status, lease/retry (LIMIT 100): estados terminales
en el ámbito consultado; sin entradas lease/retry. La primera consulta empleó
un nombre de contenedor inexistente; la segunda un prefijo job_status erróneo
(no devolvió filas); ambas se corrigieron exclusivamente en sondas readonly.
Evidencia ef99/audit_oct10_runtime_1145.json (nombre nominal, timestamp interno
autoritativo). Paper=true, live=false, auto_apply=false. No certifica salud de
producción: auxiliary sigue unhealthy y .321 activa. Sin despliegue/reinicio,
órdenes, modificación de configuración, locks o históricos.

CIM detecta múltiples pytest locales vivos del lote .359. El worker revisa
handles/procesos antes de nuevos lanzamientos. Merge y QA siguiente esperan
terminales verificables; no interpretar timeout como fin ni matar Python genérico.
Fullsuite se reserva para el árbol funcional integrado definitivo. Automatización
de despliegue sigue pausada; revisión readonly del 12-oct intacta.


## Revisión de entregas de memoria — 10-oct, 11:29 Europe/Madrid

Dictamen `needs_fix`, sin integración ni despliegue. .358 fue entregado limpio
por Luna en bolsa-digest-oct10: HEAD f52c055e963289cd813e9a56f79ca4001be2be37,
tree 938bdc7c39bd407209edaae5bdbce6532e526645. El código comparte despacho y
cierra Store en las rutas previstas. Root detectó límites de la QA entregada:
solo cuatro focales nuevos, sin pruebas de todos los fallos descritos; hijo del
test de import sin guards; paridad entre dos entrypoints candidatos, sin base
pre-refactor; normalización que elimina campos de ventanas de negocio.
Medición v2 mide el proceso propio, pero la firma WinAPI pasa un puntero donde
GetProcessMemoryInfo requiere DWORD cb; tampoco prueba pico entre fases.
No se acepta como certificación de memoria ni paridad final. El resumen del
primer resultado inválido no conserva su JSON completo original. Se pide
conservar evidencia y declarar cualquier pérdida, sin reconstruirla como original.
Luna corrige esos puntos mediante commits nuevos y evidencia v3; .358 no está
aprobado para integración todavía. El smoke .357 anterior y los 32 focales del
worker no equivalen a DoD completo.

El lanzador root con entrada fija recogió las 2830 pruebas de .357 sin error
(3.19 s); es colección, no ejecución completa. Sus siete tests de concurrencia
siguen verdes y la suite completa final se reserva para el árbol integrado.

Nuevo lote N2 .359 reservado en bolsa-controls-memory-oct10/agenteBolsa,
base exacta 43325d7b8c6525fa3665537f5109d570f2f2f5a9. Lectura de código confirma
que build_comparable_control_quality materializa hasta 50000 recomendaciones,
listas de controles y hasta 200000 outcomes completos para calcular contadores
y madurez. Corrección aislada asignada: streaming readonly mediante Store,
reutilización de helpers, contadores/IDs y madurez en lugar de payloads retenidos.
Aceptar solo con paridad campo a campo contra la base, mismos límites/orden,
exclusiones, filtros, last-wins de IDs duplicados, denominadores y errores;
legacy y lectores actuales intactos, cierre de recursos probado y reducción de
memoria medida con fixtures locales. No cambio de candidatos, selección,
órdenes, economía, aprendizaje ni promoción. Implementación/QA/revisión root
pendientes; no atribuir OOM productivo a esta función sin evidencia adicional.
La auditoría readonly separada del scheduler continúa buscando fases exactas.
No se ha cambiado configuración, límites, locks ni servicios para pasar gates.

## Diagnóstico y QA aislada — 10-oct, 11:13 Europe/Madrid

Dictamen `needs_fix`; despliegue pendiente. Esta continuación del objetivo
«Soluciónalo» es diagnóstico y preparación aislada, posterior al intento
operativo fallido de las 10:38. No se ha reanudado la automatización pausada.
Producción sigue .321; el candidato .357 conserva fuente/tests exactos de
68bfe74bfa8e5dd079a89531c322a1166b31177c. Referencia limpia antes de este
registro documental: cb3d8805a9890fab0357b0ba3a3f7afaa8577586,
tree 09ce69a049594006f990ade6004ef1e90be5c591.

El kernel del host confirma un OOM memcg el 10-oct a las 08:31:31 Madrid en
el cgroup docker-c17930611803ca55b06d953303c14072b245e0f4a0c90bec95094c7bd7998a3e
(auxiliary): límite/uso 262144 kB, Python PID411741 eliminado, anon-RSS
257008 kB y file-RSS 10368 kB. El digest falló con returncode=-9 a
06:31:32.291 UTC. Coinciden contenedor y tiempo; la etapa concreta que disparó
el pico sigue unavailable. Evidencia conservada en ef99/audit_oct10_oom_kernel.txt.
El supervisor está vivo con heartbeat fresco: healthcheck_all falla por el
estado diario failed, no por supervisor muerto. No se ha borrado ni cambiado
ese estado ni ejecutado retry/restart para forzar salud.
Seguimiento histórico del scheduler: su cgroup actual tiene oom=0 y
oom_kill=0, pero el journal del kernel identifica OOM anteriores en el mismo
ID 7e56adccf3aca898043ab00392eba1281a3ad58c37fca3067b8833305620770b:
9-oct 00:24:04, 21:31:31, 22:25:25, 23:47:27 Madrid; 10-oct 03:38:56 y
05:28:22 Madrid. Último proceso eliminado: anon-RSS 2062436 kB, file-RSS
35456 kB; arranque actual a 05:28:23.655 Madrid. Esto vincula fuertemente el
último reinicio a OOM del scheduler, separado del auxiliar. No certifica la
causa de los 13 reinicios ni la función que acumuló memoria. Docker no
conserva eventos útiles; OOMKilled=false actual no descarta historia OOM.
Evidencia ef99/audit_oct10_recent_kernel_ooms.txt y docker inspect del mismo
ID. Auditoría readonly separada asignada a Luna para correlacionar fases/logs
y proponer corrección mínima sin tocar servicios ni usar datos productivos
en tests. Su dictamen todavía pendiente.

Schedule-status real 09:09:12 UTC: XNYS cerrado, próxima apertura 12-oct
15:30 Madrid; runtime unavailable por WAL. SELECT acotados mediante
Store.read_connection, cierre explícito, a 09:11:48 UTC confirman los 18
job_status consultados terminales completed/skipped y sin entradas lease/retry
en el ámbito consultado. Paper=true, mode=paper, live=false, auto_apply=false.
La consulta inicial usó un atributo inexistente en la sonda y falló antes de
abrir conexión; se corrigió solo la sonda. Evidencia ef99/audit_oct10_runtime_1115.json.
La sesión 9-oct sigue failed terminal, con evidencia previa a 03:29:55 UTC;
los skipped del sábado no la sustituyen. No había pytest/smoke local activo
antes del smoke. Estas comprobaciones permiten QA aislada; no acreditan salud
operativa suficiente para despliegue.

QA .357: primer fullsuite 1 failed, 1313 passed, 105 warnings en 229.58 s;
segundo intento 1 failed, 1313 passed, 105 warnings en 190.54 s. Ambos fallan
antes del target de los hijos Windows: shim temporal del lanzador externo,
NameError: __args is not defined; queue.Empty es consecuencia. El test
multiproceso no cambia frente a 1adc3cec. No son suites aprobadas, ni se
atribuye automáticamente este fallo a bloqueos históricos diferentes.
Evidencias ef99/release_oct10_0357_full.txt y
release_oct10_0357_full_spawn_safe.txt, con journals separados.
El primer ajuste del lanzador pasó un focal (1 passed, 5.72 s), pero resultó
insuficiente en fullsuite. La nueva entrada absoluta verificable, con guards
heredados y comprobación de __main__.__file__ por setup, pasó los siete tests
del archivo de concurrencia en 15.38 s; sin cambiar tests ni usar skips/xfail.
Artefacto ef99/validate_oct10_isolated_entry.py, SHA256
DF5218BC30184933D6D6EC4F6AF7CC2B5F029302539A72F0ADFB47FD3046157F.
Evidencia ef99/release_oct10_entry_focal.txt y journal. La suite completa
final permanece pendiente; no repetir el mismo lanzador fallido sin nueva causa.
Smoke local .357 run-once --skip-crew y validate-agent-config: passed,
proveedores locales, DATA_DIR temporal, _env_file=None, red bloqueada,
cleanup passed. Evidencia ef99/release_oct10_0357_smoke.txt. Kernel productivo
no se ha sellado ni cambiado; no confundir este smoke con prueba ARM.

Auditoría de memoria .357: streaming de decision_context reduce su pico
tracemalloc de 118.72 MB legacy a 1.45 MB con fixture temporal de 50k filas
por fuente y paridad observada. Persisten listas grandes en digest, comparable
controls y otros helpers. La importación eager de main carga 1518 módulos.
RSS Windows no equivale a memcg Linux: ninguna medición sintética prueba que
el digest completo cabe en los 256 MiB productivos.
Lote aislado .358 reservado a Luna en bolsa-digest-oct10/agenteBolsa, desde
cb3d8805: despacho compartido del digest para evitar la importación eager del
main en supervisor, sin duplicar negocio, tocar protegidos ni añadir servicio.
Implementación, paridad, medidas por etapa y revisión root pendientes. No está
integrado ni desplegado. Criterio de aceptación: preservar salida/errores/safety,
cierre Store y órdenes/economía; declarar picos residuales, sin recortar datos
ni elevar límites para aparentar solución.

Siguiente secuencia: revisar el lote aislado de memoria y sus evidencias;
resolver el lanzador de QA con evidencia completa; validar una vez el árbol
funcional final, Ruff/NUL/diff, configuración/kernel y smoke; preparar prueba
ARM y recuperación revisable. Revalidar todos los gates antes de producción.
Salud auxiliary, diagnóstico de reinicios y riesgo de OOM residual siguen
pendientes. Sin órdenes, cambios de riesgo, configuración, históricos, locks,
push, reinicio, sellado ni despliegue en esta continuación. La revisión
read-only del 12-oct queda intacta.

## Resultado del intento retomado — 10-oct, 10:38 Europe/Madrid

Dictamen `precondition_not_met`. No se desplegó .357 ni se ejecutó sellado,
build, suite completa, smoke, reinicio, orden o reparación productiva. La
automatización de despliegue se pausa al concluir este intento; la revisión
del 12-oct se conserva. Las aprobaciones de los dos parches y del sellado
posterior a QA siguen vigentes, sin ampliar el alcance.

Preflight real por SSH: XNYS cerrado, próxima apertura 12-oct 15:30 Madrid.
Los tres servicios siguen en agente-bolsa:0.4.321-arm64, imagen
sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae.
Scheduler healthy, RestartCount=13, OOMKilled=false; web healthy,
RestartCount=0; auxiliary unhealthy, RestartCount=0, OOMKilled=true.
El contador OOM prueba un estado observado, no identifica su causa ni la hora
del episodio. La salud no pasa y bloquea el intento antes de QA/despliegue.

Kernel actual ok, violations=[], paper=true, live=false, auto-apply=false.
Carrier declarado conserva SHA256
4e60333c92b037c58a20c2cc94e6b252ffffdac9b912ab2740e3103454d5827f.
Schedule-status devuelve runtime unavailable por WAL: no acredita quietud.
SELECT acotados mediante Store.read_connection, cierre explícito, confirman
postmarket de la sesión 9-oct terminal failed a
2026-10-10T03:29:55.697543+00:00, stage_postmarket_report_failed. Evento asociado
pmr_ef2dfa7a798f, TypeError de comparación NoneType/int. Esto es compatible
con el defecto local ya corregido en el candidato; no se obtuvo traceback
remoto que demuestre la función exacta. Sesión civil 10-oct aparece skipped
market_not_ready (sábado) y no sustituye al terminal de la sesión 9-oct.
Market_cycle y portfolio_watch consultados estaban skipped; ausencia global
de todos los jobs, leases, retries y procesos sigue sin certificar. No se
continúa investigando ni reparando el runtime después del gate de salud fallido.

El intento de preparación del 9-oct fue interrumpido por el revisor automático
al alcanzar el límite de uso: la escritura final, commit documental y paquete
no se ejecutaron. Era un fallo de revisión, no un dictamen de inseguridad.
En esta reanudación las lecturas autorizadas y la documentación vuelven a
estar disponibles. Los tres cambios documentales pendientes eran propios del
lote; no había cambios de fuente, tests ni archivos ajenos. Se preservaron.

Candidato funcional 0.4.357: HEAD 68bfe74bfa8e5dd079a89531c322a1166b31177c,
tree 35a7d0c7b64c7eba1cbaae88985923ba829a0ab3. Los commits posteriores a esta
identidad son solo documentación; comprobar diff src/tests antes de heredar
las 27 focales en 2.20 s y Ruff/NUL/diff verdes. Fullsuite, smoke, ARM, preflight
válido, sellado y doble salud siguen pendientes. No existe paquete .357
completado; el .356 no representa los parches protegidos nuevos.

Siguiente gate: diagnóstico separado del estado unhealthy/OOM y del aumento
de reinicios, con evidencia de procesos, logs y recursos y causa contrastada.
Después, en un intento operativo nuevo, volver a verificar todos los gates
antes de la QA completa y del despliegue ya autorizado. No aumentar riesgo ni
forzar servicios/locks para superar estas condiciones.

## Estado vigente — 9-oct, .357 con los dos parches aprobados

Dictamen `needs_final_validation`, no desplegado. El operador aprobó ambos
parches concretos y el sellado canónico intencional tras QA mediante «Tienes mi
ok». Esta aprobación sustituye los bloqueos de revisión humana de las notas
inferiores; no amplía el alcance a otros protegidos, política u órdenes manuales.

HEAD funcional 68bfe74bfa8e5dd079a89531c322a1166b31177c, tree 35a7d0c7b64c7eba1cbaae88985923ba829a0ab3, versión 0.4.357.
La revisión independiente compara byte a byte broker.py y execution.py con
el resultado exacto de los parches aprobados sobre f758d72d. Son los únicos
protegidos distintos de 1adc3cec; kernel.py, risk.py, config.py y .env intactos.
broker.py SHA256 7656e0beb1edafbe2b648e5472d0047a80826a39d6be56f0465cd2d9366a0248.
execution.py SHA256 e3b46b5b60f91aed7bca089761486312724168766415f749ccee78a44d8d3594.

El adaptador devuelve Enum.value y conserva strings/defaults. La salida SELL
con checks.trigger=partial_take_profit_v2 utiliza la petición existente con
la cantidad del plan; el trigger nested no se añade como autoridad. Los demás
cierres completos conservan close_position y los controles previos del kernel.
No se reescriben históricos ni se afirma un fill real a partir de un cliente falso.

QA focal de este árbol: Root: 27 passed en 2.20 s sobre 53975985, SDK real y red bloqueada.
Evidencia ef99/release_oct09_0357_protected_focal.txt y
ef99/release_oct09_0357_protected_focal_journal.jsonl. El commit 68bfe74b solo
ordena imports (Ruff), sin cambio de fuente ni lógica; se hereda esa evidencia.
La regresión significativa sustituye la prueba aritmética descartada. Un test
previo de política de versión pasó; fullsuite todavía pendiente.
Ruff src/tests, NUL (548 archivos) y git diff --check verdes.
Paquete local .357 pendiente; rutas reservadas para un intento posterior: ef99/release_oct09_0357_sources.zip, con su identidad y SHA256 en
ef99/release_oct09_0357_bundle.json. Es fuente revisada, no imagen, QA ARM ni
prueba de despliegue.
La evidencia .356 no sustituye las comprobaciones afectadas de .357. Fullsuite
única, smoke aislado, configuración/kernel, preflight y prueba ARM siguen
pendientes. Python del proyecto, PYTHONPATH exacto, DATA_DIR temporal,
_env_file=None y proveedores locales son obligatorios; sin broker/red/LLM ni
datos productivos desde tests. No repetir suites idénticas sin causa nueva.

Schedule-status real a las 21:17 Madrid: XNYS abierto, cierre previsto 22:00.
Producción sigue .321, kernel ok, paper=true, live=false y auto-apply=false.
Carrier real /run/secrets/application.env: SHA256
4e60333c92b037c58a20c2cc94e6b252ffffdac9b912ab2740e3103454d5827f,
igual al declarado; se comprobó sin imprimir contenido. Evidencias en ef99:
audit_oct09_seal_carrier.json y audit_oct09_carrier_root_hash.json.

El contenedor vivo usa UID1000, cap_drop ALL y no-new-privileges: ejecutar
get_settings como UID0 falló por acceso a /data. No se selló ni se cambiaron
permisos. Para el sellado autorizado usar el procedimiento canónico de
contenedor efímero limitado documentado en informe_codex_p_l89_raspberry_docker
(sección de despliegue .244), con fuente final y carrier real; no copiar un
manifest temporal, editarlo a mano ni relajar la configuración de los servicios.
Comprobar que env y kernel.py siguen iguales antes y después, y que solo se
incorporan los hashes aprobados de broker.py/execution.py.

Intento a las 22:45 Madrid: exigir XNYS cerrado, postmarket de HOY completed o
failed, ningún job/retry/lease/pytest/despliegue activo, salud, flags y margen.
WAL/runtime unavailable no demuestra quietud. Si falla un gate operativo:
precondition_not_met y pausa del intento, sin reparación o parada implícita.
Después de QA y gates, despliegue incremental sobre imagen .321 con rollback,
verificación de fuentes, doble salud >=75s y observación OOM600s. Nada de build,
transferencia, sellado o corte antes de las 22:45. Automatización ACTIVE conserva
la aprobación; pausar al concluir ese intento. Revisión del 12-oct intacta.

APO protección/origen no certificado y LLM402 siguen pendientes; esta release
no prueba resolución ni autoriza órdenes, pagos, cambios de proveedor o riesgo.
Los resultados futuros deberán confirmar comportamiento y economía reales.

## Estado vigente — 9-oct, candidato combinado .356 para las 22:45

Dictamen `needs_final_validation`, no desplegado. HEAD funcional probado
7db0790b2f87214f291f603db470a3c97faa50b7, tree
e657e7eb9ffba7a252aa2f70db066349787965e9, versión 0.4.356. Esta sección
sustituye el estado actual de las notas inferiores, que conservan su historia.

Integración aislada --no-ff: PMR null-safe 38deb622 mediante 20533c4b y streaming
bd2dad81 mediante 7db0790b. Conflictos solo de plan/relevo/versión: se conservaron
ambos documentos/comentarios y se reservó .356. Fuente protegida intacta.

Revisión independiente corrigió una discrepancia de paridad en coverage para
decision_source ausente/falsy y el cierre al fallar PRAGMA antes de integrar.
El defecto None/int de _learning_candidates está reproducido localmente;
atribución al fallo productivo8-oct permanece inferida, sin traceback remoto.
No ocultar el fallo ni decir que la sesión se recuperó por tener un parche.

QA nueva del árbol combinado: **73 passed en 4.69 s**, exit0, Python del proyecto,
PYTHONPATH exacto, DATA_DIR temporal, _env_file=None, red externa bloqueada.
ef99/release_oct09_0356_focal2.txt y focal_journal2.jsonl. Primer intento tuvo
error de ruta de test y no ejecutó pruebas; no se contabiliza como validación.
Ruff src/tests verde, NUL548 verde, diff verde; seis archivos protegidos iguales a 1adc3cec.
No sumar 73 a las 152 anteriores solapadas ni declarar fullsuite/smoke aprobados.

Fuentes activas inspeccionadas el 9-oct: 205 Python, 204 exactas a 1adc3cec; init solo
comentario traducido deP-L155/newline, versión.321idéntica. Diferencia .340 no
se porta ni se usa como base productiva. Evidencia ef99/audit_oct09_source_*
y audit_oct09_live_init.txt. Hashes exactos de imagen en estudio9-oct.

Paquete LOCAL de 13 fuentes modificadas: ef99/release_oct09_0356_sources.zip,
sha256 7491ca944a1313d5dd53247a0e3907cdf62a96347867d768ed8b61734b02dc76.
Manifest incluye HEAD/tree/hash por archivo; no es build ni pruebaARM ni despliegue.
Scripts preparación enef99: prepare_oct09_source_bundle.py,
validate_oct08_isolated.py, smoke_oct08_isolated.py. Tras cualquier cambio
semántico, invalidar paquete/evidencia afectados y fijar versión única nueva.

Gates: fullsuite única del árbol final, smoke aislado, config/kernel/paridad N3,
XNYS cerrado y PMR9 terminal, no jobs/retries/leases/pytest activos, salud yflags,
recursos/margen; al desplegar verificar imagen/fuente y doble salud >=75 s.
No efectuar build/transfer/corte antes de las 22:45 ni forzar jobs/locks para superar gates.

Broker enum sigue pendiente de revisión humana explícita de parche y sellado.
No aplicar ni sellar mientras falte respuesta. Antes de aceptar el candidato
N3 (incluye recuperación selectiva de BUY de.352), contrastar exposición real
con la ruta de riesgo: una exposición long incorrectamente cero es un bloqueo
de seguridad, no debe ignorarse por ser preexistente ni compensarse elevando
límites. No desplegar un gate nuevo con esa inconsistencia sin resolver.

APO: protección/origen por auditar, no órdenes autorizadas desde este estudio.
FTNT: auditar salida/reentrada por IDs yprecio/condición nuevos, no introducir
cooldown ni umbral activo sin evidencia. LLM 402 requiere saldo/operador, no
pagos/config/credenciales modificados. Automatización 22:45 ACTIVE; revisión 12-oct
intacta. Al final del intento 22:45 pausar automatización y reportar resultado real.

### Gate de ejecución añadido tras auditoría FTNT

La salida exacta FTNT, plan risk_exit_922928607a7f, broker order
f0b1691d-b7af-4be2-aba0-d54439c7e965, registra qty=2.5 en el plan y fill=5.
El trigger estructurado es partial_take_profit_v2. La discrepancia permanece
sin explicación causal: revisar carrier de submit y respuesta, no concluir
sobreejecución únicamente por un payload histórico. Si la cantidad aprobada y
la enviada/ejecutada difieren realmente, es un bloqueo N3 antes del despliegue.
Auditoría exacta y seguimiento: ef99/docs/informe_oct09_exit_followup.md.
No se modifican ejecución protegida ni órdenes para resolverlo implícitamente.
La antigüedad de 9 días corresponde al origen BUY de niveles EXIT; no es la
edad de la señal de reentrada. El contraste entre captures y signal_outcomes
requiere verificar el contrato de autoridad antes de afirmar corrupción.

### Propuesta N3 preparada, pendiente de revisión humana específica

La frontera de salida parcial se reproduce localmente: _is_full_position_exit
ignora qty y trata action=exit como cierre completo. Propuesta mínima: para
checks.trigger exacto partial_take_profit_v2, devolver False para usar la
petición market existente con qty del plan. No usar el trigger nested como
segunda autoridad; cierres stop/time/trailing y controles previos permanecen.

Parche ef99/proposed_oct09_partial_exit.patch SIN aplicar; junto al parche
Enum de broker se presentó revisión humana específica y sellado tras QA.
Mientras falte respuesta no editar protegidos ni sellar ni aceptar la release
con esas inconsistencias N3. La nueva solicitud reúne ambos parches.

Caracterización independiente v6 con Python del proyecto y SDK Alpaca real,
Settings _env_file=None, DATA_DIR temporal y red bloqueada: qty2.5 enviado
como2.5, controles completos preservados y kernel bloqueado sin llamadas.
Evidencia ef99/audit_oct09_exit_followup_boundary_v6_project_sdk.json.
La prueba v5 anterior usaba emulación en otro intérprete: no heredar su
afirmación de SDK ausente al Python del proyecto. GET paper separado de tests
confirma FTNT fractionable=true, no certifica aceptación histórica.

Al aprobarse, implementar ambos parches mínimos con versión única final,
caracterizaciones/regresiones N3 y fullsuite/smoke del árbol definitivo;
invalida el paquete .356 si cambia source. No promoción ni nuevas órdenes.

## Preparación autorizada — 9-oct, despliegue objetivo 22:45 Madrid

El operador autoriza continuar las mejoras del estudio y desplegar el 9 de
octubre a las 22:45 Europe/Madrid. Automatización
`validar-mejoras-bolsa-tras-cierre` reactivada y actualizada para ese intento;
antes de la hora no hace cambios productivos. Revisión del 12-oct intacta.

Base de preparación limpia: HEAD 7d4f4bc1f54d45fca9f6cc62867f4ddf9b6d80a1,
tree 011cdf6b9608e1e8e71aba80b29b4f36169a1b3a, versión .352. El árbol funcional
ya probado sigue siendo 7dce37e1/0ec3540e; no repetir focales existentes
salvo cambios semánticos posteriores. Fullsuite y smoke siguen pendientes.

Sonda real 20:36 Madrid: XNYS abierto, cierre 22:00, lock scheduler PID7 vivo
y token coincidente. schedule-status runtime unavailable por WAL no certifica
quietud; al corte usar Store.read_connection y cerrar explícitamente lectores
para comprobar estados/leases, además de procesos y logs. Sin reparaciones
implícitas de locks ni trabajos manuales para forzar el cierre.

Estudio nuevo ef99/docs/informe_oct09_resultados_oportunidades.md: broker GET
20:09 Madrid, equity70195.73USD, efectivo89.22%, exposición10.78%. Imagen
activa .321, sin despliegue de .352. PMR8 terminal failed 22:25:38UTC por
TypeError None/int, distinto de una recuperación completada; PMR9 aún no
terminal válido. Fallos402 por saldo proveedor siguen presentes; no pagos ni
credenciales/configuración autorizados. 8 reinicios scheduler; auxiliar unhealthy;
no atribuir causa sin evidencia ni declarar salud recuperada por documentación.

Lotes aislados asignados conforme AGENTS a Luna gpt-5.6-luna/xhigh:
- .353: oct08-digest-memory-audit, rama codex/oct08-context-streaming,
  continuar cambios del lote anterior; stream RO y acumuladores con paridad,
  mismos límites y snapshots per-query. Sin integración hasta QA/revisión.
- .354: oct09-postmarket-null, base exacta anterior, diagnosticar traceback y
  caracterizar None/int; no asumir que el antecedente P-L57A sea la misma causa.
  Solo bug fix mínimo, métricas ausentes unavailable, sin histórico/trading.

Parche protegido propuesto en ef99/proposed_oct09_broker_enum.patch:
normalizar Enum.value en tools/broker.py conservando strings/None. Defecto
caracterizado con SDK real y proveedor falso: exposición0 frente a0.1 esperada.
PENDIENTE revisión humana explícita del parche y autorización de sellado
canónico intencional. La pregunta se ha presentado con las dos reglas exactas;
no asumir respuesta por tiempo transcurrido. Mientras falte, no aplicar ni
integrar ni sellar este lote. Si se autoriza, caracterizar también OrderSide,
OrderStatus, OrderType y paridad de cantidades/precios/órdenes; N3 completo.

Secuencia restante: recoger lotes y revisar diffs exactos, merge --no-ff aislado
sin cambios ajenos, fijar versión única final; QA del árbol funcional definitivo
y gates completos en ventana permitida. Deploy no antes22:45 por procedimiento
docs/despliegue_jetson_autonomo.md. Comparar fuente/hash con imagen viva y base
exacta1adc3cec; no portar a ciegas diferencias .340. Mantener .env/config,
datos e históricos; rollback conserva imagen .321. Doble salud >=75s y
observación recursos/OOM según runbook, sin atribuir OOM por correlación.

Si falta cualquier precondición: precondition_not_met y detener el intento sin
forzar jobs, borrar locks ni arrancar/desactivar gates para hacerlos pasar.
No órdenes ni cambios de riesgo/política de reentrada desde este estudio.
Reentrada FTNT, edades señal/precio y oportunidades descartadas necesitan
replay con costes y evidencia futura antes de promoción.

## Estado vigente — 8-oct, integración nocturna .352

Dictamen: `needs_final_validation`, no desplegado. Candidato funcional limpio
HEAD `7dce37e1b4464a696daaff5de65468c889396296`, tree
`0ec3540e44b2ef5f3fb1019c523ad15819095f3b`, versión `0.4.352`.
Esta sección sustituye los estados operativos y tareas abiertas de las entradas
históricas inferiores; no cambia su evidencia ni convierte pruebas antiguas en
validación del árbol actual.

Integrados ahora: controles de misma fecha `.351` (fbf01db9), reutilización de
listas del digest `.349` (acbdbf91) y salud selectiva `.350` (35c01d0d).
Merges separados --no-ff; conflictos de versión resueltos campo a campo a .352.
Salud conserva el carrier order_linkage anterior. La revisión independiente
aprobó el merge acotadamente sobre este HEAD/tree, sin repetir pruebas.

QA combinada nueva por los cambios semánticos: **152 passed en 19.20 s**,
proceso terminal exit0. Incluye salud/frescura, P59C, P80B, comparable controls,
scoreboard, digest reuse/phase3/P4/overlay y linkage. No se suma a baterías
anteriores solapadas ni equivale a fullsuite. Harness validate_oct08_isolated.py:
Python del proyecto, PYTHONPATH exacto, DATA_DIR temporal, _env_file=None y red
externa bloqueada. Evidencia ef99: goal_fix_0352_combined_focal.txt y
 goal_fix_0352_combined_journal.jsonl. Ruff completo verde; NUL547 verde;
diff limpio; los seis archivos protegidos Git idénticos a base1adc3cec.

Los controles de fecha sí cambian el emparejamiento de evidencia de aprendizaje:
rechazan fechas ausentes, inválidas o distintas, conservando rows originales.
No escriben ni promocionan históricos. Digest elimina dos lecturas/materializaciones;
no prueba una solución definitiva del OOM ni paridad bajo escrituras concurrentes.
Salud es N3: cambia intencionalmente el gate de BUY para recuperar únicamente
`data_pipeline_down:market_data` con captura aware posterior fresca de la sesión
actual. Preserva otros críticos/overrides y rechaza fechas/mtime futuros. No se
atribuye paridad BUY ni mejora económica a este cambio.

Producción verificada 22:38–22:41 Madrid: los tres servicios .321, imagen
sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae.
Scheduler/web healthy; auxiliary unhealthy. Último snapshot de cuenta21:57:
equity70000.03USD, apertura70058.49USD, delta-58.46USD/-0.0834%, provisional,
no neutral a flujos; efectivo62631.66USD,9posiciones,1orden abierta. Una compra
AMD1acción fill638.88USD, señal a plan25.16min. SPY/EOD/costes/flujos de hoy:
unavailable. Fuente ef99 audit_oct08_close_*.json/txt; informe provisional allí.

Preflight22:39 confirma XNYS cerrado y próxima apertura9-oct15:30. PMR8 sigue
sin terminal completed|failed; skipped21:29 market_not_ready es anterior al
cierre. last_session5-oct. Runtime sin running no demuestra pool quieto:
logs22:29:53 muestran max_instances para postmarket, reconciliación y estudios.
Docker inspect posterior registra scheduler running, StartedAt19:50:14UTC,
RestartCount6; no se atribuye ese reinicio a una causa no demostrada ni a estas
acciones. Consulta acotada de eventos Docker19:35–20:00 no devolvió eventos;
no demuestra ausencia histórica de OOM. Evidencia goal_fix_0352_live_scheduler_tail.txt.

Presión de memoria medida anteriormente esta noche: scheduler casi2GiB y
~1.9GiBswap; oom=0/oom_kill=0 del cgroup consultado no identifica causas de
reinicios anteriores. Auxiliarci_digest returncode-9 y oom_kill1 agregado:
causa exacta/pico no probados. LLM principal402 saldo insuficiente: estado de
cuenta solicitado al operador, sin respuesta; no pagos ni credenciales cambiadas.

Gates pendientes: fullsuite única del árbol definitivo, smoke aislado y gates
config/kernel, paridad proporcional y preflight operativo completo antes del
build/corte, doble salud tras despliegue autorizado. La interacción multiproceso
de la suite anterior sigue sin causa demostrada; timeout45s evita espera infinita,
no la resuelve. No repetir suites sobre el mismo árbol sin nueva causa.

Validación completa/despliegue `precondition_not_met` por PMR8 no terminal y
quietud operativa no acreditada. No hubo build/transfer, corte, restart, órdenes,
configuración, cambios de locks/leases, reparaciones implícitas ni promoción.
Prioridad siguiente: completar QA cuando proceda o con excepción operativa
explícita; diagnosticar recursos/cierre y auxiliar sin forzar salud; cerrar saldo
LLM. La autorización de despliegue persiste, pero no se eluden estos gates.



### Relevo inmediato tras QA focal .352

HEAD documental b15e553160f89b2bbbebcfba5a3a11ab5da82a5d mantiene src/tests
idénticos al HEAD funcional7dce37e1 ya probado. Nueva lectura directa del PID7:
VmRSS1725200kB,VmSwap2057708kB,9threads,estado sleeping; cgroup
memory.current2146594816,memory.swap.current2107727872,max452174,oom0,oom_kill0.
Fuente ef99goal_fix_0352_live_memory.txt. El comando devolvió1 solo porque
/proc/pressure/memory no existe; los campos /proc/7 y cgroup sí se obtuvieron.
No inferir causa del reinicio ni pool quieto de ese estado sleeping.

Se ha solicitado al operador una excepción acotada al gate de AGENTS: ejecutar
fullsuite/smoke SOLO en Windows, sin producción, mientras PMR8 no es terminal.
Pendiente de respuesta: el tiempo transcurrido no equivale a autorización.
La pregunta de saldo LLM también sigue pendiente. No ejecutar esos gates
dependientes hasta respuesta o hasta cumplir todas las precondiciones.

Auditoría de siguiente optimización completada por Luna: propuesta de iteración
y acumuladores para decision_context_quality, sin editar el candidato ni reducir
históricos/denominadores. Requiere fijar snapshot/concurrencia y caracterizar
payload completo antes de implementación; ver informe_oct08_digest_memory_audit.
No confundir esa propuesta con un fix integrado.

## Evidencia adicional de QA y operación nocturna

Commit test-only c7619f57 acota Pool.map_async.get a45s en P49BR1; mantiene
las mismas aserciones de idempotencia/append-only y termina hijos por contexto
si vence el timeout. Focal1passed1.45s y Ruff/diffverdes. Evita espera ilimitada,
no demuestra ni oculta la causa del fallo multiproceso anterior.

Preflight22:20Madrid mantiene postmarket8 sin terminal válido. Lectura Docker
posterior: scheduler1.92GiB/2GiB96.02%,web698.8MiB/1GiB68.24%,aux42.68MiB/256MiB.
Logs20:01–20:15UTC registran skips por max_instances1 enwatch/fillwatch/lab.
La presión de memoria es observada; no se atribuye causa ni OOMscheduler sin
prueba. No se detienen procesos, cambian límites ni ejecutan jobs manuales.

Revisión independiente de fixtures: lecciones, overlays y copy/futurebar
aprobados acotadamente. P80B:4/4 negativos carecen de controlset verificado y
no aíslan filtros. Luna prepara QA separado con carrier canónico y positivos
comparables; si aparece fallo se conserva rojo y se clasifica, sin relajarasserts.
Timingllm_decisionfailed refleja ANYsegmentfailed en_refresh_stage de forma
intencional: no cambiarlo a completed para ocultar el primer intento fallido.

## 8-oct-2026, continuación nocturna: candidato .348 y producción .321

Dictamen `needs_fix`; no desplegado. Producción comprobada a las 21:18 Madrid:
los tres contenedores usan imagen .321 sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae.
Scheduler/web healthy; auxiliary unhealthy. El último preflight, 22:15 Madrid,
confirma XNYS cerrado, siguiente apertura 9-oct15:30, paper activo, live y
auto-apply false; no hay terminal postmarket de 8-oct todavía. La vista skipped
market_not_ready anterior al cierre no acredita haber completado el postmarket.
Validación completa/despliegue `precondition_not_met`; sin reparaciones implícitas.

Candidato integrado .348 HEAD funcional 1f88f1118751dc6a95662aba7bf92641452c9ecb,
tree c7003b371aa470921c8e6144a40268d083cd3785, limpio antes de esta nota.
Integra coordinación .344, linkage .345 (d235e862), fixtures uplift .346 y
scheduler grace .347. Conflictos de versión resueltos campo a campo a .348.
El rechazo anterior de revisión automática por cuota no ejecutó el merge;
la revisión volvió a estar disponible y la integración local ya está completada.
69 focales combinadas passed en 10.07s; 28 regresiones multiproceso passed en
23.63s. Son baterías distintas; no sustituyen la suite completa. Ruff src/tests
verde, NUL545 verde, diff verde y protegidos Git idénticos a base1adc3cec.
Los comandos iniciales con nombres inexistentes no ejecutaron ninguna prueba.

Diagnóstico previo del resto .343 terminó:22 failed,1232 passed,1 skipped,
1 warning en317.75s. Reproducción exacta base de esos22:21 failed,1 passed;
el único passed fue pin de versión. Correcciones de fixtures/copy comprometidas
en2f4f4da2,8abb0255,4e2eeab7,ef4ea0bd requieren revisión independiente.
El bloqueo anterior de suite multiproceso aún no tiene causa demostrada: los
28 casos relacionados pasan juntos en el candidato, pero no se atribuye solución
a captura off ni se oculta la interacción pendiente. Journal JSONL local probado
con69 casos; conservarlo en la futura suite definitiva para capturar fallos.

Auditoría de sesión, solo lectura:21:15 patrimonio69970.85USD frente apertura
70058.49USD, delta-87.64USD/-0.1251%, provisional, no neutral a flujos. Compra
AMD1acción fill638.88USD; no comparativa SPY diaria válida. LLM principal402
Insufficient account funds; fallback~27min. Tres bloqueos BUY de la ventana
reciente usan alerta data_pipeline_down de informe19:55 pese a snapshot20:47.
Esto acredita consumo de alerta anterior, no cotizaciones suficientes para operar.
Auxiliary:ci_digest falló08:34 returncode-9 y cgroupoom_kill1 con límite256MiB;
causa exacta del pico no demostrada. No borrar estado ni reiniciar para hacer verde.

Luna revisa aisladamente frescura de salud (N3:caracterización/propuesta sin
cambiar gates), memoria digest (auditoría sin fuente) y fixtures(test-only).
No promover ni aumentar riesgo. Prioridad: recoger dictámenes, corregir mínimos,
resolver interacción de suite y precondiciones; después QA definitiva y preflight
nuevo antes de cualquier despliegue autorizado. Configurar saldo del proveedor
requiere actuación de la cuenta; ningún pago/credencial se cambia desde aquí.

## Estado vigente — 8 octubre, 14:57 Madrid

Dictamen `needs_fix`, NO desplegado. Producción sigue .321; preflight read-only
14:41 Madrid: XNYS cerrado, próxima apertura 15:30, paper/live false/auto-apply
false, sin estados activos en jobs/leases consultados. No se hereda al corte.
La candidata .343 incorporó scoreboard v3; HEAD funcional validado focalmente
`ab28bd86193ef48a18d1f058e2f79492721c1412`, tree
`daa3f125e2da5b0504924dce5a6858764a9aa1f9`. Detalle del lote en
`docs/informe_oct08_scoreboard_contract.md`: 16 passed; base exacta 11 failed,
1 passed. Conserva dirección y contratos explícitos de control, sin inferirlos.
Ruff completo/NUL 544/diff verdes; protegidos idénticos a base 1adc3cec.

Learning_mode: el fixture chocaba con el veto tóxico vigente a score 18. Commit
test-only e0c90864 separa score 17 permitido de 18 vetado, `_env_file=None`;
12 pruebas del módulo pasan en 0.94 s. No cambia política. Smoke anterior:
la limpieza WinError 32 era del harness; logging.shutdown y gc.collect antes
del cleanup permiten salida 0, flujo completed, used_crew=false, fuentes
locales una vez y validate-agent-config ok. Evidencia goal_fix_smoke.txt en ef99.

La suite completa .343 iniciada 14:25 se interrumpió tras 1501 resultados
observados, 13 fallos, al bloquearse la prueba multiproceso p49br1. No hay
resultado completo ni gate verde. Se verificó un bucle de recreación de workers
sin avance de SQLite; se detuvo sólo el PID local 17212, inicio exacto 14:25:18,
y descendientes coincidentes. Producción no se detuvo. La prueba aislada pasa
con captura desactivada (1.44 s) y activada (1.43 s): la causa de interacción
en suite sigue pendiente, no se atribuye a la captura como hecho.

Los 13 IDs se recuperaron de los marcadores conservados y colección exacta
(2756 casos). Diagnóstico focal: 9 failed, 4 passed en 22.91 s. Cuatro fallos
multiproceso no reaparecen aislados; nueve restantes: lecciones (1), uplift
LLM (3), linkage de órdenes (4), misfire (1). No se ocultan ni se suman baterías
solapadas. Evidencia ef99: goal_fix_0343_fullsuite.txt,
goal_fix_0343_hung_workers.json, goal_fix_failed_nodes.txt,
goal_fix_failure_diagnostics.txt. Diagnóstico de los 1255 nodos no alcanzados
en ejecución, con fuentes temporales y salida visible; no equivale a fullsuite.

Lecciones: reproducido sobre base exacta 1adc3cec. El fixture destilaba
HYPOTHESIS y esperaba degradación reservada a ACTIVE/WEAKENED. Commit test-only
2f4f4da2 comprueba primero que revalidar no promociona hipótesis, crea fixture
explícito ACTIVE y exige transiciones ACTIVE→WEAKENED→RETIRED con ventana
posterior 3/10; 7 passed en 1.69 s, Ruff focal/diff verdes. Fuente intacta.

Lotes aislados en revisión: .344 identidad de recuperación postmarket,
.345 enlace exacto de órdenes, .346 uplift LLM. .347 restaura misfire
documentado 300/120/120; 1 focal y 27 regresiones pasan. Informe propio
`docs/informe_oct08_scheduler_grace.md` en su worktree: todavía no integrado.
Ese cambio sí permite ciclos con retrasos de 120–300 s, no se afirma paridad
temporal. Ningún lote cambia protegidos/configuración ni reescribe históricos.
Pendientes: cerrar causas/QA de todos, integrar con revisión, fullsuite del
árbol definitivo y gates afectados, nuevo preflight y doble salud del despliegue.
Autorización de despliegue recibida; sin build, corte, restart, deploy ni push.

## Antecedente: cierre de gates tras recuperación — candidata 0.4.342

Estado de entonces: recuperación operativa completada; release `needs_fix`, NO
desplegada. HEAD funcional `0e8712b02aea10ecd8300a41f449fdd61f21b456`, tree
`20ef2ed37d24685bf78513fc16c8377166870274`, checkout limpio antes de esta nota.
Reserva 0.4.342 tras observar artefactos .340/.341-web; no cambia la imagen activa.

Se explica y corrige el fallo económico anterior sin debilitar las aserciones:
el único campo diferente en la comparación recursiva True/False era
payload.decision_context_snapshot.agent_contract.as_of, por reloj no congelado.
Commit test-only 9ea28f48 congela datetime en el productor decision_context del
fixture y fija _env_file=None en su Settings. Se preservan todos los campos
comparados, incluido as_of, IDs, hashes externos y economía. Prueba económica y
regresión del normalizador: `2 passed in 0.68s`; Ruff focal verde. No se cambia
trading ni configuración para lograr paridad. Commit 0e8712b0 reserva versión.

Linaje de imagen: manifiesto read-only de los 205 módulos Python activos contra
base 1adc3cec, SHA256 normalizando CRLF a LF: 204 coinciden; sólo difiere
__init__.py, sin módulos extra. No equivale a identidad del árbol completo ni
certifica data/config. Los tres core declaran imagen .321; carpetas .340/.341-web
no prueban despliegue. Evidencia active_oct08_source_manifest.json en ef99.

Suite completa -x intentada sobre .342, con Python del proyecto, PYTHONPATH
exacto, DATA_DIR temporal, Settings sin .env implícito y bloqueo de red externa:
`1 failed, 638 passed, 1 warning in 107.73s`. Primer fallo:
tests/test_learning_mode.py::test_learning_mode_relaxes_partial_market_state_only_when_enabled,
assert len(allowed)==1, observado 0. Reproducido focalmente sobre archive de base
exacta 1adc3cec en otro temporal: `1 failed in 1.38s`, mismo assert 0==1.
Clasificación: fallo preexistente, no aprobado ni ocultado. No se modifica
política activa para hacer pasar una expectativa de relajación. Queda por
determinar si el fixture está obsoleto o el contrato tiene un defecto.

La primera invocación del bootstrap no colectó por importar scripts desde ef99;
se corrigió sys.path para equivaler a python -m pytest desde el candidato.
Sólo después se ejecutó la suite anterior. No se repite la suite tras su fallo.
Ruff completo: All checks passed; NUL: OK (544 archivos); diff --check verde.
Los 638 casos no se suman a baterías focales solapadas.

Smoke aislado del handler run-once --skip-crew --quiet, fuentes locales para
snapshot y market_state, red bloqueada, SQLite temporal y Settings(_env_file=None):
el ciclo devolvió used_crew=false y llegó a completed; fuentes llamadas una vez.
La salida declaró smoke passed, pero el proceso acabó con WinError 32 al limpiar
el log abierto por configure_logging en Windows. Se clasifica separado como
fallo de limpieza del harness; no se declara gate smoke global verde. No hubo
red, LLM, broker ni datos productivos desde pruebas.

Evidencia local en ef99: validation_oct08_fullsuite.txt,
validation_oct08_base_learning_mode.txt, validation_oct08_ruff.txt y
validation_oct08_smoke.txt; harness validate_oct08_isolated.py. No build, parada,
reinicio ni despliegue. No push. La autorización de deploy sigue recibida;
primero resolver el fallo base con su contrato y completar gates pendientes.
Antes del corte habrá que repetir el preflight real, no heredar indefinidamente
la ventana cerrada ni el estado de jobs de esta recuperación.

## Recuperación operativa autorizada y completada — 8-oct, 13:57 Madrid

Autorización humana explícita en este chat: «Autorizo», para el alcance de
recuperación controlada presentado. Resultado `resolved`. Se comprobó otra vez
XNYS cerrado, flags paper/live/auto-apply, ausencia del PID 6, ausencia de lease
global y terminales failed exactos antes de escribir. Se respaldaron las dos
filas y sus terminales en archivo exclusivo con fsync y hash SHA256
`25515f1fe48c0b054c1d8264d9b00c09cac7930269bda7a1549681528bfd9d20`:
`/data/reports/oct08_runtime_before_25515f1fe48c0b054c1d8264d9b00c09cac7930269bda7a1549681528bfd9d20.json`.

Una sola transacción BEGIN IMMEDIATE corta, timeout 2 segundos, revalida los
bytes exactos de ambas filas y la ausencia del propietario. Compare-and-swap
marca failed/terminal la vista de sesión 7-oct conservando su identidad original,
y elimina únicamente el lease de reconciliación antiguo. En la misma transacción
inserta el evento append-only
`operational_state_recovered:oct08:25515f1fe48c0b054c1d8264d9b00c09cac7930269bda7a1549681528bfd9d20`.
No sobrescribe eventos, ni corrige retroactivamente el terminal mal etiquetado.
last_session sigue 5-oct. No ejecuta aprendizaje, broker, órdenes ni reinicios.

Script operativo revisable `recover_oct08_runtime.py` en el checkout ef99;
modo plan previo sin escritura, recibo `recovery_oct08_receipt.json` y lectura
posterior `recovery_oct08_postflight.json` en ese mismo checkout. Cuatro pruebas
locales con SQLite temporal: resolución e idempotencia, propietario reaparecido,
rollback de ambas vistas si falla la evidencia y preservación de cambio
concurrente. `Ran 4 tests in 0.052s, OK`; Python del proyecto, sin red/proveedores
productivos desde tests. El script no se incorpora a la imagen candidata.

Postflight: sesión 7-oct failed/terminal; claves global active y reconciliation
ausentes. No statuses started/running/active encontrados en los registros de jobs
consultados. Kernel-status productivo ok true, violations vacías, cuatro hashes
sellados coinciden; validate-agent-config ok true, errores y warnings vacíos.
Esto resuelve el bloqueo operativo de vistas, no demuestra postmarket completo
ni despliegue del candidato.

Siguiente gate investigado: una ejecución focal de diagnóstico de
`test_economic_parity_true_false_none_identical_payloads` en el ensayo devuelve
`1 failed in 2.56s`, `rec_payloads difiere True vs False`. Es el fallo de base
ya documentado, ahora contrastado al retomar release; no se trata como aprobado.
El fixture StoreSpy carece de record_agent_event/record_append_only_event y se
observan errores de telemetría; la diferencia exacta de payload aún no queda
explicada. No se altera código ni se debilita la aserción para desplegar.
Dictamen actual de release `needs_fix`; suite completa, smoke, identidad
.321/.340, reserva/bump y paridad completa siguen pendientes. Producción sigue
ejecutando la misma imagen .321: no build, corte, despliegue ni reinicio desde
esta intervención. Compose activo apunta a releases/0.4.297/deploy; las carpetas
.340 y .341-web existen pero los tres contenedores core declaran imagen .321.
Las etiquetas de la imagen incluyen valores heredados .320 y source-revision
1adc3cec/source-tree 00e5bdeadf1a7d6cd9340e76fbd9b136c3583412; requieren contraste
de bytes antes de atribuir identidad exacta o reutilizar un número de release.

## Reanudación y diagnóstico de estados huérfanos — 13:40–13:42 Madrid

Dictamen de despliegue `precondition_not_met`, con causa ahora más precisa.
Contenedor misma imagen, RestartCount 5, nuevo arranque 11:38:24 Madrid;
scheduler PID 7/token 4898747 vivo. Causa del reinicio no determinada. XNYS
cerrado, apertura 15:30; paper true, live/auto-apply false. Candidato limpio
919ba2f8, sin nuevos cambios funcionales. Memoria puntual 1.507 GiB/2 GiB;
no prueba causal ni benchmark.

Ya no existe post_market_coordination:active. La vista de sesión 7-oct sigue
active para pmr_150611d46dd9, y reconciliación brkrec_056138f49ca5 sigue active.
Consulta exacta por cycle_id, mediante Store.read_connection: ambos runs tienen
terminal failed/owner_dead_recovered durable. El terminal del primero se creó
11:40:24 Madrid; el del segundo a las 02:48:56. /proc/6/stat ya no existe.
No son evidencia de trabajos todavía ejecutándose; no se limpian por inferencia.

Defecto verificado de identidad: el terminal del run pmr_150611d46dd9, que la
vista y su lease identifican como sesión 7-oct, declara session_date 8-oct.
PostmarketCoordinator.acquire utiliza session_date del adquirente al construir
el evento recuperado; no toma la sesión del propietario antiguo. Su ruta también
puede recuperar como postmarket_run un antiguo run de reconciliación, y dejar
la clave de reconciliación antigua. No se afirma que causase el reinicio ni el
database is locked. Los eventos append-only existentes no deben sobrescribirse.

Próximo lote de código: caracterizar recuperación entre sesiones y entre tipos
de lease; conservar identidad original, actualizar sólo vistas que coincidan
exactamente con PID/token/run, registrar resolución durable sin reescribir
históricos y demostrar idempotencia, conflictos y no robo de propietario vivo.
Recuperación operativa propuesta, separada del deploy: comprobar otra vez la
ausencia del propietario y terminales, respaldar estado por la vía canónica,
resolver únicamente esas vistas con compare-and-swap y evidencia append-only.
No avanzar last_session ni ejecutar aprendizaje/reconciliación/órdenes. Esta
recuperación exige autorización explícita de mutación operativa: la orden de
despliegue no se usa para eludir la prohibición de reparaciones implícitas.
Después: nuevo preflight y gates pendientes; no prometer deploy antes de 15:30.

Evidencia local: audit_oct08_resume_preflight.json y
audit_oct08_resume_terminals.json en el checkout ef99 de este chat. Sólo lecturas
remotas; sin órdenes, broker, LLM, parada/reinicio, modificación de SQLite ni
despliegue. No se repiten suites sobre el mismo árbol.

## Intento de despliegue autorizado — 09:09 Europe/Madrid

El usuario solicita desplegar los nuevos cambios. Resultado del nuevo preflight:
`precondition_not_met`; no se inicia corte ni despliegue. Candidato limpio
`5b92c480051e6c62f54b48c510951ec7eb6dad4f`, tree
`155fdd4758ac79c27d6c266acb612654c01e0181`; respecto al árbol probado sólo
contiene el cierre documental anterior.

Sonda real de sólo lectura a las 09:09 del 8-oct: XNYS cerrado, apertura 15:30;
paper true, live false, auto-apply false. Scheduler PID 6/token 2686539 vivo y
coherente. Misma imagen `sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae`,
arranque 03:29:42 UTC, RestartCount 4. Lease postmarket de 7-oct
`pmr_150611d46dd9` active/outcome_update, actualizado 05:32 Madrid; lease de
reconciliación `brkrec_056138f49ca5` también figura active desde 02:38 Madrid.
No se presupone que éste sea un proceso todavía ejecutando ni se limpia como
huérfano: su estado no resuelto basta para bloquear el corte. last_session
permanece 5-oct. El último evento de postmarket observado a las 09:05 es un
scheduled missed, no el terminal del run activo.

schedule-status informa runtime_state unavailable por wal_mode_or_sidecar_present;
los leases anteriores se contrastan mediante Store.read_connection, SELECT de
sólo lectura y cierre explícito. Evidencia cruda local:
`C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_oct08_deploy_preflight.json`.
La lectura de metadatos Docker es igualmente no mutante. No se ejecutan broker,
LLM, suites, smoke, parada, restart, build, órdenes ni cambios productivos en
este intento. Kernel/configuración y salud integral no se certifican ahora:
la precondición operativa ya falla. Autorización de despliegue recibida;
resolver estos leases y completar los gates sigue pendiente. AGENTS exige
no reparar ni detener implícitamente servicios ante esta situación.

Dictamen: `partially_verified_integration_candidate`. Las siete mejoras conviven sin conflictos funcionales y pasan 87 casos focales distintos. No es una release ni un despliegue. La validación operativa conserva `precondition_not_met`: el último preflight real, a las 08:33 Europe/Madrid, encontraba un lease postmarket activo en outcome_update. No se reparan ni detienen servicios para eliminar ese bloqueo.

## Identidad y alcance

Worktree `C:/Users/utopi/.codex/worktrees/bolsa-oct08-integration/agenteBolsa`, rama `codex/oct08-integration-rehearsal`. Base exacta `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`, tree `4d118b504b305e45f45a06d9aaffa063079abaf7`. HEAD probado `5f2f530d2eab5b72c171a3fc0bd1afc1f9ddf5c4`, tree probado `9507084faf3e8e32ee1b4ad259501f70322e9f79`, checkout limpio antes de este cierre documental. Versión base 0.4.321: reserva y bump pendientes antes de release; no resuelven por sí solos la divergencia histórica .321/.340.

Se integran copias aisladas de los siguientes commits, conservando los informes de cada lote:

| Lote | HEAD de entrada |
| --- | --- |
| Guardia de portfolio ausente en postmarket | `071b4b5765ec33cacb140f4993095879b7db90db` |
| Auditoría EXIT separada de rechazos BUY | `a5ee9ce36dfe0fff977e2679884172dd700c3421` |
| Cobertura canónica de símbolos, legacy conservado | `73c3d683c9b7b64cf4e313cf16fbd795aff9f8fb` |
| Observación stop/take sin autoridad del broker | `f63464ee2c60401e89438defe068bec93274cf5e` |
| Reutilización de marcos por símbolo en outcomes | `9bd9b2eadfdb81a0528d4e0c901628df91b7e814` |
| Cierre explícito del lector SQLite de eventos | `1fda7d8d636e5197f05620f33cf10c6b00a852d5` |
| Exclusión local de estudios concurrentes duplicados | `2122fca31617bccaadc7ef2d1ba23d765b665350` |

Sólo hubo conflictos documentales en plan y relevo: se conservaron las notas de ambos lados. Los siete archivos funcionales modificados son storage.py, scheduler.py, cycle_runner.py y tools/{signal_learning,post_market_review,trade_decision,technical_study}. Los objetos Git de kernel.py, tools/broker.py, tools/execution.py, tools/risk.py, config.py y .env permanecen idénticos a la base. Los checkouts de entrada y los cambios ajenos no se modifican.

## Resultado y límites

Los tres lotes nuevos corrigen reutilización repetida de DataFrames, conexiones/cursor sin cierre físico explícito y concurrencia duplicada de estudios en el mismo Store/proceso. Las caracterizaciones de sus informes reproducen los defectos en la base y contrastan payloads y rutas aceptadas. No se ha demostrado que sean la causa de los incidentes productivos.

En capturas H, el fixture de 120 señales y dos símbolos reduce las adquisiciones de marcos de 120 a dos, conservando los 120 payloads completos e identidades frente al legacy congelado. No equivale a una medida de RAM: el loop legacy ahora retiene un marco por símbolo y puede aumentar su memoria en esa subfase. El lector cierra al agotarse, fallar o recibir close; un generador suspendido y todavía referenciado sigue reteniendo recursos. El guard de estudios excluye duplicados únicamente dentro del mismo proceso y Store; no sustituye leases entre procesos ni garantiza el avance del postmarket.

La auditoría EXIT sigue separada de BUY y del aprendizaje; la cobertura no sustituye candidatos ni métricas legacy; stop/take reutiliza fuentes ya cargadas, no añade consultas y declara protección real del broker unavailable. Estas garantías tienen evidencia sintética focal, no una demostración económica de un ciclo productivo completo.

## Validación del árbol combinado

Intérprete `C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe`, PYTHONPATH exacto del src de este checkout; DATA_DIR temporal, Settings con `_env_file=None` y proveedores locales/dobles. Sin broker, red, LLM ni datos productivos desde tests.

Primera batería: `86 passed in 5.29s`, ejecutada una vez sobre el árbol funcional definitivo:

```text
python -m pytest tests/test_oct07_postmarket_missing_portfolio.py tests/test_oct07_exit_rejection_audit.py tests/test_oct07_symbol_coverage.py tests/test_oct07_stop_take_observation.py tests/test_oct08_outcome_memory.py tests/test_oct08_event_reader_lifecycle.py tests/test_oct08_study_dedup.py tests/test_storage_read_connection.py tests/test_signal_learning.py::test_outcome_for_signal_includes_exit_policy_v2_partial_and_trailing tests/test_signal_learning.py::test_outcome_for_signal_marks_matured_when_future_bars_exist tests/test_signal_learning.py::test_outcome_for_signal_keeps_pending_when_history_is_short -q --tb=short
```

Segunda batería, caso distinto no incluido arriba: `tests/test_market_cycle_timing_integration.py::test_exit_audit_wiring_is_fail_open_and_separate`, `1 passed in 0.71s`. Total 87 casos distintos; no se suman los resultados solapados de los lotes individuales.

Ruff focal sobre siete archivos funcionales, siete archivos nuevos de tests y el test de wiring: `All checks passed!`. NUL: `OK (544 archivos)`. `git diff --check` verde. Revisión independiente Luna sin bloqueantes: signal_learning y sus fixtures son idénticos al candidato de memoria; scheduler añade al candidato dedup sólo la observación stop/take y su wiring. Revisión no implica ejecución adicional de suites.

## Producción y gates pendientes

Última observación real: XNYS cerrado, siguiente apertura 15:30 Madrid; paper activo, live y auto-apply desactivados. Imagen activa observada `sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae`, scheduler PID 6, RestartCount 4; último arranque 03:29:42 UTC. Postmarket `pmr_150611d46dd9` seguía con lease activo en outcome_update; dos intentos anteriores fallaron por database is locked. Memoria observada casi al límite de 2 GiB, sin eventos oom/oom_kill: no se atribuyen los reinicios a OOM. HEAD/tree productivos y equivalencia de imagen/release no quedan resueltos por la versión de este checkout.

No se ejecutaron suite completa, smoke operativo, kernel/config gates, promoción, merge productivo, despliegue, reinicio, órdenes ni push. HTTP y salud integral posterior a despliegue no se certifican. Sigue pendiente el fallo `test_economic_parity_true_false_none_identical_payloads`, previamente reproducido sobre la base; no se oculta ni se vuelve a ejecutar sin nueva causa. No se presenta este ensayo como aprobación de esos gates.

Siguiente secuencia: verificar nuevamente schedule-status, terminal postmarket y ausencia de jobs/reintentos/leases/validaciones; resolver identidad .321/.340 y reservar versión; completar validación proporcional pendiente y revisar el fallo económico de base antes de considerar release. La automatización `validar-mejoras-bolsa-tras-cierre` permanece PAUSED; la revisión del 12 de octubre no se altera.

Auditoría de optimización adicional: EXPLAIN sobre SQLite temporal con esquema base demuestra SCAN agent_events y ordenación temporal para la consulta por tipo/ciclo. Se propone un lote específico de consulta agrupada/índice, conservando legacy sin ciclo, orden e histórico completo. No se añade esquema ni se recorta a ciegas el histórico de 200000 señales. Cambiar atomicidad de escrituras requiere estudiar reintentos y paridad; queda fuera de estas correcciones.
