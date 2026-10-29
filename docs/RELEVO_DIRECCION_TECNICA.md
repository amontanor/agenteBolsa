## P-L159 — modelos unificados a DeepSeek V4.1 Flash via opencode Go — 29-oct-2026

Estado: `ready_for_integration_rehearsal`; candidato `codex/models-v41` en
`.worktrees/models-v41`, base `b3a1c577`/tree `dea237b9`, version `0.4.394`.
Sin integracion, imagen ni despliegue.

Objetivo del operador: un solo modelo, `deepseek-v4.1-flash` servido por
`opencode-go`. `main` ya usaba el ID v4.1 en router, cliente de mejora, scripts
y `.env.example`; el lote cierra los cuatro huecos restantes: defaults Zen en
`config.py`, fallback local qwen activo por defecto (alcanzable desde decision y
sentimiento via `role_endpoints`), catalogo de UI con glm/kimi/mimo/v4-flash
escribible a `.env`, y `.env.example` desalineado.

Cambios N3: `config.py` (protegido, autorizado) con selector/base/proveedores
Go y fallbacks locales en `False`; `web_app.py` con catalogo y selector de un
solo modelo Go/v4.1; `.env.example` alineado; `.env` local con qwen apagado,
`OPENAI_MODEL_NAME` en v4.1 y `MIMO_MODEL` retirado (backup
`.env.bak-p159-*`). Test guard nuevo `tests/test_p159_models_v41_only.py`.
Protegidos de trading sin diff; `llm_router.py` y `llm_client.py` ya eran v4.1.

QA: `116 passed / 48 failed` candidato frente a `106 / 49` base, cero fallos
nuevos y uno preexistente menos; los 48 restantes son aislamiento SQLite
preexistente en Windows (`no such table: llm_usage`). UI focales identicas
candidato/base (`15 failed / 82 passed`). Ruff 3 preexistentes, 0 nuevos;
NUL OK (598); `git diff --check` limpio.

Limites: Jetson `unavailable` (SSH `Permission denied (publickey,password)`);
sin uso real de v4.1 en `llm_usage` desde 2026-08-14; suite completa, smoke,
`validate-agent-config` y `kernel-status` omitidos por mercado abierto (15:30).
Rotacion de `OPENCODE_API_KEY` pendiente: se imprimio por error en la auditoria.
Detalle en `docs/informe_p_l159_modelos_v41.md`.

Siguiente: cerrar mercado, ejecutar suite y gates, integrar por `merge --no-ff`
en la rama de release, replicar el `.env` en el Jetson y verificar una llamada
real v4.1 antes de afirmar despliegue.

## Relevo de coordinación —24oct2026 19:31 Europe/Madrid

Dictamen actual: `blocked_qa`; port de `[AgenteBolsa] Carga` integrado en este
chat, versión local `.378`, pero sin fullsuite válida, imagen ARM ni despliegue.
Último HEAD funcional antes de actualizar documentos:
`032539c56d35e256099ee9f449146cb139bcbfdf`, tree
`668f6525b27a296c6c8566a992907f04168525a6`.

La rama histórica `0.1.13` parte de `.1.7`; no se mezcló completa. El port moderno
parte del `.376` exacto y mantiene `config.py`, `kernel.py`, `tools/broker.py`,
`tools/execution.py` y `tools/risk.py` idénticos. Se añadieron cache/asynchronous
dashboard, snapshot local por cuenta y adaptador GET de fills. 160 focales
integradas pasan; la rama de origen registra 113 pruebas y AppTest 17/17. En
synthetic review:3 fills disponibles=3 almacenados, cursor repetido=partial,
cuenta nueva no hidrata la previa, y no hubo red/datos productivos. Timeout
efectivo del SDK de cartera y p95 de navegador/producción: `unavailable`.

El recibo .378 ya muestra fecha/hora de despliegue solo tras verificación real,
con ImageID, HEAD/tree y UTC/Europe-Madrid. Sin recibo válido, muestra «Fecha de
despliegue no disponible». La imagen de rollback `.369` no contiene el lector;
no afirmar compatibilidad de fecha en rollback hasta resolverlo.

Fullsuite: no verde. Cuatro corridas dejaron 1.590 tests pasados y fallaron en
`test_multiprocess_append_only_event_has_one_canonical_without_lock` con
`NameError: __args` en el lanzador temporal de hijos. La misma prueba pasa aislada
dos veces (9,91s y 8,81s). No modificar ni omitir el test para pasar. Un intento
de `WinError 5` en replace del temporal sandbox pasó con basetemp en el worktree.
Ruff completo, NUL593, diff y config 23 agentes/6 tareas pasan. `kernel-status`
en DATA_DIR temporal dice `unsealed` de forma esperada, sin manifiesto; no da
prueba sobre producción.

Siguiente: obtener runner compatible para una fullsuite única válida en el árbol
funcional exacto; si verde, ejecutar smoke `run-once` con proveedores locales,
digest completo y smoke ARM bajo límite2GiB, revisión independiente y luego
preflight productivo actualizado. Exigir XNYS cerrado, postmarket terminal,
quietud completa, paper true, live/auto-apply false, kernel/config válidos,
recursos y rollback. No construir ni desplegar con gates fallidos. La producción
sigue con último dato documentado `.321` del23oct, no revalidado en esta corrida.
No activar política de tamaño, adds ni score. La automatización vencida sigue
pausada.

## Intento inmediato23oct09:15Madrid —precondition_not_met

El operador autoriza desplegar ahora. Preflight real schedule-status:
XNYS cerrado,next_open23oct15:30Madrid,schedulerPID7/token7769616 vivo.
Store.read_connection readonly con deadline10s y cursores/cierre explícitos:
post_market_coordination:session:2026-10-22 sigue statusactive,stagecoordination,
runpmr_19afdf738678,iniciado23oct03:46:39UTC. No acredita terminal22oct; el skipped
23oct market_not_ready no lo sustituye. Un lease registrado activo no demuestra
que el proceso siga trabajando, pero incumple el gate; no borrarlo para cortar.
Kernel actual violation broker.py/execution.py,flags papertrue/livefalse/
autoapplyfalse. Producción sigue .321. No se lanza QA pesada ni corte con gate
fallido. No paradas/reinicios/órdenes, no resellado ni edición productiva.
Evidencia EF99/audit_oct23_deploy_preflight.json. Automatización anterior sigue
PAUSED. Pendientes: diagnóstico explícito del lease/autoridad tras reinicio,
recuperación revisada con bytes aprobados y QA completa .376; no declarar listo
por focales. Requisito fecha/hora visible web conservado como aceptación futura.

## Requisito permanente del operador —23 octubre 2026

En cada despliegue la web debe mostrar junto a la versión activa la fecha y hora
del despliegue verificado, con zona horaria explícita (Europe/Madrid y referencia
UTC persistida). Usar el recibo canónico del despliegue e identidad de imagen;
no confundir fecha de build, commit, arranque o reinicio con fecha de despliegue.
Si no existe recibo verificable, mostrar «Fecha de despliegue no disponible».
El rollback debe mostrar la identidad y fecha del despliegue restaurado mediante
su recibo de rollback. Incorporar este requisito al gate de aceptación de cada
futuro corte. Pendiente de implementación UI/carrier en lote separado: no alterar
silenciosamente las fuentes congeladas del candidato .376.

Comprobación remota23oct: los tres servicios usan imagen
sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae;
paquete web0.4.321. No está desplegado .376. El scheduler arrancó23oct05:09:46UTC;
eso no acredita un despliegue ni su causa. No consta ejecución del intento22:45
en el relevo local; no atribuirlo a fallo de QA sin evidencia.

### Evidencia de capital recuperada —22oct19:53:46Madrid

Consulta canónica por rango de clave primaria, acotada/deadline, confirma123eventos
capital_allocation_shadow bajo un único policy_hash dc2810dc3b02e79187f9e74abd174dbb79e10e498f83e7598776938ea3bc7977.
Ventana13oct14:03UTC–21oct20:45UTC. Denominadores128BUY/128identidades verificadas,
sin denominadores ausentes y sin saturación. Son registros de recomendaciones,
no128oportunidades independientes ni compras maduras. Recibo
EF99/audit_oct22_capital_readiness_1955.json (hora efectiva en observed_at).
Los recibos de revisión no se escanearon y siguen unavailable, no ausentes.
El primer SELECT por event_type agotó deadline12s; se sustituyó por rango del
prefijo canónico indexado, sin añadir índices ni modificar producción.
No se acredita todavía cobertura de sesiones completas, controles maduros ni
reconciliación/protección. Conservar evidencia, no reiniciar shadow por defecto.

## Prioridad de capital —22oct19:52Madrid

El operador reitera aumentar el tamaño de las compras y reducir cash. Primer
escalón acordado: sustituir máximo fijo1000USD por máximo2,5%equity, manteniendo
15%cartera/3compras por día; después20% y25% con sus gates. Sobre equity de la
captura anterior69900,59USD,2,5%=1747,51USD (+74,75% sobre el tope fijo).
Es un techo: target, multiplicador aplicado una vez, stop, cash, reservas y
riesgo pueden reducirlo. No se garantiza ese importe ni una inversión mínima.

Revisión offline de los ZIP .369 y .376: capital_allocation_policy.py,
capital_ladder.py,position_sizing.py ytrade_decision.py son idénticos byte a byte.
Contrato SHA256 d7c56b25ef0930d0bdcc6e0e277c8f253353f9b87cec2904f01e199aa0eaa078.
Recibo EF99/audit_oct22_capital_contract_identity.json. No invalidar ni reiniciar
el período de evidencia por este despliegue sin otra causa. Tampoco confundir
paridad de código con cinco sesiones completas o aprobación económica.

Ruta comprobada: active_stage_limits sustituye el cap fijo de aprendizaje por
cap proporcional; cap_allocation_notional no vuelve a aplicar multiplicadores.
La etapa2 exige también20compras maduras/15controles por la escalera existente,
además de5sesiones completas,linaje>=95%,reconciliación y recibos canónicos.
El número de sesiones y compras elegibles actuales sigue unavailable: auditoría
readonly inicial falló en handshake SSH. El reintento schedule-status respondió
finalmente19:52:29Madrid: XNYS abierto, PID9/token2646 vivo; runtime unavailable
por WAL no acredita quietud. Se reintenta el colector; sin mutación remota.
Colector preparado EF99/audit_oct22_capital_readiness.py, SELECT acotado/deadline,
sin aprobar ni escribir remotamente. Reintentar con recibo timestamp nuevo.

Automatización existente actualizada y ACTIVE para22oct22:45Madrid, intento
único con pausa al concluir. Incluye recuperación persistente .376, QA restante,
revisión independiente y comprobación concreta de brecha para tamaño mayor.
No activa tamaño/adds/score automáticamente ni permite saltar riesgo/protección.
No se ha desplegado .376 ni activado el cap proporcional en esta continuación.

## Relevo de preparación .376 —22oct, sin corte

Candidato integrado con merge --no-ff en oct19-integration,
HEAD funcional856740a074f7e6ac314abc1cd8339a834af51a78,
tree2311d35f47a7ab330d9d5cf2886c08d69162a715. Causa del retroceso confirmada en
audit_oct22_startup_image_binding.json: runtime.env AGENTE_BOLSA_IMAGE=.321.
Se corrige mediante tercera capaCompose literal y drop-in con ExecStartPre
host de ImageID/tag/linuxarm64. Preparador puro; no se ha instalado nada remoto.
Rollback .369 verificado porID, .321 no es rollback seguro. Cinco fuentes de
código protegidas idénticas .369; storage mismo objetoGit, solo CRLF/LF en bytes.
QA:68binding+51correctivas, solapadas/no sumables, Ruff/NUL580/diff/config23/6
verdes. WinError5sandbox conservado y reintento justificado pasó51. Fullsuite,
smokes y volumenARM pendientes de cierre. Ver informe único de binding y recibos.
No usar sin cambios el cut.py .369: exige base .364/kernelactivook. Resolver
violación de imagen actual por recuperación revisada contra sello intacto,
sinresellar/forzarjobs/borrarlocks. Copia fría solo trasquietud y parada canónica.
No declarar OOMresuelto ni aprendizajeCLIequivalente al productor; diferencia
agent_learning reproducida en base369, mismas rutas entre369/376 sí coinciden
en fixture78señales salvo dos as_of. Primerharness aliasDATA_DIRfalló y queda
invalidado; localDBconsolo fixtures preservada, Jetson intacto. No usar ese dato
local en futuros tests. Nueva claveLLM siguependienteoperador.

## Auditoría22oct15:50Madrid — retroceso productivo e incoherencia kernel

Tres servicios .321 imagen8ff2bedce363... con205fuentes exactas del inventario
archivado; el20corría .369/211fuentes. Causa y autoría pendientes. Contenedor
creado22oct09:01Madrid y arrancado09:35; Compose apunta release0.4.297.
Kernel-status posterior: ok=false/status=violation en broker.py y execution.py.
Kernel y carrier.env coinciden. No resellar ni restaurar a ciegas; resolver
identidad de imagen y bytes aprobados por procedimiento canónico.
Mercado abierto; auditoría solo lectura, HTTP200/PID9token2646 coherente. Memoria
scheduler≈2GiB;0reinicios tras recreación no cierra OOMhistóricos. LLM401persiste.
Postmarket20failed,21sin terminal observado;último completed19. Resultados20/21
+0,072%/+0,155% frente SPY+0,335%/+0,525%;cash88,76%/exposición11,24% en captura22.
MAR/CRLsalidas coherentes porIDs/cantidades antes de recreación, no paridad futura.
Evidencia: EF99/informe_oct22_resultados_mejoras.md y audit_oct22_*.json.
.375sigue sin fullsuite/smokes/digestARM; no código funcional/protegido ni despliegue.

## Cierre focal del candidato .375 —19oct, sin despliegue

Dictamen: partially_verified_corrective_rehearsal. Mercado confirmado abierto
18:03:51Madrid; precondition_not_met para suite/smokes/corte productivo. No
despliegue ni cambios de configuración, riesgo, credenciales, protección u órdenes.

HEAD funcional final e42d956620e34334cec2e924975c439e153c30f7,
tree01b07aafb92e755734e1b8e973fec12f30953099, versión0.4.375.
QA final51passed9.25s con sockets bloqueados, _env_file=None y DATA_DIR temporal;
Ruff src/tests, NUL576 y diff verdes. Configuración estática23agentes/6tareas
válida y objetos protegidos idénticos a base. Las95regresiones anteriores no
se declaran ejecución del árbol final. No fullsuite, smokes ni QA/digest ARM.

Nuevo carrier durable en evento ya existente gate_evaluation_snapshots_captured:
decision_paths.v1 conserva todos los snapshots, attachment_counts deja visible
conflict y multi_decision_learning_status=unavailable. Prueba con SQLite temporal
lee BUY/EXIT y captura exacta de ambos; el attachment original permanece intacto
al repetir. No nueva tabla, consultas ni autoridad de ejecución. El consumidor
legacy de aprendizaje sigue parcial: no promover cobertura/control multi-decisión
sin contrato completo revisado. La pérdida auditable queda mitigada, no se
presenta el carrier como aprendizaje real incorporado.

Fallos conservados: WinError5 al replace en sandbox (19passed antes de stop;
reintento motivado fuera del sandbox pasa); un gate de versión falló tras el
último cambio no anotado aún en __init__ (50passed/1failed). Se completó la
anotación de la misma versión .375 reservada y la nueva ejecución pasó51.
Un control NUL lanzado desde EF99 recorrió109archivos y NO cuenta; el control
final desde el worktree real recorrió576 y pasó. No se ocultaron fallos de base.

Revisión independiente detectó además que --force permite PMR con mercado abierto.
Se comprobó que existe en base2999414f y no lo usan scheduler/bootstrap normales;
es deuda de hardening, no regresión .375. No se ejecutó ese job en producción.
Revisar excepción manual y paridad de laboratorio en lote separado; no usar force
para fabricar quietud o superar un gate.

Pendientes: renovar clave LLM por canal de secretos del operador (no existe
refresh automático canónico); coordinación N3 de protección/EXIT con diff
protegido revisado; aprendizaje multi-decisión; fullsuite única final, smoke
Windows/ARM, digest ARM completo y preflight de cierre con postmarket terminal,
sin jobs/reintentos/leases, configuración/kernel válidos y rollback preparado.
Ninguna promoción de tamaños, score o ampliaciones; producción sigue .369 según
la captura auditada. Siguiente trabajo condicionado al mercado y a estos gates.

### Correcciones nuevas y cierre focal del19oct

La revisión reprodujo pérdida silenciosa de filas: dos decisiones legacy BUY/EXIT
con mismo signal_id producían una única fila. Se conservan ambas mediante claves
de colección no autoritativas, se incluye signal_capture_id en snapshot_id y
las identidades exactamente duplicadas se marcan conflict/unavailable, excluidas
del aprendizaje. Se conservan las claves legacy cuando son únicas.

La clasificación Crew ahora considera HTTP401 y api_key_expired terminales para
el reintento Crew, manteniendo direct decision y fallback determinista existentes.
No renueva la clave ni cambia proveedor. La revisión local no encuentra refresh
canónico; hace falta una clave nueva en el canal de secretos del operador y
recreación controlada fuera de sesión. No pegar secretos en el chat/informes.

HEAD funcional corregido ae6bf6b3/treeb6903c5c. Tras el cambio,50 focales
combinadas passed9.70s con sockets bloqueados, DATA_DIR temporal y _env_file=None.
Las41focales y95regresiones anteriores pertenecen al árbol34d9e93f; no se
presentan como QA completa del nuevo árbol ni se suman con baterías solapadas.
Ruff completo/NUL575/diff y configuración estática pasan. Suite única final,
smokes Windows/ARM y digest completo ARM pendientes de mercado cerrado/quietud.

Protección: caracterización reforzada14passed2.60s en rama separada
codex/oct19-protection-contract, HEADa318a547/treef5052e28. Plan BUY temporal
real, stop alcanzado y sentinel de submit; control sin órdenes sí alcanza submit.
El contrato OrderSnapshot pierde TIF/parent/legs, así que el arreglo requiere
revisión N3 de adaptador protegido y coordinación. No GTC aislado, no nueva
autoridad de cancel/replace ni reparación implícita de posiciones actuales.

## 19-oct — ensayo correctivo integrado .375 (sin despliegue)

Usuario autoriza avanzar tras auditoría de resultados. XNYS confirmado abierto
19-oct18:03:51Madrid; cierre22:00. Trabajo aislado, no corte operativo.

Base .3692999414f, rama codex/oct19-corrective-integration. Integra mediante
merge --no-ff los candidatos .3700a8e2e43, .371a43f863f, .3736d5243b8 y
.3744d3aad50. Sólo conflictos de versión/comentarios y aserción de versión;
reserva combinada .375. HEAD funcional34d9e93f/tree13360e44, antes de esta nota.
Objetos protegidos idénticos a .369. Políticas tamaño/adds/score inactivas.

QA combinada:41focales11.05s y95regresiones21.08s; una aserción de versión
solapada, no sumarlas como casos únicos. Python del proyecto, PYTHONPATH exacto,
DATA_DIR temporal, Settings _env_file=None y sockets bloqueados. Primera batería
paró tras19passed por WinError5 al replace de informe temporal en sandbox;
fallo conservado, reintento motivado fuera de sandbox pasó. Ruff src/tests,
NUL574, diff y configuración estática23agentes/6tareas verdes. Fullsuite,
smokes Windows/ARM, digest completo ARM, kernel y preflight operativo pendientes;
no se repiten antes de cierre/quietud. Focales no certifican release.

Protección: GTC aislado NO se aplica. El vigilante omite símbolos con cualquier
orden abierta antes de parcial/trailing/time stop; caracterización y diseño de
coordinación pendientes. APO/WAT/VEEV requieren reconciliación de protección;
HPE ya fue vendido el15, no es posición actual. No órdenes/cancelaciones.

LLM401 api_key_expired no se arregla con .371402. Se investiga recuperación
canónica sin leer/exponer secretos ni cambiar proveedor, credenciales o pagos.

Evidencia: EF99 audit_oct19_*.json, informe_oct19_resultados_mejoras.md,
release_oct19_0375_rehearsal_snapshot.json y recibos oct19_combined_*.
Producción sigue .369 según lectura17:44Madrid; no despliegue/reinicio ni
escrituras productivas. Estado ready_for_closed_market_full_validation sujeto
a revisión independiente; protección/credenciales son lotes separados pendientes.
Git maintenance reportó ref ajena turn-diffs rota; merges válidos verificados,
no se borró/reparó la ref ni se modificó configuración Git compartida.

## Cierre de la revisión de gates — 14-oct

El lote .370 quedó corregido tras revisión: HEAD0a8e2e43/tree374b4a7b, rama
codex/oct14-gate-identity limpia. Identidad completa, rechazo ambiguo sin
matching[0] y autoridad contradictoria unavailable/conflict; las observaciones
con conflicto se excluyen de aprendizaje y se cuentan. La separación se hace
en una pasada, sin comparaciones profundas cuadráticas. Treinta y dos focales
offline4.35s más versión0.83s, Ruffcompleto/NUL571/diff verdes. Se corrigió la
comprobación del worker que había recorrido0archivos y su aserción de versión.

Cuatro candidatos revisados para ensayo aislado, no integrados ni desplegados:
.370gates, .371Crew402, .373EOD, .374buffers. No se suma QA de árboles distintos
como suite. Fullsuite única del árbol combinado definitivo, configuración/kernel,
smokes/ARM y preflight operativo pendientes. GTC protegido sigue sólo propuesto
y con revisión humana pendiente; no hay reparación automática de APO/HPE.

## Cierre parcial de candidatos — 14-oct

Tres lotes aislados preparados, sin integración ni despliegue:

- EOD .373: HEAD funcional07489e2c, diez focales offline7.50s más contrato
  de versión; Ruff completo, NUL572 y diff verdes. El recibo se prepara antes
  de performance_daily y el evento completed conserva sesión/hash/path/reloj.
- Crew402 .371: funcionalc8665a81, documental a43f863f/treec69d3bb6; siete
  focales independientes offline1.18s. La revisión independiente informa13
  focales; baterías solapadas, no se suman como suite. Sin mejora viva certificada.
- Buffers .374: HEAD4d3aad50/tree2da4158e, rama codex/oct14-outcome-buffer-release;
  diecisiete focales/paridad/versionoffline1.76s con Pythonproyecto, Ruff completo,
  NUL572/diff verdes. Sólo del referencias locales tras persistir; no muta
  diccionarios prestados. La QA inicial del worker con Python global no se
  hereda; se documentó y repitió por esa causa concreta. No OOMtotal resuelto.

Gates .370: sigue en revisión; no aceptar blocked como rechazo efectivo si
existe plan final admitido de idéntica decisión. Exigir unavailable/conflict y
exclusión de esa observación de aprendizaje; IDs incompatibles no se degradan
a joins débiles. La propuesta de staging .372 es investigación, no código
activado ni nuevo schema. Fullsuite/smokes/QA ARM/integración pendientes.

Parche GTC propuesto válido (gitapplycheck exit0 y caracterización fakeAlpaca:
bracketgtc,limit/fractional/sellDAY), SHA256dbc8609c64ea5671405e53fdca4431222008bf07cc79772636cb3e46648be296.
execution.py protegido permanece intacto; solicitud de revisión humana pendiente.
El cambio futuro no restaura órdenes de posiciones ya abiertas.

El mantenimiento Git automático falló en commits por ref ajena turn-diffs rota;
commits/árboles comprobados utilizables y limpios. No se borró/reparó la ref.
No se suman focales como suite final, no se reservó release combinado ni imagen.
Límites actuales/política inactiva/producción intactos en este trabajo.

## 14-oct — correcciones operativas en preparación (sin despliegue)

Dictamen: candidato aislado .373 de medición EOD con QA focal; no release integrado
ni nueva política activa. Base exacta 2999414f/tree ffc5b118 (.369), sin cambios ajenos.

Lectura fresca 14:37–14:42 Madrid: .369 y sus 211 hashes siguen activos en los tres
servicios; scheduler acumula dos reinicios. Dmesg confirma OOM el 13-oct a las
22:05:42 y 23:53:35 Madrid en docker-5f5f52a6f25c2208f3c1d0b804451d249e8c936398d9a617d9c3ccafabc24f69,
ID exacto del scheduler activo. OOMKilled=false y cgroup oom=0 tras reinicio no
acreditan ausencia histórica de OOM. Lock PID7/token52511816 coincide en scheduler;
schedule-status desde web compara contra el namespace web y produce pid_reused:
no se borró el lock ni se interpretó como segundo scheduler.

El PMR pmr_1a18d2935cef de sesión13-oct terminó completed a 14-oct01:02:36 UTC;
last_session avanzó a13-oct. Learning pipeline9693.093s,122020outcomes actualizados,
digest557.472s. Existen equity70021.54 y fila performance13-oct, pero retorno diario
y alpha siguen unavailable: falta sesión12-oct válida y autoridad SPY a tiempo.
Recibo SPY comparable apareció después, capturado04:05:13 UTC, con cierres
778.0999755859375/778.010009765625. No se reescriben las filas ni se usa precio
posterior como si hubiese estado disponible al decidir.

La observación del recibo se adjunta al evento durable existente
post_market_review_completed, no al report ya serializado; el recibo separado
con content_hash conserva su autoridad.

Candidato .373 prepara el recibo SPY antes de guardar la próxima performance_daily.
Reutiliza recibo comparable validado; en ausencia usa refresh_and_capture_spy_eod
existente para la sesión exacta. Una lectura/descarga adicional SPY puede ocurrir
en PMR si falta autoridad: fuera del ciclo intradía, mismo proveedor, fail-open.
No rellena equity previa, costes o flujos; no convierte snapshot contable en valid.
No corrige todos los costes/benchmark del snapshot contable canónico ni backfill.
El job standalone de reconciliación conserva su captura anterior; posible refresco
posterior redundante queda pendiente de integración/QA proporcional.

QA focal final con socket.connect/create_connection bloqueados:10passed en7.26s.
Ruff específico, NUL572 y diff pasan. La primera batería ampliada fue abortada tras
fallo por secuencia de stages y demora; no cuenta como QA verde. Se reprodujo el
fallo exacto QA-1 (stage nuevo spy_eod_authority), se actualizó el contrato esperado
y su harness local; no skip/xfail. Las cuatro pruebas iniciales del helper fallaron
por contrato aún no implementado: aceptación TDD, no reproducción de bug base.
Fullsuite, configuración/kernel, smoke Windows/ARM e integración pendientes.

Protección: GET14:42 confirma APO7/HPE14 todavía en cartera. Ambos brackets eran
DAY: APOtakeexpired/stopcanceled17ago; HPEtakeexpired13oct20:01:23.877Z y
stopcanceled20:01:23.880Z. Parche GTC exclusivo para futuros brackets enteros
propuesto en EF99/proposed_oct14_protection_gtc.patch; execution.py intacto y
aprobación humana específica pendiente. No reparar posiciones antiguas con stops
caducados ni enviar/cancelar órdenes manuales. WAT protección broker unavailable.

Lotes paralelos aislados: identidad de gates .370; latencia CrewAI .371; memoria
daily_learning .372 en investigación. No se asumen listos ni integrados por la
reserva. Políticas tamaño/adds/score inactivas, sin aumento de límites/proveedor.

Evidencias EF99: audit_oct14_acceptance_initial.json, audit_oct14_postmarket_exact.json,
audit_oct14_eod_sources.json, audit_oct14_protection_tif.json. Dos consultas de eventos
agotaron deadline10s y cerraron lectura: cobertura unavailable, no ausencia probada.
XNYS cerrado14:35Madrid, apertura15:30; no preflight de despliegue aprobado ni
servicios detenidos. Sólo trabajos aislados y auditorías read-only. Sin push.

Siguiente: revisión independiente, reparación memoria reproducible, recibo GTC
humano, integración con versiones únicas y QA final. Despliegue futuro requiere
XNYS cerrado, PMR terminal, quietud real, configuración/kernel/rollback y salud.

## Despliegue verificado .369 — 13 de octubre de 2026

Dictamen: **deployed**. La imagen .369 sustituyó a .364 a las 09:46 Madrid,
con XNYS cerrado. Scheduler, web y auxiliar ejecutan la misma imagen inmutable:
sha256:cbc77775407aa56f12be8be31a9000f888720c8d27d141112d33c259d284dde7. Los 211 hashes de fuentes coinciden en los tres servicios.

Se despliega la observación preparada en .368 y las reparaciones de memoria y
del adaptador CI. La política nueva permanece inactiva. Configuración efectiva:
learning habilitado, 15% de exposición, 1.000 USD por compra, tres compras
diarias, ampliaciones desactivadas y `builtin_pullback` en sombra. No hubo
promociones, cambios de límites, proveedor o estrategia ni órdenes manuales.

Fuente funcional: HEAD 02f6d8ddf54084b9d94b91132a3a0e83495fade7, tree 05f54b96ea754ea1339951ac3c8577757e208745, rama `codex/bolsa-repair-oct13`.
El árbol estaba limpio antes del corte; los commits posteriores sólo documentan
resultados. Los cinco archivos protegidos coinciden con .364. Los hashes de
application.env, runtime.env y kernel_manifest.json se conservaron. No se ejecutó
kernel-seal ni se copió un manifiesto. Compose recreó exclusivamente scheduler,
web y auxiliary mediante `up -d --no-deps`. Las imágenes .364 y .321 se conservan.

QA del árbol definitivo: **2.992 passed, 1 skipped preexistente, 0 failed**,
765,52 segundos de tiempo total. El skip corresponde a un histórico local
unavailable; no se modificó. Ruff, NUL (571 archivos), diff, configuración y
smoke Windows pasan. Python del proyecto, PYTHONPATH exacto, DATA_DIR temporal,
`_env_file=None`, proveedores locales y bloqueo de acceso externo en tests.
Journal: EF99/oct13_0369_final_full.jsonl.

El smoke ARM pasó con 211 hashes y cero OOM. La medición sintética de 200.000
señales, con 24 KB descartables por fila, registró 556,5 MiB de RSS para las
métricas y 877,1 MiB para outcomes con entradas distintas y serialización real,
sin OOM bajo 1.536 MiB. La base utilizada era temporal y vacía; precios y
capturas estaban simulados. No equivale a medir el download, las capturas
históricas, el digest ni el postmarket completos. La paridad de resultados,
capturas, IDs, hashes, consultas, errores y cierre de recursos se comprobó localmente.

Los iteradores conservan selección, SQL, orden, filtros y límites. La proyección
retiene sólo los carriers consumidos; no reduce los límites de 200.000/100.000
ni los denominadores. CI402 evita reintentos HTTP 402 en ImprovementLLMClient y
conserva su fallback. No corrige los reintentos internos de CrewAI ni el saldo
del proveedor; no hubo pagos ni cambios de configuración.

El kernel acreditó OOM anteriores en el cgroup de 2 GiB y 11 reinicios de .364.
El último run del día 12 estaba en outcome_update antes del OOM; esto no prueba
la asignación exacta que lo causó. Su terminal canónico es
`pmr:pmr_150ac5ed97a6:terminal:failed`, del 13 de octubre a las 04:14:00 UTC,
con `owner_dead_recovered`. La lectura anterior era incompleta: revisaba la vista
runtime y eventos post_market_review_failed, omitiendo postmarket_run. No se
fabricó ningún terminal. El snapshot EOD del día 12 permanece collecting/unavailable;
se descartó un catchup que habría asociado la cartera del día 13 al día 12.

Preflight fresco a las 09:45:59 Madrid: terminal failed acreditado, 84 estados
runtime, ningún job/reintento/lease activo, kernel ok, paper true, live false y
auto-apply false. Salud operativa: cero alertas críticas y cuatro warnings.
El primer preflight agotó una lectura porque su deadline incluía el cálculo del
calendario; abortó sin cambiar servicios. Se corrigió sólo el helper mediante
consulta exacta, cobertura posterior acotada y presupuesto por lectura.

La primera construcción ARM agotó 120 segundos; se comprobó que no quedaban
procesos propios activos. El reintento con log persistido reutilizó la capa COPY
y terminó correctamente. El primer harness falló por usar str en vez de Path;
se corrigió sólo el harness y se conservó la evidencia. No se repitió la suite
ni se cambió la imagen. El ZIP definitivo v2 contiene sólo Python; los YAML se
heredan de la base y coinciden por hash con QA local. SHA del ZIP: 9abc8223bfceb313e108c4e4c47c1d83bdd31cc028d85cc4bb04bbf3b38301ec.

Aceptación: HTTP 200, scheduler lógico único con PID 7 y token 47424932, actividad
fresca y creciente de portfolio_watch/CI y auxiliar idle con cadencia de 300 s.
Dos controles separados 130.9 s y observación de recursos durante
600.8 s (14 muestras): cero reinicios y cero OOM.
Kernel, flags, política inactiva y ausencia de alertas críticas comprobados.
Web alcanzó el límite del cgroup con reclamación memory.max: una lectura mostró
690 MB de caché de archivos, 410 MB inactivos y 145 MB de RSS del proceso principal.
No se presenta como OOM; queda una auditoría de caché/lecturas UI, sin subir límites.
Persisten warnings de deterioro de los setups confirmed_pattern, orderly_breakout
y trend_volume, y de atribución postmarket degradada.

Evidencia: EF99/release_oct13_0369_deployment.json,
EF99/deploy_oct13_0369_cut_receipt.json, EF99/release_oct13_0369_local_qa.json,
EF99/release_oct13_0369_arm_qa.json y EF99/release_oct13_0369_arm_memory_qa.json.

Pendiente: observar un postmarket productivo completo y medir el digest; evaluar
cinco sesiones shadow completas, cobertura de IDs ≥95%, reconciliación de
cantidades/protección y recibos humanos antes de activar tamaño, ampliaciones o
score. Se conservan los criterios de promoción a 20%/25%. La revisión del día 12
no se modificó y la automatización de despliegue sigue pausada. No se hizo push.


## Intento automatizado 13-oct08:07Madrid — bloqueado

Dictamen:precondition_not_met. XNYS cerrado,próxima apertura13-oct15:30Madrid,
pero continuous_improvement running ci_sched_57b02603af40 iniciado08:07:56.
No se acredita terminal postmarket12-oct: sin coordinación12-oct en runtime
recogido, terminales recientes acotados siguen siendo fallos9-oct. Es evidencia
unavailable para este gate, no afirmación de ausencia absoluta en toda la BD.
Store.read_connection,SELECT acotados,cierre explícito y procesos contrastados.
Producción .364,kernelok,papertrue/livefalse/auto-applyfalse.

Git candidato limpio HEAD7b597a56498b56847a41b7650a39e1f14b5e6e61,
tree692eefdcf3e820f6e9d5916d5dd5145970f62f1e. QA e imagen .368 anteriores
no se repiten ni se confunden con despliegue. Sin corte,reinicio,órdenes,
reparaciones,locks borrados ni resellado. Automatización se pausa al concluir
este intento; la revisión12-oct permanece intacta. Recibo y lectura preservados:
EF99/release_oct13_0368_attempt_0807.json,
EF99/deploy_oct13_0368_preflight_0807_readonly.json.

AGENTS solicita caveman; no se encontró SKILL.md en catálogo ni raíces de skills
y plugins inspeccionadas. No se afirma haberlo invocado. Esta carencia de estilo
no sustituye ni altera los gates operativos que bloquean el intento.

## Resultado del nuevo intento — 12-oct18:42Madrid

precondition_not_met. Revalidación fresca:continuous_improvement running,
ci_sched_f44c93c441ad desde18:40:37;XNYS abierto. No corte, no reinicio,
no interrupción de jobs. Tres servicios .364 healthy,RestartCount0,OOMfalse;
kernelok/papertrue/livefalse/auto-applyfalse,memoria disponible3153MiB.
La QA ya está completa y la imagen .368 construida: no repetir suites ni
smokes idénticos. Sólo quedan gates/corte/aceptación operativa. Automatización
22:45 continúa autorizada y debe consumir los recibos actuales. Evidencia
EF99/release_oct12_0368_retry_result.json. Ninguna política nueva activada.

## QA ARM .368 cerrada — 12-oct-2026

Smoke ARM exit0,0OOM,211 hashes exactos; política inactiva, cash reservado y
protección desconocida bloqueada. Imagen candidata:
sha256:71c5a4d9ca7fe4dd09db9bb5d7bcb491640343977b751649da9431c3f00e7a1e,
tag agente-bolsa:0.4.368-arm64-qa, basada exactamente en imagen .364.
Rednone,entrypointpython controlado,readonly,medioCPU/512MiB,DATA_DIR temporal,
sin volúmenes productivos. Contenedor QA propio eliminado tras éxito; contexto
auditado preservado /tmp/bolsa-0368-qa-45cy675q/qa_receipt.json.

Primer build alcanzó300s y no produjo tag; diagnóstico no encontró procesos
propios activos ni contenedor QA. Dockerfile válido/contexto6,49MB. Reintento
acotado con pullfalse/log persistido reutilizó capas y terminó exit0. No se
atribuye causa no probada al primer timeout; no afectó fuentes ni producción.
Logs y recibos EF99/qa_oct12_arm_build_retry_diagnostic.json,
EF99/release_oct12_0368_arm_qa.json. No repetir suite ni smoke ARM idénticos.

QA completa:2964 passed,1 skipped preexistente,0 failed;Ruff/NUL/diff,
configuración/smoke Windows y smoke ARM pasan. Cortar exige revalidar gates y
garantizar imagen/config/hashes/rollback, doble salud75s y recursos/OOM600s.
No activar tamaño/adds/score durante este corte: faltan sesiones y recibos.
Producción aún .364; esta imagen candidata no constituye despliegue.

## QA local .368 cerrada — 12-oct-2026

Suite del árbol corregido:2964 passed,1 skipped preexistente,0 failed,exit0,
798,46s sumados en reports. Skip test_pre_earnings_current_sqlite por histórico
local unavailable; no se altera ni oculta. Causa de repetición:únicamente el
test de calendario corregido, después de reproducir el fallo en base .364.
Hashes de fuentes y tests intactos antes/después. No repetir esta suite salvo
nueva causa/árbol. Ruff/diff/NUL511/configuración y smoke Windows aislados pasan.
QAARM, imagen y aceptación operativa pendientes; no desplegado ni activo.
Evidencia:EF99/release_oct12_0368_local_qa.json y
EF99/oct12_0368_final_full_v6_clockfix.jsonl.

Los cinco archivos protegidos coinciden byte a byte con release .364: no hace
falta sellado ni nueva aprobación de cambios protegidos para este candidato.
Tres diferencias adicionales agent_run/digest/storage frente al ZIP .364 son
solo CRLF/LF; comparación normalizada idéntica, sin cambios de código. No se
portó otra rama ni se añadieron optimizaciones ajenas.

Nuevo intento18:08Madrid:marketopen,CIrunning ci_sched_71685d3f67bc desde18:04.
No se interrumpieron jobs. Revalidación final en curso; no inferir quietud a partir
de la terminación del pytest local. El corte y QAARM siguen condicionados a los
gates del plan. La automatización22:45 debe consumir esta QA, no repetirla.

## Intento inmediato autorizado — 12-oct-2026

Dictamen:precondition_not_met; no corte ni mutación de producción. Preflight
17:45Madrid:producción .364/kernelok/papertrue/livefalse/auto-applyfalse;
XNYS abierto y continuous_improvement running,run ci_sched_cc8808830225 desde
17:41Madrid. No se interrumpió el job ni se fabricó quietud.

La autorización de intentar ahora se aplicó a QA Windows aislada, sin competir
con Jetson. Smoke/configuración pasan. Fullsuite única inicial:2228 passed,
1 failed; se detuvo, no es aceptación verde. El test de schedule-status esperaba
cerrado sin fijar hora. Se reprodujo exactamente en base .364 limpia; scheduler
y test eran idénticos a base antes de la reparación. Se corrigió sólo el test,
fijando dos horas XNYS abiertas/cerradas:11 focales del archivo pasan. Ningún
fuente de producción cambió desde el snapshot. La nueva fullsuite del árbol
de tests corregido tiene causa documentada y queda para el intento22:45; no
repetir la suite fallida idéntica. Journal y snapshotv2:
EF99/release_oct12_0368_full_attempt_result.json.

Fuentes .368 congeladas:211 archivos,zipSHA256
d29d69e3d4cbabaded991b4d2c02ae2e5a265a8ed66c5edf6298bb361e4d171c.
El ZIP no es imagen ni aprobación; ARM sigue pendiente. Automatización22:45
permanece activa y deberá leer este relevo, comprobar gates y el árbol más
reciente antes de QA/corte. No activar tamaños/adds/score sin evidencia previa.

## Capital 25% — candidato .368 local, sin activar — 12-oct-2026

Código de tamaños y observación integrado sobre .364 exacta;315 focales verdes,
Ruff/diff/configuración aislada/NUL511 pasan. Objetos protegidos intactos.
Fullsuite única, smoke y QA ARM pendientes de cierre y preflight; no desplegado.
Observación no acredita cinco sesiones ni autorización de inversión. BUY inválidas
se bloquean sin bloquear SELL; cash reservado broker/local/ciclo y riesgo
desconocido failclosed. Ampliaciones bloqueadas hasta protección canónica de
cantidad añadida; score y tamaño5% sin autoridad activa. Lotes separados.
Informe vigente:docs/informe_oct12_capital_25.md. Evidencia:
EF99/release_oct12_0368_focal_snapshot.json. Mantener revisión del12 sin cambios.

## .364 desplegada y verificada — 11-oct-2026

Dictamen: deployed. Corte completado 18:42:39 Madrid; sellado canónico intencional
18:42:33, kernel ok. Imagen activa en scheduler/web/auxiliary: sha256:8515f6bd289759827e6c04670fd02006bbf58dfb4879d817ce8d97f7991a7208.
Fuentes de release HEAD efce78861c3040ee996d85e82b9841d143ece3f9, tree 7583fe8fdf5a53f5ac5cc2eb6847ccaa0d426173; 206 hashes
verificados en los tres servicios. Los commits documentales posteriores no
cambian la imagen ni las fuentes probadas. Rollback .321 inmutable conservado.

QA final:2869 passed,1 skipped preexistente,0 failed;89 focales,Ruff,NUL,diff,
configuración y smoke aislados pasan. Paridad exacta de productividad; iterator
de ciclos conserva fila,orden,límite,errores y cierre. ARM digest completo ampliado
con 5000 ciclos/reportes grandes,18MiB de padre y256MiB de cgroup:exit0,0OOM,
peak RSS hijo226914304. No elevar límites ni extrapolar garantía infinita.

Recuperación real .364 completed 18:36:43 Madrid con informe no vacío SHA256
ebc1f15848bf4f63c8b1098629c87858288ab167270bda2e6713e03bdfe84cea.
Failed original d828eec315c4303cd64579b5b39bf86edf7f6acfa2169b02b36f54e064eece6a
y recibos preservados en /data/reports/deployment_recovery; ningún nuevo
oom_kill en este intento. La ejecución real tardó unos10min por I/O sobre
históricos: memoria corregida, latencia de digest pendiente de medir/optimizar.
No se vaciaron estados ni históricos para aparentar salud.

Preflight: XNYS cerrado; postmarket última sesión9-oct terminal failed
stage_postmarket_report_failed (deuda previa, no ocultada); sin jobs/leases
activos en consulta RO contrastada con procesos. Paper true,live/auto-apply false,
kernel/config válidos y margen de recursos. Configuración Compose igual excepto
imagen. Dos incidentes del controlador quedaron auditados: comparación inicial
del alias YAML x-app-common/image abortó sin corte; primer sellado efímero root
sin capacidades no pudo leer /data/state y produjo rollback automático .321.
Se verificó DAC_OVERRIDE sólo para el contenedor temporal autorizado de sellado;
no se cambió la configuración/capacidades de los servicios operativos.

Aceptación: controles 2026-10-11T16:43:08.678731+00:00 y 2026-10-11T16:44:27.628487+00:00 (>75s),
HTTP / y /_stcore/health200; tres healthy,RestartCount0,OOMKilledfalse.
Scheduler único PID7/token33364117, coincide con
lock y proceso; actividad fresca tras arranque,operational_health_refresh completed.
Auxiliar heartbeat nuevo 2026-10-11T16:52:40.664650+00:00,ci_digest completed.
Observación 601.01s/14muestras: sin
reinicios ni OOM; vecinos intactos. Evidencia EF99/deploy_oct11_0364_acceptance_*.json,
deploy_oct11_0364_resource_observation.jsonl y release_oct11_0364_deployed_receipt.json.
Web alcanzó presión de caché cerca del cgroup1GiB (memory.events max1130,oom0);
lectura memory.stat muestra unos661MB file/348MB anon y proceso padreRSS134396kB.
No confundir max con OOM ni RSS padre con todo el servicio; seguir midiendo caché.
Hashes application.env y runtime.env intactos; manifiesto cambia sólo por sellado
aprobado y conserva copia exacta para rollback.

Salud funcional existente: operational_health fresco16:43:08UTC warning,0critical,
5warnings (3setup_edge_deterioration,post_market_attribution_degraded,
post_market_pipeline_slow). No desactivar estas alertas válidas para invertir más.
latest_production_health fecha10-sep es obsoleto y market_data_quality unavailable;
no certifican datos actuales ni preparación BUY. Son gates/deudas para la sesión,
distintos de liveness e integridad del despliegue; no generar jobs manuales para
maquillar informes. Digest completado no repara automáticamente postmarket9-oct.

Siguientes pasos: conservar revisión12-oct10:00Madrid sin cambios. Sesiones5–9oct
corrieron .321; no atribuirles .364. Medir5 sesiones completas12–16oct si .364 se
mantiene activa: exposición temporal/cash,embudo109BUY/IDs exactos,primera frontera,
sizing,costes,rotación,errores y SPY comparable. Capital:53BUY bloqueados por
position_adds_disabled;8planes/fills con0.5/cap1000 y redondeo;48BUY frontera
unavailable. Eso identifica causas/cobertura, no beneficio ejecutable perdido.
Prioridades: completar carriers de frontera/sizing sin consultas extra ni autoridad,
medir fallback/latencia LLM y digest, verificar exposición long y partial EXIT en
eventos reales. Sin mínimos de inversión ni aumento de riesgo; asignación futura
en lote separado con costes,validación cronológica y paper. Protección broker APO
requiere evidencia broker; niveles locales no la certifican.

## QA local final .364 cerrada — 11-oct-2026

Fullsuite del árbol definitivo:2869 passed,1 skipped,0 failed,791.51s,exit0.
Skip preexistente de historia local unavailable. Focales89, Ruff,NUL556/0,
diff, configuración y smoke aislados pasan; Python proyecto,PYTHONPATH exacto,
DATA_DIR temporal,_env_file=None,PYTHON_DOTENV_DISABLED=1 y red externa bloqueada.
No repetir esta suite sin nueva causa. Snapshot fuentes/tests en EF99
release_oct11_0364_tested_tree_snapshot.json y journal
EF99/oct11_0364_final_full_v6.jsonl. Fuentes/tests congelados desde su inicio.
Paridad exacta de solicitudes y ARM preliminar combinado constan abajo.
Producción todavía .321; ARM final, recuperación y corte pendientes.

## .363 no apta para despliegue real; .364 en QA — 11-oct-2026

La recuperación canónica real con .363 falló returncode=-9. Failed original
SHA256 d828eec315c4303cd64579b5b39bf86edf7f6acfa2169b02b36f54e064eece6a
se conservó sin modificar last_status. Backups/receipts en
/data/reports/deployment_recovery. cgroup oom_kill aumentó4->5: OOM real.
El perfil operativo posterior exit137 localiza acumulaciones en listas del
laboratorio y reconstrucción de agentes; el proceso cae al comenzar
build_research_mode_usage. No desplegar .363 por pasar fixture insuficiente.
La raíz readonly rechazó docker cp antes de la recuperación; staging permitido
/data/tmp/oct11-0363-recovery contiene fuentes alternativas, NO hotpatch de
/app/src ni cambio de imagen activa. Producción sigue .321; no sellado/corte.

Reserva.364: iterator read-only de ciclos conserva SELECT,ORDER,LIMIT y decodificación
legacy, con cierre explícito incluso error/close temprano; research conserva
sólo cycle_id tras validar cada fila. Resumen de agentes libera run_states por
orden original a medida que reconstruye runs. Sin recortar históricos ni límites.
89 focales pasan; Ruff pasa. Paridad exacta productividad contra HEAD.363
46598ad621c30730f0bc783a134b9599da918e61 con8000 eventos/4000runs sintéticos.
Fullsuite del nuevo árbol en curso:EF99/oct11_0364_final_full_v6.jsonl;
fuentes/tests congelados y snapshot EF99/release_oct11_0364_tested_tree_snapshot.json.
Imagen agente-bolsa:0.4.364-qa-arm64 sólo QA; ZIP/manifest preparatorios no
acreditan aprobación de corte. Ensayo ampliado añade propuestas,experimentos,
decisiones y5000 ciclos con informes grandes; datos exclusivamente sintéticos.

La auditoría agregada de tamaños terminó timeout60s y queda unavailable;
no usar resultados inexistentes ni repetirla sobre producción sin nueva causa.
El profile operativo sí quedó capturado en EF99/audit_oct11_digest_live_profile_stderr.txt.
Pendientes: QA final/ARM, recuperación satisfactoria real con failed preservado,
preflight inmediato completo, sellado aprobado y deploy +doble salud/OOM600s.
Revisión12-oct y límites intactos.

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

# Relevo de direccion tecnica — agenteBolsa

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

## Estado vigente — 9-oct, candidato N2 `.353` de streaming de contexto

Dictamen: `partially_verified_context_streaming_candidate`; no integrado ni
desplegado. Base `7d4f4bc1f54d45fca9f6cc62867f4ddf9b6d80a1`/tree
`011cdf6b9608e1e8e71aba80b29b4f36169a1b3a`, rama
`codex/oct08-context-streaming`, versión `0.4.353`.

Cambios en `storage.py` y `tools/decision_context.py`: cuatro consultas
independientes RO con cursores `fetchmany`, acumuladores de calidad y fallback
legacy. Límites exactos `50000/50000/200000/200000`, orden, filtros, IDs,
payloads y denominadores preservados. Sin transacción snapshot común. El
context manager cierra cursor/conexión en agotamiento, error y abandono
explícito. Commits: `9c66ccc9` funcional, `d339d78d` corrección de paridad,
`98af4766` y `4ee590fb` tests.

QA aislada: `5 passed` streaming; `45 passed` streaming + snapshot + digest
reuse; Ruff `src tests`, NUL y `git diff --check` verdes. XNYS abierto fue
verificado por `schedule-status` a las 20:36 Madrid. No fullsuite, smoke,
build, broker, red, LLM, producción, merge, push o despliegue. La evidencia
prueba lectura por lotes y paridad contra baseline/oráculo legacy; no prueba
RSS productivo ni causa única del OOM.

Revisión independiente detectó y corrigió regresión en `decision_source_coverage`:
se conserva exactamente `snapshot.get("decision_source") != "unknown"` para
coverage, mientras `sources` mantiene su normalización legacy. Se añadieron
variantes missing/`None`/`''`/falsy/malformed, comparación de payload completo y
caso de cierre de conexión tras fallo de `PRAGMA`.

Siguiente: revisión independiente y ensayo de integración en ventana cerrada,
manteniendo fuera de este lote `comparable_controls`, `performance_daily`,
`llm_usage`, stdout del supervisor, esquema, configuración y archivos
protegidos. Informe único: `docs/informe_oct08_digest_memory_audit.md`.

## Estado vigente — 8-oct, integración nocturna .352

Dictamen: `needs_final_validation`, no desplegado. Candidato funcional limpio
HEAD `7dce37e1b4464a696daaff5de65468c889396296`, tree
`0ec3540e44b2ef5f3fb1019c523ad15819095f3b`, versión `0.4.352`.
Esta sección sustituye los estados operativos y tareas abiertas de las entradas
históricas inferiores; no cambia su evidencia ni convierte pruebas antiguas en
validación del árbol actual.

## Relevo Oct09 N2 — cierre del TypeError postmercado

El defecto local compatible con el fallo de la sesión 8-oct queda confirmado
contra la base: el resumen diario puede transportar `open_unrealized_pl=None`
sin posiciones y
`_learning_candidates` lo comparaba directamente con cero. El snapshot de ef99
registra el mismo `TypeError`, pero ese literal no confirma frame ni inputs
productivos; el corte del 9-oct tenía nueve posiciones. Los logs Docker remotos
de la ventana autorizada están ausentes o rotados, por lo que la causa
productiva queda inferida/compatible, no confirmada. El cambio mínimo en la línea
`.354` conserva
unavailable como `None`, descarta booleanos y no finitos, y mantiene el criterio
para P/L negativo válido. No toca trading, órdenes, históricos ni archivos
protegidos.

Caracterización `b1d5169d`, fix `b4ddf194`; documentación en
`docs/informe_oct09_postmarket_null.md`. Verificación: `23 passed` en las dos
baterías focales, casos nuevos de strings/containers, Ruff/diff/NUL verdes y
reproducción base resuelta. XNYS estaba
abierto: no fullsuite, smoke, build, producción, broker, red, LLM, locks ni
configuración. El checkout final debe quedar limpio tras el commit documental;
registrar HEAD/tree/status en la entrega.

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

## 8-oct-2026, 14:57: relevo vigente

Release needs_fix, producción .321 sin build/corte/restart/deploy. Candidata
.343 scoreboard v3, HEAD funcional ab28bd86/tree daa3f125, más fixture test-only
2f4f4da2 de lecciones; learning_mode corregido e0c90864, smoke limpio/config ok.
Suite .343 interrumpida tras 1501 resultados/13 fallos por bucle de workers en
p49br1; NO repetirla sin cerrar causas ni presentarla como verde. Nueve fallos
persisten en diagnóstico focal; cuatro multiproceso pasan solos. Captura on/off
p49br1 pasa; interacción de suite aún sin explicar. Diagnóstico de 1255 restantes
corre en session70586; no duplicarlo ni detenerlo por mera observación lenta.

Luna trabaja aislada: coordinación .344, linkage .345, uplift .346. Dirección
preparó scheduler grace .347, HEAD 5bf84282, 1+27 pruebas verdes, no integrado.
Consultar informes propios; resolver versiones campo a campo, sin ours/theirs.
Preflight 14:41 XNYS cerrado, paper/livefalse/autoapplyfalse, sin jobs/leases
activos observados, próxima apertura 15:30. No heredar este gate al corte.
Ver informe integrado/plan para causas y evidencias. Autorización deploy recibida;
faltan revisión/integración, fullsuite definitiva, gates y doble salud productiva.

## Antecedente 8-oct-2026: estado del ensayo conjunto

Estado de entonces: recuperación operativa completada; candidato .342, HEAD 0e8712b0.
Paridad resuelta con reloj congelado del fixture (sin retirar as_of). Suite -x
se detuvo: 638 passed, 1 failed en learning_mode, reproducido en base 1adc3cec.
No repetir suite sin causa ni cambiar política para aprobar el test. Ruff
completo/NUL/diff verdes. Smoke flujo completed, limpieza Windows WinError 32.
Release needs_fix; no build, corte, restart ni deploy. Resolver contrato/fixture
de learning_mode y limpieza del harness antes del siguiente preflight de corte.

Actualización 13:57 Madrid: recuperación autorizada completada, dos vistas
resueltas con respaldo y evento atómicos; kernel/config productivos ok. No
repetir limpieza ni avanzar last_session. Nuevo gate actual `needs_fix`: la
prueba económica conocida falla rec_payloads True/False; explicar diferencia
antes de release, sin retirar aserciones. No hubo corte, build ni despliegue.

Actualización 13:42 Madrid: nuevo scheduler PID 7, reinicio 11:38, misma imagen.
PID 6 ausente; terminales failed exactos de ambos runs antiguos contrastados.
Vistas antiguas active no equivalen a trabajo vivo. Recuperación PMR emitió
terminal con sesión 8-oct para el run del 7-oct: defecto de identidad verificado.
No corregir historial append-only ni limpiar claves a ciegas; preparar lote
acotado y recuperación operativa explícita antes del nuevo preflight/deploy.

Actualización 09:09 Madrid: el usuario autoriza desplegar; nuevo preflight
devuelve `precondition_not_met`, con lease postmarket active/outcome_update y
reconciliación registrada active. No se interrumpen ni limpian implícitamente.
Producción intacta; queda pendiente resolver estado operativo antes del corte.

Siete lotes reunidos en `codex/oct08-integration-rehearsal`; informe único
`docs/informe_oct08_integration.md`. Dictamen `partially_verified_integration_candidate`:
87 casos distintos pasan, Ruff/NUL/diff verdes y protegidos sin cambios.
HEAD funcional probado `5f2f530d2eab5b72c171a3fc0bd1afc1f9ddf5c4`;
las notas inferiores de ensayo pendiente quedan como historia de los lotes.
Producción intacta. Último preflight 08:33 Madrid: lease postmarket activo;
validación operativa `precondition_not_met`, automatización de cierre PAUSED.
No repetir focales sin nueva causa. Antes de release: nuevo preflight completo,
resolver identidad .321/.340, reservar/bump y gates pendientes, incluido fallo
económico reproducido en base. No reiniciar ni forzar postmarket implícitamente.

## 8 octubre 2026: exclusión local de estudios duplicados

Candidato N2 `ready_for_integration_rehearsal`, rama
`codex/oct08-study-dedup`, base `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`.
Informe único `docs/informe_oct08_study_dedup.md`. Guard no bloqueante por
Store/job entre bootstrap y APScheduler; diagnóstico de archivo fail-open,
sin SQLite/runtime del duplicado. 37 focales passed; Ruff/NUL/diff verdes.
Sin fullsuite, smoke, producción, red/broker/LLM, restart/deploy/push.
Versión/reserva diferidas; NO release. Siguiente: ensayo aislado por dirección;
validación operativa requiere lease postmarket terminal y gates autorizados.

## 8-oct-2026: candidato aislado de memoria en outcomes

Dictamen `partially_verified_outcome_memory_candidate`; informe único
`docs/informe_oct08_outcome_memory.md`. Base `1adc3cec`/v0.4.321, rama
`codex/oct08-outcome-memory`. Cachés locales por símbolo exacto en capturas H
y loop legacy; identidad, linaje y fallos por fila conservados. QA: 12 passed,
Ruff focal/NUL/diff verdes. Paridad de payloads completos con reloj fijo.
No RAM productiva medida ni causalidad operativa demostrada; el loop legacy
retiene ahora un marco por símbolo, tradeoff documentado. Producción intacta.
Bump/reserva diferidos al coordinador; no release. Validación completa y
operativa omitida y no aprobada: lease postmarket activo comunicado 08:33 Madrid.
Siguiente paso: revisión, reserva/bump y ventana cerrada sin leases/jobs activos.


## P-L155: lector de recibos EOD de SPY y reloj del productor (28-sep-2026)

Dictamen: `ready_for_integration_rehearsal`. Worktree exclusivo
`pl155_spy_eod_post_session`, rama `codex/pl155-spy-eod-post-session`, base
exacta `1b87e886a2f682d599ada157bd22074f0d622219`/tree
`e7246bb057a9b75f0a94086824f9469ff0f8cee2`/v0.4.320. XNYS cerrado a las
12:49:33Z con `next_open` 2026-09-28 15:30 Europe/Madrid. Produccion NO tocada:
sigue `agente-bolsa:0.4.320-arm64` en el Jetson 192.168.1.186, sin SSH, sin
docker, sin despliegue, sin push. Checkout principal y worktree
`pl155-deepseek` intactos.

Causa raiz: `load_spy_eod_receipt` ordenaba por nombre de fichero, cuyo sufijo
es `content_hash[:8]` y no tiempo, y no filtraba por `comparison_status`.
`reversed` empezaba por el `unavailable` `spy_eod_close_20260924_fdf426ce.json`
y tapaba los `comparable` `8a09005c` y `a5284111`; el overlay caia a la cache
same-day y el Telegram salia con SP500 n/d. El productor fijaba el reloj de
captura antes de descargar, dejando 5 de 18 recibos con
`cache_created_at_future`.

Cambios, solo en `src/agente_bolsa/tools/spy_eod_authority.py`: precedencia
`comparable` sobre `unavailable`, luego `captured_at` mas reciente en UTC, con
desempate determinista declarado en `_receipt_precedence` (`content_hash`
completo, luego `receipt_path`); validacion de `schema_version`,
`session_date` y `content_hash` intacta y lectura estrictamente append-only.
`_capture_clock` toma el reloj de captura despues de la descarga, avanzado
hasta el `created_at` declarado; `session_status` se sigue evaluando antes de
descargar y no se descarga con la sesion abierta. Firma publica sin cambios,
fail-open intacto. Bump 0.4.321. Ningun archivo protegido modificado.

Commits: caracterizacion `7a5829202b2d79160feb112c32b53fdf37db4a8a` (7 tests
en rojo contra la base) y funcional
`1de86db07875cc3a3002b96dda8cb31de3912ce1`/tree
`30563d7ffa54b4d569ff63a60b4e409e4b491a37`; el hash del commit de
documentacion lo registra direccion. Ficheros: `spy_eod_authority.py`
(+94/-9), `__init__.py` (bump), `tests/test_p155_spy_eod_receipt_selection.py`
(nuevo, 15 tests) y pin de version en
`tests/test_p59c_llm_selected_authority.py`.

Pruebas: focal del lote 15 passed; focales relacionadas 96 passed; regresion
amplia filtrada por overlay, spy, eod, benchmark, telegram y performance:
candidato 17 failed / 308 passed frente a base 23 failed / 302 passed, con
`Compare-Object` de las listas `FAILED` sin ninguna entrada solo en candidato.
Ruff, `check_no_nulls` (537 archivos) y `git diff --check` verdes. CLI
`spy-eod-coverage --json` aislado responde `ok: true` y `receipt_missing` con
`DATA_DIR` vacio.

A1-A9 pasan. A6 paridad total: el diff no toca `performance_daily`, candidatos,
scores, ranks, gates, sizing, planes, ordenes, precios, stops, exposicion ni
limites. A7 sin backfill, sin reescritura, sin esquema ni tablas. A8
`0.4.321` no estaba reservado y no colisiona con P-L148 (0.4.250).

Gates omitidos y NO aprobados: suite completa, benchmark de 33.336
observaciones, smoke `run-once --skip-crew`, `validate-agent-config --json`,
`kernel-status --json` y despliegue. Justificacion: lote N2 sobre un unico
lector, presupuesto proporcional, margen operativo corto y `storage.py` sin
diff. Los 17 fallos de la regresion amplia son copy de Telegram preexistente,
reproducidos tambien contra la base, y se dejan como micro-lote separado sin
`skip` ni `xfail`. Defecto de test preexistente detectado:
`test_p127_spy_slice_characterization.py::test_refresh_open_session_never_downloads`
parchea un simbolo que la funcion importa dentro del cuerpo, asi que su doble
es ineffective; A4 lo cubre parcheando `agente_bolsa.tools.market_data`.

Limitacion declarada: la fixture de A1 replica los nombres y la distribucion
de `comparison_status` exactos de produccion con contenido generado por el
productor real; los `content_hash` interiores no coinciden con los del Jetson
y los `captured_at` reales de produccion siguen `unavailable` para este lote.
El defecto es de orden por nombre, que depende solo del nombre y del estado.

Siguiente paso minimo, sin ejecutar: ensayo de integracion con `merge --no-ff`
de `1de86db07875cc3a3002b96dda8cb31de3912ce1` sobre la base exacta, tree del
merge con los cuatro ficheros efectivos identicos al candidato, y repetir alli
regresion amplia mas Ruff, NUL y `git diff --check`. Precondiciones: XNYS
cerrado, sin leases ni jobs activos, arboles limpios, version sin colision.
Informe unico: `docs/informe_p_l155_lector_spy_eod.md`.

## P-L137-R + P-L133-R + P-L140A-R + P-L140B-R desplegado 0.4.320 (26-sep-2026)

Dictamen: `deployed`. Port de 4 ficheros de `src` sobre la imagen
`0.4.316-arm64` ya productiva, con autorizacion explicita del operador
("Si, despliega 0.4.320 ahora", 20:31). Tree funcional
`00e5bdeadf1a7d6cd9340e76fbd9b136c3583412`; candidato
`d39ed702ea511fc33893bfd26564d103cea44da8`/tree
`2efe05d0173dcaa853904de25e0e6b8ed9d68470`/v0.4.320, rama
`codex/pl137-140-readd-rehearsal`. Imagen
`agente-bolsa:0.4.320-arm64`
`sha256:35f1cca4871d54247d92ae5c41c6976c00da9a5c024b449218e3f5ea895f9683`,
runtime verificado 0.4.320, port-base 0.4.316-arm64.

Validacion cerrada por particiones (suite completa en un unico proceso
detenida a las 18:57 por presupuesto 2x): A `41F/153P`, B `164P`,
C `2310P/1 skip`, P-L45B2 `33P` -> **2660 passed, 41 failed, 1 skipped,
0 collection errors**. Los 41 fallos son subconjunto exacto de los 46
del baseline 0.4.316; los 4 errores de coleccion de la base
(p133/p137/p140a/p140b) desaparecen. Nodo lento explicado:
`test_current_sequential_baseline...[33336]` = 181,62 s aislada, con
`storage.py` sin diff frente a la base.

Corte: 0 leases antes de parar; `docker stop` de los 3 contenedores;
backup del selector `runtime.env.bak-pl-0320`; flip a
`AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.320-arm64`;
`jetson-ops deploy-agente-bolsa` con `init-db` `Exited(0)`. Doble salud
`18:33:28Z` y `18:35:22Z` (114 s): healthy x3, restart 0, OOM false,
HTTP `/`,`/health`,`/_stcore/health`,`/kindle` 200, kernel `ok` con 0
violaciones, flags paper/live-false/auto-apply-false, lock pid 7 token
`4298981`, listener unico 8081, 0 leases, 0 ordenes, 0 planes,
`MAX_EVENT` 18:33:04Z -> 18:34:52Z, sin alertas criticas. Bootstrap
`skipped`/`market_not_ready` para 26-sep (sabado). Sin migracion de
datos, sin `kernel-seal`, sin tocar `.env`, sin `whale-copy`, sin push.
Rollback: `AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.316-arm64` + re-`up`.

Mejoras del release, todas N2/N1 sin cambio de politica: P-L137 recorte
de outcomes a sesiones XNYS completadas con `session_seal_degraded`;
P-L133 resumen de skips por job y vaciedad de outcomes en health
(fail-open, `pct_empty=None` con denominador 0); P-L140A franja Mis
inversiones; P-L140B SPY unico, leaderboard a Config via
`session_state`, baseline duplicado sin render. P-L148 sigue 0/5.

Deuda de suite restante, en micro-lotes y sin mezclarla con este
despliegue: P-L80B x2, P-L131 x4, P-L132 x3, P-L134 x3, P-L135 x4,
P-L139 x1, P-L71 x3, P-L72 x1, P-L81 x1, copy Telegram x12,
`learning_mode` x1, `learning_scoreboard` x4, `lesson_distiller` x1,
`market_cycle_timing_integration` x1. P-L154-A sigue siendo la
prioridad economica, sin cambio de politica activa. Informe unico
`docs/informe_p_l137_140_readd_rehearsal.md`.

## Ensayo combinado P-L137+P-L133+P-L140A+P-L140B (rehearsal 0.4.320, 26-sep-2026)

Dictamen: `ready_for_closed_market_full_validation` (integracion
aislada N2/N1, sin validacion completa ni despliegue). Worktree
NUEVO exclusivo `pl137_140_readd_rehearsal`, rama
`codex/pl137-140-readd-rehearsal`, base exacta P-L158-B
`85e28447`/tree `70d487e7`/v0.4.316. Merge `--no-ff` `338136fa`
(parents `85e28447`+`09980875`) del candidato extremo exacto
`09980875`/tree `00e5bdea`/v0.4.320, sin conflictos; tree del
merge identico al candidato (diff vacio). XNYS cerrado 26-sep;
next_open 28-sep 15:30 Europe/Madrid. Cero cambios
`src/tests/version`; protegidos/`.env` sin diff. Paridad por
fuente: recorte P-L137 pre-bucle, health P-L133 fail-open sin
alertas, UI P-L140 solo lectura (baseline sin render, leaderboard
via `session_state`), timers P-L158 intactos, denominadores
missing/`unavailable` intactos. QA: 186 passed combinados
(solapes declarados), Ruff/NUL(536)/diff/validate verdes. Gates
omitidos: suite, smoke, benchmark, kernel-status, validacion
completa, despliegue, doble salud. Informe unico
`docs/informe_p_l137_140_readd_rehearsal.md`; plan maestro con
entrada del ensayo. Siguiente: una sola validacion completa del
arbol `00e5bdea` con precondiciones frescas; despliegue solo con
autorizacion explicita. Sin push. Produccion Jetson 0.4.316 y
principal intactos.

## P-L140B-R re-add minimo (candidato 0.4.320, 26-sep-2026)

Dictamen: `ready_for_integration_rehearsal` (N1 UI, solo presentacion).
Worktree exclusivo `pl140b_readd_0320`, rama `codex/pl140b-readd-0320`,
base exacta P-L140A-R docs-corrected `49f3b19f`/tree `041b4bbc`/
v0.4.319. XNYS cerrado 26-sep-2026; next_open 28-sep 15:30
Europe/Madrid. Causa reproducida en base: ImportError
`_spy_alpha_summary` (coleccion 1 error en `test_p140b_spy_unico.py`)
+ guard p65a rojo por `_render_performance_baseline` en
`page_dashboard`; referencia historica `1b29df23`/`10dcd62b` sin
cherry-pick. Cambio solo `web_app.py` (+53/-6): helper puro
(final+comparable, geometrica, `None` sin filas, nunca cero),
quinta metrica Alpha (4→5 columnas), leaderboard Dashboard→Config
via `session_state` sin mutar autoridad ni llamadas, llamada
baseline retirada del expander (helpers conservados por P-L140C).
Sin P-L139/scoreboard/politica/persistencia/fuente nueva/broker.
P-L140A/P-L137/P-L133 y timers P-L158 intactos. Bump 0.4.319→0.4.320
+ pin P-L59C: funcional `cb2f6808` + version/pin `2a88081f` (+ docs;
HEAD/tree finales en entrega). QA: focales 17, combinada 147,
regresiones 37; Ruff/NUL(536)/diff/validate verdes; protegidos sin
diff. Gates omitidos: suite, smoke, benchmark, kernel-status,
integracion final. Informe unico ampliado
`docs/informe_p_l140b_spy_unico.md`; plan maestro con entrada
P-L140B-R. Siguiente: ensayo combinado de integracion en mercado
cerrado. Sin merge, despliegue, reinicio ni push. Produccion Jetson
0.4.316 y principal intactos.

## P-L140A-R re-add minimo (candidato 0.4.319, 26-sep-2026)

Dictamen: `ready_for_integration_rehearsal` (N1 UI, solo presentacion).
Worktree exclusivo `pl140a_readd_0319`, rama `codex/pl140a-readd-0319`,
base exacta P-L133-R `baba2dd9`/tree `06270950`/v0.4.318; funcional
`60fe034a` + version/pin `88ce177f`/tree `0b4340d5` (version 0.4.319, pin
P-L59C actualizado) + documental previo `58e9497c`/tree `f5cf652b`.
Correccion N0 26-sep-2026: la mencion anterior a `88ce177f` como
candidato final era stale pre-docs; el HEAD/tree finales post-correccion
N0 se consignan en la entrega/HANDOFF.
Causa: `784e6cd7` retiro helpers/render dejando ImportError
`_invested_day_metric` (reproducido en base); re-add campo a campo
(+84 en `web_app.py`, mismo conteo que `e7244de2`) con snapshots ya
cargados, `n/d` si invertido<=0/missing, cero broker nuevo, sin
persistencia ni autoridad; P-L137/P-L133 intactos, sin P-L140B/P-L139/
scoreboard/politica/telemetry. QA: focales 7, combinada 113, version
54; Ruff/NUL(536)/diff/validate verdes; protegidos sin diff. Gates
omitidos: suite, smoke, benchmark, kernel-status, integracion final.
Informe unico ampliado en `docs/informe_p_l140a_mis_inversiones.md`;
plan maestro con entrada P-L140A-R. Siguiente: P-L140B re-add
separado, luego ensayo combinado. Sin merge, despliegue ni push.
Produccion Jetson 0.4.316 y principal intactos.

## Prioridad vigente - P-L158-B, 26-sep-2026

Dictamen: `ready_for_closed_market_deployment` **con reserva** (N1, solo
observacion) tras la validacion completa aislada del 26-sep. Candidato
`codex/pl158b-integration-rehearsal` HEAD `6aab5028`, tree `0de7b35c`,
v0.4.316 (merge --no-ff `7ad1d2e9`; base `708f0e46`, tree `585a7557`).
Informe unico: `docs/informe_p_l158b_perfil_fino.md`; backlog en plan maestro.
**Este lote no propone corte.**

- Sub-secciones finas dentro de opening_context (5 funciones), setup (2) y kpis
  (2) con el `_DashboardTimer` existente; `total_seconds` = seccion envolvente
  `total` (corrige la doble suma de P-L158-A). Cero cambios de logica, trading,
  riesgo, UI, cache o firmas. Protegidos sin diff (blobs identicos). Produccion
  Jetson 0.4.315-arm64 intacta.
- Suite completa aislada 26-sep (sabado, XNYS cerrado), sin `-x` y con
  `--continue-on-collection-errors`: candidato `6aab5028` 46 failed/2586
  passed/1 skipped/105 warnings/4 errors en 1437.59 s; base `708f0e46` 46
  failed/2582 passed/1 skipped/105 warnings/4 errors en 886.98 s. Fallos y
  errores identicos entre ambos; delta +4 = tests nuevos
  `tests/test_p158b_dashboard_perf.py`. 4 errores de coleccion preexistentes
  (test_p133/test_p137/test_p140a/test_p140b, simbolos ausentes en `src`) y 1
  skip preexistente (`test_score_study_regression_current_sqlite`). Benchmark
  P-L45 omitido por coste.
- Smoke aislado `run-once --skip-crew`: exit 0, ciclo `20260926-080243`,
  `used_crew=false`, `broker_orders=0`, `order_plans=0`, `agent_events=52`.
  Ruff/NUL/diff/config verdes; `kernel-status=unsealed` esperado en `DATA_DIR`
  temporal.
- Fase 1 productiva (read-only): sesion `2026-09-25` terminal `completed`
  (`pmr_a2c364c6dbc5`, 20:28:09Z); 0 leases activos en la relectura.
- Reserva: la deuda de suite (46 failed + 4 errores de coleccion) es
  preexistente e identica en la base 0.4.315; se repara en lotes aparte y no se
  oculta con skip/xfail ni se aprueba por omision.
- Secuencia siguiente (no ejecutada en este lote): ventana cerrada con postmarket
  terminal, leases/jobs ausentes y autorizacion explicita del operador -> port
  Jetson + corte con snapshot frio y doble healthcheck. Nunca desplegar por el
  worker.

## Prioridad vigente - P-L137-R (re-add trim_to_completed_sessions), 26-sep-2026

Dictamen: `ready_for_integration_rehearsal` (N2 finality outcomes). Lote unico
de re-add puro, sin despliegue. Candidato `codex/pl137-trim-readd` v0.4.317;
base `85e28447` (P-L158-B rehearsal, tree `70d487e7`, v0.4.316); commits
`c8ddabc7` (feat) + `98d91bdc` (test) + `1dd3d5fe` (docs). Informe unico:
`docs/informe_p_l137_trim_readd.md`; backlog en plan maestro.

- Causa: `784e6cd7` (reconstruccion Jetson `.310`) elimino 4 helpers puros
  conservando sus tests, dejando 4 errores de coleccion. Este lote re-anade
  solo `trim_to_completed_sessions` + `last_completed_session` y el cableado
  en `update_signal_outcomes` (recorte una vez pre-bucle, publica
  `bars_trimmed_universe`/`last_completed_session`/`session_seal_degraded`,
  kwarg `now`). Sin autoridad trading/riesgo/ejecucion ni politica.
- QA: focales 4 passed; regresiones 47 passed (signal_learning 27 +
  counterfactual_analysis 20); Ruff/NUL(536)/diff/config (`ok=true`) verdes.
  Paridad bit-identica historia cerrada probada. Suite completa y smoke
  omitidos (lote N2 aislado; suite roja preexistente identica en base).
- Los otros 3 errores de coleccion (p133/p140a/p140b) y la deuda de suite
  siguen en lotes aparte, sin mezclar. Despliegue: NO autorizado.

## Prioridad vigente - P-L133-R (re-add skip/emptiness observacional), 26-sep-2026

Dictamen: `ready_for_integration_rehearsal` (N2 observabilidad fail-open).
Lote unico de re-add minimo sobre P-L137-R, sin despliegue. Candidato
`codex/pl133-skip-emptiness-readd` v0.4.318; base `26f144fa` (P-L137-R,
tree `1f2d90bd`, v0.4.317); commits `769e26db` (feat) + `92834f76`
(test pin) + docs. Informe unico ampliado:
`docs/informe_p_l133_misfire_health.md`; backlog en plan maestro.

- Causa: `784e6cd7` (reconstruccion Jetson `.310`) elimino
  `scheduler_skip_summary` + `signal_outcome_emptiness` conservando
  `tests/test_p133_misfire_health.py` (error de coleccion). La parte
  scheduler (`_skip_delay_seconds` + `delay_seconds`) sobrevivio intacta
  y no se toca. Re-add byte-identico al diff `30def441` (solo
  `operational_health.py`, 58 inserciones): 2 helpers puros read-only +
  wiring fail-open en `build_production_health_report` (summary y
  top-level). Sin grace P-L139, UI, costes, politica, schema ni
  telemetria nueva; sin alertas/gates nuevos.
- QA: focales p133 7 passed; relacionadas 91 passed (p137 +
  operational_health + scheduler observability/lock + autonomous_operations
  + pin p59c; combinada 98 passed); Ruff focal, NUL(536), diff,
  validate (`ok=true`) verdes. Suite/smoke/benchmark omitidos (N2
  aislado; deuda preexistente en lotes aparte). Missing permanece
  `unavailable`; cero solo con denominador conocido.
- Quedan 2 errores de coleccion (p140a/p140b) y la deuda de suite en
  lotes aparte, sin mezclar. Siguiente: revision direccion -> ensayo de
  integracion aislado; sin merge/despliegue/push. Despliegue: NO autorizado.

## Prioridad vigente - P-L154; lote tecnico P-L157, 24-sep-2026

Dictamen: ready_for_implementation para P-L154-A (caracterizacion), sin
promocion economica aprobada. Este bloque prevalece sobre secuencias historicas.
Informe unico: `docs/informe_p_l154_rendimiento_vs_spy.md`; backlog en plan maestro.

- Produccion auditada Jetson .310; imagen
  sha256:9ffd565d051972952601ccc1b6408eaaa6b8493c46d6143b2dd6b0438712194a.
  Checkout local .253, HEAD 694359a6, tree 230e405c; no son equivalentes.
  Etiqueta port-p141-0.4.305: reconstruir procedencia antes de editar.
- 21-sep: 92,811590% efectivo. Comparacion 9-21-sep: equity -0,226486%,
  SPY +0,533151%, ocho intervalos; flujos no verificados.
- Resumen principal excluye learning_experiment; otras fuentes terminan 7-jul.
  Existe apartado separado: verificar consumidores, no asumir truncado.
  Controles comparables 0/78. CI: 192/200 PROSA, cero contratos completos
  y cero experimentos en el ultimo digest.
- Secuencia: A base/caracterizacion; B evidencia reciente/identidad exacta;
  C retorno/costes/atribucion; D challenger de seleccion; E capital/core SPY
  shadow; F propuestas verificables. Una tarea Luna nueva por lote; Astra revisa.
- No activar P-L148 por cinco sesiones ni ampliar limites. Core disabled;
  P-L138 requiere atribucion y ensayo separado de una sola regla.
- Primera release B+C observacional con QA y despliegue cerrado N3.
  Politicas requieren OOS, control y revision posterior. Automatizacion pausada.
- Luna auditora: 01a0c94d-dc10-7023-936a-6dca1444f089; auditoria completada tras
  limite de uso; needs_fix medicion/consumo. Astra reviso dictamen y mantiene sizing. No hay implementacion ni despliegue P-L154.

### P-L157 — migracion exacta de modelo Zen (candidato 0.4.311)

- Dictamen de direccion 24-sep noche: `precondition_not_met` (ver R1 abajo:
  el motivo 403/1010 era artefacto de sonda; el modelo SI responde).
- Base: HEAD `784e6cd7d3170681d6f03c5d39f95442d3fc865a`, tree
  `58fc1824e387b6e72c432119a6c1b60d2b8fb05d`, paquete reconstruido `.310`.
  Etiqueta de imagen `82708495d8b9c7942d461daed38efee54b0aeaf7` no es objeto
  Git; equivalencia demostrada por sha256 identicos en `__init__`/`config`/
  `kernel` y `broker`/`execution` iguales al manifiesto.
- P-L157 migra el ID exacto retirado en Settings, roles, agentes CI, orquestador,
  codegen, probes y selector UI. Proveedor Zen, endpoint, fallback Go/local y
  modelos distintos siguen iguales. Version candidata `0.4.311`.
- Commits separados: caracterizacion `6c68b33f194ceaa84e3154866ef9fa4425f35ba5`;
  implementacion `bea56fb7992103ff267edbf1a6ac693fcc047233`, tree funcional
  `9995ff90a6116c5a84b15d98e78ac77135fc073d`. Documentacion queda en commit aparte.
- `config.py` protegido tiene cambios propuestos y requiere revision explicita
  de direccion; ver inventario de lineas en
  `docs/informe_p_l157_migracion_modelo_zen.md`. No integrar antes de aprobarlo.
- Focales: `21 passed in 2.65s` (Luna); direccion repitio lote ampliado:
  `202 passed in 20.76s`. Ruff completo, `git diff --check`,
  `validate-agent-config` (`ok=true`) y smoke `run-once --skip-crew` (ciclo
  completed, cero ordenes) verdes. `check_no_nulls.py`: `OK (534 archivos)`
  tras corregir el byte historico `0x97` (em-dash cp1252) a UTF-8.
- Suite completa aislada: candidato `2578 passed, 46 failed, 1 skipped`;
  base `2567 passed, 48 failed` (mismos 4 errores de coleccion ignorados,
  reproducidos en base). Cero fallos nuevos, +11 pases; resto = deriva
  preexistente. `kernel-status` aislado `unsealed` esperado; hashes iguales
  al manifiesto productivo.
- El encargo comunico scheduler local `stale_dead_owner` y `runtime_state`
  unavailable; no se repararon. El `schedule-status` de esta tarea uso
  `DATA_DIR` temporal y mostro `missing_lock`/`database_missing`, por lo que no
  clasifica el runtime local. Mantener sin cambios hasta preflight autorizado.
- R3 25-sep 11:00: `deployed`. Port de 10 ficheros sobre imagen `.310`
  (3-way verificado), imagen `72ad000f...`, corte con snapshot frio,
  doble validacion verde y llamada real `v4.1-flash` OK en produccion.
  Reboots 09:12/09:17/10:18/10:29 sin causa determinada: seguimiento
  operador. Vigilar coste LLM en sesion 15:30. Sin push.

### P-L70 — resumen diario Telegram UX (candidato 0.4.203)

- Base `87d29018`/árbol `fd690a93`; worktree aislado
  `pl70_telegram_summary_ux`; rama `codex/pl70-telegram-summary-ux`.
- El resumen usa `p-l70.telegram-daily-summary.v2`, conserva idempotencia por
  `session_date`, no toca fills y no envía mensajes durante pruebas.
- El saldo es absoluto; la variación monetaria exige el par equity de
  `performance_benchmark`; SP500 conserva valor provisional sin declarar
  ganador si P-L68 no confirma comparabilidad; posiciones llevan cobertura y
  grupos deterministas.
- Implementación `f78de077` y QA `0a18924c`, `b3c4d1c2`, `7e96191a`,
  `12de9be5`, `1b64dc5a`. La regresión de fecha dinámica P-L63 quedó congelada
  en el test, sin tocar comportamiento. El recibo v2 conserva texto exacto,
  `text_sha256` y unidades UTF-16; `content_hash` sigue siendo el hash del
  payload canónico. La suite aislada final obtuvo `2261 passed, 1 skipped, 1
  warning`; el skip es el test condicional preexistente
  `test_score_study_regression_current_sqlite` por historia local insuficiente
  o no disponible. Ruff/NUL/diff/compile/config verdes. No se ejecutó smoke real
  ni se enviaron mensajes.

> Actualizado: **28-jul-2026**. Producción estable **0.4.201**
> (`915481ab325d46c81a92986bfd603f13c5134dd9`, árbol funcional
> `f3a2eda76f3c317d68d8679ce00a7ea43a6aa023`). P-L67R1 desplegado y
> validado con dos comprobaciones; candidato final `b25c9603` conservado.

### P-L71 — autoridad EOD y coherencia temporal Sistema vs benchmark

- Candidato aislado `pl71_eod_authority`, versión `0.4.205`. La base de
  producción `0.4.202` conserva el SPY 28-jul incorrecto en storage; no se
  reescribió ni se hizo backfill.
- El bug era la elección por nombre/hash de caches mutables same-day. Ahora se
  exige metadata diaria, rango, fuente, basis explícita, par de cierres y
  autoridad temporal; la vista puede usar solo un cache posterior validado.
- La cabecera live muestra su propia captura/as_of y el panel diario/Telegram
  rotulan `SPY (ETF S&P 500)` y `Provisional`/`n/d` cuando corresponde. No hay
  cambios de trading ni despliegue. Siguiente: ensayo cerrado P-L71 con suite
  completa verde (2260 passed, 1 skip preexistente) y smoke temporal pendiente
  de un ensayo posterior sin servicios reales.

### P-L67R1 — despliegue productivo 0.4.201

- Se preservaron los cambios productivos previos en `b2d7c5c6`; el merge
  `--no-ff` `915481ab` resolvió versión, plan y UI campo a campo.
- El árbol funcional coincide exactamente con el candidato final. La suite
  productiva pasó `2243` pruebas; Ruff, NUL, diff, configuración y kernel
  quedaron verdes.
- Stack gestionado arriba: HTTP raíz y `/health` 200, scheduler
  launcher→runtime único, lock v1 PID 18888/token coherente, lease PMR vacío.
- Tras la parada apareció una alerta transitoria de datos >30 min; el ciclo
  natural `mkt_2fe0c3db689e` terminó en 598,277 s y la salud regenerada quedó
  `warning` con `0 critical`. Cero órdenes fueron creadas desde el reinicio.
- Telegram diario está programado a las 22:05 Europe/Madrid y los avisos de
  fills están activos. No hubo push.

### P-L65A — caracterización diaria Sistema vs SP500 (28-jul-2026)

- Dictamen: `ready_for_p65b_implementation`; worktree aislado y versión
  `0.4.198` preservada. XNYS abierto.
- Equity diaria (`equity_t - equity_prev_close`) es la autoridad primaria;
  invertido queda como métrica secundaria. El consumidor baseline actual usa
  `pnl_pct`/`spy_pct` legacy sin exigir comparabilidad del payload canónico.
- El selector existente de `Valor de cartera` es calendario: con huecos puede
  mostrar menos de 7 sesiones. El baseline Sistema/SP500 no tiene selector ni
  contadores en este árbol; la observación `13/17/0/9 de 39` queda
  `unavailable`, no se atribuye por nombre.
- 12 tests P-L65A pasan. Suite completa, smoke, benchmark largo y validación
  cerrada pendientes por XNYS abierto. Siguiente único lote: P-L65B, rowset
  canónico read-only por sesiones con estados pending/unavailable y cierre
  aritmético de contadores.
### P-L71-R1 - wiring EOD comun para Telegram

- La reproduccion contra `7beeb135` demostro que Telegram ignoraba el overlay
  EOD y usaba `row['spy_pct']` stale: `-0,30%` en lugar de `+0,25%`.
- `publish_daily_summary` es ahora la frontera comun de proyeccion para el job
  22:05 y el fallback PMR. `build_daily_summary` solo acepta benchmark
  proyectado/comparable con autoridad EOD completa; sin cache posterior queda
  `n/d`, incluso si existe un scalar legacy.
- P-L70BR1 permanece paralelo y no se mezcla. Siguiente lote: ensayo cerrado
  P-L71; no backfill, no reenvio automatico de sesiones ya recibidas.

> P-L48B sigue desplegado y P-L44B sigue en shadow.

### P-L70BR1 — ensayo integrado cerrado

- Merge `--no-ff` `0083f414` desde producción documental exacta; tree funcional
  resultante igual al candidato P-L70R1. QA adicional `a64c493a` conserva la
  separación del evento de resumen frente a notificaciones de fills.
- Suite integrada `2261 passed, 1 skipped, 1 warning`; focales `86 passed` y
  QA integrada `1 passed`. El skip es únicamente el test condicional
  `test_score_study_regression_current_sqlite` por historia local insuficiente
  o no disponible. No se añadió skip/xfail.
- `telegram_daily_summary.py` es la única lógica funcional modificada; el
  recibo v2 guarda texto exacto, `text_sha256`, `content_hash` independiente y
  unidades UTF-16. Fills, scheduler, Store, PMR y trading permanecen iguales.
- Dictamen `ready_for_closed_market_deployment`, sin despliegue, reinicio,
  push ni mensaje real. El siguiente lote mínimo es el preflight/normalización
  productiva autorizado para despliegue; no iniciar P-L69 en paralelo.

P-L65A version policy required candidate `0.4.199`; no production logic
changed. The next lot is P-L65B after closed-market validation gates.

> P-L65A-R1 (28-jul-2026): se corrigió el alcance de la caracterización. El
> checkout productivo dirty sí contiene `_render_daily_vs_spy_table` P-L61 y
> P-L62, pero P-L63R1/P-L65A no lo contienen. Hashes dirty:
> `web_app.py` `FC6ABAD9D799077D402866194A93D939657CC16CAC6943BC40B139A608D8205A`,
> `test_web_app.py`
> `9580147B3E0C8F0E264A1721AA95D13C5EFF3E14F75634517E25C1C551EA1E1B`.
> El panel dirty explica `13/17/0/9 de 39`: cuenta antes del filtro, prioriza
> `pnl_invested_pct`, recorta tabla y gráfico sobre rowsets distintos y deja
> interpolados/parciales en la comparación. 22 pruebas aisladas pasan; no hubo
> cambios en src ni producción. Dictamen `ready_for_p65b_implementation`
> condicionado a componer el diff exacto, manteniendo `0.4.200` reservado
> para P-L65B.

> P-L54B-T (27-jul-2026): caracterizacion aislada completada en
> `C:\Antonio\Bref\agenteBolsa_worktrees\pl54bt_capital_funnel_characterization`,
> rama `codex/pl54bt-capital-funnel-characterization`, desde P-L58R1 exacto.
> Dictamen `ready_for_p54b_implementation`: el productor real queda trazado
> hasta `save_order_plan`/`save_broker_order`, pero target exposure y notional
> objetivo no tienen autoridad estructurada y deben permanecer
> `unavailable`. La fixture 376 -> 15 -> 15 y la bateria focal pasan; no hubo
> cambios en src, produccion ni politica. Siguiente paso: implementar el
> shadow en worktree separado, sin desplegar.

> P-L54B-T-R1 (27-jul-2026): se corrigieron las invariantes del contrato sin
> tocar src. El snapshot anterior permitia risk-approved=135 y risk-rejected=80
> con gates-passed=135, y 135.000 USD de notional no alcanzable. La tabla
> cerrada es 376 -> 306 -> 256 -> 95 -> 15, con 361 caidas y 15 planes.
> Dictamen: `ready_for_p54b_implementation`. El siguiente lote unico es
> implementar el productor shadow en worktree separado.

> P-L58R1-Retry (27-jul-2026): worktree
> `C:\Antonio\Bref\agenteBolsa_worktrees\pl58r1_measurement_safety_rehearsal`,
> rama `codex/pl58r1-measurement-safety-rehearsal`, HEAD final posterior al
> commit documental. Merges `01c2c564` -> `b61a3036` -> `e0e19625` en orden.
> Dictamen `ready_for_closed_market_full_validation`: 1987 passed, 1 skip
> preexistente, Ruff/NUL/diff/config/version policy verdes. No despliegue.
> El siguiente gate es preflight humano y smoke completamente aislado; no
> promover sombras ni cambiar politica.

> P-L50BR1: el worktree combinado queda en candidato **0.4.188**, con la
> secuencia P-L49B 0.4.186 -> P-L46BR3 0.4.187 -> P-L50B 0.4.188. No es un
> despliegue productivo.

> P-L51BR1 (21-jul-2026): el worktree combinado queda en candidato **0.4.189**.
> P-L51B-W esta integrado como shadow fail-open, pero la captura futura real
> queda bloqueada por falta de provenance BUY->SELL y fill fragments canonicos
> en los objetos persistidos. Dictamen: `needs_redesign`; produccion intacta.

> P-L51C-T (21-jul-2026): el carrier minimo ya esta caracterizado en tests.
> La frontera seleccionada es metadata del `order_plan` transportada al payload
> local de `broker_order`; sobrevive reconciliacion y no cambia el request del
> broker. P-L48 aun lo descarta al proyectar operaciones. Siguiente lote:
> implementar esa proyeccion acotada sin tocar kernel/broker/execution/risk/config.
> Dictamen: `ready_for_p51c_implementation`.
## P-L66 — candidato Telegram

El candidato 0.4.201 añade un consumidor externo para el resumen
diario. Debe integrarse después de P-L65 para preservar la secuencia de
versiones. Hace el primer intento a las 22:05 Europe/Madrid y conserva el hook
postmarket como fallback idempotente. Está desactivado por defecto y requiere
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_DAILY_SUMMARY_CHAT_ID` y
`TELEGRAM_DAILY_SUMMARY_ENABLED=true` únicamente en el entorno productivo.
No desplegar con XNYS abierto.

## Objetivo

Mejorar beneficio neto sin aceptar grandes caidas y construir expertos
autonomos que aprendan con evidencia. Live, apply, configuracion sensible y
promociones siguen human-gated.

## Produccion

- Paper activo; live y auto-apply desactivados.
- Kernel sellado sin violaciones. `unsealed` temporal no describe produccion.
- P-L45B1 desplegado: un postmarket efectivo, reconciliacion coordinada, una
  actualizacion de outcomes y terminales duraderos.
- P-L48B desplegado (19-jul): telemetria canonica shadow `p-l48b.canonical-operation-telemetry.v1`
  unidad `broker_order_id`; consumo read-only en digest/health/CLI/performance_daily.
  Sin backfill, sin tablas/migraciones, sin autoridad sobre trading.
- P-L57A corrige en candidato aislado la continuidad null-safe de
  `postmarket_report`, `performance_daily`, `profitability_scoreboard`,
  `promotion_readiness`, digest semanal y serie web read-only. La causa
  reproducida es `pnl_pct=NULL` entrando en la reducción de drawdown; los
  valores faltantes siguen `null/unavailable`, con cobertura parcial explícita.
  No se ha desplegado ni se ha hecho backfill del PMR fallido del 23-jul.
- P-L43: legacy gobierna time-stop; XNYS es exclusivamente shadow.
- Cohortes P-L27/P-L29/P-L30/P-L31/P-L32/P-L33 siguen collecting.
- Overrides adaptativos historicos permanecen; la frontera actual impide nuevas
  promociones con auto-apply false.
- P-L49B-W queda en ensayo aislado como `0.4.186`: captura/finalización shadow
  de calidad por candidato, evento append-only y consumidores read-only. No
  concede autoridad sobre entradas, gates ni salidas y requiere identidad de
  observación y temporalidad verificables.

## Secuencia validada

1. **0.4.175 P-L45B2**: observations en chunks de 250; 33.336 filas, 134
   commits, paridad exacta y sin locks normales; desplegado dentro de 0.4.176.
2. **0.4.176 P-L43BR5**: autoridad desde buy order exacta; corrige
   `PositionSide.LONG -> unsupported_side` solo en shadow.
3. **0.4.177 P-L44B**: penalizacion unica solo shadow; esperar evidencia real.
4. **0.4.178 P-L46B UI**: Cartera abierta por ultima compra y fecha/hora.

P-L46B queda desplegado como cambio exclusivamente visual; la fecha procede
de lotes BUY filled locales verificables y las posiciones sin autoridad quedan
al final como `Fecha de compra no disponible`.

No combinar releases sin ensayo conjunto. Despliegue: XNYS cerrado, sin jobs,
suite verde, hash sensible intacto y rollback por revert.

## Evidencia reciente

- P-L43C: 69 portfolio watches, cinco eventos idempotentes, cero ordenes XNYS.
- P-L45A: postmarket p50 ~23 min, maximo ~41 min; P-L45B1 coordina y P-L45B2
  reduce commits.
- 7–13 jul: cuenta -0,0401%, SPY +0,1953%; muestra/exposicion insuficientes.
- Salidas time-stop: muestra pequena/mixta; no cambiar politica aun.

## Agenda

- Cada sesion: ciclos, identidad, shadow, ejecucion y terminal PMR.
- Tras P-L45B2: cinco sesiones antes de juzgar duracion/locks; evidencia aún
  collecting.
- 20-jul: relectura `builtin_pullback`.
- 27/28-jul: primeras madureces tecnicas RR/salidas, aun no muestra suficiente.
- Tras 45 dias agent_run: evaluar roles.
- 1-sep: dictamen de aprendizaje con criterio original.

## Reglas

- No rellenar legacy ni IDs por simbolo/fecha.
- No usar fills/P&L como forward.
- No promover collecting/unavailable.
- No tocar archivos protegidos sin revision humana.
- No desplegar/reiniciar con XNYS abierto salvo emergencia expresa.
- No servicios manuales: tareas y `scripts/stack_*.ps1`.
- No ocultar suite roja con skip/xfail.

## P-L57A — continuidad null-safe del cierre postmarket (candidato 0.4.193)

- Base exacta: `24537e813ff0905696cda0b3925a212045ee7b09`, producción intacta
  con su suciedad conocida. Worktree:
  `C:\Antonio\Bref\agenteBolsa_worktrees\pl57a_pmr_null_safety`, rama
  `codex/pl57a-pmr-null-safety`.
- PMR `pmr_dbfa382016b8` del 23-jul: reconciliación completada, pero
  `postmarket_report` falló con `stage_postmarket_report_failed` y el
  `TypeError` de comparación/agregación causado por `pnl_pct=NULL` y ausencia
  de drawdown numérico. El 24-jul conservó `pnl_pct`, `previous_equity` y
  `alpha` como null cuando faltaba una sesión XNYS comparable; no se copió el
  `result_metrics.pnl_pct` al ledger SQL.
- Estado de commits: `5d05092c` test/reproducción, `12684790` fix,
  `6ddf93da` expectativa null-safe de primera sesión y `ee9afee6` documentación.
  La suite cerrada terminó `1698 passed, 1 skipped`; el skip preexistente es
  `test_score_study_regression_current_sqlite` por ausencia de SQLite local.
  Ruff, NUL, diff, configuración, kernel productivo sellado y version policy
  pasan. No cambiar la secuencia PMR: solo se hace observacionalmente tolerante
  a filas incompletas; no se reconstruyen datos ni se reejecutan sesiones.
- Dictamen P-L57A: `ready_for_integration_rehearsal`. Próximo paso: ensayo de
  integración aislado; la promoción a producción requiere otra precondición
  cerrada, comparación de objetos protegidos y autorización explícita.

## Comandos

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main validate-agent-config --json
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
```

`docs/plan_mejoras_y_tareas.md` es la unica fuente de tareas.

## P-L43C-W - estado del candidato shadow (22-jul-2026)

- Candidato aislado: worktree `pl43c_exit_authority_impl`, rama
  `codex/pl43c-exit-authority-impl`, version `0.4.192`.
- La autoridad activa sigue siendo `legacy_calendar_days`; XNYS es
  `shadow_only`. No se modifica la politica ni la llamada protegida
  `close_position(symbol)`.
- Carrier: captura en memoria antes del submit; decision/link append-only
  despues del intento; identidad exacta de lote y conflicto seguro. Sin
  simbolo/fecha/FIFO.
- QA: 40 pruebas P-L43C-W, 178 focales relacionadas, Ruff/NUL/diff/config
  verdes. Suite completa, smoke aislado y validacion cerrada integrada quedan
  pendientes; no desplegar hasta completarlos con XNYS cerrado.

### P-L43C-R1 - orden durable post-submit (22-jul-2026)

- Worktree aislado `pl43cr1_exit_authority_ordering`, version `0.4.192`.
- La prioridad corregida es `submit -> save_broker_order local -> persistencia
  P-L43C fail-open -> reconciliacion`.
- La reproduccion de la base observo `submit -> P-L43C -> save_broker_order`;
  la prueba R1 confirma el orden corregido, sin duplicar save ni alterar la
  llamada activa.
- 44 pruebas focales y Ruff verdes. Suite completa, smoke, benchmark largo y
  validacion cerrada permanecen pendientes con XNYS cerrado.
## P-L43B — estado del candidato shadow (15-jul-2026)

- P-L43BR4 desplegó en producción la versión `0.4.173` mediante merge no destructivo.
- `legacy_calendar_days` es la única ruta activa de `time_stop_v2`; XNYS es exclusivamente shadow.
- La evidencia histórica usa eventos append-only por `position_identity` y `shadow_observation_id`; `runtime_state` es `latest_view`.
- Los datos prospectivos reales permanecen `collecting`; la activación XNYS requiere autorización humana y otro lote.

## P-L44BR2 — ensayo de integración shadow (15-jul-2026)

- El candidato `0.4.177` integra P-L44B sobre P-L43BR5 desplegado mediante un
  merge no destructivo en un worktree aislado.
- `legacy_double_application` sigue activa; `single_application` es sólo
  shadow y los datos reales permanecen `collecting`.
- Dictamen del ensayo: `ready_for_future_shadow_deployment`; producción no se
  modificó ni reinició.

## P-L47B1 — recuperación de leases desplegada (0.4.180)

El despliegue del 18-jul-2026 (`f60a3d82`) confirmó que Windows ejecuta un
único scheduler lógico mediante wrapper → launcher `.venv` → runtime Python.
El lock v1 quedó asociado al runtime real. El bootstrap recuperó de forma
append-only el lease terminal residual de reconciliación, conservó el terminal
original y no reprocesó postmarket, reconciliación ni outcomes. No cambian
stops, takes, time-stop, ranking, gates, órdenes, exposición ni límites.
P-L43BR6 y P-L44BR3 permanecen fuera y conservan los slots `0.4.181` y
`0.4.182`.

## Secuencia post-P-L47B1 del ensayo

## Estado actual tras el despliegue P-L43BR6 + P-L44BR3 (18-jul-2026)

- Producción: versión `0.4.182`, merge `7cc432aee3f594d946f5a65d1f86f3e49fa82e4`.
- Secuencia: P-L47B1 `0.4.180`, P-L43BR6 `0.4.181`, P-L44BR3 `0.4.182`.
- El stack quedó con un scheduler lógico wrapper → launcher venv → runtime,
  lock v1 propiedad del runtime y heartbeat fresco.
- `legacy_calendar_days` y `legacy_double_application` siguen siendo las
  políticas activas; XNYS y `single_application` continúan exclusivamente
  shadow. La evidencia sigue `collecting`/`partial`, sin backfill.

- 0.4.180: P-L47B1 desplegado.
- 0.4.181: P-L43BR6 integrado primero en este ensayo.
- 0.4.182: P-L44BR3 integrado después; versión final del ensayo.
- Ambos lotes continúan exclusivamente shadow y no modifican trading.
## P-L44BR3 — corrección del contrato lector (candidato 0.4.181, 18-jul-2026)

- Se corrigió la frontera de lectura del shadow: primero se valida
  `signal_capture_id`/`signal_id` y después la disponibilidad de scoring.
- Los candidatos identificados sin inputs quedan `shadow_inputs_unavailable`;
  no se convierten en `identity_unavailable` ni reciben score inventado.
- Digest, health y CLI cuentan un único evento canónico por `cycle_id`, ignoran
  filas genéricas del reporter y dejan los conflictos visibles.
- P-L44 conserva `legacy_double_application` activa y
  `single_application` exclusivamente shadow. La evidencia previa queda
  invalidada para interpretación y no se hace backfill; P-L43BR6 sigue como
  prioridad `0.4.181`; P-L44BR3 deja el ensayo en `0.4.182`.

## P-L44BR3 — despliegue cerrado (17-jul-2026)

- Producción quedó en `0.4.177` mediante el merge `23e4bf4d`, con el tree
  validado del ensayo y sin incluir P-L46B.

## P-L48B-W - telemetria canonica de operaciones (candidato 0.4.184)

- Productor shadow unico `p-l48b.canonical-operation-telemetry.v1` con unidad
  `broker_order_id`, denominadores separados y freshness descriptiva.
- Evento append-only por sesion, hash estable excluyendo `captured_at`,
  idempotencia y conflictos auditables. Consumidores read-only.
- No altera trading ni activa ninguna politica shadow; P-L43/P-L44/P-L45/P-L47
  permanecen con sus invariantes.

## P-L48BR1 - ensayo de integracion superado (0.4.185)

- Worktree `pl48br1_integration_rehearsal`, rama
  `codex/pl48br1-integration-rehearsal`: merge `--no-ff` del candidato exacto
  mas tres commits QA (`b3155389`, `919f58b6`, `77d2e743`).
- QA adversarial completo (65 pruebas nuevas): fuente unica, orden postmarket,
  fail-open, idempotencia, fragmentacion, ANET, performance_daily,
  reconciliacion, freshness, volumen, lectores y paridad
  P-L43/P-L44/P-L45/P-L47. Suite 1689 passed y gates en verde.
- Tres defectos del candidato corregidos en el ensayo (D1 centinela
  `_MISSING`, D2 digest tras conflicto, D3 `candidate_count`); un defecto
  preexistente de `profitability_scoreboard` documentado para el backlog.
- Dictamen: `ready_for_closed_market_deployment`. Siguiente paso: despliegue
  con XNYS cerrado mediante merge `--no-ff` del tree validado del ensayo a
  produccion, conservando los commits QA.
- `legacy_double_application` conserva la autoridad; `single_application` es
  exclusivamente shadow y la captura real permanece `collecting`.
- Suite, kernel, configuración y stack pasan; no se generaron órdenes por P-L44B.

## P-L48BD - despliegue cerrado de P-L48B (0.4.185). DEPLOYED

- Auditoria P-L48BD-P: `single_logical_stack_launcher_runtime_chains`,
  `ready_to_resume_p48bd`. Una sola cadena logica por servicio
  (launcher venv → runtime Python base); el `scheduler.lock` v1 pertenece al
  runtime APScheduler hijo del launcher `.venv`, no al launcher. No se
  "normalizo" la topologia.
- Stack down con `scripts\stack_down.ps1 -IncludeScheduled`; merge `--no-ff`
  de `266950a0` a produccion: commit `8cfa0db3`, tree funcional
  `4c3636be` identico al ensayo, sin conflictos, sin squash/rebase/amend.
- Validacion con stack detenido: baterias P-L48BR1 + P-L48B-T/W (111 passed),
  focales scheduler/storage/postmarket/performance/reconciliation/execution/
  digest/health/CLI y P-L43/P-L44/P-L45/P-L47 (verdes), suite completa ≈1693
  passed/0 fallos, Ruff limpio, `check_no_nulls.py` OK, `git diff --check` OK,
  `validate-agent-config` `ok=true`, `kernel-status` sellado sin violaciones.
- `scripts\stack_up.ps1`: dos comprobaciones con HTTP 200/200, unico listener
  8501, lock v1 PID 49096 token `134289557074352030` coincide con el runtime
  real, `post_market_coordination:active = None`, 0 ordenes desde el reinicio,
  0 `database is locked`, health `warning` con 0 alertas criticas.
- Bootstrap: `terminal:skipped` reason `market_not_ready` unico; sin reprocesar
  17-jul, sin repetir reconciliacion/outcomes, sin crear telemetria/ordenes ni
  lease residual. Estado P-L48B inicial: CLI/digest/health `collecting`,
  denominadores null, 0 eventos canonicos, sin backfill.
- Deuda `profitability_scoreboard` (`pnl_pct=NULL` sin `max_dd`) NO corregida
  (backlog). Sin push. Produccion `8cfa0db3` / tree `4c3636be` limpia.

## P-L49BR1 — relevo de QA

- Worktree de ensayo: `pl49br1_shadow_rehearsal`, merge `2ea57983`, QA
  `b8aee78a`/`db6577b2`, versión `0.4.186`; producción no modificada.
- Hallazgo operativo: `market_snapshot`/`market_state` no transportan hoy la
  observación OHLC exacta por feature. El shadow lo hace visible como
  `unavailable_temporal` y conserva `PARTIAL`; nunca convierte calidad global
  en bloqueo ni usa un informe posterior.
- La corrección de identidad canónica (zona horaria equivalente y `-0.0`) y la
  clasificación temporal están solo en el ensayo. Suite completa y smoke
  requieren ventana con XNYS cerrado; P-L48C permanece prohibido hasta
  postmarket terminal.
## P-L46BR3 - metricas del periodo de cartera (candidato 0.4.187)

- Corrige una contradiccion visual: la grafica mostraba equity descendente,
  pero `P/L desde abril` usaba el P/L del historial de operaciones y podia ser
  positivo. Ahora `Resultado del periodo` usa exactamente los extremos de la
  curva visible y sigue el filtro de rango.
- El bloque queda reducido a `Resultado del periodo` y `P/L abierto`; `P/L
  hoy` se mantiene solo en la cabecera. El abierto procede de las posiciones
  actuales ya obtenidas.
- `Desde inicio` solicita todo el historial disponible. Cabecera y control
  externo quedan alineados con la misma serie de equity.
- Solo UI/lectura; no cambia rutas de trading ni persistencia. P-L49 mantiene
  el slot `0.4.186`; P-L46BR3 usa `0.4.187`.
## P-L50BR1 - ensayo combinado pendiente de validacion cerrada

Secuencia del worktree: P-L49B `0.4.186`, P-L46BR3 `0.4.187`, P-L50B `0.4.188`.
Los shadows conservan identidades y eventos independientes; la UI sigue siendo
solo lectura. QA focal: 675 passed; interacción: 10 passed. XNYS estaba abierto,
por lo que no se ejecutaron suite completa, smoke ni despliegue.

## P-L50BR1 - cierre del relevo QA (20-jul-2026)

- Worktree/rama: `C:\Antonio\Bref\agenteBolsa_worktrees\pl49_pl46_pl50_combined_rehearsal`,
  `codex/pl49-pl46-pl50-combined-rehearsal`; versión final `0.4.188`.
- Orden de merges: `0f5a26a0` P-L49B (`753136fc`), `17b5fbc7` P-L46BR3
  (`a0ab7ce4`), `045288dd` P-L50B (`8ebac5f2`). QA adicional: `c99cd318`.
- Secuencia temporal y separación de identidades verificadas; los shadows son
  fail-open y la UI es read-only. No se modificaron kernel, broker, execution,
  risk, config ni `.env`.
- QA: 90 + 84 + 211 + 290 = **675 passed**; Ruff, nulls, diff y
  `validate-agent-config --json` temporal (`ok=true`) verdes.
- Producción permanece en `24537e81`/0.4.185 con solo su suciedad UI previa;
  candidatos originales permanecen en sus HEAD/tree indicados. No hubo
  despliegue, reinicio, detención de servicios ni push.
- Pendiente con XNYS cerrado: suite completa, smoke, jobs reales y validación
  histórica de 33.336 filas. Dictamen:
  `ready_for_closed_market_full_validation`.

## P-L50B - candidato shadow de linaje (0.4.188)

- Corrige el wiring P-L44 preparando `signal_capture_id`/`signal_id` antes de
  anotación y ranking y proyectando una copia profunda acotada hacia fase A.
- El schema v2 separa identidad, inputs, decisiones (`action` +
  `recommendation_id`), controles, rechazos canónicos y freshness descriptiva;
  el lector mantiene compatibilidad v1 declarada.
- No parsea texto, no inventa IDs, no convierte missing en cero y no enlaza por
  símbolo/fecha. No altera ranking, selección, gates, sizing, planes ni órdenes.
- Fixture 443: 425 identidades verificadas, 8 unavailable, 10 ambiguous, 420
  inputs disponibles y 23 unavailable. Estado `ready_for_integration_rehearsal`.
- P-L49B conserva el slot 0.4.186 y P-L46BR3 el 0.4.187. No hubo despliegue ni
  push; la suite completa queda para mercado cerrado.

## P-L51C-W - relevo del carrier BUY -> SELL (candidato 0.4.189)

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl51c_provenance_carrier_impl`;
  rama `codex/pl51c-provenance-carrier-impl`; base P-L51C-T
  `0c5f1314986d5cf8bfdbe3a691dd7706be096903`.
- La frontera validada es metadata de `order_plan` transportada al payload
  local de `broker_order`, conservada por reconciliacion y proyectada de forma
  explicita por P-L48 para P-L51. No se cambia el request broker ni la ruta
  activa.
- End-to-end temporal: `buy-1 -> sell-1`, fills canonicos 2, allocation 1,
  `attributed_sell_count=1`, `closed_lot_count=1`, gross 100.0 y net 98.5.
  Costes incompletos, historicos sin carrier y provenance ambigua permanecen
  null/unavailable; no se hace FIFO ni backfill.
- Commits: `c86917ee feat: persist exit lot provenance carrier` y
  `5c0077d9 test: verify end-to-end exit lot provenance`. Falta el commit
  documental de este lote.
- No promover ni desplegar con XNYS abierto. Siguiente gate: ejecutar Ruff,
  `check_no_nulls.py` y `validate-agent-config --json` con DATA_DIR temporal;
  posteriormente, con XNYS cerrado y PMR terminal, suite completa, smoke y
  validacion de mercado cerrado. Sin cambios en archivos protegidos, produccion,
  SQLite productiva, servicios, reinicios o push.
## P-L51CV2 - validacion completa nocturna (21-jul-2026)

- Candidato `codex/pl51c-provenance-carrier-impl`, HEAD
  `a889dd976af11435bbcaf2d9a8e8cd59981e546b`, tree
  `7f04dbb5f528388cc01b060839378d141b39cdb6`, version `0.4.189`, limpio.
- PMR terminal y lease vacio; suite `1864 passed, 1 skipped`, focales y
  regresiones `364 passed`, P-L45B2 `1 passed`, Ruff/NUL/diff/configuracion
  verdes. El smoke real queda `smoke_unavailable_by_safety`; el sustituto
  seguro paso 8 pruebas.
- Dictamen: `ready_for_closed_market_deployment`, sin despliegue. La siguiente
  tarea decide/promueve separadamente y conserva el control humano; no tocar
  produccion, SQLite productiva, servicios, archivos protegidos ni hacer push.
## P-L52B-T — snapshot EOD contable y benchmark comparable (21-jul-2026)

- Se caracterizó en worktree aislado el contrato
  `p-l52b.canonical-eod-account-snapshot.v1`, sin cambios en `src` ni en
  producción. La ecuación probada es `delta_equity = flows + net_realized_pl
  + delta_open_pl + residual`.
- El contrato exige ledger exacto de flujos, costes completos para neto,
  posiciones/lot IDs exactos y SPY con misma ventana, timestamps, `price_basis`
  y calidad. P-L52A queda reproducible como pérdida absoluta verificada, cash
  opportunity descriptiva y residual/atribución unavailable.
- Resultado: `21 passed` P-L52B-T, `248 passed` focales, Ruff/NUL/diff/config
  verdes. Dictamen: `ready_for_p52b_implementation`.
- Próximo lote: implementación shadow mínima, fail-open y append-only, sin
  tablas/migraciones ni consumo en trading hasta demostrar paridad.

## P-L52B-W — implementación shadow EOD contable (candidato 0.4.190)

- Worktree/rama: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52b_eod_snapshot_impl`,
  `codex/pl52b-eod-snapshot-impl`, base `609183e1`.
- Secuencia PMR verificada en tests: P-L48 → P-L51 → P-L52 → performance.
  P-L52 reutiliza los objetos ya construidos, publica el contrato
  `p-l52b.canonical-eod-account-snapshot.v1`, conserva missing/unavailable y
  falla abierto. No aparece en la ruta de trading ni toca archivos protegidos.
- Commits: `57ec7b7f` feature, `eb17d582` tests, `4e868109` QA freshness.
  Focales del lote: `32 passed`; Ruff y diff verdes.
- Estado: `ready_for_integration_rehearsal`, no desplegado. Suite completa,
  P-L45B2, smoke y promoción quedan pendientes con XNYS cerrado y PMR terminal.

## P-L52BR1 — cierre del ensayo integrado (22-jul-2026)

- Ensayo: `C:\Antonio\Bref\agenteBolsa_worktrees\pl52br1_integration_rehearsal`,
  rama `codex/pl52br1-integration-rehearsal`, version 0.4.190.
- Merge `36bdd366` (`--no-ff`) de P-L52B-W; correccion QA `932c648a`.
- Secuencia final: reconciliation -> P-L48 -> P-L51 -> P-L52 -> performance ->
  measurement -> thesis -> terminal. Los tres eventos son append-only,
  idempotentes/conflict-safe y fail-open; el mismo objeto P-L52 llega a
  performance.
- Evidencia E2E real temporal: BUY/SELL carrier exacto, reconciliacion,
  `attributed_sell_count=1`, neto 98.5 y contribution exacta por lote. Las
  salidas multi-lote sin importe por allocation quedan con importe null.
- QA: `1899 passed, 1 skipped, 1 warning`; P-L45B2 33.336 filas pasado,
  volumen 100 sesiones/1000 operaciones sin locks, Ruff/NUL/diff/config verdes.
  Smoke CLI real: `smoke_unavailable_by_safety`; sustituto aislado verde.
- Produccion 0.4.185 y candidatos P-L51C/P-L52B-W intactos. Kernel productivo
  sellado; archivos protegidos iguales a base/produccion. No hubo SQLite
  productiva, despliegue, reinicio, servicios ni push.
- Dictamen: `ready_for_closed_market_deployment`. Siguiente paso: preflight
  operativo independiente y autorizacion humana; no promover automaticamente
  desde este ensayo.
## P-L51CR2 - correccion de regresiones temporales de provenance (22-jul-2026)

- El padre P-L52BR1 fue reproducido en un worktree nuevo. Los tres fallos de
  provenance no eran perdida de carrier: las fixtures persistian ordenes con
  `created_at` del 22-jul y consultaban sesion 21-jul.
- `9a7b46d2` anade la caracterizacion de la frontera temporal y `494e6515`
  congela el reloj de las tres pruebas. No cambia `src/`, por lo que la version
  permanece `0.4.190`; no se reserva 0.4.191 para este lote.
- Resultado: tres regresiones verdes, `239` focales relacionadas y suite segura
  `1900 passed, 1 deselected`. La exclusion es unicamente el test legado que
  apunta a `data/state/agente_bolsa.sqlite3`; no se anadieron skips/xfails.
- El carrier sobrevive plan -> orden local -> reconciliacion -> P-L48 -> P-L51
  -> P-L52 con IDs exactos, sin joins por simbolo/fecha y con request broker
  identico. Produccion, P-L52BR1 y P-L53BR1 permanecen intactos.
- Dictamen: `ready_for_reintegration`. Siguiente lote: reintentar P-L53BR1
  sobre este worktree con slot posterior 0.4.192, sin ejecutarlo ahora.

## P-L53B-W - handoff del candidato 0.4.191

- Worktree aislado: `C:\Antonio\Bref\agenteBolsa_worktrees\pl53b_selection_ledger_impl`;
  rama `codex/pl53b-selection-ledger-impl`.
- Commits funcional/QA: `e5ace319` y `eea3794a`; falta únicamente el commit
  documental separado de este lote.
- El ledger shadow captura una vez por ciclo la fase A completa y las etapas
  reales de decisión posteriores, con identidad `signal_capture_id` exacta,
  fallback explícito `signal_id`, estados separados y persistencia
  append-only/conflict-safe.
- No cambia prompts, ranking, selección, LLM, gates, sizing, planes, órdenes,
  broker requests, exposición ni límites. Históricos sin identidad permanecen
  unavailable; outcomes futuros se unen solo por identidad y madurez XNYS.
- Validación focal P-L53B-T/W: 28 passed, Ruff/check_no_nulls/diff/version en
  verde. Suite completa y smoke están pendientes de precondiciones cerradas.

Siguiente lote único: P-L53BR1, ensayo integrado aislado desde el candidato
0.4.191; no desplegar ni hacer push antes de esa validación.

## P-L53BR1 - ensayo integrado sobre P-L52BR1 (22-jul-2026)

## P-L53BR2 - relevo final del reensayo limpio (22-jul-2026)

- Worktree `C:\Antonio\Bref\agenteBolsa_worktrees\pl53br2_integration_rehearsal`,
  rama `codex/pl53br2-integration-rehearsal`, base `2da5ccda`, merge
  `3b2ae0bf`, version `0.4.191`.
- Gate temporal `3 passed`; QA de volumen `2bb92a4b`/`165ad748` y fixture
  concurrente `ff6267a0`, sin cambio productivo.
- Orden de mercado y PMR conservado; P-L53 fase A tras ranking, finalizacion
  despues del envio activo y fuera de PMR. Identidades/paridad exactas.
- BR2: 100x500 y escalas, 109 eventos/conexiones/transacciones, evento p50/max
  `757177`, memoria pico `17066653`, WAL `0`, shadow p50 `511.6280 ms`; riesgo
  `medium`, sin O(n2) descriptivo y sin retraso del envio.
- Suite final `1933 passed, 1 deselected, 1 warning`; el unico deselect es el
  test legado que abre `data/state/agente_bolsa.sqlite3`; no hay skips/xfails.
  P-L45 33.336 esta incluido. Smoke real:
  `smoke_unavailable_by_safety`.
- Dictamen: `ready_for_closed_market_deployment` como candidato no desplegado.
  Siguiente paso unico: preflight cerrado y autorizacion humana; no deploy ni
  push desde este ensayo.

- Se creó el worktree aislado `pl53br1_integration_rehearsal` desde
  `134ec525` y se fusionó P-L53B-W con `--no-ff` en `fc4eb767`; la QA quedó en
  `52668b42`. Versión final: `0.4.191`.
- La ruta de mercado verificada conserva P-L49/P-L50/P-L44, añade P-L53 como
  sombra predecisión/finalización y no altera decisiones ni retrasa el envío.
  El PMR permanece `reconciliation -> P-L48 -> P-L51 -> P-L52 -> performance
  -> measurement -> thesis -> terminal`, con sus etapas previas ya validadas.
- La batería combinada cubrió 500 observaciones, 37 anomalías, 443 candidatos,
  20 finalistas, 5 recomendaciones, 3 planes y 2 órdenes; la persistencia
  concurrente fue `inserted` sin locks, con idempotencia y conflictos separados.
  El volumen 100x500 fue verde, con p50/p95/máximo de construcción
  373,9511/406,0575/434,1302 ms y persistencia 67,8627/82,5894/86,6022 ms.
- Gates: Ruff, NUL, diff, configuración, versión, kernel productivo sellado y
  suite segura `1928 passed, 4 deselected`. Tres tests P-L51/P-L51C fallan
  también en el padre P-L52BR1 y quedan como deuda heredada; el cuarto es el
  test legado que intenta abrir SQLite productiva. No se añadieron skips/xfails.
- Dictamen: `needs_fix`; no desplegar. Siguiente lote mínimo: resolver esos
  tres focales heredados y repetir suite/preflight cerrado. Producción,
  servicios, SQLite productiva, locks y candidatos originales permanecen
  intactos; no hubo reinicio, despliegue ni push.

## P-L54B-W - relevo del candidato 0.4.194

- Worktree aislado: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54bw_capital_funnel_shadow`;
  rama `codex/pl54bw-capital-funnel-shadow`; base `20e8be04`; version 0.4.194.
- El productor shadow captura transiciones ya decididas y persiste un unico
  evento por `cycle_id` despues de la ruta activa. No tiene autoridad sobre
  seleccion, gates, sizing, RiskManager, planes, ordenes o exposicion.
- Persistencia append-only, hash sin `captured_at`, idempotencia y conflictos
  separados. Lector/CLI devuelven `collecting` con denominadores null cuando
  no existe evento. Target exposure permanece unavailable sin autoridad.
- QA focal P-L54B-T/R1/W: 33 passed; quedan pendientes suite completa, smoke,
  prueba P-L45 larga y ensayo integrado cerrado P-L54BR1. No desplegar ni hacer
  push desde este lote.

## P-L54B-R1 - relevo de identidad de decision

- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl54br1_decision_identity`;
  rama `codex/pl54br1-decision-identity`; base `9c8940a0`; version `0.4.194`.
- La decision canonica es `cycle_id + signal_identity + action +
  recommendation_id` cuando existe. Repeticion exacta es idempotente; contenido
  incompatible es conflicto auditable; faltante es partial/ambiguous segun
  colision. No se adjuntan planes u ordenes por simbolo, fecha o candidato.
- Stages y notional solo cuentan decision identity verificada y exponen la
  poblacion excluida. La paridad de la ruta activa no cambia.
- Commits `de08b9fd`, `8d814934`, `3f85071f`; focales `49 passed` incluyendo
  P-L54B T/R1/W y cycle funnel. Siguiente paso unico: reintentar P-L54BR1;
  suite completa y smoke siguen pendientes. Produccion intacta; sin deploy ni
  push.

### P-L65B — implementación aislada (28-jul-2026)

- Worktree `pl65b_daily_vs_spy_consistency`, rama
  `codex/pl65b-daily-vs-spy-consistency`, base P-L65A-R1
  `53b49f71e3acedd9b5ed73f80ff8cb793221df8`, candidato `0.4.200`.
- La UI usa `performance_daily(readonly=True)` y un rowset canónico común para
  selector, contadores, tabla y gráfico. Equity contra SPY es la comparación
  primaria; exposición-normalizada es descriptiva; missing/partial/stale/
  interpolated/future quedan pending.
- Feature `8d4deca6`, tests `0cb872a9`, QA `02aee0c9`; focales
  P-L65/P-L63/P-L46/UI: 129 passed.
  Ruff, NUL, diff, py_compile, validate-agent-config y version policy aislados
  deben cerrarse antes del ensayo integrado; suite completa y smoke se omiten
  con XNYS abierto.
- Producción dirty, P-L66 y archivos protegidos intactos. No despliegue.
  Siguiente paso único: ensayo combinado aislado P-L63/P-L65B, revalidando
  XNYS cerrado y precondiciones; P-L66 no se integra aquí.

## P-L54BR1-Retry - relevo (27-jul-2026)

- Worktree `pl54br1_integration_rehearsal`, rama
  `codex/pl54br1-integration-rehearsal`, merge `8574a227`, version `0.4.194`,
  tree `ff42c750`.
- XNYS estaba abierto al comenzar; PMR 24-jul terminal completed y leases
  activos vacios se verificaron mediante fuentes persistidas/directas.
- QA focal integrada: `330 passed`; Ruff, NUL, diff y validate-agent-config
  verdes. No se ejecutaron suite completa, P-L45 33336, smoke ni benchmark
  combinado.
- P-L54 mantiene `376 -> 306 -> 145 -> 95 -> 15`, 361 razones primarias y
  notional target unavailable. No cambia trading, riesgo, ejecucion ni PMR.
- Dictamen: `ready_for_closed_market_full_validation`. Siguiente paso unico:
  repetir los gates cerrados, incluida suite/smoke/benchmark, sin desplegar
  automaticamente. El incidente previo queda documentado como
  `unconfirmed_sqlite_mutation`, sin limpieza.

## P-L46BR4 - filtro calendario de cartera (candidato 0.4.195)

P-L46BR4 corrige la interpretacion del selector del grafico: `days` ya no es
un numero de filas sino una ventana calendario anclada al ultimo snapshot
visible. Se conservan 7/15/30/90/`Desde inicio`, el orden y la deduplicacion
de fechas, y la serie visible alimenta tanto grafica como Resultado del
periodo. El cambio no toca trading ni broker. El worktree tiene 75 pruebas UI
verdes; con XNYS abierto quedan pendientes suite completa, smoke y validacion
cerrada.

## P-L60R1 - ensayo integrado UI sobre P-L54BR1 (27-jul-2026)

- Worktree/rama: `pl60r1_ui_measurement_integration`,
  `codex/pl60r1-ui-measurement-integration`; merge `489b229f`, version
  `0.4.195`, tree `5f3afdc7`.
- P-L46BR3 ya estaba presente. El selector unico y estable ofrece
  7/15/30/90/`Desde inicio`; la ventana se aplica por fechas calendario al
  ultimo snapshot visible, con orden/deduplicacion deterministas y sin mutar
  la fuente. Grafica y Resultado del periodo comparten la misma serie; P/L
  abierto reutiliza posiciones ya cargadas.
- QA focal: `83 passed`; relacionados: `159 passed, 1 warning`; Ruff, NUL,
  diff, py_compile y config temporal verdes. Con XNYS abierto quedan
  pendientes suite completa, smoke y validacion cerrada. No hubo broker, red,
  SQLite productiva, despliegue ni push. La incertidumbre historica
  `unconfirmed_sqlite_mutation` y P-L54 se conservan sin declararlas resueltas.

## P-L59B-T-R5 (final) - caracterizacion cerrada (27-jul-2026)

- Dictamen: **`needs_fix`**. XNYS abierto. Hora real: 19:43 CEST. HEAD: `a48113fe`.
- 27 P-L59 + 5 integracion (32 total). Ruff/NUL/diff verdes.
- Stage order: rama 2399/2412. plan_id nace en plan_records; identidades por
  symbol+side+lineage reales del modelo. Sin object.__setattr__.
- Informe unico sin secciones duplicadas. Caracterizacion cerrada.
- Siguiente: P-L59C.

## P-L59C-R6 - autoridad prospectiva estructurada de llm_selected (27-jul-2026)

- Dictamen: **`ready_for_integration_rehearsal`** (R6 corregido). XNYS abierto, 20:30 CEST.
- R6: list branch inside_dcs=False. Docs con hashes R5 reales. 15 integration.
  Ruff/NUL/diff verdes. Brecha P-L53 abierta.
- Siguiente: P-L59D rehearsal de integracion.

## P-L59D - rehearsal de integracion (27-jul-2026)

- Dictamen: **`ready_for_closed_market_full_validation`**. XNYS abierto, ~21:32 CEST.
- Merge `--no-ff` de P-L59C-R6D (`30b6b76b`, v0.4.196) sobre P-L60R1 (`70de3401`, v0.4.195).
  Sin conflictos. HEAD final `4524cbe3` (tree `661216b3`); merge `9009c7f2` (tree `ad69264e`, identico a P-L59C-R6D).
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl59d_llm_selected_rehearsal`,
  rama `codex/pl59d-llm-selected-rehearsal`.
- 5 protegidos versionados identicos contra base y produccion; .env no modificado (hash unavailable). Ruta activa P-L60R1 intacta.
- QA: 300 passed (10 archivos, 65.53s). Ruff/NUL/diff/py_compile/validate-config verdes.
- Brecha P-L53 recommendation_id sigue abierta.
- Gates omitidos: suite, smoke, benchmark, P-L45 33.336, kernel (XNYS abierto).
- Siguiente: P-L59E validacion cerrada completa.

## P-L59F-T-R3 — caracterizacion final, contrato cerrado (27-jul-2026)

- Dictamen: **`ready_for_implementation`**. XNYS cerrado (~22:15 CEST),
  postmarket no terminal, P-L59E bloqueado.
- HEAD tests R3: `e14caa1e`. Solo tests/docs, sin src.
- R3: lineage literal, adjuntos P-L53/P-L54 coherentes, stage explicito,
  `_denominators` real en expansion.
- 17 tests pasan (0.90s). Ruff/NUL/diff verdes.
- Contrato de implementacion completo en informe.
- Siguiente: P-L59F-I (requiere precondiciones XNYS verificadas).

## P-L59F-T-R4 — cierre de diseño (27-jul-2026)

- Dictamen: `ready_for_implementation`. HEAD `224b4958`, tree `135df124`, v0.4.196.
- 17 tests verdes. Contrato decision_rows completo. P-L59E bloqueado.

## P-L59F-I-R1 — implementacion decision_rows v2 corregida (27-jul-2026)

- El candidato inicial `305b56ee` fue `needs_fix`; la correccion del worker se
  interrumpio y direccion clasifico el diff antes de completarlo.
- Dictamen final: **`ready_for_integration_rehearsal`**.
- Worktree/rama: `pl59fi_decision_rows`, `codex/pl59fi-decision-rows`.
- Base `224b4958`, tree `135df124`, version `0.4.196`.
- Candidato v0.4.197. Commit correctivo `1ce3c155`, tree funcional
  `ed1e6879`.
- SCHEMA_VERSION v2. decision_rows por identidad exacta de recomendacion.
  candidate_rows summary 8 estados. Bounded 600. Denominadores v2.
  Reader backward-compatible v1. Sin cambios en cycle_runner/storage/protegidos.
- 169 passed en la bateria focal disjunta; Ruff completo, NUL y diff verdes.
- Recomendaciones fuera de Fase A/ciclo quedan unavailable; adjuntos exigen
  IDs y linaje exactos; idempotencias y conflictos tienen denominadores
  separados; el test fail-open fuerza un fallo real.
- Brecha P-L53 recommendation_id: CERRADA.
- Gates omitidos: suite, smoke, benchmark, P-L45, kernel (precondiciones
  no terminales: postmarket no terminal, continuous_improvement running).
- Siguiente: P-L59F-D rehearsal de integracion. P-L59E sigue bloqueado.

## P-L59F-D — ensayo integrado cerrado (27-jul-2026)

- Dictamen: `ready_for_closed_market_deployment`, sin autorizacion para
  desplegar.
- Worktree/rama: `pl59fd_decision_rows_rehearsal`,
  `codex/pl59fd-decision-rows-rehearsal`.
- Merge `f535923f`; QA `e0290762`, `2f156eb8`; tree `f8193f6d`; version
  `0.4.197`.
- Suite completa: 2184 passed, 1 skip y 1 warning preexistentes. Ruff, NUL,
  diff/config/kernel/protegidos verdes.
- QA corrigio una asercion v1 exacta para validar v1+v2 y movio la
  instrumentacion de `_attach_phase_b` a `_build_decision_rows`.
- Benchmark 500 candidatos: total p95 649.32 ms, 840,943 bytes/evento,
  memoria pico 17.2 MB. Riesgo operativo medio por volumen.
- Smoke real no ejecutado por seguridad; sin proveedor CLI sintetico que
  garantice cero red/broker/LLM.
- Produccion y servicios intactos; sin SQLite productiva, despliegue ni push.

## P-L63 - contrato de equity desde el 1 de abril (28-jul-2026)

- Worktree/rama: `pl63_portfolio_april_baseline`,
  `codex/pl63-portfolio-april-baseline`; base `8c66f966`/tree `fb96f589`/
  v0.4.197. Fix `cad229af`, candidato v0.4.198.
- La causa fue la constante divergente `PORTFOLIO_CHART_START_DATE=2026-04-28`.
  Se alinea con `DEFAULT_START_DATE=2026-04-01`; la historia se solicita una
  sola vez con `period="all"`. La cabecera ya no usa `current_statistics.total_pl`
  como baseline y captura el resumen real de equity.
- Cuenta, grafica y Resultado comparten fuente/ventana/primer y ultimo equity;
  fechas, source y coverage se muestran. Sin punto de abril: partial/unavailable,
  sin reconstruccion desde trades. P/L hoy y P/L abierto permanecen separados.
- `101 passed` focales UI/portfolio/version; Ruff, NUL, diff, py_compile y
  configuracion temporal verdes. Con XNYS cerrado se requieren suite completa,
  smoke aislado y validacion cerrada; no se ejecutaron ni hubo despliegue.

### P-L63 — corrección semántica UX de equity (28-jul-2026)

- La reproducción adicional mostró que `equity 71.550 -> 70.700` con
  `trade_history.total_pl=+106,83` podía producir una tarjeta verde. El
  resultado correcto es `-850,00` (aprox. `-1,19%`), calculado solo como
  último menos primer equity visible; `total_pl` queda fuera de la cabecera y
  del baseline.
- El copy es `Resultado del periodo`/`Variación de equity`, con fechas exactas
  y tone derivado del signo. P/L hoy y P/L abierto son snapshots separados.
  Se añade ventana explícita `Desde 01/06/2026`; la misma serie filtrada
  alimenta gráfica, importe, porcentaje y fechas.
- Commits: `50976dfe` (tests/reproducción) y `22609ba3` (fix). Versión
  `0.4.198` sin cambio. QA focal `103 passed`; estáticos y configuración
  temporal verdes. Suite completa, smoke y validación cerrada quedan
  pendientes con XNYS abierto/premarket. No producción, broker, red, SQLite
  productiva, despliegue ni push.

### P-L63R1 — semántica diaria y tooltip del baseline (28-jul-2026)

- 2,10% sobre exposición no es el retorno diario de la cuenta. La cabecera
  usa ahora today_equity_change / previous_equity, con copy Variación de
  equity hoy y desde el cierre anterior; cambios de exposición no alteran
  el porcentaje. Sin cierre previo: n/d, nunca sustitución por exposición.
- No se publica desde apertura ni se interpreta la curva diaria como
  intradía. P/L abierto, variación diaria y resultado histórico son métricas
  separadas.
- Sistema/SP500: línea y puntos comparten tooltip explícito Fecha, %
  ganancias, Serie, el campo retorno_acumulado y formato +.2%. La fuente,
  el eje y los valores no cambian; desaparece el tooltip automático con
  decimal crudo.
- QA focal 106 passed; Ruff, NUL, diff, py_compile y config temporal
  verdes. Suite completa, smoke y benchmark largo pendientes por XNYS abierto.
  Versión 0.4.198; commits 12a6cb11, bef256d6, 031597c7, 89adde7f
  y fb2c47a7. Sin producción, broker, red, SQLite productiva, despliegue ni
  push.
## P-L68 — corrección Sistema vs SP500 (28-jul-2026)

- Worktree `pl68_benchmark_comparability_fix`, rama
  `codex/pl68-benchmark-comparability-fix`, base productiva `f015428f`.
- Versión candidata `0.4.202`.
- Se corrige la base de precio yfinance, la dirección de la latencia
  benchmark/captura y la visualización de históricos `pending`.
- Línea continua = comparable; discontinua = provisional. Solo la primera
  participa en ganadores. No hay backfill ni neutralización de flujos.
- El baseline acumulado usa composición geométrica.
- Suite completa 2249 passed, 1 skip y 1 warning preexistentes. Ruff, NUL,
  diff, configuración y kernel productivo verdes.
- Dictamen `ready_for_integration_rehearsal`; producción sigue en 0.4.201.

Siguiente secuencia:

1. ensayo `--no-ff` de P-L68 sobre producción exacta y QA visual aislada;
2. despliegue solo con autorización humana y precondiciones cerradas;
3. P-L69 separado para que Telegram detecte fills durante mercado abierto:
   persistencia local primero, envío idempotente después, nunca al submit.

## P-L68 — desplegado (28-jul-2026)

- Producción quedó en versión `0.4.202`, merge `18add12488cfb4179391d685540d65aac9f8870d`
  y árbol funcional `68a7b4c5d04d78a54df425ab15d9c13431d7bc13`.
- Suite productiva: 2250 passed; estáticos, configuración y kernel verdes.
- Stack arriba mediante helpers gestionados; HTTP 200/200, listener único,
  scheduler lógico único y lock/token coherentes en dos comprobaciones.
- PMR 2026-07-28 permaneció terminal `completed`; bootstrap posterior
  `session_already_completed`, lease vacío y cero órdenes nuevas.
- Los históricos con base desconocida se dibujan como provisionales y no
  cuentan como victorias. Las nuevas capturas pueden adquirir comparabilidad
  canónica sin backfill.
- P-L69 continúa como lote independiente para detectar y notificar fills
  durante mercado abierto; no mezclarlo con cambios de política.

## P-L66 - siguiente paso

El candidato 0.4.201 incluye resumen Telegram a las 22:05 y avisos de fills.
Antes de desplegar requiere ensayo `--no-ff`, suite completa y smoke aislado
con XNYS cerrado. No desplegar automaticamente.

## P-L67R1 — ensayo combinado final (28-jul-2026)

- Worktree `pl67_p65_p62_p66_deployment_rehearsal`, HEAD `62de5525`, tree
  `77ec5a4f`, versión 0.4.201. Merge P-L66 `--no-ff` conservado.
- P-L62 freshness quedó subsumido sin copiar el panel P-L61 dirty; P-L65B
  conserva la comparación canónica sin yfinance. P-L66 queda desactivado por
  defecto y fail-open.
- QA final: 2242 passed, 1 skip preexistente (`test_pre_earnings.py:1041`),
  Ruff/NUL/diff/compile/config verdes. XNYS estaba abierto; no hubo despliegue.
- Smoke CLI real queda pendiente por seguridad; el sustituto monkeypatched de
  `run_observable_cycle(use_crew=False)` pasó en DATA_DIR temporal. Antes de
  desplegar hay que repetir preflight cerrado y normalizar el checkout dirty
  sin descartar cambios del operador.

## P-L72 — siguiente integración (29-jul-2026)

- Worktree `pl72_open_to_open_performance`, rama
  `codex/pl72-open-to-open-performance`, versión `0.4.206`.
- Integra P-L70 y P-L71 y corrige la frontera diaria con aperturas exactas
  Alpaca 15 minutos y Open ajustado de SPY.
- Semántica única: T open → next T open; para la sesión vigente, open → now.
  No utilizar `performance_daily`, timestamps midnight de 1D ni exposición
  actual como denominador.
- La UI muestra las últimas sesiones completas, tabla descendente y cero
  `pending`. Telegram comparte el intervalo cuando existe evidencia exacta.
- Suite completa `2283 passed, 1 skipped`; gates estáticos/configuración
  verdes. Siguiente paso: preflight cerrado, merge `--no-ff`, validación
  productiva con stack detenido, arranque gestionado y doble salud.

## P-L72 — desplegado (29-jul-2026)

- Producción `0.4.206`, merge funcional
  `50d959d76de113da40067dfbb3a03973d5635d2f`, árbol
  `b7eb971fc7fa8733706a6eef826ba5750e1aa267`.
- Suite sobre producción detenida: `2284 passed`; Ruff, NUL, diff,
  configuración, kernel y smoke aislado verdes.
- Doble comprobación: HTTP 200/200, scheduler único lógico, lock del runtime
  con token exacto, kernel sellado, lease PMR vacío y cero órdenes nuevas.
- UI productiva comprobada: siete filas completas y descendentes; seis
  intervalos finales y uno `En curso`, sin `Pendiente`.
- La próxima apertura XNYS es 29-jul a las 15:30 Europe/Madrid. Desde ese
  instante el intervalo vigente cambia automáticamente a apertura 29-jul →
  ahora.

## P-L74 - siguiente lote

- Candidato 0.4.208 con productor dedicado de apertura SPY y lector
  conflict-safe. La cache `market_data` no es autoridad por recencia: se
  requiere provenance explicita para resolver aperturas distintas.
- La captura corre al final del ciclo natural, no en `portfolio_watch`; no
  hay limite artificial de tres intentos. `inserted/available/idempotent/
  recovered` detienen el guard; metadata sin `.pkl` recuperable no lo detiene.
- Siguiente paso: ensayo `--no-ff` cerrado y suite completa aislada; mantener
  produccion 0.4.206 intacta hasta superar precondiciones y paridad.
- No hubo push ni cambio de política activa.

## P-L73 — cartera abierta con P/L total y diario

- Worktree `pl73_position_daily_pl`, rama
  `codex/pl73-position-daily-pl`, base productiva `36077a06`.
- Versión candidata `0.4.207`.
- `trade_history` conserva los campos total e intradía del mismo
  `PositionSnapshot` ya cargado por la UI.
- Dashboard y página Cartera muestran USD y porcentaje para `P/L total` y
  `P/L día`; missing se publica `n/d`.
- No se añade una llamada al broker y no se unen posiciones con otra fuente por
  símbolo. P-L72 conserva por separado la métrica de apertura a apertura.
- Focales `129 passed`; suite completa `2289 passed, 1 skipped`; Ruff, NUL,
  diff y configuración temporal verdes. Smoke sustituto aislado verde; CLI
  real omitido por seguridad de proveedores.

## P-L69-W - watcher intradia de fills confirmados

- Candidato aislado 0.4.209 en `pl69_fill_watch_impl`, rama
  `codex/pl69-fill-watch-impl`, base P-L75 `08e8f8fa`.
- El contrato consulta un `OrderStatusProvider` por `broker_order_id`; el
  adaptador del proveedor esta confinado en `tools/fill_provider.py`. La
  secuencia segura es snapshot remoto, commit local filled, claim, Telegram
  fail-open y recibo `telegram_trade_fill:<broker_order_id>`.
- Job separado, `max_instances=1`, cap 25, cadence 30 s por defecto y backoff
  acotado 30->300 s. Esta desactivado por defecto. Fills parciales/pending no
  avisan; SELL requiere `source_plan_id` exacto y compra unica filled.
- Commits: caracterizacion `581f6bfc`, implementacion `6bffedf2`, QA
  `9a689153`, fixes QA `fc9f7206`/`8e8da2c1`; documentacion `5c87cdd2`.
- XNYS abierto: no se ejecutaron suite completa, smoke, broker, red, Telegram
  real, SQLite productiva ni despliegue. Dictamen provisional
  `ready_for_closed_market_full_validation`; siguiente paso unico: ensayo
  cerrado con las precondiciones operativas completas.

## P-L75 - siguiente paso

- Ensayo combinado P-L73 + P-L74 integrado con `--no-ff` en version 0.4.208.
- P-L73 conserva el carrier de posicion; P-L74 conserva autoridad SPY,
  recovery de `.pkl` y retry por ciclo natural de mercado.
- Focales combinadas verdes; con XNYS abierto quedan pendientes suite completa
  y smoke. Repetir validacion cerrada antes de cualquier despliegue.
- Dictamen `ready_for_integration_rehearsal`. Sin despliegue, reinicio, push o
  cambios de política.

## P-L69-R1 - finalización downstream tras fill intradía

- En `pl69_fill_watch_impl`, `31560cfb` reprodujo que una orden terminalizada
  por el watcher desaparecía de `_pending_orders` y no alcanzaba la
  finalización postmarket. El recibo Telegram estaba presente, pero signal,
  learning y execution quality quedaban sin el paso posterior.
- `584575c1` añade el marcador durable `reconciliation_finalization` al payload
  de `broker_orders` y hace que PMR procese esos terminales con el snapshot
  local exacto. Claim transaccional `pending -> processing -> applied`, sin
  reabrir orden ni consultar otra transición remota; efectos y attach se
  confirman en la misma transacción. `0c121836`/`86b653ce`/`0909ea4b` cubren
  restart, idempotencia, carrera, SELL/rejected/cancelled y fallback SDK.
- Estado: `ready_for_closed_market_full_validation`, versión 0.4.209. Focales
  `133 passed` y R1 `18 passed`; suite completa/smoke y proveedor real siguen
  pendientes por XNYS abierto. Siguiente lote único: validación cerrada del
  candidato, sin despliegue automático.

## P-L69-R2 - endpoint provider y rollback de finalización

- `dac98d0b` reprodujo con el `TradingClient` real que `_base_url` enum se
  serializaba como `BaseURL.TRADING_PAPER`, generando URL inválida.
- `de8b250e` usa `.value` cuando existe, valida HTTP(S) y conserva el endpoint
  paper/live de la instancia; mantiene timeout, headers, redirects y fallback
  exacto por client ID. Endpoint inválido queda fail-open y no altera la orden.
- `f6c82f85`/`b819c540` cubren rollback transaccional del marcador R1, GET,
  fallback, live y ausencia de Telegram/transición en error. Batería final:
  `138 passed`; Ruff/NUL/compile/diff/config verdes.
- Dictamen: `ready_for_closed_market_full_validation`, versión 0.4.209.
  XNYS abierto; pendiente solo la validación cerrada antes de reintegrar o
  desplegar.

## P-L76-CLOSE - despliegue validado

- Producción desplegada en merge `49d33e17`, árbol funcional `3f2b859b`,
  versión `0.4.210`; tracked limpio y untracked del operador preservados.
- Suite merged `2340 passed`, focales `107 passed`, gates estáticos/config,
  kernel y smoke aislado verdes.
- PMR 2026-07-31 completed; XNYS cerrado. El watcher está activo en config
  `True/30/25/5/30/300`, pero el estado natural es `skipped` por mercado
  cerrado; no se provocaron fills ni Telegram real.
- Health 10:20:02 y 10:22:45 CEST, HTTP raíz/health 200/200, cero críticos,
  cero órdenes nuevas/duplicados/locks post-arranque. El `lock_orphan` es el
  falso positivo launcher/runtime documentado y el árbol PID es coherente.
- Dictamen final: `deployed`; sin push y sin abrir mejoras nuevas.

## P-L76R1 - gate funcional cerrado

- El candidato `pl76_p69_predeployment_rehearsal` queda en versión `0.4.210`
  tras `00015af6`; `1f4b4a79` y `2b2a21d0` son QA de expectativas obsoletas.
- Causa corregida: `capital_deployment_funnel_shadow_conflicts()` no debe
  importar ni filtrar por estados de `broker_orders`; su consulta solo contiene
  `agent_events`. La frontera `pending_broker_orders()` conserva su propio
  filtro terminal.
- Suite cerrada final: `2339 passed`, un skip preexistente y una advertencia
  externa; focales `107 passed`; gates estáticos/config y smoke de entrypoint
  temporal aislado verdes.
- No se ha tocado producción. Reanudar únicamente con el preflight cerrado
  exigido, merge exacto, delta `.env` autorizado y doble health posterior.

## P-L76-PRECLOSE - relevo para validación cerrada

- Ensayo aislado: `pl76_p69_predeployment_rehearsal`, rama
  `codex/pl76-p69-predeployment-rehearsal`.
- Merge `faccc5de42064211276b449d3cc78ebb6c022212`, tree
  `f2b5a7728b04e73916c95fec02c5ea1bb0c0bc18`, versión `0.4.209`.
- Producción base `36077a06`/tree `b15ac3a2`, P-L69-R2
  `4c3ed11d`/tree `f2b5a772`; referencias/tracked limpios y untracked del
  operador fuera del ensayo.
- QA focal `145 passed` + `2 passed`; Ruff/NUL/py_compile/diff/config verdes.
  XNYS abierto impidió suite completa, smoke y operación real.
- Contrato: snapshot provider-neutral por `broker_order_id` → commit local
  terminal → Telegram fail-open → recibo; PMR aplica
  `reconciliation_finalization` pendiente una sola vez. Watcher disabled por
  defecto y separado del ciclo activo.
- Antes de promover: XNYS cerrado, PMR terminal/lease vacío, sin jobs/test/
  deploy activos, paper/live/auto-apply seguros, suite `tests/ -x -q`, smoke
  temporal o `smoke_unavailable_by_safety`, doble salud >=75 s tras
  `stack_up`, cero órdenes inesperadas y cero locks. No desplegar desde este
  relevo sin esos gates.

## P-L77B1 - autoridad fail-closed de overrides adaptativos

- Candidato `pl77b1_adaptive_override_authority`, versión `0.4.211`, sobre
  `ba9d60d4`/árbol `7ea8ea9a`. La reproducción confirmó que la lectura legacy
  podía materializar `MAX_ORDERS_PER_CYCLE=2` con global false; la base es 4.
- `active_adaptive_overrides` ahora exige autorización global literal,
  `requested_auto_apply` y `authorized_auto_apply` individuales, y caducidad
  evaluable por sesiones XNYS. Sin sesión fiable, devuelve vacío; no usa mtime.
  El inventario health continúa mostrando `preexisting_unauthorized`.
- `config.py`, los protegidos, `.env`, SQLite y producción no se modificaron.
  Focales `49 passed`; suite `2361 passed`, un skip preexistente y una warning;
  Ruff/NUL/py_compile/diff/config/kernel aislado y smoke temporal verdes.
  Estado previo del candidato: `ready_for_closed_market_deployment`.
- Cierre P-L77B1 completado en producción mediante merge `7682901a` desde el
  candidato exacto `9701e2f1`; versión `0.4.211`, árbol funcional
  `ea93a512`. Suite `2361 passed`, `1 skipped` preexistente y `1 warning`,
  focales post-merge `73 passed`; dos checks post-arranque separados por más
  de 75 s confirmaron HTTP `200/200`, kernel `sealed/ok`, paper/live-off,
  scheduler/token coherentes, `MAX_ORDERS_PER_CYCLE=4`, cero órdenes abiertas
  y cero críticos. El inventario legacy sigue `preexisting_unauthorized` y
  warning observacional; no tiene autoridad efectiva. No abrir P-L78 en este
  turno.

## P-L79H - cierre intentado, gate rojo y rollback

- El preflight del 02-ago-2026 fue verde: XNYS cerrado, PMR 2026-07-31
  terminal `completed/pipeline_completed`, lease vacio, kernel `ok` y
  referencias limpias. Se preservaron los untracked del operador.
- El merge `--no-ff` `d05ce134` integro `222d2371` sobre `ba7d488d` y produjo
  temporalmente el arbol `205964d4`, version `0.4.214`.
- La suite completa se detuvo por un fallo real despues de `1678 passed` y
  `751.99 s`:
  `tests/test_p69_fill_watch_implementation.py::test_configuration_is_disabled_and_provider_timeout_is_neutral`
  afirma `False`, pero el `.env` productivo autorizado activa el watcher por
  P-L76. Hubo una warning externa y ningun cambio de test/config para ocultarlo.
- Revert auditable `6c36c062` dejo el arbol funcional `6938d157`, version
  `0.4.211`; `stack_up` y dos comprobaciones a las `01:31:22` y `01:33:06`
  CEST confirmaron HTTP raiz/health `200/200`, un scheduler, listener unico,
  kernel `ok` y ausencia de blockers.
- Estado: `needs_fix`. Proximo unico lote: aislar esa expectativa de test del
  `.env` productivo o actualizar su contrato de forma autorizada, sin cambiar
  la activacion del watcher; despues repetir suite y cierre. No desplegar
  `0.4.214` hasta obtener suite completamente verde.
## P-L78B - default global DeepSeek V4 Flash

- Candidato aislado `pl78b_deepseek_default`, versión `0.4.212`, sobre la base
  productiva `ba7d488d`/tree `6938d157`.
- `opencode-go/deepseek-v4-flash` es el default global. Los fallbacks técnicos
  siguen siendo Qwen y luego deterministas; GLM/Kimi/MiMo solo quedan como
  overrides explícitos, compatibilidad o historia.
- La telemetría de uso, snapshots de decisión y eventos CrewAI llevan
  `requested/effective/provider/fallback` del endpoint real. No se cambia la
  autoridad económica de gates, riesgo, sizing, planes u órdenes.
- QA: focales `317 passed`; suite completa aislada `2370 passed`, 1 skip
  preexistente y 1 warning externo en `812.37 s`; Ruff, NUL, compilación,
  diff, config, kernel temporal y smoke `run-once --skip-crew` temporal verdes.
- El worktree está listo para ensayo de integración cerrado. No tocar
  producción ni `.env` desde este relevo; el siguiente turno debe integrar el
  HEAD final con `merge --no-ff`, repetir gates y verificar dos health checks.

## P-L78C - `schedule-status` read-only (0.4.213)

- El candidato `pl78c_schedule_status_readonly` parte de P-L78B exacto y
  elimina la ruta `ensure_schema` del lector de estado del scheduler.
- `Store.read_runtime_values` usa SQLite URI `mode=ro` + `query_only`, cierra
  la conexión y falla cerrado ante DB ausente, schema legacy/incompatible,
  error de acceso, payload inválido o WAL/sidecars cuya lectura podría tocar
  `-shm`. En esos casos `runtime_state.available=false` y los jobs tienen
  `null`; calendario/cadencias permanecen informativos.
- El contrato CLI acepta `schedule-status --json`. No representa runtime
  unavailable como cero o como actividad confirmada; mantiene código `0` por
  compatibilidad y exige consumir `runtime_state.reason`.
- Suite final: `2380 passed, 1 skipped` preexistente
  (`test_score_study_regression_current_sqlite`, sin SQLite histórica local) y
  `1 warning` externo; focal P-L78C `10 passed`; Ruff, NUL, compilación, diff,
  config y smoke fake aislado verdes. Kernel temporal `unsealed` esperado sin
  violaciones.
  `schedule-status --json` real con DB ausente no crea `DATA_DIR` ni logs.
  La deriva productiva de `.env`/kernel continúa bloqueando P-L78B y no fue
  tocada por este lote.
- No integrar ni desplegar desde este relevo. Siguiente paso único: cerrar
  gates del candidato y resolver la procedencia autorizada de `.env` antes del
  ensayo combinado P-L78B+P-L78C.

## P-L78D - ensayo combinado P-L78B + P-L78C

- Merge de ensayo `304a61ab` con padres exactos producción `ba7d488d` y
  candidato `1bab847a`; árbol funcional `308baa64`, versión 0.4.213.
- Focales `174 passed`; suite `2380 passed`, un skip preexistente y una warning
  externa; Ruff, NUL, compilación, diff, config y smoke fake aislado verdes.
- Kernel temporal `unsealed` esperado sin violaciones. Kernel/broker/execution/
  risk son idénticos a producción; `config.py` solo contiene los cuatro
  defaults DeepSeek autorizados por P-L78B.
- Producción, `.env`, manifest, stack, SQLite, locks, leases y untracked del
  operador no se tocaron. La deriva `.env` continúa bloqueando el despliegue.
- Siguiente paso único: resolver autoridad/procedencia `.env` y repetir gates
  cerrados; no desplegar desde este ensayo.

## P-L79 - tabla de configuración Streamlit segura para PyArrow

- Candidato: `pl79_arrow_safe_config_table`, versión `0.4.214`, base
  `5e0f41e2`/tree `d00abe9c`.
- `page_config()` ya no entrega valores heterogéneos al serializador: la
  frontera informativa convierte booleanos, números, paths, secuencias y
  missing a texto determinista (`true`/`false`, valor numérico o `n/d`). No
  muta Settings ni añade claves o secretos.
- Suite `2385 passed`, un skip histórico preexistente y una warning externa;
  focales P-L79/P-L78B/P-L78C y flujo con dobles verdes. Ruff, NUL,
  compilación, diff, configuración temporal y kernel temporal (`unsealed`, sin
  violaciones) verdes. La ruta CLI real `run-once` no se lanzó porque exigiría
  adquisición de mercado; no se hizo red/broker/LLM.
- Siguiente paso único: revisar y ensayar integración `--no-ff` del candidato.
  El bloqueo productivo `.env`/kernel de P-L78 continúa intacto; P-L79 no lo
  repara ni autoriza despliegue.

## P-L79I - aislamiento de tests P-L69 respecto del entorno

- Contra `222d2371`, la prueba de defaults heredaba
  `TRADE_FILL_WATCH_ENABLED=true` del entorno del proceso aunque usara
  `DATA_DIR` temporal. La reproducción roja fue `1 failed`.
- Se corrigieron únicamente `tests/test_p69_fill_watch_implementation.py` y
  `tests/test_p76_p69_predeployment_rehearsal.py`: `_env_file=None`, entorno
  saneado con `monkeypatch` y regresión negativa con las seis variables del
  watcher. No cambia `.env`, Settings, watcher ni política.
- QA: `159 passed, 1 warning` con entorno activo externo y `3 passed` limpio;
  Ruff/NUL/diff verdes. Suite completa y smoke se reservan para la integración
  cerrada siguiente.
- Estado: `ready_for_closed_market_redeployment_rehearsal`; candidato limpio
  pendiente de ensayo `--no-ff`, sin despliegue en este lote.
## P-L79L - cierre productivo completado

- Dictamen: deployed el 02-ago-2026 con XNYS cerrado.
- Produccion integro 6c91279f mediante merge --no-ff 9b6c4a7b sobre
  1b88ae4a; padres exactos, tree funcional 8a0622ce y version 0.4.214.
- Preflight: PMR 2026-07-31 completed/pipeline_completed, lease vacio,
  runtime sin jobs activos, paper true, live/auto-apply false, kernel
  sellado/ok y .env autorizado estable (86a8420f...dfc35afb).
- Gates: focales activos/limpios 168 passed cada uno; suite 2387 passed y
  1 warning en 880.33 s; Ruff/NUL/compile/diff/config/kernel/smoke aislado
  verdes. Warning externa: websockets.legacy.
- Health: 02:46:27 y 02:48:08 CEST, separacion 101 s; raiz y /health
  200/200, un scheduler, listener unico, PID/lock/heartbeat coherentes y
  sin orden inesperada/database locked observado. lock_orphan continua siendo
  la etiqueta conocida del launcher/runtime, no un segundo scheduler.
- No tocar .env/manifest/protegidos, no kernel-seal, no broker/red/LLM real,
  jobs manuales, postmarket/reconciliacion, reinicio adicional ni push.

## P-L80A - auditoría del embudo de aprendizaje

Dictamen: `ready_for_implementation`. El worktree aislado documenta la
auditoría read-only de producción `0.4.214` del 02-ago. La actividad de
agentes está confirmada, pero el scoreboard `pmr_dfe5e200c9cc_measure_scoreboard`
recibe 43 ejecuciones sin controles: hay 493–496 filas de misma fecha y
489–496 intersecciones de `source_run_ids` por ejecución, pero las 43 llegan
como `executed_buy` con `gate.execution={}`. El matcher exacto no debe
relajarse ni sustituirse por SPY/régimen.

También quedan cuantificados 36/43 linajes verificados, 7
`legacy_unverified`, 199/200 propuestas PROSA, 0 experimentos de evidencia
admitidos en el digest vigente, WIP 14, 37 anomalías de market-data stale y
la discrepancia entre `duplicate_ratio=0,8433` del artefacto diario y la
proyección de SQLite consultada directamente. No se mezclan sus ventanas ni
denominadores. Runtime productivo se dejó `unavailable` por
`wal_mode_or_sidecar_present`, sin reparar sidecars.

Siguiente lote único: **P-L80B — cierre del carrier same-cycle**. Debe seguir
`signal_learning` → `signal_outcomes.gate_json` →
`learning_observations.gate_json` y conservar `source_run_id`, decisión,
razón/estado de capacidad y linaje; una fixture exacta debe producir pareja
control solo cuando todos esos campos estén presentes. Missing/conflict sigue
sin pareja. Probables fronteras: `signal_learning.py`, `daily_learning.py`,
`counterfactual_analysis.py` y tests; no tocar matcher, trading, risk,
execution, scheduler ni política. No reservar todavía versión.

Precondiciones y gates del siguiente lote: XNYS cerrado, PMR/lease terminales,
DATA_DIR temporal, `_env_file=None`, fakes sin red y suite completa únicamente
cuando no compita con producción. Si el carrier no existe o exige una frontera
protegida, detener y pedir revisión humana. P-L80C…P-L80G quedan únicamente
como cola provisional; no iniciar otro lote en paralelo.
## P-L80B - cierre prospectivo del carrier same-cycle

Dictamen del candidato: `ready_for_integration_rehearsal`. El productor
conserva `signal_id`, `source_run_id`, `cycle_id`, decisión y capacidad en el
carrier exacto hasta `signal_outcomes` y `learning_observations`; el matcher
no fue relajado. La fixture positiva produce un control solo con misma fecha,
source-run, `approved_buy*` y estado/razón allowlisted. Fecha/source distintos,
missing, conflicto o decisión no elegible siguen sin control.

Base P-L80A `b89bef47`; worktree
`pl80b_same_cycle_control_carrier`; rama
`codex/p-l80b-same-cycle-control-carrier`; versión candidata `0.4.215`.
Commits separados: `39ac28c6` (caracterización), `e089f7f3` (implementación)
y `a57c0f67` (QA/version policy). Suite: 2392 passed, 1 skip preexistente,
1 warning externo; focales 147 passed; Ruff/NUL/compile/diff/config y smoke
fake aislado verdes. Protegidos y producción permanecen intactos.

No hay backfill de las 43 filas históricas. El cutoff de cinco sesiones solo
se fija tras despliegue como `deployment_activation_at` UTC más la primera y
cuatro sesiones XNYS posteriores completadas con carrier exacto y outcomes
maduros. Siguiente lote único: ensayo de integración `--no-ff`; no desplegar
ni iniciar P-L80C-G en paralelo.

## P-L80BR - ensayo de integración P-L80B

El ensayo aislado quedó `ready_for_closed_market_deployment` en el merge
`5d7ea285` (`eb662c07` + `b0ff0d94`), versión `0.4.215`, tree idéntico al
candidato. Focales: 110 passed; suite completa reutilizada por identidad exacta
del tree: 2395 passed, 1 skip preexistente, 1 warning externo. Ruff/NUL/
compile/diff/config/smoke aislado verdes; kernel temporal unsealed esperado y
producción ok. No hubo cambios de trading/riesgo/ejecución ni backfill.

Siguiente paso único: cierre de mercado con preflight, suite/gates operativos y
despliegue secuenciado si todas las precondiciones siguen verdes. No iniciar
P-L80C-G ni ejecutar el carrier contra producción en este ensayo.

## P-L80H2 - estado del health DeepSeek

- Candidato aislado v0.4.216 en `codex/pl80h2-opencode-go-health`; script
  `scripts/check_opencode_go_deepseek.py` exige OpenCode Go/DeepSeek Flash y una
  sola llamada sin fallback ni reintento.
- La probe real del 02-ago devolvió `HTTP 403 region_forbidden`, con una sola
  petición y sin contenido/secretos expuestos. El proyecto resuelve de forma
  coherente `opencode-go/deepseek-v4-flash`; Qwen sigue siendo fallback técnico.
- Dictamen: `blocked_external_provider`. No desplegar ni cambiar proveedor.
  La única acción siguiente es habilitar el opt-in regional oficial y repetir
  exactamente este healthcheck una vez.

## P-L80H4 - estado del candidato tras el rollback

El primer gate de P-L80H3 fue una expectativa de version stale: la base
0.4.214 pasa, mientras el candidato 0.4.216 esperaba incorrectamente 0.4.215.
El fix minimo solo modifica esa prueba en `338d0cc0`.

QA cerrada del worktree P-L80H4: 70 focales passed; suite 2410 passed,
1 skip preexistente, 1 warning externo en 815.69 s; Ruff, NUL, compilacion,
diff, config y smoke fake aislado verdes. Kernel temporal unsealed esperado,
sin violaciones. Produccion sigue restaurada en `b1c4cc0f`/tree `2ee61f28`,
v0.4.214, stack sano. Proximo paso unico: redeploy cerrado de `338d0cc0` y
documentacion final, sin repetir probe DeepSeek.

## P-L80H5 - relevo tras despliegue

P-L80 v0.4.216 esta desplegado en el merge productivo `3e3ead0e` (padres
`97af2f24` y `f4b4bc58`, tree funcional `59097b81`). El revert-of-revert fue
auditable; no hubo conflictos. Suite: 2410 passed, 1 skip preexistente,
1 warning externa; focales 70 passed. Kernel/config, paper y stack quedaron
validos y las dos comprobaciones de salud fueron 200/200 con 136 s de
separacion. `lock_orphan` sigue siendo el falso positivo conocido del arbol
launcher/runtime, no un duplicado.

La probe DeepSeek verde existente se reutilizo sin nueva llamada
(`opencode-go/deepseek-v4-flash`, HTTP 200, stop, sin fallback, una request).
Cutoff: `2026-08-02T15:51:41.5484478Z`; cohorte: cinco sesiones XNYS
posteriores, previstas 03-07-ago si completan. Durante la ventana registrar
controles same-cycle, linaje, selected/not_selected, outcomes maduros,
costes/slippage/P-L/MFE/MAE/drawdown/concentracion, DeepSeek/fallback y
overnight. No abrir otro lote funcional antes de cerrar esa cohorte; observar
warnings preexistentes sin repararlos en este lote.
## P-L81 - relevo tras rollback

El candidato `7bc4648c`/tree `fc6916c2` fue integrado como `e8f7874e`, con
`2423 passed` post-merge, pero kernel rechazo el nuevo hash de `broker.py`.
Rollback auditable `6f86f260` restauro `e4fe1ddb` funcional/tree `ce15c1b0`,
v0.4.216; stack arriba y doble salud 200/200. El carry de `last_equity` es el
unico delta. Dictamen `needs_fix`: falta autoridad/procedimiento de sello
especifico antes de otro despliegue. No tocar P-L80, trading ni politica.
## P-L81 - relevo UI y metricas diarias

El candidato `codex/pl81-ui-daily-equity` adopta `daily_equity_pl = current_equity - account.last_equity` y su porcentaje sobre `last_equity`. La tarjeta global, Telegram cuando dispone del carrier oficial y la reconciliacion secundaria de posiciones distinguen diario, abierto, periodo y desde apertura. El chart conecta el punto actual con tramo discontinuo y muestra la fecha visual sin perder la sesion canónica.

Dictamen provisional: `ready_for_next_closed_market_deployment`. QA focal: 168 passed, 1 warning externo. No se requieren cambios en skills/runbooks. No desplegar si no queda margen para rollback, arranque y dos health checks antes de la apertura XNYS; produccion 0.4.216 permanece intacta.
## P-L81 - relevo tras reinicio y hard stop

El candidato `365d855f`/tree `8890f377`, v0.4.217, esta limpio. La primera suite termino `1555 passed, 1 failed, 1 warning` por expectativa stale `0.4.216`; se corrigio solo esa prueba y pasa aislada. La segunda suite fue interrumpida por reinicio sin salida recuperable: queda pendiente, sin repetirla durante la apertura.

Dictamen `ready_for_next_closed_market_deployment`: produccion `e4fe1ddb`/tree `ce15c1b0`, v0.4.216, stack arriba. Siguiente paso unico en cierre: suite completa aislada, gates restantes y despliegue solo si el preflight y el margen son seguros. No tocar broker carry, .env, protegidos ni politica.

## P-L81A - reaplicacion en curso

Se reaplica el contenido funcional validado desde `91ad200b` mediante
revert-of-revert auditable de `6f86f260`; los conflictos fueron solo
documentales y se conservaron las trazas de rollback y P-L81R. Falta ejecutar
la suite fresca y los gates antes de cualquier stack_down, sello o merge
productivo. No iniciar P-L82/P-L83.

## P-L81A - cierre productivo (04-ago-2026)

Dictamen: `deployed`. Merge `32c4025b` sobre `91ad200b`, segundo padre
`dc5df89e`, tree `0619f5b6`, version `0.4.217`. El carry autorizado de
`account.last_equity` se limito a `broker.py` y el resto de protegidos conserva
sus objetos Git; `.env` no cambio.

La suite fresca post-merge fue `2422 passed, 1 skipped preexistente, 1 warning`
en 975.02 s; focales `109 passed`. Ruff/NUL/compile/diff/version policy,
validate-agent-config aislado, kernel temporal y smoke fake pasaron. El sello
canonico unico termino con kernel `ok` sin violaciones. Salud 1
`2026-08-04T08:45:16+02:00` y salud 2 `2026-08-04T08:47:19+02:00` quedaron
separadas 123 s, con HTTP 200/200, scheduler y listener unicos, token/lock
coherentes, paper activo, live/auto-apply off y 0 criticos. Los tres warnings
preexistentes siguen observacionales.

El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` permanece vigente. No hubo probe
DeepSeek adicional, jobs manuales, backfill, reconciliacion forzada ni push.
La siguiente accion es observar la cohorte prospectiva P-L80; no abrir P-L82/P-L83
en este turno.

## P-L82 - relevo de autoridad SPY

El candidato `0.4.218` resuelve la autoridad de apertura SPY por grupo de valor
canónico y no por el primer artefacto leído. La reproducción base fue roja
cuando el genérico del mismo precio precedía a la cache dedicada; el orden
inverso era verde. Autoridades discordantes siguen en `conflict`. La UI expone
sesiones omitidas con fecha, estado, motivo y cobertura sin fabricar puntos.

Worktree `pl82_spy_opening_authority`, rama
`codex/pl82-spy-opening-authority`; commits `e1538614`, `87919ee2`, `d5228ac4`
y `b938eaa9`. Suite fresca `2430 passed, 1 skipped preexistente, 1 warning`;
focales `193 passed, 1 warning`; Ruff, NUL, compile, diff, config y kernel
temporal sin violaciones verdes. Producción P-L81A permanece intacta en
`0.4.217`; no tocar broker/kernel/execution/risk/config/.env ni la captura
P-L80. Siguiente paso único: preflight cerrado y despliegue secuenciado solo
con margen suficiente; no iniciar P-L83.

## P-L82 - relevo tras despliegue

P-L82 esta desplegado en `0.4.218`: merge productivo
`df80dee8` (padres `31b7367b` y `a0ac5eed`), tree funcional `93d8a756`.
La tentativa accidental `098283bf` fue revertida auditablemente por
`31b7367b` antes de la integracion final. La suite post-merge fue `2431
passed, 1 warning`; focales `193 passed, 1 warning`; kernel `ok`, paper
activo, live/auto-apply off. Salud 1 `09:59:51 CEST` y salud 2 `10:02:08
CEST` fueron 200/200 con `136.89s` de separacion, scheduler/listener unicos,
token coherente y 0 criticos. El runtime de `schedule-status` queda
`unavailable` por WAL/sidecars segun el contrato read-only, sin reparacion.

El cutoff P-L80 `2026-08-02T15:51:41.5484478Z` no cambia y no hubo backfill,
jobs manuales, nueva probe DeepSeek ni push. No iniciar P-L83 en este turno.

### P-L82R - cierre productivo

P-L82R queda `deployed` en version `0.4.219`: merge `b0a88b98`, primer padre
`d73a8971`, segundo padre `06152971`, tree `cd75d3de`. El ensayo aislado
`67183356` tuvo el mismo tree y cero conflictos. Suite post-merge `2436
passed, 1 skipped preexistente, 1 warning` en `763.44s`; Ruff, NUL, compile,
diff, version policy, config aislada, kernel temporal/productivo y smoke fake
verdes. Salud 1 `11:07:20 CEST` y salud 2 `11:09:34 CEST`, separadas `134.33s`,
confirmaron HTTP raíz/health 200/200, listener único, wrapper/launcher/runtime,
scheduler con owner/token coherentes, paper activo, live/auto-apply off, kernel
`ok`, 0 críticos y cero órdenes desde el merge. `schedule-status` mantiene
runtime `unavailable` por WAL/sidecars bajo contrato read-only, sin reparación;
PMR 03/08 terminal y coordinación activa vacía. Cutoff P-L80 intacto. No
backfill, jobs manuales, nueva probe DeepSeek, P-L83 ni push.

## P-L82R - continuidad temporal Sistema vs SPY

El candidato `0.4.219` queda listo para integración cerrada, no desplegado.
Base productiva exacta `d73a8971` / tree `f966a725`; worktree
`pl82r_spy_temporal_continuity`, rama `codex/pl82r-spy-temporal-continuity`,
HEAD `1fab7813`, tree `32506e65`. La regresión estaba en la presentación y
comparabilidad: la línea atravesaba omisiones y un SPY stale se trataba como
ganador vigente.

El fix segmenta únicamente intervalos XNYS contiguos, no conecta sobre
omitted/conflict/missing y exige igualdad exacta UTC de los dos `as_of` para
comparar la fila `En curso`. Si no están alineados, ambos valores siguen
visibles con `comparison_status=unavailable`, razón, lag y cobertura; no hay
ganador ni conector. El caso sistema 04/08 08:11Z frente a SPY 03/08 20:12:55Z
queda fuera de comparación. Conflictos y cuatro omisiones P-L82 se preservan.

QA: focales `6 passed`; regresiones UI/SPY/Telegram `200 passed, 1 warning`;
suite `2436 passed, 1 skipped preexistente, 1 warning` en `786.12s`; Ruff,
NUL, compile, diff, version policy, configuración aislada, kernel temporal
`unsealed` sin violaciones y smoke fake aislado verdes. Protegidos iguales a
la base; producción/stack/cutoff P-L80 sin cambios. Siguiente paso único:
ensayo `merge --no-ff`, preflight cerrado renovado y despliegue secuenciado
solo con margen; no iniciar P-L83.

## P-L83D - cierre productivo y congelacion

P-L83D esta `deployed` en `0.4.220`: merge `613aab87` sobre `5d53e24c`,
segundo padre `c3a5e671`, tree `57780f1d`. La UI ancla los buckets diarios a
cierres XNYS, corrige epoch seconds y mantiene el current provisional
separado. No se modificaron broker, kernel, execution, risk, config, `.env`,
trading ni la cohorte P-L80.

Suite `2444 passed, 1 skip preexistente, 1 warning`; focales post-merge `227
passed, 1 warning`; gates verdes. Salud 1 `12:36:06 CEST` y salud 2
`12:37:58 CEST`, separadas `111.83s`: HTTP 200/200, scheduler/listener
unicos, owner/token/heartbeat coherentes, paper activo, live/auto-apply off,
kernel ok, 0 criticos y 0 ordenes abiertas. Los tres warnings preexistentes
siguen observacionales.

Cutoff P-L80 `2026-08-02T15:51:41.5484478Z` intacto. Congelar cambios
funcionales hasta la revision del 08/08; no iniciar P-L82/P-L83 adicionales,
no backfill, no jobs manuales y no push.

## P-L83D - dashboard y fechas temporales

El candidato aislado `codex/pl83d-dashboard-temporal-dates`, version `0.4.220`,
HEAD `d15eb37e` y tree `306a3dae`, corrige la interpretacion de buckets Alpaca
1D: los epoch se normalizan por unidad y cada punto se ancla a la sesion XNYS
de cierre. El current queda separado como provisional, no pisa cierres y la
ventana de siete dias usa `session_date`. Se preservan P-L80 y P-L82R.

QA fresca: `2444 passed, 1 skip preexistente, 1 warning` en 1139.57 s;
focales P-L83D/UI `133 passed` y regresiones adicionales `102 passed`; Ruff,
NUL, compile, diff-check, version, config aislada y smoke fake verdes. Los
archivos protegidos permanecen iguales y produccion continua en `0.4.219`.

Dictamen provisional: `ready_for_closed_market_deployment`. Siguiente accion
unica: ensayo `merge --no-ff` y preflight cerrado con margen; no detener el
stack si no se puede completar rollback, arranque y dos health checks antes de
la apertura. Tras el cierre de P-L83D, congelar cambios hasta la revision del
08/08.

## P-L84 - plan condicional de evidencia multi-agente

Se incorpora al plan maestro una cola condicional inspirada por la arquitectura
publica de BQuant Agents: contrato efectivo de agentes, aportacion ortogonal,
debate auditado, decision no-trade, horizontes y datos point-in-time. Es una
actualizacion exclusivamente documental, sin version ni autorizacion de
implementacion.

La siguiente accion sigue siendo la revision prospectiva P-L80 del 08/08. Si
las cinco sesiones y outcomes estan maduros, se elegira un unico lote por riesgo
y valor de informacion. P-L84A, auditoria read-only del contrato real de cada
agente, es solo el candidato por defecto; queda desplazado si la revision
descubre antes un defecto critico de captura, control same-cycle, linaje,
costes o outcomes. P-L84B-H no se ejecutan en paralelo, no cambian politica y
requieren autorizacion posterior segun su alcance.

## P-L85 - estado para cierre Zen Free

La incertidumbre de la probe Zen quedo caracterizada sin relajar el contrato.
Las cuatro llamadas Zen corregidas y la health Go fueron HTTP 200, `stop`, con
contenido final y `reasoning_content` presentes; se consumio el presupuesto
`10/10` y no se observaron limites de rate ni errores HTTP. La respuesta
historica `length` queda como evidencia invalida de la bateria original y su
causa exacta es `unavailable`.

El candidato aislado configura Zen Free como primario y una sola tentativa Go
como fallback inmediato, con fallbacks locales posteriores. La telemetria no
publica mensajes crudos del proveedor; solo clase/HTTP acotados. Suite fresca:
`2456 passed, 1 skipped preexistente, 1 warning` en `752.91s`; focales
posteriores `106 passed`. Produccion sigue Go/v0.4.220 hasta un preflight
cerrado, gates detenidos, delta `.env` no secreto revisado, eventual sello
canonico unico, stack_up y doble salud >=75 s. No iniciar otro lote en paralelo,
no tocar el cutoff P-L80 ni hacer backfill.

### P-L85 - desplegado

P-L85 queda desplegado en `0.4.221`, merge `78bb0758`, tree funcional
`8ea38dbb`. Zen Free es primario y Go es fallback inmediato de una sola
tentativa; los fallbacks locales existentes siguen después. El sello canónico
único de `.env` terminó `ok`; no se tocaron credenciales ni política. Suite
`2456 passed, 1 skip preexistente, 1 warning`, focales post-merge `161 passed`.
Salud 1 `01:12:25.746` y salud 2 `01:14:15.675` Madrid, separadas `109.9286s`,
confirmaron HTTP 200/200, scheduler/listener únicos, owner/token/heartbeat,
paper/live/auto-apply seguros y cero órdenes abiertas. `activation_at`:
`2026-08-05T23:14:15.6752134Z`; cutoff P-L80 intacto, sin backfill ni nueva
probe. La prioridad siguiente es la revisión de cohorte del 08/08, no otro
lote de proveedores en paralelo.

## P-L86R - página Kindle oculta en Streamlit

P-L86R sustituye la tentativa independiente de servidor/puerto/tarea por una
única ruta `/kindle` dentro de `AgenteBolsaWeb` en el puerto 8501. El candidato
usa Streamlit 1.58 (`st.Page(url_path="kindle", visibility="hidden")` y
`st.navigation(position="hidden")`), conserva la navegación manual en `/` y
no expone la ruta en el menú.

La vista reutiliza `PortfolioSnapshot`, `daily_equity_change`, el consumidor
SPY del dashboard y las posiciones ya cargadas. No crea snapshots, carriers,
archivos, jobs, procesos ni escrituras; no llama a broker/LLM/red desde un
productor nuevo. El HTML es básico, escapado, blanco/negro y sin JavaScript ni
recursos externos. La versión candidata es `0.4.222`.

La caracterización y los focales iniciales pasan `54`. Falta la suite completa
y los gates de cierre en árbol final. Producción sigue `0.4.221`, P-L80/P-L85
permanecen intactos y los componentes independientes antiguos no deben
reaparecer. Solo si el preflight cerrado y el margen hasta XNYS siguen verdes
se hará merge `--no-ff`, stack gestionado, comprobación real de `/kindle` y dos
health checks separados >=75 s. Sin push.

### P-L86R - cierre productivo

P-L86R queda `deployed` en `0.4.222`: merge `849feebd`, primer padre
`faa2e157`, segundo padre `307658f3`, árbol funcional del candidato `bd5e10d4`.
La ruta oculta `/kindle` comparte `AgenteBolsaWeb` y 8501, sin servidor,
snapshot, carrier, tarea o scheduler nuevos. La suite final fue
`2464 passed, 1 skip, 1 warning` en `891.60s`; focales post-merge `54`, gates
breves verdes. Salud 1/2 200/200, separadas `134.66s`, kernel `ok`, scheduler y
listener únicos, paper activo, live/auto-apply off y 0 críticos. El cutoff
P-L80 y P-L85 permanecen intactos. No abrir otro lote ni hacer push.

## P-L86L - habilitación LAN privada

Lote operacional pendiente: actualizar únicamente `install_web_task.ps1` para
`--host 0.0.0.0`, reconciliar la tarea existente y crear una regla TCP 8501
limitada a `Private/LocalSubnet`. La WLAN ya está en `Private`; no tocar
scheduler, trading, configuración protegida ni otros puertos. Tras reiniciar
solo web, validar localhost/LAN, `/health`, `/kindle`, listener y Git limpio.

## P-L86K - ruta Kindle raw

Dictamen: `deployed`. La caracterizacion
confirmo que `/kindle` devolvia el shell JS de Streamlit. El candidato v0.4.223
registra una ruta ASGI oficial `st.App`/Starlette antes de las rutas internas,
sin servidor, proceso, puerto, tarea o persistencia nuevos. Loading y vista
cargada son HTML simple sin JS; la vista usa el snapshot de cuenta, no expone
`Cantidad` y deja SPY en `n/d` si el carrier diario no prueba comparabilidad.
Focales y lint son verdes. Merge `9b9068f3`, tarea web gestionada Running,
HTTP 200 local/LAN y dos saludes separadas 121.28 s. Produccion queda en
v0.4.223; scheduler, LAN, P-L80 y P-L85 no cambian.

## P-L87 - siguiente cierre

P-L87 queda `deployed` en v0.4.224 mediante merge `db5a8584`: añade
la cuarta tarjeta de ganancia/pérdida intradía de posiciones con cobertura K/N
y las ventas desde la apertura XNYS, una fila por sell fill. Reutiliza los
carriers ya cargados, conserva `n/d` cuando falta P/L realizado o apertura y no
altera trading, riesgo, ejecución ni P-L80. La tarea web fue reiniciada de
forma gestionada; raíz, `/health` y `/kindle` quedaron 200 local/LAN y las dos
saludes se separaron 110,6 s. No iniciar P-L88.

## P-L88 - dashboard Sistema vs S&P 500

El candidato aislado `codex/pl88-system-spy-temporal-ui` adopta la ventana
apertura XNYS exacta -> ahora para Sistema y el carrier existente de SPY. Un
SPY solo se dibuja/compara si es el ETF correcto, transporta
`provider_observed_at`/`market_observed_at` explicito y su observacion esta a
<=300 segundos del `account_read_at`; `created_at` de cache no sustituye ese
timestamp. Sin carrier explicito el caso queda `n/d` con razon
`current_observation_timestamp_unverified`, sin ganador. La cabecera conserva
el P/L oficial desde cierre anterior pero lo identifica con ese nombre. El
commit N1 separado etiqueta cada punto visible de `Valor de cartera` con
porcentaje y color semantico, preservando el predecesor oculto.

Base productiva: `0cf8a535` / tree `57ad3370` / v0.4.224 limpia. Candidato
v0.4.225; commits `81a2bcd0`, `64bf9b59`, `7717c20f`, `e04f3ba0`, `7abdfb1f`,
`9350f024`; informe unico `docs/informe_p_l88_sistema_spy_temporal.md`.
P-L88R: caracterizacion roja `1 failed`, despues `10 passed` y `40 passed` de
regresiones SPY; Ruff/NUL/diff verdes. XNYS estaba abierto durante la
ejecucion, por lo que no hubo suite completa, merge, reinicio ni despliegue.
La UI queda lista para un despliegue veraz, pero la comparacion SPY
apertura->ahora sigue `unavailable` hasta resolver fuente/cadencia. P-L80 y la
politica de trading permanecen intactos.

### Cierre productivo P-L88R-D

P-L88R-D queda `deployed` en v0.4.225: merge `8b572948` con primer padre
`0cf8a535` y segundo padre `2884f2ac`, tree `3d0c8650`. Suite definitiva
`2493 passed, 1 skipped, 1 warning`; focal post-merge `111 passed, 1 warning`
y gates estaticos/config/kernel/smoke verdes. Dos saludes: 00:01:49 y
00:04:19 CEST (~150 s), HTTP 200 local/LAN en `/`, `/health` y `/kindle`,
listener unico, scheduler owner/token coherentes, paper activo y live/
auto-apply off. El kernel productivo sigue valido. SPY no comparable sin
`provider_observed_at`/`market_observed_at`; no iniciar una fuente nueva en
este lote.

### Cierre P-L88R-D

La suite cerrada inicial encontro una expectativa de version stale en
`test_p59c_llm_selected_authority.py` (`1567 passed, 1 failed, 1 warning`),
reproducible tambien en la base `0cf8a535`. `de7b9923` corrigio solo el test a
`0.4.225`; la suite fresca definitiva termino `2493 passed, 1 skipped, 1
warning` en `801.14 s`. Smoke fake `1 passed`, Ruff/NUL/compile/diff-check y
configuracion aislada verdes. No se repite la suite por cambios documentales
posteriores; el siguiente paso unico es preflight cerrado, merge gestionado y
dos comprobaciones de salud. SPY sigue honestamente `n/d` si no existe
`provider_observed_at`/`market_observed_at` alineado.

## P-L89B - siguiente paso unico

El candidato `codex/pl89b-capital-observability` queda listo para integracion
cerrada en version `0.4.226`. Completa el carrier observacional append-only
del funnel de capital con IDs exactos y proyecta la cuenta desde el snapshot
ya cargado, sin llamadas broker nuevas ni autoridad sobre sizing, gates,
riesgo, seleccion o ejecucion. El EOD lleva `previous_close_equity` como
`equity_start` y timestamps UTC coherentes; sigue `unavailable` si faltan
ventana XNYS, flows, costes, exposicion temporal o benchmark comparable.

QA final: `2497 passed, 1 skip preexistente, 1 warning` en `797.61s`; focales
36 y policy 47, Ruff/NUL/compile/diff/config/kernel/smoke verdes. Produccion
base `eb9d6bede5a5aa55de10441fb442430028d1fb47` / tree
`250dfa2c527d53c1d3d13ecda1ea5027f496e149` permanece intacta. El cutoff
P-L80 no cambia. No iniciar experimento de capital: esperar dos ventanas
maduras con controles same-cycle y EOD/costes/exposicion validos.

Siguiente accion: renovar preflight cerrado, hacer merge `--no-ff` del
candidato, repetir gates con stack detenido y ejecutar stack_up con dos
saludes separadas. Si falla una precondicion, no desplegar y dejar produccion
intacta. Sin backfill, jobs manuales, kernel-seal, cambios de `.env` ni push.

### Cierre productivo P-L89B

P-L89B fue desplegado en v0.4.226 mediante merge `4efd58ff` (primer padre
`eb9d6bde`, segundo `6a87c589`, tree funcional `505c3ee8`). La suite definitiva
reutilizada por identidad exacta fue `2497 passed, 1 skipped preexistente,
1 warning`; gates post-merge verdes. Salud 1 a las 23:51:33.9799274 CEST y
salud 2 a las 23:53:37.2454445 CEST, separadas 123.27 s: HTTP 200 en las tres
rutas web, listener unico, scheduler owner/token coherentes, paper activo,
live/auto-apply off, kernel/config validos y 0 criticos. El funnel/EOD
historico sigue `unavailable` cuando faltan carriers; no se imputo nada. El
cutoff P-L80 permanece intacto. Siguiente paso unico: observar dos ventanas
maduras con controles same-cycle y EOD/costes/exposicion validos antes de
valorar una dimension shadow, siempre human-gated.
## P-L89-RPI-HARDENING - estado operativo

El lote `codex/operational-hardening` añade un preflight Raspberry read-only y
corrige la detección de ownership Windows en la cadena wrapper -> launcher
`.venv` -> runtime Python. No toca trading, riesgo, broker, `.env`, SQLite
activa ni `whale-copy`.

Preflight real 2026-08-12 23:21 Europe/Madrid: Raspberry `Raspberryi5`,
`aarch64`, USB `/dev/sda1` ext4 `rw`, UUID esperado, espacio suficiente,
contenedores core healthy, imagen `0.4.230-arm64` cargada y flags PAPER
correctos. Dictamen `precondition_not_met`: el host se reinicio a las 23:15:16 y
solo tenia 455 s de uptime; falta receipt de snapshot frio SQLite. La lectura
no produjo mutaciones ni dejo procesos `D`.

Siguiente secuencia: esperar estabilidad, producir y validar el snapshot frio
autorizado, ejecutar el preflight con `--sqlite-receipt`, confirmar postmarket,
leases y exclusividad Windows, y solo despues realizar el corte cerrado con
rollback a `0.4.229-arm64` preparado.

La herramienta `scripts/sqlite_cold_snapshot.py` implementa ese snapshot sin
`VACUUM`, checkpoint ni backfill: exige `--writers-stopped`, no sobrescribe,
conserva los sidecars presentes, valida la copia y genera `receipt.json` con
hashes y resultados de integridad.

Ultimo preflight estricto 2026-08-12 23:37 CEST: Raspberry estable (uptime
1306 s), USB esperado ext4/rw sin I/O reciente, core Docker healthy, candidata
`0.4.230-arm64` cargada y flags PAPER coherentes por contenedor. Dictamen
`precondition_not_met`: falta receipt de snapshot fria y Windows aun mantiene
scheduler/web activos. No detener, reiniciar ni cambiar Compose/env hasta el
corte autorizado; conservar rollback a `0.4.229-arm64`.

Reconciliacion 23:42 CEST: `windows_exclusivity` ya informa `foreign=[]` al
resolver el checkout principal desde `git-common-dir`; la foreign process
anterior era un falso positivo del worktree candidato. Permanecen solo falta
de receipt SQLite y scheduler/web Windows activos.

Ventana 2026-08-12 23:46-23:53 CEST: se detuvo Windows con el helper canonico,
se creo y valido la snapshot fria v2 en
`C:\Antonio\Bref\agenteBolsa_backups\raspberry-cut-20260812-2350` (base
`7fab2f7f...`, WAL `66632ef2...`, SHM `e5e00a5e...`, quick/integrity ok). El
preflight Raspberry bloqueo el corte por `whale-copy` en estado D y memoria
disponible bajo 256 MiB. Se hizo rollback a Windows; despues Raspberry se
reinicio externamente y el preflight final mostro uptime 67 s y core
unhealthy. Dictamen `precondition_not_met`; no transferir ni desplegar hasta
auditoria read-only del reinicio y estabilidad >=600 s. La snapshot y la
candidata se conservan; la exclusividad queda sin demostrar porque Raspberry
conserva el core antiguo `0.4.229-arm64`.

Auditoria 23:56 CEST: Raspberry respondia, USB ext4/rw y `whale-copy`
`running/healthy`, pero uptime solo 4 min. `journalctl` no conserva el boot
anterior ni evidencia OOM/I/O/watchdog; causa del reinicio `unavailable`. No
hacer otro corte hasta superar 600 s y repetir el preflight.

Actualizacion 2026-08-13 00:08 CEST: el preflight con `receipt.json` valida
identidad, USB ext4/rw, recursos basicos, SQLite/WAL/SHM, imagen candidata y
flags PAPER. La Raspberry sigue en `0.4.229-arm64`; el scheduler figura
healthy pero acumula 37 reinicios y CPU alta, por lo que no se declara corte
listo. Windows sigue activo con scheduler unico y lock/token coherentes.
El commit candidato `611da4b1` aligera el healthcheck ARM64, pero requiere
rebuild ARM64 y verificacion de contenido antes de cargarlo; Docker Desktop
estaba inaccesible en esta ronda. Proxima accion: rebuild local, validacion de
imagen/Compose, preflight estricto con Windows detenido solo dentro de una
ventana autorizada y dos healthchecks separados; sin tocar `whale-copy`.

Preflight estricto 2026-08-13 00:17 CEST: `ok=false` por dos razones
reproducibles: scheduler Raspberry con 37 reinicios y Windows con scheduler/web
activos. Identidad, USB ext4/rw, I/O, snapshot SQLite, imagen, flags PAPER y
salud actual pasaron. El nuevo flag `--require-core-restart-zero` queda como
gate obligatorio del corte. No detener ni arrancar nada hasta reconstruir la
imagen `611da4b1` y repetir el preflight con ambos bloqueos resueltos.

Incidente posterior 2026-08-13 00:22 CEST: TCP/22 responde y ARP resuelve
`192.168.1.234`, pero SSH expira durante el banner en dos intentos acotados.
Raspberry queda `unavailable`; no reiniciar ni limpiar remotamente. Reanudar
solo cuando una lectura SSH autenticada confirme host, montaje, I/O y Docker.

Bloqueo local adicional: Docker Desktop `4.33.1` no levanta el engine porque
requiere `WSL update required` y la actualizacion elevada fue denegada. No
ejecutar `wsl --update` automaticamente; requiere autoridad administrativa.

## P-L90-CUTOVER-R10 - cierre de identidad y OOM (13-ago-2026 22:41 CEST)

Dictamen vigente: `precondition_not_met`. No declarar desplegada la Raspberry y
no iniciar Jetson.

La lectura actual confirma que Windows sigue en HEAD `3ebff4e2`/tree
`d4071dcb`/v0.4.226 y detenido. Raspberry ejecuta realmente la imagen
`0.4.241-arm64`, revision `1e5c3c32`, pero su Compose/env efectivo contiene la
etiqueta `0.4.229-arm64`. La candidata cargada `0.4.230-arm64` es
`42b8dfc1`/tree `7c204e6c`/digest `sha256:c9745ce0...`; su merge-base es el
antiguo `0e4e1194`, no el Windows actual. Frente a la base actual elimina
preflight, snapshot y documentacion operativa, por lo que no se puede usar sin
reconstruccion exacta.

La causa de los reinicios ya esta demostrada: Docker events registran `oom`,
`die exitCode=137` y `start`; dmesg registra OOM del memory cgroup. El contador
del scheduler llego a 9 y el preflight estricto marco `ok=false` por reinicios
y memoria disponible de 118 MiB. Los solapamientos/missed de APScheduler y
errores LLM 429 son factores de carga, no causa primaria confirmada.

El USB sigue sano (`/dev/sda1`, ext4/rw, UUID esperado), pero no se hizo nuevo
snapshot frio porque no se detuvieron escritores. `whale-copy` fue restaurado
healthy tras su stop/start exclusivo y queda fuera de la paridad; su watchdog
con permisos defectuosos es deuda separada.

Siguiente encargo: candidato desde el HEAD Windows exacto, Compose/env/runtime
inmutables y caracterizacion observacional de jobs/LLM/SQLite. No cambiar
trading, riesgo, politica, locks ni SQLite; no desplegar ni migrar a Jetson
hasta superar preflight, snapshot y estabilidad prolongada.

## P-L90R10 - relevo candidato ARM64 (13-ago-2026)

Dictamen: `precondition_not_met`; candidato local `ready_for_jetson` como
fuente de build, Raspberry no desplegada. Base Windows exacta
`3ebff4e2`/`d4071dcb`, worktree
`C:\Antonio\Bref\agenteBolsa_worktrees\pl90r10_arm64_oom_guard`, commit
`d8629489`, tree `9159be36`, v0.4.242.

La mitigación única es `SCHEDULER_MAX_WORKERS=2` en el executor APScheduler.
Mantiene jobs/cadencias y las garantías de trading. La suite final dio
`2524 passed, 1 skipped, 1 warning`; focales, smoke fake, Ruff/NUL/diff y
config aislada pasaron. Los archivos protegidos y carriers P-L89B son
idénticos a la base. Compose, entrypoint, supervisor auxiliar, sonda ligera y
preflight parametrizado forman la capa ARM64; no hay digest porque Docker
Desktop/WSL no tiene engine utilizable.

### Relectura read-only 13-ago-2026 23:31 CEST

Preflight Jetson 14-ago-2026: TCP/22 en `192.168.1.186` responde y la consola
local confirmó la huella `MD5 73:81:ac:da:43:ad:f5:ad:f9:4e:c0:5b:a6:49:54:1a`.
El acceso remoto desde Windows falla por `Permission denied
(publickey,password)`; no hay clave autorizada y no se usa contraseña en logs.
No transferir ni ejecutar comandos remotos hasta habilitar autenticación.
Windows también aparece con scheduler/lock vivos; mantener
`precondition_not_met` y resolver ambas precondiciones en la próxima ventana
segura.

Raspberry sigue en 0.4.241-arm64. El core responde healthy, pero scheduler
`restart=23`, consumo 907.6 MiB/1 GiB y 286 MiB disponibles con swap elevada;
no cumple el gate de estabilidad. `/dev/sda1` ext4/rw y `mmcblk0p2` siguen
intactos; `whale-copy` healthy e independiente. Mantener
`precondition_not_met`: no snapshot, corte, reinicio, limpieza de locks ni
Jetson hasta builder/digest, preflight y datos fríos válidos.

Raspberry sigue en 0.4.241 con historial OOM/exit 137/restarts y presión de
memoria; Windows está detenido y recuperable. No ejecutar snapshot, stack,
SQLite/WAL/SHM, locks ni `whale-copy` en este relevo. Falta recuperar un
builder ARM64, comprobar digest/Compose, repetir preflight con restart=0,
crear snapshot frío y demostrar salud >=600 s. Jetson queda pendiente de IP,
SSH y preflight propio; no copiar ni arrancar allí todavía.

## P-L90R10-JETSON - host preparado, build listo, persistencia pendiente (14-ago-2026)

Dictamen vigente: `authority_required` / `precondition_not_met`. El destino de
esta fase es el Jetson Orin Nano por Wi-Fi `192.168.1.186`; no se usa la IP
Ethernet `.187` porque la interfaz está sin enlace. SSH por clave funciona.

El host está preparado sin mutaciones de agenteBolsa: Ubuntu 24.04.4,
aarch64, JetPack/L4T R39.2.1, GPU Orin operativa, Docker 29.1.3, Compose
2.40.3, buildx 0.30.1, unos 7.3 GiB RAM, sin swap y unos 424 GiB libres en
NVMe ext4/rw. `docker ps` está vacío; no hay contenedores, volúmenes,
imágenes agenteBolsa ni otro proyecto Docker que inventariar o detener.

Fuente de build exacta: worktree
`C:\Antonio\Bref\agenteBolsa_worktrees\pl90r10_arm64_oom_guard`, commit
`d4dcb075db8f8a5285a1f2e35cfe23fb64c55df9`, tree
`5d311ccceb62a7a95c950f6d3237d527a36e6a1d`, v0.4.242. Imagen nativa
`agente-bolsa:0.4.242-arm64`, digest
`sha256:42a7b88d7f4f31c9c434795b8b6eea09ceeed1d27458622db96a71a384303a42`,
config digest `sha256:9efde97ca3aa27aedbfbc7795b239f62e3c08ecce443786da6f3b95768568d51`.
El bundle de build sin secretos ni datos tiene SHA-256
`46a0ddfdf3958a3ab3fbd1a6f2b5d63066cdfb62708f045cfbd608be3e4b740`.
Compose candidato valida con `config --quiet`; todavía no se ha hecho `up`.

Bloqueo exacto: las rutas persistentes recomendadas (`/opt/agente-bolsa`,
`/etc/agente-bolsa`, `/var/lib/agente-bolsa`, `/var/backups/agente-bolsa`)
requieren `sudo` y la sesión Codex no dispone de elevación no interactiva.
No improvisar ownership, no copiar secretos por SCP y no iniciar el stack con
el env de ejemplo. El operador debe ejecutar en el Jetson, desde su terminal:

```bash
sudo sh -c 'install -d -o root -g root -m 0755 /opt/agente-bolsa /etc/agente-bolsa /var/backups/agente-bolsa; install -d -o antonio -g antonio -m 0750 /opt/agente-bolsa/releases /var/lib/agente-bolsa'
```

Después debe confirmar que las rutas existen y provisionar manualmente
`/etc/agente-bolsa/application.env` mediante el mecanismo seguro aprobado,
con permisos `600`, sin pegar credenciales en el chat. No detener Windows ni
Raspberry, no crear snapshot ni copiar SQLite hasta que ese env esté listo y
se confirme la ventana segura; Windows/Raspberry permanecen como rollback.

La orden fue ejecutada correctamente. La sesión remota confirmó ownership y
permisos de las cinco rutas y `application.env` sigue ausente. Se dejaron solo
los cuatro archivos Compose no secretos en
`/opt/agente-bolsa/releases/0.4.242/deploy/`; el stack sigue sin contenedores.
Siguiente acción única del operador: provisionar el env efectivo aprobado en
`/etc/agente-bolsa/application.env` con permisos `600` por el canal seguro
existente. No pegar credenciales en el chat. Hasta confirmarlo, no detener
Windows/Raspberry, no crear snapshot y no ejecutar `docker compose up`.

La auditoría posterior clasificó el `application.env.example` como plantilla
no productiva: contiene placeholders de `OPENCODE_API_KEY` e
`IMPROVEMENT_LLM_API_KEY`, fija `AUTO_PAPER_TRADING=false` y
`REQUIRE_HUMAN_APPROVAL=true`, y no incluye todas las claves efectivas de
Windows. La comparación redacted de Windows confirmó `TRADING_MODE=paper`,
`BROKER=alpaca`, `ALPACA_PAPER=true`, `AUTO_PAPER_TRADING=true`,
`REQUIRE_HUMAN_APPROVAL=false`, `ALLOW_LIVE_TRADING=false` y
`ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, además de sus parámetros efectivos de
LLM y mejora continua, sin imprimir valores secretos.

La identidad final remota queda reconciliada: imagen
`agente-bolsa@sha256:42a7b88d7f4f31c9c434795b8b6eea09ceeed1d27458622db96a71a384303a42`,
`linux/arm64`, revision `d4dcb075db8f8a5285a1f2e35cfe23fb64c55df9`.
Compose redacted: proyecto/red `agente-bolsa`/`agente-bolsa-net`, servicios
`init-db`, `scheduler`, `auxiliary`, `web`, datos
`/var/lib/agente-bolsa:/data` y panel `0.0.0.0:8081 -> 8501`; ningún contenedor
está iniciado.

Bloqueo vigente: falta transferir el `.env` efectivo por un mecanismo seguro y
aprobado. No sintetizarlo desde el example ni copiarlo automáticamente. El
único paso pendiente del operador es autorizar/ejecutar esa transferencia sin
mostrar secretos; después se validará de nuevo en redacted y se continuará con
snapshot frío y corte controlado.
Bloqueo operativo actualizado: `sudo -n true` devuelve `no` y
`/etc/agente-bolsa/application.env` sigue ausente. No se transfirió el secreto
ni se dejó staging temporal. Ejecutar desde PowerShell el bloque siguiente;
la sesión SSH pedirá la contraseña de sudo directamente al operador, nunca a
Codex ni al chat:

```powershell
$JetsonKey="$env:USERPROFILE\.ssh\codex_jetson_ed25519"
$Stage="/tmp/agente-bolsa.application.env.$PID"
$Target="antonio@192.168.1.186"
$Copied=$false
try {
    scp -i $JetsonKey -o IdentitiesOnly=yes "C:\Antonio\Bref\agenteBolsa\.env" "${Target}:$Stage"
    if ($LASTEXITCODE -ne 0) { throw "scp falló; no continuar" }
    $Copied=$true
    $Remote="sudo install -o root -g root -m 600 $Stage /etc/agente-bolsa/application.env; rc=`$?; rm -f $Stage; exit `$rc"
    ssh -tt -i $JetsonKey -o IdentitiesOnly=yes $Target $Remote
    if ($LASTEXITCODE -ne 0) { throw "instalación remota falló" }
} finally {
    if ($Copied) { ssh -i $JetsonKey -o IdentitiesOnly=yes $Target "rm -f $Stage" 2>$null | Out-Null }
}
```

Después de ese único paso, no arrancar manualmente nada: devolver el control a
Codex para validar hash redacted, flags PAPER y Compose antes del snapshot.
Snapshot/corte 2026-08-14: Windows se detuvo con `stack_down.ps1
-IncludeScheduled`; scheduler/web quedaron parados y no se borró el lock
huérfano. Receipt local:
`C:\Antonio\Bref\agenteBolsa_backups\jetson-cutover-20260814-1457\receipt.json`.
SQLite/WAL/SHM pasaron `quick_check` e `integrity_check`; hashes SQLite/WAL/SHM
`b3345059...2857` / `8dc6275d...41ae9` / `94eef1e3...be0e`. La misma terna y
receipt fueron copiadas al volumen Jetson y revalidadas remotamente con los
mismos hashes e integridad correcta.

No iniciar manualmente el stack todavía: el env es `root:root 600` y el
Compose necesita `sudo` interactivo. Ejecutar en el Jetson este único comando;
pedirá la contraseña solo en la terminal local y no imprime secretos:

```bash
cd /opt/agente-bolsa/releases/0.4.242 && sudo sh -c 'docker compose --env-file /etc/agente-bolsa/application.env -f deploy/docker-compose.yml -f deploy/docker-compose.raspberry.override.yml config --quiet && docker compose --env-file /etc/agente-bolsa/application.env -f deploy/docker-compose.yml -f deploy/docker-compose.raspberry.override.yml up -d'
```

Después devolver el control a Codex sin ejecutar `run-once`, `job-once`,
`decide-once`, `down` global ni tocar whale-copy. Windows permanece detenido
para impedir dos schedulers.

El intento falló antes de `up`: se usó incorrectamente el env de servicio como
`--env-file` de Compose y se resolvió la ruta por defecto inexistente
`deploy/deploy/application.env.example`. `docker ps` sigue vacío y el env
continúa `root:root 600`. Reintentar solo con `deploy/deploy.env.example` como
archivo de interpolación; este referencia el env real protegido.
Diagnóstico del fallo `init-db`: el contenedor recibió `DATA_DIR=data` y el
entrypoint intentó crear `data` bajo un root filesystem `read_only`; el bind
`/data` no era el problema. Corrección mínima ya transferida y con hash
coincidente: `DATA_DIR: /data` explícito en los cuatro servicios del override,
commit `1d09ce13` / tree `414e4999`, override SHA-256
`08ee9b4957c7307bbdc9316a919c211809a730bfc7c299db5fa7ba70bc588a93`. La
imagen `sha256:42a7b88d...` y la SQLite no cambiaron.

El primer intento dejó `init-db` en exit 1 y los demás contenedores en Created;
no hay servicios activos. Ejecutar en Jetson, con sudo interactivo, el mismo
Compose usando el override corregido:

```bash
cd /opt/agente-bolsa/releases/0.4.242 && sudo sh -c 'docker compose --env-file deploy/deploy.env.example -f deploy/docker-compose.yml -f deploy/docker-compose.raspberry.override.yml config --quiet && docker compose --env-file deploy/deploy.env.example -f deploy/docker-compose.yml -f deploy/docker-compose.raspberry.override.yml up -d'
```

No ejecutar `down` global ni borrar volúmenes; después devolver el control para
inspección de `init-db`, scheduler, web y auxiliary.
Hallazgo posterior al primer arranque: la ruta de datos efectiva es
`/var/lib/agente-bolsa/state/agente_bolsa.sqlite3`, no la raíz del bind. El
primer `init-db` creó una SQLite nueva de 581632 bytes; no era la histórica.
Los cuatro contenedores se detuvieron selectivamente. La copia generada y sus
sidecars se conservaron en
`/var/lib/agente-bolsa/misconfigured-initdb-20260814-1531/`; no se borró nada.
La snapshot original se restauró en `state/` y mantiene los hashes del
receipt, con `quick_check` e `integrity_check` correctos.

Ejecutar de nuevo el comando Compose corregido del lote. El gate posterior
obligatorio es confirmar que `state/agente_bolsa.sqlite3` mide 1803337728 bytes
y conserva el hash `b3345059...02857`, antes de declarar desplegado.

### Relevo final Jetson 2026-08-14

Dictamen actual: `partially_verified_kernel_unsealed`. El Compose corregido ya
está arriba en `192.168.1.186`; no declarar `deployed` todavía.

Hechos verificados:

- `agente-bolsa:0.4.242-arm64`, digest
  `sha256:42a7b88d7f4f31c9c434795b8b6eea09ceeed1d27458622db96a71a384303a42`,
  commit de imagen `d4dcb075`, tree funcional `5d311cc`;
- override Compose operativo en commit `1d09ce13`, tree `414e4999`, con
  `DATA_DIR=/data` explícito en los cuatro servicios;
- env root-only instalado y verificado redacted, SHA-256
  `8e9bef2d8130071d9f9cb4796365ad32d97a3176be540867c2c5531679ed0171`, con
  PAPER activo y live/auto-apply desactivados;
- `init-db` terminó `0`; scheduler, auxiliary y web `healthy`,
  `RestartCount=0`, `OOMKilled=false`; scheduler único y sonda ligera verde;
- raíz, `/health`, `/_stcore/health` y `/kindle` devuelven `200` local y por
  LAN `192.168.1.186:8081`; listener único en `0.0.0.0:8081`;
- snapshot fría y sidecars validados, SQLite efectiva íntegra, sin backfill,
  VACUUM, checkpoint ni reparación; Windows sigue detenido como rollback;
- Raspberry y `whale-copy` permanecen intactos.

Bloqueo restante: `docker exec agente-bolsa-scheduler-1 python -m
agente_bolsa.main kernel-status --json` devuelve `unsealed`, sin violaciones,
porque falta `state/kernel_manifest.json` en Jetson. Los hashes efectivos de
`kernel.py`, `broker.py` y `execution.py` coinciden con Windows, cuyo estado es
`ok`; el manifiesto Windows validado tiene SHA-256
`0542cc1028a216bca711dfb6921878888fb9bcfd04d5e26e3672a86eb87e8ce3`.
No ejecutar `kernel-seal` ni copiarlo sin decisión/autoridad explícita. La
instancia PAPER está viva y sana operacionalmente, pero el cierre formal queda
pendiente de resolver este gate.

### Bloqueo confirmado del manifiesto

El procedimiento canónico (`kernel-seal`) calcula también el hash de `.env`.
En Jetson la configuración efectiva está en `/etc/agente-bolsa/application.env`
con `root:root 600`, mientras que los contenedores no root solo reciben sus
variables mediante `env_file`; `/app/.env` no existe. Montar el fichero como
`/app/.env:ro` no es solución con estos permisos porque el proceso no podría
leerlo. No cambiar permisos, usuario del contenedor, código protegido ni
copiar secretos.

Se preparó y revirtió un ensayo local de Compose; no se transfirió ni se
reinició Jetson. El candidato vuelve a tree `414e4999` con HEAD de revert
`714e5942`. El runtime remoto sigue siendo el previamente validado, con
`kernel-status=unsealed` y sin violaciones. Dictamen de cierre:
`authority_required / precondition_not_met`. Resolver exige una decisión humana
sobre una integración protegida para que el kernel verifique el env efectivo, o
aceptar formalmente `unsealed`; hasta entonces no liberar `whale-copy`.

### Relevo P-L90R10B antes del corte Jetson

La candidata `0.4.243` está implementada y construida en ARM64. Código de
imagen: commit `bf3306bf`, tree `42fa1270`; imagen/index digest
`sha256:8d36f420b668f6b1be6826d81296b846cf03d2b46e098ad7ada6a78cfcf21fbe`.
El Compose usa el secret efímero Docker derivado de
`/etc/agente-bolsa/application.env` y expone al proceso no root la ruta
`/run/secrets/application.env` mediante `AGENTE_BOLSA_KERNEL_ENV_PATH`.
No se cambia el modo `root:root 600` ni se persiste una copia del secreto.

Focales `70 passed`, Ruff/NUL/diff verdes. La suite completa se intentó una
única vez y terminó por timeout a los 604 s sin resultado; el proceso hijo fue
detenido selectivamente. No repetirla por inercia. El runtime Jetson sigue en
`0.4.242`, sano y sin reinicio; Windows continúa detenido como rollback.

Staging remoto pendiente de aplicar:

- `/tmp/agente-bolsa-v0.4.243-override.yml`, SHA-256
  `feded9b7fad919873752811685464bf5ab1f2083466d70e546a6570275c9004f`;
- `/tmp/agente-bolsa-v0.4.243-deploy.env`, SHA-256
  `3b4ae56c82da9ae6229c31fb968122326f31a2a6f1075cd1742a8b3732450ef3`.

El operador debe ejecutar con `sudo` interactivo el bloque de instalación,
`config`, recreación exclusiva del Compose agenteBolsa y después devolver la
salida. Hasta validar secret accesible, `kernel-seal`, `kernel-status=ok` y dos
healthchecks nuevos, el dictamen no es `deployed` y no se libera whale-copy.

Comando único pendiente, con contraseña solo cuando `sudo` la solicite:

```powershell
$JetsonKey="$env:USERPROFILE\.ssh\codex_jetson_ed25519"
ssh -t -i $JetsonKey -o IdentitiesOnly=yes antonio@192.168.1.186 `
  "mkdir -p /opt/agente-bolsa/releases/0.4.243; cp -a /tmp/agente-bolsa-v0.4.243-bf3306bf/source/. /opt/agente-bolsa/releases/0.4.243/; cp /tmp/agente-bolsa-v0.4.243-override.yml /opt/agente-bolsa/releases/0.4.243/deploy/docker-compose.raspberry.override.yml; cp /tmp/agente-bolsa-v0.4.243-deploy.env /opt/agente-bolsa/releases/0.4.243/deploy/deploy.env.example; sudo sh -c 'cd /opt/agente-bolsa/releases/0.4.243 && docker compose --env-file deploy/deploy.env.example -f deploy/docker-compose.yml -f deploy/docker-compose.raspberry.override.yml config --quiet && docker compose --env-file deploy/deploy.env.example -f deploy/docker-compose.yml -f deploy/docker-compose.raspberry.override.yml up -d --force-recreate'"
```

El comando no usa `docker compose down` global, no toca `whale-copy` y solo
recrea el namespace `agente-bolsa`.

### Relevo actual P-L90R10B/C — 2026-08-14 21:26 Europe/Madrid

Dictamen: `precondition_not_met / rollback_required`. El runtime Jetson
`0.4.243` no es aceptable: web y auxiliary están healthy e init-db=0, pero el
scheduler reinicia con `exit=0`, `RestartCount=15`, `OOMKilled=false`. La
causa demostrada es `state/scheduler.lock` legado (`pid=7`, token nulo,
creado 18:13:54Z) cuyo PID fue reutilizado tras el contenedor iniciado
19:12:58Z. No apartar ese lock hasta XNYS cerrado y sin escritor activo; hacerlo
solo con esta evidencia de stale/PID reuse, nunca a ciegas.

La prueba de permisos también es concluyente: el secret bind desde
`/etc/agente-bolsa/application.env` (`root:root 600`) no es legible por
`uid=1000(app)`. La candidata `0.4.244` añade el carrier no secreto
`AGENTE_BOLSA_KERNEL_ENV_SHA256` y conserva `kernel-seal` estricto sobre el
fichero real. No cambiar permisos, no usar root como servicio y no persistir
copias del secreto.

Artefacto listo pero aún no desplegado:

- commit `84b85501b67b750a28e1cbb75775322852a99bc7`, tree
  `f66f4cc10a1e3e4d2645e58e753f7a53a2881523`, v0.4.244;
- imagen ARM64 manifest/index
  `sha256:22afb9c8846e3b9dbb1417fef51ffa33da20d4b0dd4c02ace1acc7844edcc021`,
  config `sha256:06c37a2059f4f7c7eba31f708899e8f40c29e5f228b4072d4f0524bab627c`;
- bundle SHA-256
  `aaf8ab067af082b08d7f723cde5472074fafefb5c564a4dd9a6e40ce54ec19f1`;
- focales/regresiones `72 passed`, Ruff/NUL/diff verdes;
- release staging `/opt/agente-bolsa/releases/0.4.244`, sin recreación aún.

XNYS sigue abierto hasta las 22:00. No se hizo snapshot fría nueva ni corte;
la snapshot anterior se conserva, pero no se presenta como fotografía final.
Windows está detenido como fallback; Raspberry, `whale-copy` y ngrok no se han
modificado. No liberar `whale-copy`.

Siguiente secuencia única tras cierre: comprobar postmarket/leases/jobs
terminales y recursos; detener canónicamente solo escritores agenteBolsa;
crear snapshot fría SQLite/WAL/SHM con receipt e integridad; apartar el lock
stale demostrado; validar `compose config` como root sin revelar el env;
recrear solo el proyecto agenteBolsa con 0.4.244; ejecutar `kernel-seal` una
vez como root dentro del scheduler; comprobar `kernel-status=ok`, PAPER,
listener/scheduler únicos, lock/heartbeat, HTTP local/LAN y dos healthchecks
separados >=75 s. Ante cualquier fallo: detener solo agenteBolsa Jetson y
conservar Windows para rollback auditable.

### Cierre P-L90R10C - Jetson 2026-08-14 21:48 Europe/Madrid

Dictamen final: `deployed`. AgenteBolsa queda como unica instancia activa en
Jetson `192.168.1.186`, v0.4.244 ARM64, commit
`84b85501b67b750a28e1cbb75775322852a99bc7`, tree
`f66f4cc10a1e3e4d2645e58e753f7a53a2881523`, manifest/index
`sha256:22afb9c8846e3b9dbb1417fef51ffa33da20d4b0dd4c02ace1acc7844edcc021`.
Windows permanece detenido como fallback; Raspberry, whale-copy y ngrok no se
han modificado.

Kernel sellado y verificado: `kernel-status --json=ok`, sin violaciones,
carrier `/run/secrets/application.env`, env externo `root:root 600`, hash
redacted conservado. Dos lecturas separadas (19:44:40Z y 19:48:35Z) dejaron
web, auxiliary y scheduler healthy, `RestartCount=0`, `OOMKilled=false`,
`init-db=0`, sonda de scheduler retorno 0 y flags PAPER/live/auto-apply
correctos. `/`, `/health`, `/_stcore/health` y `/kindle` respondieron 200 por
LAN en `192.168.1.186:8081`; `/health` es el shell HTML y `/_stcore/health` la
sonda real de Streamlit.

Snapshot frio validado: receipt v2 en
`/home/antonio/agente-bolsa-backups/p-l90r10c-20260814T2126Z/receipt.json`,
quick/integrity correctos, journal WAL y SHA-256
`b47857b7048d87b7b1448c651dd83b9c0867e5168fa6d9a0e9e012552aaf18fb`.
No hubo `database locked`, OOM/exit137 ni ordenes inesperadas observadas; no
se ejecutaron trabajos manuales. La suite completa previa agoto 604 s y no se
repitio; la limitacion queda registrada en el informe.

Handoff: el lote de whale-copy puede liberarse ahora como tarea independiente,
pero debe hacer su propio inventario, Compose/namespace/puertos, preflight,
healthchecks y rollback. No reutilizar este informe como prueba de salud de
whale-copy ni ejecutar un `docker compose down` global.

### Relevo P-L90R10D - preflight Jetson 2026-08-14 22:59 Europe/Madrid

XNYS cerrado. Candidata 0.4.245: commit `1e400e9a`, tree `474eb223`, imagen
ARM64 `sha256:7a2266d86b5726bbb5cec4b9c1c139eafa553cf87d8bdcd4da851eeafd1763c2`.
Fix Linux de lock/PID reutilizado probado dentro de la imagen; `18 passed`,
Ruff/NUL/diff verdes. Snapshot fria v2 integra en
`/home/antonio/agente-bolsa-backups/p-l90r10d-20260814T203544Z/receipt.json`,
hash `98d1ae5c1397d4870966f6c438fbfeedfe598e916ecc8fbcc0955913ddfdadf6`.

Jetson sano en almacenamiento, Docker, Compose, memoria disponible e I/O;
los contenedores antiguos estan detenidos y Windows continua como rollback.
El corte esta bloqueado unicamente porque Compose no puede leer el env
`root:root 600` sin sudo interactivo (`sudo -n` no disponible). No modificar
permisos, locks, SQLite ni otros proyectos. Siguiente paso: ejecutar el bloque
sudo exacto, y despues comprobar kernel, PAPER, scheduler estable y dos
healthchecks separados >=75 s.

### Cierre P-L90R10D - Fase 2 Jetson 2026-08-14 23:12 Europe/Madrid

Dictamen: `deployed`. v0.4.245 ARM64 esta estable en Jetson como unica
instancia agenteBolsa. Commit `1e400e9a`, tree `474eb223`, imagen
`sha256:7a2266d86b5726bbb5cec4b9c1c139eafa553cf87d8bdcd4da851eeafd1763c2`.
Arranque `21:01:38Z`; cierre de observacion `21:12:11Z`.

Scheduler, auxiliary y web healthy, restart 0, sin OOM, init-db 0, probe de
scheduler 0 y lock PID/token coherente. Kernel `ok`, carrier externo correcto,
env root:600 y flags PAPER verificados. Dos lecturas separadas mas de 75 s y
observacion de mas de 10 minutos sin database locked ni errores OOM/137.
Raiz, `/health`, `/_stcore/health` y `/kindle` devolvieron 200 localmente y
por LAN en `192.168.1.186:8081`.

Snapshot rollback v2: receipt
`/home/antonio/agente-bolsa-backups/p-l90r10d-20260814T203544Z/receipt.json`,
hash `98d1ae5c1397d4870966f6c438fbfeedfe598e916ecc8fbcc0955913ddfdadf6`,
quick/integrity OK. No se tocaron Windows, Raspberry, whale-copy ni ngrok.

Handoff: ventana Docker liberada para el lote independiente de whale-copy. Ese
lote debe hacer su propio preflight y no usar `docker compose down` global.

### Relevo P-L90R10E - corte Windows pendiente de elevacion 2026-08-15 02:08 Europe/Madrid

Dictamen actual: `precondition_not_met`. XNYS esta cerrado y el Jetson
`192.168.1.186` permanece sano con agenteBolsa v0.4.245 y whale-copy healthy,
pero la sesion Windows actual no esta elevada. No se ha ejecutado la parada
canonica ni se han deshabilitado tareas. El checkout sigue en HEAD
`3ebff4e298d67472a9c26380dc407f9f5210639b`, tree
`d4071dcb23b6560711eadec069e7a5796adc8f11`, conservando cambios documentales y
`.playwright-cli/` preexistentes.

Read-only Windows: Scheduler/Web estan parados, sin listeners del proyecto ni
procesos persistentes agenteBolsa/whale-copy. El scheduler lock PID `13140` es
un huerfano de propietario muerto y no se ha limpiado. `AgenteBolsaScheduler`,
`AgenteBolsaWeb` y `AgenteBolsaDBMaintenance` figuran `Ready` y habilitadas;
DBMaintenance ejecuta `-Mode apply` y tiene proxima ejecucion el 2026-08-16 a
las 03:00, por lo que bloquea la ventana de rollback hasta deshabilitarse. La
lectura SQLite no muestra jobs/runtime activos; el laboratorio esta `IDLE` y el
ultimo lease postmarket observado esta liberado. No existe escritor Windows de
whale-copy.

Receipt local validada:
`C:\Antonio\Bref\agenteBolsa_backups\jetson-cutover-20260814-1457\receipt.json`,
`status=ok`, quick/integrity OK, hash
`b33450595512f9d697d3bd4a1767a9586abdec142b22274cb76673e7f7002857`.
Receipt remota de rollback: `/home/antonio/agente-bolsa-backups/p-l90r10d-20260814T203544Z/receipt.json`,
hash `98d1ae5c1397d4870966f6c438fbfeedfe598e916ecc8fbcc0955913ddfdadf6`.

Siguiente paso unico: el operador debe abrir PowerShell como administrador y
ejecutar el bloque documentado en el informe P-L90R10E: `stack_status.ps1`,
`stack_down.ps1 -IncludeScheduled` y `Disable-ScheduledTask` para Scheduler,
Web y DBMaintenance. Despues, la tarea principal verificara exclusividad
Windows y dejara el host conservado siete dias como rollback. No tocar Jetson,
Raspberry, whale-copy, ngrok, SQLite ni locks mientras la elevacion no este
resuelta.

### Cierre P-L90R10E - Windows detenido 2026-08-15 08:33 Europe/Madrid

Dictamen: `deployed_windows_stopped`. Tras la elevacion correcta, las tareas
`AgenteBolsaScheduler`, `AgenteBolsaWeb` y `AgenteBolsaDBMaintenance` quedaron
`Disabled`/`Enabled=False`. `stack_status.ps1` confirma Scheduler/Web parados;
no hay procesos Python persistentes ni listeners Windows del proyecto. El
laboratorio esta `IDLE` y el ultimo lease observado esta liberado. El lock
huerfano PID `13140` permanece intacto y documentado, sin limpieza manual.

Jetson `192.168.1.186` no se toco: systemd activo, cuatro contenedores healthy,
restart 0, OOM false y `/`, `/health`, `/_stcore/health`, `/kindle` con HTTP 200
local/LAN. Windows queda preservado siete dias como rollback. No se modificaron
Raspberry, whale-copy, ngrok, SQLite, configuracion ni credenciales; no hubo
push. Las receipts local/remota y sus hashes estan en el informe P-L90R10E.

Siguiente control: durante siete dias observar exclusivamente Jetson y mantener
Windows sin autoarranque. Para rollback, habilitar las tareas y usar los
helpers canonicos solo con un lote operativo autorizado y preflight completo.

### Relevo P-L90R10F - ngrok pendiente de instalación 2026-08-15 09:02 Europe/Madrid

#### Cierre P-L90R10F - ngrok desplegado 2026-08-15 09:16 Europe/Madrid

Dictamen final: `deployed_ngrok`. Un unico agente ngrok esta `enabled/active`
con dos endpoints HTTPS y un solo proceso:

- agenteBolsa: `https://fbd3-2a0c-5a84-780b-aa00-9951-66f7-f23f-b066.ngrok-free.app`
  -> `127.0.0.1:8081`
- whale-copy: `https://43dc-2a0c-5a84-780b-aa00-9951-66f7-f23f-b066.ngrok-free.app`
  -> `127.0.0.1:8082`

Desde Windows, ambas URLs respondieron 200 en sus sondas externas. AgenteBolsa
respondio 200 en `/`, `/health`, `/_stcore/health` y `/kindle`; whale-copy en
`/`, `/ready` y `/health`. El interstitial HTML del plan Free se salto solo con
el header documentado de prueba; no se inventaron credenciales.

Configuracion/token: `/etc/ngrok/ngrok-auth.yml` y
`/etc/ngrok/ngrok-endpoints.yml`, `root:root 600`; copia de usuario y staging
temporales eliminados. El listener de inspeccion queda en `127.0.0.1:4040`;
no se abrio firewall ni puertos entrantes. Los cuatro contenedores permanecen
healthy, restart 0, OOM false y PAPER/live/auto-apply invariantes.

El wrapper `jetson-ops` es valido y su rama `logs` esta completa. Su alias
historico consulta `ngrok.service`, que sigue `not-found`; la unidad real
aislada y habilitada es `ngrok-agente-bolsa-whale.service`. Rollback:
`sudo systemctl disable --now ngrok-agente-bolsa-whale.service`; reactivacion:
`sudo systemctl enable --now ngrok-agente-bolsa-whale.service`.

Dictamen historico del preflight inicial: `needs_authority`. AgenteBolsa y whale-copy estan sanos en Jetson
`192.168.1.186`; destinos confirmados: `127.0.0.1:8081` y
`127.0.0.1:8082`. HTTP local de ambos devuelve 200 y los cuatro contenedores
permanecen healthy, restart 0, OOM false. Ngrok no esta instalado ni activo,
por lo que no se ha modificado ningun servicio ni se ha expuesto ningun puerto.

La documentación oficial actual permite hasta tres endpoints online en Free,
un dominio dev y recomienda un solo agente con varios endpoints mediante
`endpoints` y `ngrok start --all`; el plan Free añade un interstitial al tráfico
HTML. Dos túneles HTTP caben en ese límite, sujeto a la cuenta real una vez
autenticada.

Ejecutar en una terminal del Jetson como `antonio` con sudo interactivo; no
introducir el token en chat:

```bash
set -eu
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
curl -fL --proto '=https' --tlsv1.2 \
  -o "$tmpdir/ngrok.tgz" \
  https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
tar -xzf "$tmpdir/ngrok.tgz" -C "$tmpdir"
sudo install -o root -g root -m 0755 "$tmpdir/ngrok" /usr/local/bin/ngrok
ngrok version
```

Despues de la instalación, se provisionara el authtoken por el canal seguro
aprobado y se creara la configuración root:root 600 y una unica unidad ngrok;
no se iniciara nada antes de verificar la configuración redacted.

### Relevo P-L95 — auditoría de observación 2026-08-26/27

Dictamen: `needs_observational_fix`. La corrección aislada del funnel está en
`C:\Antonio\Bref\agenteBolsa_worktrees\pl95_funnel_attachment_fix_final`,
candidato `0.4.255`, worktree final limpio, HEAD
`fe4fae3a7e3ba6c1920d0fdcc0b472905558ebfa`, tree
`d68cbce83f680b046f9ba5ee393239eda41f94a3`, sin diff en objetos protegidos.
El árbol funcional validado es `2f84b805...`. Suite completa única:
`2570 passed, 1 skipped, 1 warning`; el último commit fue solo documental y
no requiere repetir suite.

Producción Jetson no cambió: `0.4.254-arm64`, scheduler/web/aux healthy,
`RestartCount=0`, `OOMKilled=false`, PAPER activo, live/auto-apply false,
kernel válido. El último fallo productivo del funnel sigue siendo
`KeyError('recommendation_attachment_unavailable')`. EOD y SPY permanecen
`unavailable` por carriers/timestamps incompletos; el scheduler mantiene
misfires de `1`–`13` segundos; `whale-copy-jetson` está `unhealthy` y queda
fuera de este lote. El perfil read-only detecta además `1713/2291` outcomes
recientes (`74.8%`) vacíos y `63` órdenes `filled` antiguas sin fila enlazable
en `order_plans`; el linaje no es suficiente para sizing.

Siguiente acción, solo en ventana cerrada y con autorización operativa: validar
preflight, integrar P-L95 con `merge --no-ff`, desplegar, comprobar desaparición
del error y realizar dos healthchecks separados. Después tratar EOD, SPY y
misfires en lotes independientes. Sizing sigue bloqueado; no hacer backfill,
reconciliación manual ni cambios de política.
### P-L124 — bucle de mejora continua desplegado pendiente arranque (17-sep-2026)

- Merge `83e366d9`, v0.4.230. Suite 2531 passed con 2 preexistentes
  clasificados. Kernel con violacion preexistente solo en `.env`.
- Tareas `AgenteBolsaScheduler`/`AgenteBolsaWeb` deshabilitadas antes del
  despliegue; `stack_up.ps1` exige PowerShell elevado para habilitarlas.
- Siguiente unico paso: en sesion elevada ejecutar `stack_up.ps1`, doble
  salud separada 75 s, y cerrar `informe_p_l124` a `deployed` verificado.
  No hacer merge, push ni re-sellar kernel sin confirmacion.

### P-L130 — funnel dataclass + attachment fail-open (candidato 0.4.234, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto (sesion 2026-09-17, cierre
  22:00 Europe/Madrid); sin merge, despliegue, push ni escritura productiva.
- Worktree `pl130_funnel_dataclass_fix`, rama
  `codex/pl130-funnel-dataclass-fix`, base `c40ac2fd`, version `0.4.234`.
  Commits: `fb11b7bb` (tests, rojo 5/5 confirmado), `e96f263a` (fix
  ledger + bump + pin), `5ddcb923` (fix contadores funnel + 2 tests).
- Port byte-identico (`diff-count=0`) de `6d6a8e67` y `927e830e`
  (rama `codex/pl95-funnel-attachment-fix`, nunca integrada): 1 linea
  `_mapping()` en `_build_decision_row` + contadores `.get(key, 0) + 1`.
  Cierra el `KeyError` de P-L95 en la linea Windows.
- QA aislada: focales 60 passed, regresiones 80-91 passed, Ruff/NUL/diff
  verdes, `validate-agent-config ok=true`, smoke temporal exit=0. Suite
  completa pendiente de ventana cerrada.
- Informe: `docs/informe_p_l130_funnel_dataclass.md`; plan maestro con
  fila P-L130.
- Siguiente: revision operador → `merge --no-ff` a `codex/astra` en
  ventana cerrada → suite completa → port Jetson `0.4.305+arm64`.

### P-L131 — coste calibrado en scoreboard (candidato 0.4.235, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl131_calibrated_costs`, rama
  `codex/pl131-calibrated-costs`, base `e24f34e1`, version `0.4.235`.
  Commits: `461ee0dd` (tests, rojo 4/4), `35958530` (feat + bump + pins).
- Solo observacional: mediana `signal_to_fill_bps`, umbral 10, corte
  200; bandas 10/20 y criterio intactos; schema 2→3 aditivo.
- QA: focales 9, regresiones 19-55, Ruff/NUL/diff/config verdes. Suite
  pendiente de ventana cerrada.
- Informe: `docs/informe_p_l131_costes_calibrados.md`.
- Siguiente: merge conjunto P-L130+P-L131 → suite → port Jetson.

### P-L132 — cobertura same-cycle por semana (candidato 0.4.236, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl132_same_cycle_controls`, rama
  `codex/pl132-same-cycle-controls`, base `5f7035e6`, version `0.4.236`.
  Commits: `2e148fa2` (tests, rojo 3/3), `81bae8ff` (feat + bump + pin).
- Solo observacional: `matched/unmatched_executed` por semana,
  `control_cost_basis` explicito; matcher sin cambios (control
  compartido declarado como limite).
- QA: focales 12, regresiones 68, Ruff/NUL/diff/config verdes. Suite
  pendiente de ventana cerrada.
- Informe: `docs/informe_p_l132_controles_same_cycle.md`.
- Siguiente: merge conjunto P-L130+P-L131+P-L132 → suite → port Jetson.

### P-L133 — delays de misfire y vaciedad en health (candidato 0.4.237, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl133_misfire_health`, rama
  `codex/pl133-misfire-health`, base `d44beb52`, version `0.4.237`.
  Commits: `c46254c4` (tests), `30def441` (feat + bump + pin).
- Solo observacional: `delay_seconds` aditivo, resumen por job,
  `% vacios` en health, fail-open, sin alertas nuevas. Linkage → R2b.
- QA: focales 7, regresiones 69, Ruff/NUL/diff/config verdes. Suite
  pendiente de ventana cerrada.
- Informe: `docs/informe_p_l133_misfire_health.md`.
- Siguiente: merge conjunto P-L130→P-L133 → suite → port Jetson.

### P-L134 — reporte de uplift LLM (candidato 0.4.238, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl134_llm_uplift`, rama `codex/pl134-llm-uplift`, base
  `06b8e6d1`, version `0.4.238`. Commits: `d69b0bf5` (modulo + 4
  tests), `5db22b69` (bump + pin).
- Solo lectura: brazos por flag causal, pre-registro 30/10/0.70,
  veredicto sin promotion. Anti-proxy probado.
- QA: focales 4, regresiones 55, Ruff/NUL/diff/config verdes. Suite
  pendiente de ventana cerrada.
- Informe: `docs/informe_p_l134_uplift_llm.md`.
- Siguiente: merge conjunto P-L130→P-L134 → suite → port Jetson.

### P-L135 — linkage orden-plan (candidato 0.4.239, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl135_order_linkage`, rama `codex/pl135-order-linkage`,
  base `5d7d998f`, version `0.4.239`. Commits: `382e79a7` (tests, rojo
  4/4), `9b2cfcbe` (feat + bump + pin).
- Lector aditivo en `Store` + health fail-open; ruta de submit sin
  cambios (ya plan-first). Sin enlace → `legacy_unverified`.
- QA: focales 4, regresiones 70, Ruff/NUL/diff/config verdes. Suite
  pendiente de ventana cerrada.
- Informe: `docs/informe_p_l135_linkage_ordenes.md`.
- Siguiente: merge conjunto P-L130→P-L135 → suite → medir cobertura
  real → port Jetson.

### P-L136 — ledger de flujos de caja (candidato 0.4.240, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl136_cash_flows`, rama `codex/pl136-cash-flows`, base
  `ca876b97`, version `0.4.240`. Commits: `b7cefc8b` (tests),
  `cc289559` (feat + bump + pin).
- Productor EOD compatible probado; cableado PMR diferido con paridad.
- QA: focales 5, regresiones 83, Ruff/NUL/diff/config verdes. Suite
  pendiente de ventana cerrada.
- Informe: `docs/informe_p_l136_flujos_caja.md`.
- Siguiente: merge conjunto P-L130→P-L136 → suite → cableado PMR →
  port Jetson.

### P-L137 — sellos de sesion en maduracion (candidato 0.4.241, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS abierto; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl137_session_seals`, rama `codex/pl137-session-seals`,
  base `c785b0b1`, version `0.4.241`. Commits: `7cd1bdd2` (tests),
  `726d223b` (feat + bump + pin).
- Recorte same-day con calendario real, fallback degradado, paridad
  probada con historia cerrada.
- QA: focales 4, regresiones 97, Ruff/NUL/diff/config verdes. Suite
  pendiente de ventana cerrada.
- Informe: `docs/informe_p_l137_sellos_sesion.md`.
- Siguiente: merge conjunto P-L130→P-L137 → suite → port Jetson.

### P-L138 — geometria stop/take (bloqueado, sin codigo, 17-sep-2026)

- `blocked` hasta 2-3 semanas de outcomes maduros con P-L131/P-L132/
  P-L137 en produccion y `sufficient_sample` en uplift. Pre-registro
  §6 + checklist de promocion congelados antes de mirar resultados.
  Sin sizing hasta revision humana.

### P-L140A — franja Mis inversiones (candidato 0.4.242, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl140a_mis_inversiones`, rama
  `codex/pl140a-mis-inversiones`, base `a6655e10`, version `0.4.242`.
  Commits: `587f711e` (tests), `e7244de2` (feat + bump + pin).
- Solo `web_app.py`: helper puro + franja de 4 tarjetas, misma fuente
  ya cargada. Sin broker nuevo, sin escrituras, sin trading.
- QA: focales 7 (render headless incluido), regresiones 128,
  Ruff/NUL/diff/config verdes. Suite pendiente de integracion.
- Informe: `docs/informe_p_l140a_mis_inversiones.md`.
- Siguiente: P-L140B sobre esta rama → merge P-L130→P-L140 → suite →
  port Jetson.

### P-L140B — SPY unico y leaderboard a Config (candidato 0.4.243, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl140b_spy_leaderboard`, rama
  `codex/pl140b-spy-leaderboard`, base `66103e2f`, version `0.4.243`.
  Commits: `3664038e` (tests), `10dcd62b` (feat + bump + pin).
- Solo `web_app.py`: alpha misma-ventana, leaderboard via
  session_state, baseline muerto fuera (~90 lineas menos).
- QA: focales 5 (+2 renders), regresiones 134, Ruff/NUL/diff/config
  verdes. Suite pendiente de integracion.
- Informe: `docs/informe_p_l140b_spy_unico.md`.
- Siguiente: revision → merge P-L130→P-L140 → suite → verificado
  visual con operador → port Jetson.

### P-L140C — contrato baseline conservado (candidato 0.4.244, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl140c_baseline_contract`, rama
  `codex/pl140c-baseline-contract`, base `b6e1a48c`, version `0.4.244`.
  Commit: `0d53944c` (fix + bump + pin).
- La suite de integracion detecto el import P-L63 roto; helpers puros
  restaurados verbatim, contenedor fuera. Leccion: integrar pronto.
- QA: p63 11, bateria 145, Ruff/NUL/diff/config verdes.
- Informe: `docs/informe_p_l140c_baseline_contract.md`.
- Siguiente: merge a `codex/astra` → suite completa → port Jetson.

### P-L140D — guardia SPY unica (candidato 0.4.244 sin bump, 17-sep-2026)

- Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl140d_spy_contract_guard`, rama
  `codex/pl140d-spy-contract-guard`, base `15a3698d`. Commit:
  `67a0dac4` (test). Solo tests, sin `src`, sin bump.
- QA: p65a 12 passed, Ruff/diff verdes.
- Informe: `docs/informe_p_l140d_spy_guard.md`.
- Siguiente: merge a `codex/astra` → suite completa → port Jetson.

### INTEGRACION P-L130→P-L140D (17/18-sep-2026, XNYS cerrado)

- Dictamen: `integrated_validated_awaiting_jetson_port`. Produccion
  `eb35ff86` (0.4.244), merges `--no-ff` b6e1a48c/15a3698d/089144d2.
- Suite: 2591 passed, 1 skip + 1 fallo preexistentes (p71 en base).
  Ruff/NUL/diff/config/kernel/smoke verdes. Revision PASS previa.
- Jetson DIFERIDO (sin rama local 0.4.304; port P-L141 con validacion;
  postmarket activo; Windows parado como rollback).
- Auditoria Jetson del dia: scheduler vivo pero 22/22 ciclos `missed`
  (grace 1 s), 1 ciclo `failed` (crew→observer), LLM mejora caido
  (400 + fallback), 0 recs/ordenes. P-L139 urgente siguiente.

### P-L139 — grace de misfire (candidato 0.4.245, 18-sep-2026)

- Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl139_scheduler_rescue`, rama
  `codex/pl139-scheduler-rescue`, base `39195b78`, version `0.4.245`.
  Commits: `06b2c557` (tests), `0baf7aa3` (feat + bump + pin).
- Solo `scheduler.py`: grace 300/120/120, coalesce intacto. Causa
  verificada en produccion Jetson (22/22 missed).
- QA: focales 1, regresiones 8/47, Ruff/NUL/diff/config verdes.
- Informe: `docs/informe_p_l139_misfire_grace.md`.
- Siguiente: P-L142 (sesion LLM) → merge → suite → port → corte.

### P-L142 — sesion del proveedor (candidato 0.4.246, 18-sep-2026)

- Dictamen: `ready_for_review`. XNYS cerrado; sin merge, despliegue,
  push ni escritura productiva.
- Worktree `pl142_provider_session`, rama
  `codex/pl142-provider-session`, base `0796d003`, version `0.4.246`.
  Commits: `b82ad1ae` (tests), `6edb351f` (feat + bump + pin + fakes).
- Transporte LLM: sesion estable + UA propio en router y CI, SDK y
  urllib. Contrato de docs oficiales.
- QA: focales 6, regresiones 68+82, Ruff/NUL/diff/config verdes.
- Informe: `docs/informe_p_l142_sesion_proveedor.md`.
- Siguiente: merge P-L139+P-L142 → suite → port Jetson → corte con
  verificacion del 400 en logs.

### P-L141 — port 0.4.305 listo, corte BLOQUEADO (18-sep-2026 ~07:00Z)

- Dictamen: `precondition_not_met`. Imagen verificada en Jetson;
  cero mutaciones en servicios/datos (solo `docker build`).
- Bloqueo: postmarket `failed` (SQLITE_FULL bajo presion de memoria:
  109M libres/sin swap, whale-copy OOM x4, disco OK). No cortar ni
  reparar a ciegas; whale-copy es del operador.
- Informe: `docs/informe_p_l141_port_jetson.md`.
- Siguiente: operador + memoria sana + postmarket terminal →
  preflight/snapshot/corte/doble salud → oleada 2.

## Intento anticipado de validación — 7-oct-2026, 22:37 Madrid

Dictamen: `precondition_not_met`. El operador pidió ejecutar inmediatamente la automatización prevista para las 23:00; se ejecutó su preflight en este chat, sin esperar al horario.

Hechos verificados en producción, solo lectura: XNYS cerrado a las 22:37:01 Madrid, próxima apertura 8-oct15:30; paquete activo0.4.321, paper true, live false. No hay eventos post_market_review_started/completed/failed del7-oct en la consulta acotada. Estado latest postmarket `skipped`, pmr_78fd692e3f98, actualizado21:51:38 Madrid, motivo mercado aún no apto. post_market_review_last_session sigue2026-10-05. La sesión7-oct no cumple terminal completed/failed; un skipped previo al cierre no lo sustituye.

Candidatos: los cuatro worktrees estaban limpios al iniciar este intento, con los HEAD/tree previamente documentados. Se detuvo antes de suites, smoke, integración o versión. Imagen/diferencia.340, kernel, configuración completa, leases y ausencia de procesos de validación no se declaran comprobados en este intento: el preflight terminó por la precondición anterior. El campo auto-apply del sondeo resultó unavailable, no false verificado.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_preflight_live.json; SQLite mediante Store.read_connection, mode=ro/query_only; sin reparaciones ni mutación productiva. No se fuerza postmarket, reconciliación o ciclo; sin órdenes, reinicios, despliegue ni promoción. Sólo se añaden estas notas documentales.

La automatización `validar-mejoras-bolsa-tras-cierre` quedó PAUSED tras este intento, tal como ordena su prompt; no volverá a ejecutarse a las23:00. La revisión del12-oct sigue programada. Siguiente condición: diagnosticar por qué no consta terminal de postmarket y volver a comprobarlo junto a los demás gates; no marcar completada la validación ni los candidatos como desplegados.

## Diagnóstico del retraso postmarket — 7-oct-2026, corte 22:44 Madrid

Dictamen: retraso reproducible en la coordinación del scheduler; validación permanece `precondition_not_met`. Auditoría exclusivamente de lectura. No se declara recuperado ni terminado el postmarket del 7-oct.

Hechos: proceso iniciado a las 22:02:54 Madrid tras arranque del contenedor a las 22:02:27 (causa de ese reinicio unavailable). Estudio cerrado `closed_523dac115aed` empezó 22:04:32 y terminó su ciclo 22:40:16. Mientras seguía activo arrancó `closed_0b9f7358249e` a las 22:17:56. El estudio diario `daily_655975c9bb97` empezó 22:17:58 y terminó 22:42:29; otro, `daily_3df5ffc3734f`, empezó 22:40:17 antes de terminar el anterior. El postmarket programado registró `max_instances` a las 22:32:54 y `missed` a las 22:42:29. No constan started/completed/failed de postmarket en la ventana capturada; la coordinación de hoy conserva skipped/market_not_ready de las 21:51 y last_session sigue 5-oct. El calendario confirma should_run_daily_study=true y mercado cerrado a las 22:44:26, siguiente apertura 8-oct 15:30.

Causa contrastada con fuente .321: run_scheduler_forever arranca el scheduler antes del bootstrap; en cerrado ejecuta sincrónicamente estudio técnico, estudio diario y sólo después postmarket. Los intervalos comparten un pool de dos trabajadores; los tres jobs tienen max_instances=1 y grace de 300 s, pero las llamadas directas del bootstrap quedan fuera de ese contador. Los marcadores de deduplicación de estudio cerrado y diario se escriben al final, permitiendo el solapamiento observado. Los eventos missed demuestran que al menos un intento programado de postmarket perdió su ventana; no prueban que todos los intentos futuros vayan a fallar. La atribución exacta de cada hilo no se ha capturado, por lo que cola ocupada por esos jobs es inferencia fuerte apoyada por código y cronología, no un stack dump.

Factores adicionales: errores LLM 402/Insufficient account funds con activación de fallback; ejecuciones crew de unos 24 minutos en los dos ciclos terminados. SQLite emite database is locked en capturas observacionales, pero esa ruta usa lock_timeout_seconds=0.0 y falla abierta; no acredita una espera de 30 s ni un deadlock. Los eventos posteriores prueban progreso. No se ha demostrado que esos errores sean la causa primaria. Tampoco se atribuyen pérdidas económicas a estos retrasos sin comparación causal.

Siguiente lote único pendiente: caracterizar en aislamiento la carrera bootstrap/intervalo; impedir duplicados por sesión entre ambas entradas y proteger el cierre operativo frente a estudios LLM largos, con límites y degradación explícitos. Exigir pruebas de no duplicación, progreso postmarket y conservación de trading/riesgo/ejecución, manteniendo coordinador y leases. No aumentar trabajadores ni grace a ciegas. Resolver identidad .321/.340 antes de integración. No hay implementación de este lote ni autorización inferida para reiniciar, forzar jobs o desplegar. Automatización de validación sigue PAUSED.

Evidencia local: `C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_postmarket_queue_live.json` (últimas 3000 filas por rowid, ventana 20:34–22:44 Madrid; timestamps originales UTC); `audit_postmarket_stall_live.json`; `audit_postmarket_runtime_logs.txt`. Consultas SQLite con Store.read_connection, mode=ro/query_only. Fuentes: scheduler.py líneas 137–145, 2505–2512, 2741, 2938–2954, 4488, 4528–4562, 4694–4720; tools/h_capture.py línea 669. Sin suites, broker, LLM manual, órdenes ni mutación productiva. Sólo documentación; revisión por Luna de implementación no aplicable: no se asigna validación con precondiciones fallidas.

## Validación de las 23:05 — 7-oct-2026

Dictamen: `precondition_not_met`. Sondeo a las 23:05:22–23:05:24 Madrid: XNYS cerrado, próxima apertura 8-oct 15:30. Producción 0.4.321, paper=true, allow_live_trading=false, allow_auto_apply_improvements=false. Imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, running, arranque 22:52:55, RestartCount=2; causa de reinicios unavailable, sin intervención desde este intento. Lock vivo PID6/token305725. schedule-status no acredita jobs inactivos: runtime unavailable/wal_mode_or_sidecar_present.

Bloqueo confirmado por Store.read_connection mode=ro/query_only: lease post_market_coordination:active, sesión 2026-10-07, run pmr_b2deee2ab986, bootstrap, stage=outcome_update, actualizado 22:54:32. Started a las 22:54:15, sin terminal completed/failed en últimas 3000 filas (ventana 20:36–23:02 Madrid); last_session sigue 5-oct. Otros started a las 22:47:59 y 22:51:22 no prueban procesos simultáneos. Lease persistido activo no demuestra progreso, pero incumple el gate de ausencia de leases.

Cuatro candidatos limpios antes de esta nota, separados sobre 1adc3cec/.321: postmarket HEAD d4956030705933d32c062b347658d9eb4e795d73/tree 1e22c25327414be9e2751508b5b5732bc32374e7; exit-audit HEAD 8bece4d45de1d9f00e463e2b512d8553e407e443/tree 01f7db8cd76d6cd261ac314a6498acb6b4e40fa4; cobertura HEAD 5cdc9d83f7ffd392c6479d518301256a7d2588f9/tree 5559ac5ed76420359d98312c13fc1b7751df884d; observación HEAD 2cd1425fd728105c04a40843518f6937a7dbbb54/tree e638955373e2f052f8b76a4e0b3ff886eae1884c. Sin bump/release. Divergencia histórica .340 no resuelta; checkout C:/Antonio/Bref/agenteBolsa observado ahora b411e9a7445bfa4da6de8329e668d30864090522, paquete .253, cambios ajenos preservados; no representa identidad del Jetson.

Detenido antes de asignar validaciones, suites, smoke, integración o cambios funcionales. Focales anteriores no repetidos ni declarados validación operativa. Kernel/configuración completa, exclusividad de procesos y demás gates no aprobados. Sólo lectura productiva y documentación local, diff --check; sin órdenes, broker/LLM desde tests, protegidos, históricos, locks, producción, reinicios, merge, promoción o despliegue. Automatización validar-mejoras-bolsa-tras-cierre PAUSED tras este intento; estudio del 12-oct sin cambios. Siguiente: terminal de sesión y ausencia de lease/job/retry antes de reprogramar; no forzar cierre ni borrar leases.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_2305_live.json y audit_validation_2305_image.txt; timestamps originales UTC.

## Continuación del diagnóstico — 8-oct-2026, 08:26–08:30 Madrid

Dictamen: `precondition_not_met` para validar; diagnóstico ampliado, sin reparación productiva. XNYS cerrado, próxima apertura hoy 15:30. Runtime 0.4.321, imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, paper=true/live=false/auto-apply=false. Contenedor iniciado 05:29:42 Madrid, RestartCount=4; lock PID6/token2686539 vivo. Causa de reinicios no demostrada.

Hechos nuevos: sesión 7-oct registró failed a las 02:25:59 (`pmr_b2deee2ab986`, LearningObservationBatchError: fallo persistiendo learning_observations en chunk 0: database is locked) y 05:06:25 (`pmr_c8ffd44c108d`, OperationalError: database is locked). El fallo de SQLite ya no es sólo telemetría: figura explícitamente como error terminal. Un nuevo bootstrap `pmr_150611d46dd9` empezó 05:31:43 y conserva lease activo en outcome_update actualizado 05:32:00. last_session sigue 5-oct. Latest event observado 07:56:13; esto no demuestra progreso del postmarket. Aunque existen terminales failed de intentos previos, el lease/reintento posterior activo impide validar.

Recursos: docker stats muestra scheduler 1.998 GiB/2 GiB. Cgroup memory.current=2147278848 y memory.max=2147483648 bytes, max=278082, oom=0, oom_kill=0: presión al límite observada, sin prueba de muertes OOM ni atribución de los cuatro reinicios. Contadores pressure unavailable en este host. Muestreo /proc/locks sólo capturó locks SQLite de lectura; no identifica un escritor culpable ni demuestra deadlock permanente. Un proceso con descriptores de esa SQLite estaba en folio_wait_bit_common; requiere correlación temporal para atribuir la espera a un archivo concreto. BlockIO de docker stats es acumulado, no tasa ni causalidad. Logs muestran persistencia de eventos y runtime también fallando por database is locked y jobs missed/max_instances.

Fuente .321: tools/post_market_review.py:832 solicita update_signal_outcomes con since_date=2026-04-01 y limit=200000. signal_learning.update_signal_outcomes carga señales, descarga barras, conserva outcome_cache y outcomes_to_save; storage.update_signal_outcomes_bulk ejecuta todos los UPDATE recibidos en una única transacción. Es carga potencialmente grande y sin memoria/transacción acotadas; no se ha medido aquí el número exacto de señales ni demostrado que esa función retuviera el lock en el instante auditado. La persistencia de learning_observations ya usa chunks y timeout 30 s, por lo que no basta con repetir la propuesta de dividir esa ruta existente.

Siguiente lote mínimo propuesto, separado del guard de cartera y de la carrera scheduler: caracterizar consumo y atomicidad de update_signal_outcomes; diseñar lectura/procesamiento acotados y transacciones cortas conservando conjunto de señales, IDs, outcomes, temporalidad y aprendizaje. No reducir histórico/limit para aparentar éxito, no cambiar umbrales ni ampliar workers/memoria a ciegas. Antes de implementar, definir explícitamente recuperación y retry ante commits parciales: pasar de transacción global a chunks cambia atomicidad y requiere contrato/revisión, no sólo optimización. Ensayo aislado con fixtures temporales, paridad legacy, fallo entre chunks y retry idempotente; no validación ni promoción con lease activo. No se ha implementado este lote ni asignado trabajo con precondiciones fallidas.

Evidencia local en C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/: audit_validation_oct08_live.json, audit_oct08_scheduler_logs.txt, audit_oct08_host_locks.json, audit_oct08_resources.txt, audit_oct08_cgroup.txt. Sólo SSH/lecturas, Store.read_connection mode=ro/query_only; sin broker/LLM manual, órdenes, limpieza, checkpoint, VACUUM, locks, históricos, configuración, restart, merge o despliegue. Automatización de validación permanece pausada. Este añadido N0 se revisa con diff --check; no se repiten suites. HEAD previo b83010d5dcd5b37cade344638d18af839e4183f2, tree d591de7bc9afe9e87df41603cea74ae07a00bf4d, checkout inicialmente limpio.


## Auditoría 7-oct-2026 — integridad postmarket y salidas (candidatos aislados)

- Usuario autoriza avanzar con mejoras válidas sin comprometer integridad. Producción observada .321; divergencia con recibos .340 pendiente. No desplegado.
- Postmarket: guard de cartera ausente, 24 focales/regresiones verdes; rama codex/oct07-postmarket, informe docs/informe_oct07_postmarket.md en worktree bolsa-oct07-321.
- Salidas: carrier EXIT separado de rechazos BUY y evento fail-open; 38 focales/regresiones verdes; 1 fallo de integración reproducido en base. Rama codex/oct07-exit-audit, informe docs/informe_oct07_exit_audit.md en worktree bolsa-exit-audit-oct07.
- Pendiente antes de release: paridad ciclo/consumidores, gates completos proporcionales, reserva de versión e integración; nunca interpretar focales como despliegue aprobado.
- Prioridad: APO sin orden protectora nested ni origen local recuperable por vigilante; conservar unavailable y exigir IDs exactos. Veto textual de rotación reproducido con negación, sin cambiar política activa.
- Siguientes lotes separados: diagnóstico adquisición de snapshot, latencia/proveedor, denominadores y controles prospectivos de oportunidades. No subir exposición ni promover evidencia inmadura.
- Validación aislada programada 7-oct 23:00 Madrid condicionada a cierre/precondiciones; revisión solo lectura 12-oct 10:00 Madrid. Ambas pausan tras el intento/entrega.

## Intento anticipado de validación — 7-oct-2026, 22:37 Madrid

Dictamen: `precondition_not_met`. El operador pidió ejecutar inmediatamente la automatización prevista para las 23:00; se ejecutó su preflight en este chat, sin esperar al horario.

Hechos verificados en producción, solo lectura: XNYS cerrado a las 22:37:01 Madrid, próxima apertura 8-oct15:30; paquete activo0.4.321, paper true, live false. No hay eventos post_market_review_started/completed/failed del7-oct en la consulta acotada. Estado latest postmarket `skipped`, pmr_78fd692e3f98, actualizado21:51:38 Madrid, motivo mercado aún no apto. post_market_review_last_session sigue2026-10-05. La sesión7-oct no cumple terminal completed/failed; un skipped previo al cierre no lo sustituye.

Candidatos: los cuatro worktrees estaban limpios al iniciar este intento, con los HEAD/tree previamente documentados. Se detuvo antes de suites, smoke, integración o versión. Imagen/diferencia.340, kernel, configuración completa, leases y ausencia de procesos de validación no se declaran comprobados en este intento: el preflight terminó por la precondición anterior. El campo auto-apply del sondeo resultó unavailable, no false verificado.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_preflight_live.json; SQLite mediante Store.read_connection, mode=ro/query_only; sin reparaciones ni mutación productiva. No se fuerza postmarket, reconciliación o ciclo; sin órdenes, reinicios, despliegue ni promoción. Sólo se añaden estas notas documentales.

La automatización `validar-mejoras-bolsa-tras-cierre` quedó PAUSED tras este intento, tal como ordena su prompt; no volverá a ejecutarse a las23:00. La revisión del12-oct sigue programada. Siguiente condición: diagnosticar por qué no consta terminal de postmarket y volver a comprobarlo junto a los demás gates; no marcar completada la validación ni los candidatos como desplegados.

## Validación de las 23:05 — 7-oct-2026

Dictamen: `precondition_not_met`. Sondeo a las 23:05:22–23:05:24 Madrid: XNYS cerrado, próxima apertura 8-oct 15:30. Producción 0.4.321, paper=true, allow_live_trading=false, allow_auto_apply_improvements=false. Imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, running, arranque 22:52:55, RestartCount=2; causa de reinicios unavailable, sin intervención desde este intento. Lock vivo PID6/token305725. schedule-status no acredita jobs inactivos: runtime unavailable/wal_mode_or_sidecar_present.

Bloqueo confirmado por Store.read_connection mode=ro/query_only: lease post_market_coordination:active, sesión 2026-10-07, run pmr_b2deee2ab986, bootstrap, stage=outcome_update, actualizado 22:54:32. Started a las 22:54:15, sin terminal completed/failed en últimas 3000 filas (ventana 20:36–23:02 Madrid); last_session sigue 5-oct. Otros started a las 22:47:59 y 22:51:22 no prueban procesos simultáneos. Lease persistido activo no demuestra progreso, pero incumple el gate de ausencia de leases.

Cuatro candidatos limpios antes de esta nota, separados sobre 1adc3cec/.321: postmarket HEAD d4956030705933d32c062b347658d9eb4e795d73/tree 1e22c25327414be9e2751508b5b5732bc32374e7; exit-audit HEAD 8bece4d45de1d9f00e463e2b512d8553e407e443/tree 01f7db8cd76d6cd261ac314a6498acb6b4e40fa4; cobertura HEAD 5cdc9d83f7ffd392c6479d518301256a7d2588f9/tree 5559ac5ed76420359d98312c13fc1b7751df884d; observación HEAD 2cd1425fd728105c04a40843518f6937a7dbbb54/tree e638955373e2f052f8b76a4e0b3ff886eae1884c. Sin bump/release. Divergencia histórica .340 no resuelta; checkout C:/Antonio/Bref/agenteBolsa observado ahora b411e9a7445bfa4da6de8329e668d30864090522, paquete .253, cambios ajenos preservados; no representa identidad del Jetson.

Detenido antes de asignar validaciones, suites, smoke, integración o cambios funcionales. Focales anteriores no repetidos ni declarados validación operativa. Kernel/configuración completa, exclusividad de procesos y demás gates no aprobados. Sólo lectura productiva y documentación local, diff --check; sin órdenes, broker/LLM desde tests, protegidos, históricos, locks, producción, reinicios, merge, promoción o despliegue. Automatización validar-mejoras-bolsa-tras-cierre PAUSED tras este intento; estudio del 12-oct sin cambios. Siguiente: terminal de sesión y ausencia de lease/job/retry antes de reprogramar; no forzar cierre ni borrar leases.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_2305_live.json y audit_validation_2305_image.txt; timestamps originales UTC.



## OCT07 — cobertura real de símbolos (N2, candidato aislado)

- Dictamen: `ready_for_integration_rehearsal`; rama `codex/oct07-symbol-coverage`,
  base runtime `1adc3cec` / versión `0.4.321`. Sin bump ni despliegue.
- Bloque `symbol_coverage` canónico, separado de candidatos; legacy intacto.
- QA: 27 focales verdes, paridad completa del informe contra fuente base, Ruff/NUL/diff.
- Informe único: `docs/informe_oct07_symbol_coverage.md`.
- Siguiente: revisión e integración aislada, resolver reserva/divergencia `.340`,
  gates proporcionales y ventana operativa autorizada. Suite/smoke omitidos.

## Intento anticipado de validación — 7-oct-2026, 22:37 Madrid

Dictamen: `precondition_not_met`. El operador pidió ejecutar inmediatamente la automatización prevista para las 23:00; se ejecutó su preflight en este chat, sin esperar al horario.

Hechos verificados en producción, solo lectura: XNYS cerrado a las 22:37:01 Madrid, próxima apertura 8-oct15:30; paquete activo0.4.321, paper true, live false. No hay eventos post_market_review_started/completed/failed del7-oct en la consulta acotada. Estado latest postmarket `skipped`, pmr_78fd692e3f98, actualizado21:51:38 Madrid, motivo mercado aún no apto. post_market_review_last_session sigue2026-10-05. La sesión7-oct no cumple terminal completed/failed; un skipped previo al cierre no lo sustituye.

Candidatos: los cuatro worktrees estaban limpios al iniciar este intento, con los HEAD/tree previamente documentados. Se detuvo antes de suites, smoke, integración o versión. Imagen/diferencia.340, kernel, configuración completa, leases y ausencia de procesos de validación no se declaran comprobados en este intento: el preflight terminó por la precondición anterior. El campo auto-apply del sondeo resultó unavailable, no false verificado.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_preflight_live.json; SQLite mediante Store.read_connection, mode=ro/query_only; sin reparaciones ni mutación productiva. No se fuerza postmarket, reconciliación o ciclo; sin órdenes, reinicios, despliegue ni promoción. Sólo se añaden estas notas documentales.

La automatización `validar-mejoras-bolsa-tras-cierre` quedó PAUSED tras este intento, tal como ordena su prompt; no volverá a ejecutarse a las23:00. La revisión del12-oct sigue programada. Siguiente condición: diagnosticar por qué no consta terminal de postmarket y volver a comprobarlo junto a los demás gates; no marcar completada la validación ni los candidatos como desplegados.

## Validación de las 23:05 — 7-oct-2026

Dictamen: `precondition_not_met`. Sondeo a las 23:05:22–23:05:24 Madrid: XNYS cerrado, próxima apertura 8-oct 15:30. Producción 0.4.321, paper=true, allow_live_trading=false, allow_auto_apply_improvements=false. Imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, running, arranque 22:52:55, RestartCount=2; causa de reinicios unavailable, sin intervención desde este intento. Lock vivo PID6/token305725. schedule-status no acredita jobs inactivos: runtime unavailable/wal_mode_or_sidecar_present.

Bloqueo confirmado por Store.read_connection mode=ro/query_only: lease post_market_coordination:active, sesión 2026-10-07, run pmr_b2deee2ab986, bootstrap, stage=outcome_update, actualizado 22:54:32. Started a las 22:54:15, sin terminal completed/failed en últimas 3000 filas (ventana 20:36–23:02 Madrid); last_session sigue 5-oct. Otros started a las 22:47:59 y 22:51:22 no prueban procesos simultáneos. Lease persistido activo no demuestra progreso, pero incumple el gate de ausencia de leases.

Cuatro candidatos limpios antes de esta nota, separados sobre 1adc3cec/.321: postmarket HEAD d4956030705933d32c062b347658d9eb4e795d73/tree 1e22c25327414be9e2751508b5b5732bc32374e7; exit-audit HEAD 8bece4d45de1d9f00e463e2b512d8553e407e443/tree 01f7db8cd76d6cd261ac314a6498acb6b4e40fa4; cobertura HEAD 5cdc9d83f7ffd392c6479d518301256a7d2588f9/tree 5559ac5ed76420359d98312c13fc1b7751df884d; observación HEAD 2cd1425fd728105c04a40843518f6937a7dbbb54/tree e638955373e2f052f8b76a4e0b3ff886eae1884c. Sin bump/release. Divergencia histórica .340 no resuelta; checkout C:/Antonio/Bref/agenteBolsa observado ahora b411e9a7445bfa4da6de8329e668d30864090522, paquete .253, cambios ajenos preservados; no representa identidad del Jetson.

Detenido antes de asignar validaciones, suites, smoke, integración o cambios funcionales. Focales anteriores no repetidos ni declarados validación operativa. Kernel/configuración completa, exclusividad de procesos y demás gates no aprobados. Sólo lectura productiva y documentación local, diff --check; sin órdenes, broker/LLM desde tests, protegidos, históricos, locks, producción, reinicios, merge, promoción o despliegue. Automatización validar-mejoras-bolsa-tras-cierre PAUSED tras este intento; estudio del 12-oct sin cambios. Siguiente: terminal de sesión y ausencia de lease/job/retry antes de reprogramar; no forzar cierre ni borrar leases.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_2305_live.json y audit_validation_2305_image.txt; timestamps originales UTC.


## 7-oct-2026 — diagnóstico observacional del vigilante (N2 aislado)

- Rama codex/oct07-exit-observation, base exacta1adc3cec/.321; sin release ni despliegue.
- Bloque stop_take_observation en eventos completed existentes, reutilizando cartera/planes ya cargados. Sin nuevas consultas, sin cambiar salidas ni afirmar protección del broker.
- Distingue ausencia de origen/niveles, orden abierta, dato inválido, snapshot ausente y cartera vacía. Lookup legacy declarado, sin IDs inferidos.
- 62 focales/regresiones passed; paridad completa de plan enviado/eventos con diagnóstico normal/fallido; Ruff/NUL/diff verdes. Revisión independiente sin bloqueantes.
- Informe único docs/informe_oct07_stop_take_observation.md. Integración/gates proporcionales/versionado pendientes tras cierre; no subir exposición ni reparar históricos.
- Automatizaciones existentes actualizadas: validación aislada 7-oct23:00 y estudio solo lectura12-oct10:00 Madrid incluyen este lote y cobertura de símbolos; no despliegue.

## Intento anticipado de validación — 7-oct-2026, 22:37 Madrid

Dictamen: `precondition_not_met`. El operador pidió ejecutar inmediatamente la automatización prevista para las 23:00; se ejecutó su preflight en este chat, sin esperar al horario.

Hechos verificados en producción, solo lectura: XNYS cerrado a las 22:37:01 Madrid, próxima apertura 8-oct15:30; paquete activo0.4.321, paper true, live false. No hay eventos post_market_review_started/completed/failed del7-oct en la consulta acotada. Estado latest postmarket `skipped`, pmr_78fd692e3f98, actualizado21:51:38 Madrid, motivo mercado aún no apto. post_market_review_last_session sigue2026-10-05. La sesión7-oct no cumple terminal completed/failed; un skipped previo al cierre no lo sustituye.

Candidatos: los cuatro worktrees estaban limpios al iniciar este intento, con los HEAD/tree previamente documentados. Se detuvo antes de suites, smoke, integración o versión. Imagen/diferencia.340, kernel, configuración completa, leases y ausencia de procesos de validación no se declaran comprobados en este intento: el preflight terminó por la precondición anterior. El campo auto-apply del sondeo resultó unavailable, no false verificado.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_preflight_live.json; SQLite mediante Store.read_connection, mode=ro/query_only; sin reparaciones ni mutación productiva. No se fuerza postmarket, reconciliación o ciclo; sin órdenes, reinicios, despliegue ni promoción. Sólo se añaden estas notas documentales.

La automatización `validar-mejoras-bolsa-tras-cierre` quedó PAUSED tras este intento, tal como ordena su prompt; no volverá a ejecutarse a las23:00. La revisión del12-oct sigue programada. Siguiente condición: diagnosticar por qué no consta terminal de postmarket y volver a comprobarlo junto a los demás gates; no marcar completada la validación ni los candidatos como desplegados.

## Validación de las 23:05 — 7-oct-2026

Dictamen: `precondition_not_met`. Sondeo a las 23:05:22–23:05:24 Madrid: XNYS cerrado, próxima apertura 8-oct 15:30. Producción 0.4.321, paper=true, allow_live_trading=false, allow_auto_apply_improvements=false. Imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, running, arranque 22:52:55, RestartCount=2; causa de reinicios unavailable, sin intervención desde este intento. Lock vivo PID6/token305725. schedule-status no acredita jobs inactivos: runtime unavailable/wal_mode_or_sidecar_present.

Bloqueo confirmado por Store.read_connection mode=ro/query_only: lease post_market_coordination:active, sesión 2026-10-07, run pmr_b2deee2ab986, bootstrap, stage=outcome_update, actualizado 22:54:32. Started a las 22:54:15, sin terminal completed/failed en últimas 3000 filas (ventana 20:36–23:02 Madrid); last_session sigue 5-oct. Otros started a las 22:47:59 y 22:51:22 no prueban procesos simultáneos. Lease persistido activo no demuestra progreso, pero incumple el gate de ausencia de leases.

Cuatro candidatos limpios antes de esta nota, separados sobre 1adc3cec/.321: postmarket HEAD d4956030705933d32c062b347658d9eb4e795d73/tree 1e22c25327414be9e2751508b5b5732bc32374e7; exit-audit HEAD 8bece4d45de1d9f00e463e2b512d8553e407e443/tree 01f7db8cd76d6cd261ac314a6498acb6b4e40fa4; cobertura HEAD 5cdc9d83f7ffd392c6479d518301256a7d2588f9/tree 5559ac5ed76420359d98312c13fc1b7751df884d; observación HEAD 2cd1425fd728105c04a40843518f6937a7dbbb54/tree e638955373e2f052f8b76a4e0b3ff886eae1884c. Sin bump/release. Divergencia histórica .340 no resuelta; checkout C:/Antonio/Bref/agenteBolsa observado ahora b411e9a7445bfa4da6de8329e668d30864090522, paquete .253, cambios ajenos preservados; no representa identidad del Jetson.

Detenido antes de asignar validaciones, suites, smoke, integración o cambios funcionales. Focales anteriores no repetidos ni declarados validación operativa. Kernel/configuración completa, exclusividad de procesos y demás gates no aprobados. Sólo lectura productiva y documentación local, diff --check; sin órdenes, broker/LLM desde tests, protegidos, históricos, locks, producción, reinicios, merge, promoción o despliegue. Automatización validar-mejoras-bolsa-tras-cierre PAUSED tras este intento; estudio del 12-oct sin cambios. Siguiente: terminal de sesión y ausencia de lease/job/retry antes de reprogramar; no forzar cierre ni borrar leases.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_2305_live.json y audit_validation_2305_image.txt; timestamps originales UTC.


## 8-oct — cierre explícito del lector de eventos (candidato aislado N2)

- Rama codex/oct08-event-reader-lifecycle, base exacta 1adc3cec/.321; QA HEAD 501052f9/tree48a3b3a1. Sin release, integración ni despliegue.
- Store.iter_agent_events cierra cursor y conexión propia al agotar, fallar o cerrar generador; SQL/filtros/orden/payload intactos. No soluciona generadores suspendidos aún referenciados ni todos los lectores del proyecto.
- Seis fallos reproducidos en base; final 11 passed (siete nuevos + cuatro regresiones), Ruff/NUL/diff verdes. Revisión independiente sin bloqueantes. Evidencia y límites: docs/informe_oct08_event_reader_lifecycle.md.
- Encargo aislado nuevo autorizado por usuario; validación operativa permanece precondition_not_met por lease postmarket activo. Sin suites largas, broker/LLM desde tests ni mutaciones productivas.
- Auditoría adicional: EXPLAIN temporal confirma SCAN agent_events + TEMP B-TREE en consultas H por ciclo; agrupar/indexar requiere lote aparte con legacy e identidad exacta. Optimización de copias de velas en candidato bolsa-outcome-memory-oct08; carrera scheduler y atomicidad/chunks pendientes separados.

## 29-oct — P-L160 cerrado en worktree: `ready_for_closed_market_deployment` (0.4.395)

Worktree `.worktrees/agents-objectives`, rama `codex/agents-objectives`, base
exacta `11ac8074`/tree `f885b206` (main, 0.4.394, P-L159 integrado). Candidato
0.4.395 con commits separados de implementación, pruebas, versión y
documentación. Sin push, sin merge, sin despliegue en el momento de escribir
este bloque.

Lo desplegado hoy sigue siendo 0.4.393: en producción
`initiative_owner_from_key('trading:outcome_generation')` devuelve
`StrategyEvaluatorAgent`, lo que confirma que la corrección de dueños aún no está
en el Jetson.

Causa raíz corregida: el comité decidía en bloque y contagiaba el rechazo a
propuestas vivas (2.475 rechazos heredados de 2.946), y `MONITOR` cerraba la
iniciativa (1.271 de 1.271 en `REJECTED`, 1.256 del Orquestador). El embudo
productivo queda medido: 2.965 propuestas, admisión 0,57 %, la
`READY_TO_APPLY` más antigua con 118,85 días.

Gates: focales 20 verdes; regresiones sin cambios (mismos 79 fallos que la base);
suite completa idéntica en identificadores (858 compartidos, cero regresiones);
Ruff del lote limpio, NUL 603, diff limpio, configuración válida. Protegidos sin
diff.

Secuencia siguiente, en este orden: (1) merge `--no-ff` a `main`; (2) preflight
Jetson read-only con la comprobación completa de precondiciones de mercado
cerrado; (3) imagen port `0.4.395` desde `agente-bolsa:0.4.393-arm64` con digest
y verificación byte a byte en contenedor temporal; (4) despliegue con Compose
completo (base más override Raspberry y `--env-file /etc/agente-bolsa/runtime.env`);
(5) colocar `agent_objectives.json` en `/data/config` antes de arrancar; (6)
doble salud a 75 s o más y recibo de despliegue; (7) verificar en producción que
`agent-funnel --json` entrega objetivos sin `config_missing`; (8) tag
`prod-jetson-0.4.395`.

Pendiente y bloqueado: pasos 8–11 del plan (ventana de laboratorio en mercado
cerrado, cuota por dominio, presupuesto LLM en `config.py` y cierre
`READY_TO_APPLY` a `APPLIED`) son N3 y exigen autorización explícita y ventana
cerrada verificada. La superficie de objetivos en Config y la inyección de
`objective_status` en el scoreboard son lotes separados.

### 29-oct — P-L160 desplegado: 0.4.395 en producción

Producción: `agente-bolsa:0.4.395-arm64`
`sha256:0b31237635edd8cb51462a1ba084e95b3971e753044ed2138c83e462501f5917`,
runtime `0.4.395`, commit `c1e925c702e15332c1ecd177cb34eade65eb716b`, tree
`f72b091baa213c0bb1176e1d0c62d8b1dc74cf42`, tag `prod-jetson-0.4.395`. Recibo
verificado 2026-10-29T11:08:30Z. Doble salud verde, cero reinicios, cero OOM,
HTTP 200 en cuatro rutas, kernel `ok` con 0 violaciones y flags
`paper`/`true`/`false`/`false`. Sin órdenes ni planes desde el corte.

Estado de mercado en el corte: XNYS cerrado, apertura 14:30 local; margen
suficiente. Postmarket de la sesión 2026-10-28 `skipped` por `market_not_ready`
a las 19:54Z, terminal y sin lease vivo: el código de recuperación de leases
considera `skipped` estado terminal. Se documenta como desviación literal de la
letra de AGENTS ("completed o failed") y como defecto de producto abierto, no
como causa del lote.

Pendientes inmediatos, por orden:

1. Revisar por qué el postmarket no se reintenta después del cierre:
   `post_market_review_job` usa `should_run_daily_study` sobre la fecha de mercado
   vigente y el ciclo de intervalo se agota; la última revisión completada es
   `2026-10-19`. Lote N2 propio, con caracterización de cadencia.
2. Decidir la unificación real de modelos en producción: requiere cambiar
   `/etc/agente-bolsa/application.env` (protegido, hash del carrier del kernel y
   resello). Hoy el entorno sigue forzando `opencode-zen`, `zen/v1`,
   `deepseek-v4-flash-free` y mimo con `kimi-k2.6`, así que P-L159 no surte
   efecto en el Jetson.
3. Pasos 8–11 del plan (ventana de laboratorio en mercado cerrado, cuota por
   dominio, presupuesto LLM en `config.py`, cierre `READY_TO_APPLY` a `APPLIED`)
   siguen siendo N3 y necesitan autorización explícita.
4. Superficie de objetivos en Config e inyección de `objective_status` en el
   scoreboard, como lote de UI separado.
5. Limpiar vistas `post_market_coordination:session:*` atascadas en `active`
   (2026-10-22, 10-23, 10-27) y decidir si procede retirar `.orig` de la imagen.

### 29-oct — P-L162 + P-L161 desplegados: 0.4.397

Producción: `agente-bolsa:0.4.397-arm64`
`sha256:1df7c5720c86e817bd312fb1ab4e2a296c9fe04408cb0314c47ec2b4a3a04621`,
commit `1ff8e4f9ed51ae95deef9265d052079107fe2c9f`, tree
`d129e2863871b12bebd3885f87fac8c389c17134`, tag `prod-jetson-0.4.397`, recibo
verificado 12:27:29Z. Corte 12:26Z con XNYS cerrado; doble salud verde, kernel
`ok` con 0 violaciones, flags paper/true/false/false, cero órdenes y cero
`critical`/`traceback`/`database is locked`.

Qué cambia: el esquema crea bases nuevas (los índices de ciclos y de
recomendaciones se declaran junto a su tabla) y el fallo del postmarket deja su
traza en el evento durable, acotada a 6.000 caracteres.

Qué no cambia: el postmarket continúa sin completar desde 2026-10-19. Este lote
es diagnóstico, no la cura. Si hoy vuelve a fallar, la traza dirá el frame
exacto y se convertirá en lote mínimo. Si completa, el hueco queda cerrado por
la vía normal.

Siguiente secuencia, por orden: (1) observar el postmarket de hoy tras las 22:00
Madrid y leer la traza si falla; (2) repetir la suite completa sobre `main` para
medir cuántos de los 858 identificadores caen con P-L162; (3) unificación real de
modelos en `/etc/agente-bolsa/application.env` (N3, protegido, carrier del kernel
y resello); (4) pasos 8–11 del plan de agentes (N3, sin autorización todavía).
