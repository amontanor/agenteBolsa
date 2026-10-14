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

# Reparaciones operativas del 14 de octubre

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
