# Ensayo conjunto de siete mejoras — 8-oct-2026

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

Auditoría de siguiente optimización asignada a Luna: solo propuesta de iteración
y acumuladores para decision_context_quality, sin editar el candidato ni reducir
históricos/denominadores. No confundir esa propuesta con un fix integrado.

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
