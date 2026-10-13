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

# Capital hasta 25% — candidato .368, 12 de octubre de 2026

Dictamen: candidato local preparado; no desplegado ni activado. El mercado está
abierto y la aceptación N3 completa sigue pendiente. La preparación de código
no acredita cinco sesiones shadow, mejora económica ni protección broker.

## Implementación y autoridad

- Tamaño: etapas versionadas 15%/20%/25%, tope ordinario 2,5% del equity,
  tres/cuatro/cuatro compras. El clamp se aplica al importe ya ajustado por
  stop y multiplicadores, sin duplicar el factor 0,5. Cash y buying power se
  intersectan; se reservan BUY broker, planes locales y planes del ciclo.
  El enlace aún no reconciliado se cuenta conservadoramente por ambos lados.
- Ausencia de política: shadow, aprendizaje existente y estrategias actuales.
  Una activación inválida bloquea BUY, incluidas las preconstruidas, y conserva
  la evaluación de SELL con el cupo global legacy. No se eleva ese cupo de EXIT.
- Stop/riesgo desconocido: bloquea nuevas BUY con la política activa.
- Multiplicador cero: tamaño cero. Es una corrección intencional del defecto
  previo `or 1`; constituye la única excepción deliberada a la paridad de
  tamaños positivos con política nueva desactivada.
- Observación: evento append-only independiente `capital_allocation_shadow`,
  hash e ID por política/ciclo, IDs exactos y frontera de rechazo. Reutiliza el
  contexto de riesgo ya consultado: ninguna consulta adicional para observarlo.
  Cada etapa acumula sus reservas proyectadas; son presupuestos hipotéticos,
  no oportunidades ejecutables ni beneficios. Campos ausentes: unavailable.
- Score: challenger 55/20/15/10 y calibración del score actual separados; noticias
  disponibles al decidir, deduplicación, identidad del modelo/prompt y recibos
  maduros. Datos ausentes no redistribuyen pesos. Confianza declarada no es
  probabilidad de beneficio. No hay consultas nuevas, cambios de selección,
  aprendizaje real ni autoridad sobre órdenes.
- Ampliaciones: evaluador puro cubre nueva señal, sesión XNYS completa,
  ganancia, tesis, órdenes y protección exacta por cantidad/parent/OCO. La ruta
  actual no demuestra la protección canónica de la cantidad añadida: incluso
  con enable_adds=true, rechaza `controlled_add_protection_unavailable`.
  No se cancela ni modifica protección existente. El sublote requiere diseñar,
  probar y revisar el diff concreto del adaptador broker antes de habilitarlo.
- Tope superior 5%: helper exige evidencia independiente, score>=85,
  componentes completos, expectativa neta positiva, costes y aprobación; la
  ruta actual no consume un shadow score como autoridad. Promoción independiente
  y adaptador validado pendientes; actualmente no habilita ese tamaño.

## Activación y evidencia

Archivo previsto: DATA_DIR/config/capital_allocation_policy.json. Su ausencia
es el estado seguro; este lote no crea ni modifica configuración productiva.
`mode=guarded_active` exige paper/live/auto-apply y límites vigentes correctos,
registro y árbol base congelados, hash de política, aprobación exacta y recibos
canónicos `capital_allocation_session_reviewed` y
`capital_allocation_evidence_reviewed`, resueltos mediante lectura acotada.
Un JSON con conteos sin los eventos exactos no activa la política.

Primer gate: cinco sesiones XNYS completas posteriores al registro y a su
cobertura efectiva, identidad>=95%, cero incidentes críticos y reconciliación
de cantidades/protección. Se conservan requisitos adicionales del ladder.
20% exige 35 compras maduras/25 controles; 25%, 50/35, con dos ventanas no
solapadas positivas después de costes y deterioro máximo de drawdown de 1pp.
El CLI `python -m agente_bolsa.tools.capital_allocation_status --data-dir RUTA
--json` es de solo lectura: no transforma fechas observadas en sesiones completas,
no aprueba ni promociona. Está acotado y expone saturación/errores/conflictos.

## QA y procedencia

Base exacta HEAD 63cb6f9883f22c0d11dba20dd59c315ceae5dc0e,
tree a7167bca1b9387c40eb37d32d3497505dd573bf7. Módulos entregados desde ramas
score 5d30e8f67e6f384a4ae3b3b5ec5a9aebc2e7cafe y adds
d7f3a124ece0ee3e1ed9fc36f4973594674e1eb0; integración explícita de sus seis
archivos, sin portar otras ramas. Ningún archivo protegido modificado:
objetos Git de kernel/config/broker/execution/risk iguales a la base.

Batería focal combinada:315 passed,0 failed (incluye la de105; no se suman).
Ruff, diff, configuración paper aislada y NUL src/tests 511/0 pasan.
Python del proyecto, PYTHONPATH exacto, DATA_DIR temporal, _env_file=None,
proveedores locales y bloqueo de red externa. Fallo inicial de fixture EXIT:
lambda de test no aceptaba nuevo keyword include_allocation; fixture corregida,
manteniendo su prueba del cupo legacy. No se clasifica como fallo de producción.

Snapshot de fuentes/tests, hashes y objetos protegidos:
EF99/release_oct12_0368_focal_snapshot.json. Suite completa aún no ejecutada:
una por árbol funcional definitivo, después del cierre y preflight. También
pendientes smoke/configuración/kernel completos y QA ARM sin volúmenes vivos.
No se certifica N3 ni se ha construido una imagen .368 de producción.

## Secuencia pendiente

1. Revalidar quietud al cierre: XNYS cerrado, postmarket terminal, sin jobs,
   reintentos, leases, reconciliaciones ni validaciones/despliegues activos.
   Si falla: precondition_not_met; no fabricar quietud.
2. Fullsuite única del árbol congelado, smoke offline, QA ARM y manifiesto exacto.
   Los fallos se investigan con evidencia; no repetir un árbol sin causa.
3. Desplegar inicialmente observación, conservando .364 y .321 para rollback,
   mediante runbook. Confirmar imagen/hashes, doble salud>=75s y OOM/recursos600s.
   No activar tamaños ni adds ni score por el mero despliegue del observador.
4. Obtener cinco sesiones completas y recibos revisados. Activar tamaños como
   lote separado solo entonces. Ampliaciones y scoring conservan gates propios.
5. Comparación cronológica principal cinco sesiones, secundarias tres/diez,
   costes/spread/slippage/rotación/gaps, control y SPY con flujos equivalentes.
   No existe aún un resultado económico atribuible a .368.


## Identidad del checkpoint y continuidad

HEAD funcional579dc2ad173454aa632cf26420e30742251a1c2d,
tree612df176c1adc580293ed4e48172681826c9bec4, worktree limpio al commit.
Reanudación de QA/corte de observación a las22:45Madrid del12-oct mediante
automatización validar-mejoras-bolsa-tras-cierre actualizada (ACTIVE), pausándose
al terminar el intento. No activa política, tamaños, adds ni score. Cualquier
precondición ausente detiene el intento sin fabricar quietud. No cambia la
revisión del12. Recibo EF99/release_oct12_0368_checkpoint.json.
