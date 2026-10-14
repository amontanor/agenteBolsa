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
