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

# Ensayo correctivo del19oct

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

