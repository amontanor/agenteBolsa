# AGENTS.md — agenteBolsa

## Alcance y prioridad

Estas instrucciones se aplican a todo el repositorio, salvo directorios con un
`AGENTS.md` más específico. No inspecciones ni modifiques `.venv/`,
`.venv_old_codex/`, cachés o `llama.cpp/` salvo que la tarea los mencione.

El proyecto es un sistema de trading paper con componentes de investigación,
aprendizaje, riesgo, ejecución y observabilidad. La prioridad es siempre:

1. seguridad de trading y preservación de capital;
2. integridad de identidad, temporalidad y datos;
3. paridad de la ruta activa;
4. evidencia auditable;
5. rendimiento y comodidad de desarrollo.

No asumas que una mejora documentada está desplegada. Verifica siempre HEAD,
versión, árbol, configuración y eventos reales.

## Idioma y estilo

- Código, nombres de campos e identificadores: inglés.
- Mensajes para operador, documentación e informes: español claro.
- Empieza los informes por el dictamen y la causa; después aporta evidencia.
- Distingue hechos verificados, inferencias y datos `unavailable`.
- No presentes correlación, P/L intradía o una sesión como evidencia causal.
- No uses texto libre como fuente de IDs, scores o estados estructurados.

## Primeros pasos obligatorios

Antes de cambiar nada:

```powershell
git status --short
git rev-parse HEAD
git rev-parse "HEAD^{tree}"
Get-Content src\agente_bolsa\__init__.py
```

Lee solo lo necesario, empezando por:

- `docs/plan_mejoras_y_tareas.md`: fuente única de backlog y estado.
- `docs/RELEVO_DIRECCION_TECNICA.md`: secuencia y contexto vigente.
- informe único del lote actual, si existe.
- `docs/operating_model.md` para cambios de política o promoción.
- `docs/startup_runbook.md` y `docs/tutorial_arranque_diario.md` para operación.
- `docs/promotion_checklist.md` para cualquier promoción.

Instrucciones reutilizables del repositorio:

- código, tests, configuración, documentación, versiones o Git:
  `.agents/skills/buenas-practicas/SKILL.md`;
- arranque, recuperación, despliegue o comprobación diaria:
  `.agents/skills/start-agente-bolsa/SKILL.md`.

Léelas completas cuando apliquen; prevalece siempre la instrucción más segura y
específica para el contexto actual.

Comprueba si XNYS está abierto antes de decidir el tipo de trabajo:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
```

Si el árbol está sucio, clasifica cada archivo antes de actuar. Los cambios
preexistentes pertenecen al usuario: no los restaures, sobrescribas, incluyas en
otro lote ni uses para completar una integración sin autorización explícita.

## Matriz de trabajo según el mercado

### XNYS abierto

Permitido:

- auditorías read-only;
- trabajo en worktrees aislados;
- caracterización y pruebas focales con datos temporales;
- documentación y QA que no compitan con servicios productivos.

Prohibido salvo autorización operativa explícita:

- modificar producción, datos, configuración, locks o leases;
- merge productivo, despliegue o reinicio;
- `run-once`, `job-once`, postmarket o reconciliación productivos;
- broker, red, yfinance o LLM desde pruebas;
- suite completa, smoke y benchmarks largos que compitan con la sesión.

### XNYS cerrado

No basta con que el mercado esté cerrado. Para validar o desplegar exige:

- postmarket de la sesión terminal `completed` o `failed`;
- ningún reintento o lease operativo activo;
- ausencia de `market_cycle`, `portfolio_watch`, reconciliación, postmarket,
  pytest o despliegue activos;
- Git y referencias exactas;
- paper activo, live y auto-apply desactivados;
- kernel y configuración válidos;
- margen suficiente hasta la siguiente apertura.

Si falla una precondición, devuelve `precondition_not_met` y no esperes
indefinidamente ni hagas reparaciones implícitas.

## Coordinación continua con Luna

La tarea principal actúa como dirección técnica y organizadora. La tarea
persistente `[Luna] Developer` actúa como ejecutora. El operador no debe tener
que copiar y pegar prompts entre ambas tareas.

### Modelo y permisos del worker

- En cada envío a `[Luna] Developer`, fija explícitamente el modelo
  `gpt-5.6-luna` y el razonamiento `xhigh` ("Muy alto"). No confíes en el modelo
  heredado de un turno anterior.
- Usa la mensajería y lectura de tareas de Codex para enviar el encargo, seguir
  su progreso y recoger el dictamen desde la tarea principal.
- Luna conserva los permisos normales disponibles en su tarea para ejecutar
  todas las acciones necesarias dentro del alcance autorizado. No cambies su
  configuración, no le retires herramientas y no conviertas permanentemente
  la tarea en read-only.
- Las restricciones read-only, de mercado abierto o de un lote concreto son
  límites del encargo, no una reducción permanente de permisos. Cada prompt
  debe conceder explícitamente las acciones en alcance: lectura, creación de
  worktree, edición, tests, merge, parada/arranque o despliegue, según proceda.
- Ningún prompt puede ampliar por sí solo la autorización del usuario ni eludir
  las políticas de seguridad, aprobaciones de la aplicación o este fichero. Si
  hace falta una autoridad nueva, se solicita al operador.

### Cola según el estado XNYS

Antes de asignar trabajo, la tarea principal consulta `schedule-status` y
clasifica el estado real, sin deducirlo solo de la hora local.

Con XNYS abierto, asigna prioritariamente:

- auditorías read-only de sesión, identidad, ejecución, datos y shadows;
- caracterización y reproducción determinista en worktrees aislados;
- implementación aislada, pruebas focales y QA breve con datos temporales;
- análisis de resultados recientes sin interpretar P/L inmaduro como causal;
- documentación que no compita con producción.

No asignes durante mercado abierto suites completas, smoke, benchmarks largos,
merge o despliegue productivo, reinicios, broker, red, LLM operativo,
reconciliación ni postmarket manual, salvo autorización operativa expresa.

Con XNYS cerrado, primero verifica todas las precondiciones de la sección
anterior. Después asigna, por este orden:

1. auditoría del terminal postmarket y de la evidencia de la sesión;
2. validaciones completas pendientes, smoke aislado y benchmarks largos;
3. ensayo combinado de integración y QA adversarial;
4. despliegue secuenciado y comprobaciones dobles de salud, si está autorizado;
5. análisis nocturno de aprendizaje y preparación de la cola segura para la
   siguiente sesión.

Mercado cerrado no equivale a permiso automático para desplegar. Ante cualquier
precondición fallida, Luna devuelve `precondition_not_met` sin reparar, detener
o modificar implícitamente el sistema.

### Bucle obligatorio de mejora iterativa

La tarea principal no se limita a retransmitir mensajes. Para cada entrega de
Luna debe:

1. contrastar el dictamen con el encargo, HEAD/tree/versión, estado XNYS,
   denominadores, tests ejecutados y gates omitidos;
2. separar hechos, inferencias, conflictos y valores `unavailable`;
3. buscar contradicciones entre productor, evento y consumidor, y comprobar
   que las afirmaciones de paridad incluyen trading, riesgo y ejecución;
4. convertir cada defecto reproducible en un único lote mínimo, sin mezclar
   política activa, telemetría y deudas ajenas;
5. enviar a Luna el siguiente encargo acotado con referencias exactas,
   precondiciones, acciones permitidas/prohibidas, criterios de aceptación y
   dictamen esperado;
6. seguir la tarea sin lanzar trabajos duplicados ni interrumpir procesos
   útiles; pedir evidencia adicional cuando el resultado no sea concluyente;
7. actualizar el informe único del lote y, cuando corresponda, el plan maestro
   y el relevo técnico;
8. elegir el siguiente trabajo por riesgo y valor de información, no por la
   facilidad de acumular cambios o tests.

No mantengas dos workers modificando el mismo checkout o lote. Los encargos de
implementación usan worktrees distintos; las auditorías productivas son
read-only. El coordinador conserva la responsabilidad final sobre integración,
despliegue, promoción y cualquier solicitud de autorización humana.

## Estructura relevante

- `src/agente_bolsa/main.py`: CLI.
- `src/agente_bolsa/scheduler.py`: jobs, coordinación y wiring de alto nivel.
- `src/agente_bolsa/cycle_runner.py`: fases del ciclo de mercado.
- `src/agente_bolsa/storage.py`: única frontera normal de SQLite mediante
  `Store`.
- `src/agente_bolsa/models.py`: contratos de dominio.
- `src/agente_bolsa/web_app.py`: presentación Streamlit; no debe adquirir
  autoridad de trading.
- `src/agente_bolsa/tools/`: productores, políticas, auditorías y consumidores.
- `src/agente_bolsa/continuous_improvement/`: laboratorio, propuestas,
  evidencias y aprendizaje.
- `src/agente_bolsa/docker_supervisor.py`: supervisor Linux de auxiliares
  Docker.
- `src/agente_bolsa/runtime_paths.py`: rutas del intérprete en Windows y
  contenedor.
- `tests/`: pruebas aisladas y caracterizaciones.
- `data/state/agente_bolsa.sqlite3`: SQLite productiva; nunca usar en tests.
- `data/reports/`: artefactos operativos, no fixtures de test.
- `scripts/stack_*.ps1`: helpers canónicos del stack.
- `scripts/raspberry_preflight.py`: preflight Raspberry read-only con salida JSON;
  nunca ejecuta Compose, toca locks ni abre/repara SQLite activa.
- `scripts/sqlite_cold_snapshot.py`: snapshot frio explicito de SQLite y
  sidecars, con hashes/receipt; requiere `--writers-stopped` y no sobrescribe.
- `scripts/container_scheduler_health.py`: sonda Docker ARM64 de liveness del
  scheduler basada en lock/PID; no sustituye el preflight funcional.
- `data/config/`: configuración versionada que puede entrar en la imagen.
- `deploy/`: Compose y ejemplos de configuración para Docker/ARM64; nunca
  poner secretos reales aquí.
- `docs/guia_proyecto_y_operacion.md`: mapa estable del proyecto, persistencia,
  políticas, Windows, Raspberry, Docker, salud y rollback.
- `docs/informe_codex_p_l89_raspberry_docker.md`: fotografía única de la
  migración Raspberry, hashes, dictamen y siguiente ventana.

Busca primero con `rg`/`rg --files`. No dupliques contratos o helpers existentes.

### Mapa funcional para explicar el sistema

- **Entrada y coordinación:** `main.py` expone la CLI; `scheduler.py` coordina
  jobs, locks, leases y cadencias.
- **Ciclo de mercado:** `cycle_runner.py` orquesta investigación, selección,
  decisión, gates, sizing y carriers observacionales.
- **Seguridad y ejecución:** `kernel.py`, `tools/risk.py`,
  `tools/execution.py` y `tools/broker.py` son fronteras protegidas.
- **Persistencia y evidencia:** `storage.py` usa `Store`; `agent_events` es
  historia append-only y `runtime_state` es vista latest.
- **Presentación:** `web_app.py` muestra el estado; la UI no es autoridad de
  trading ni fuente de identidad.
- **Aprendizaje y shadows:** `continuous_improvement/` y `tools/` generan
  evidencia; una ruta shadow no puede cambiar órdenes.
- **Operación multiplataforma:** Windows usa `scripts/stack_*.ps1`; Raspberry
  usa Compose separado, `docker_supervisor.py`, red propia y datos en USB.
- **Documentación:** el plan maestro define backlog; el relevo define la
  siguiente secuencia; la guía explica el mapa; el informe único registra la
  evidencia fechada del lote.

## Código y configuración

- Sigue Python `>=3.10,<3.14`, Ruff y longitud de línea configurada en
  `pyproject.toml`.
- Los parámetros operables pertenecen a `Settings`, con alias en mayúsculas y
  ejemplo documentado. No hardcodees thresholds de trading.
- Nunca cambies `.env` para hacer pasar una prueba o gate.
- No añadas dependencias si la biblioteca estándar o una dependencia existente
  resuelve el problema.
- Todo subsistema consultable debe ofrecer salida `--json` cuando aporte valor
  operativo.
- Telemetría puede ser fail-open; kernel, riesgo, kill switch y gates de
  seguridad conservan su semántica fail-closed.
- Una ruta shadow no puede crear, bloquear, retrasar o cambiar órdenes.
- Toda integración nueva debe depender de interfaces y snapshots canónicos del
  dominio; SDKs y payloads específicos de un proveedor quedan confinados en
  adaptadores, de modo que añadir o sustituir un proveedor no cambie trading,
  riesgo ni consumidores.

## Archivos protegidos

Sin revisión humana explícita no modifiques:

- `src/agente_bolsa/kernel.py`
- `src/agente_bolsa/tools/broker.py`
- `src/agente_bolsa/tools/execution.py`
- `src/agente_bolsa/tools/risk.py`
- `src/agente_bolsa/config.py`
- `.env`

Compara objetos Git, no solo contenido visual, al validar un ensayo. Nunca
ejecutes `kernel-seal` ni copies un manifiesto para ocultar diferencias.
`kernel-status=unsealed` con `DATA_DIR` temporal solo indica que falta el
manifiesto productivo; repite la comprobación desde producción antes de
clasificarlo.

## SQLite y persistencia

- Accede mediante `Store` en `storage.py`.
- Reutiliza tablas y bloques JSON antes de crear esquemas nuevos.
- No hagas backfill, VACUUM, checkpoint, reparación o reescritura histórica sin
  autorización expresa.
- Auditorías: URI `mode=ro` y `PRAGMA query_only=ON`.
- Prepara, valida y serializa fuera de SQLite.
- Usa transacciones cortas; `BEGIN IMMEDIATE` únicamente durante la escritura.
- Para volumen, usa chunks cortos y memoria acotada. No abras una conexión por
  fila ni incluyas cálculo externo en una transacción global.
- No uses `INSERT OR REPLACE` para evidencia histórica.

Contrato append-only:

- mismo ID + mismo contenido: no-op/idempotent;
- mismo ID + contenido distinto: conserva el original y crea conflicto
  auditable;
- los conflictos no cuentan como observaciones canónicas;
- `captured_at` u otros tiempos de observación no deben romper un hash de
  contenido cuando no forman parte de la semántica.

## Identidad, eventos y temporalidad

- Nada importante ocurre sin evento durable.
- Todo `started` termina en `completed`, `failed` o `skipped`.
- `runtime_state` es vista mutable/latest; `agent_events` es historia.
- No reconstruyas identidades por símbolo/fecha, “última compra” o texto.
- Usa IDs exactos: `cycle_id`, `signal_capture_id`, `signal_id`,
  `candidate_id`, `recommendation_id`, `plan_id`, `broker_order_id` y
  `client_order_id`, según la frontera.
- `candidate_id` aislado no sustituye una identidad canónica de señal.
- Identidad de señal e identidad de decisión son dominios distintos; BUY y EXIT
  pueden compartir señal y deben conservar `action`/recomendación.
- Missing permanece `null`/`unavailable`; nunca `UNKNOWN` o cero supuesto.
- Normaliza timestamps a UTC para identidad y muestra Europe/Madrid en UI.
- Expresa latencias en unidades explícitas, normalmente `*_seconds`.
- Separa predecisión, decisión, ejecución y postdecisión.
- Fills, P/L, MFE/MAE, first-hit o retornos futuros no entran en features
  predecisión.
- Para reglas de sesiones, el calendario XNYS y las sesiones completadas
  estrictamente posteriores al fill son la autoridad.

## Trading, aprendizaje y shadows

- No cambies simultáneamente telemetría y política activa.
- Preserva paridad de candidatos, scores, ranks, gates, sizing,
  microexperimentos, planes, cantidades, precios, stops, takes, trailing,
  órdenes, exposición y límites cuando el lote sea observacional.
- Orden de promoción: `shadow -> guarded_active -> active`.
- No promociones estados `collecting`, `partial`, `unavailable` o muestras
  inmaduras.
- Exige evidencia preregistrada, costes, OOS/walk-forward, paper, tamaño de
  muestra, drawdown, MAE/tail loss, concentración, linaje y control comparable.
- Un LLM puede proponer o analizar; no decide readiness ni autoriza cambios de
  configuración o producción.
- Comprueba la política activa en código/configuración/eventos; no la deduzcas
  del nombre del lote.
- Un resultado mejor con peor drawdown o cola no se promociona.

## UI y métricas

- Una tarjeta debe usar la misma fuente, ventana y denominador que la gráfica a
  la que explica.
- Distingue variación de equity, P/L realizado, P/L abierto y rentabilidad
  neutral a flujos. No los mezcles.
- No inventes rentabilidad neutral a depósitos/retiradas sin un ledger de
  flujos.
- Reutiliza snapshots ya cargados; evita llamadas adicionales al broker desde
  presentación.
- La UI no escribe estado operativo ni se convierte en fuente de identidad.
- Fechas provisionales deben estar etiquetadas y nunca alimentar trading.
- Cubre copy, ausencia de datos, orden estable, zona horaria y casos negativos
  con pruebas.

## Tests aislados

Usa siempre el Python del proyecto y el `src` del worktree actual:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& "C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe" -m pytest <tests> -q
& "C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe" -m ruff check src tests
& "C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe" scripts\check_no_nulls.py
git diff --check
```

Reglas:

- `DATA_DIR` temporal, `_env_file=None`, configuración explícita y reloj
  congelado.
- Sin red, broker, LLM, yfinance, servicios o SQLite productiva.
- Concurrencia con barreras deterministas, no sleeps arbitrarios.
- Cubre legacy, idempotencia, conflictos, no mutación, fallos intermedios,
  rollback, retry, cierres de conexión y paridad.
- No añadas skip/xfail para ocultar un fallo.
- Reproduce un fallo supuesto preexistente contra la base antes de clasificarlo.
- La caracterización histórica de 33.336 observaciones es deliberadamente
  lenta; ejecútala solo cuando el lote o la validación cerrada lo requiera y con
  timeout suficiente.

Definition of Done para un cambio funcional:

1. focales del lote y regresiones relacionadas;
2. `python -m pytest tests/ -x -q`;
3. Ruff completo;
4. `scripts/check_no_nulls.py`;
5. `git diff --check`;
6. `validate-agent-config --json` aislado;
7. `kernel-status --json` interpretado en el entorno correcto;
8. smoke `run-once --skip-crew` con `DATA_DIR` y proveedores temporales;
9. paridad exacta si se toca una ruta compartida;
10. documentación y versión coherentes.

## Git, worktrees y versiones

- Desarrollo funcional siempre en un worktree `codex/<lote>` basado en un
  commit exacto; producción no es área de trabajo.
- Registra base, rama, HEAD y tree antes y después.
- Conserva commits separados para caracterización, implementación, QA y
  documentación.
- Integra con `merge --no-ff`; no squash, rebase, cherry-pick o amend sobre
  commits ya validados.
- Resuelve conflictos campo a campo. No uses `ours`/`theirs` global en archivos
  compartidos como `storage.py`, `scheduler.py`, versión o plan maestro.
- Candidatos paralelos reservan patches distintos. Inspecciona el plan antes de
  asignar versión; no puede haber dos releases con el mismo número.
- Todo cambio funcional, de comportamiento o UI requiere bump. Tests/docs solos
  no lo requieren salvo que `test_version_policy` lo exija.
- No hagas push salvo petición explícita.
- Rollback productivo mediante `git revert` auditable, nunca reset destructivo.
- Un árbol productivo sucio bloquea el despliegue. Antes de normalizar cambios
  conocidos, verifica hashes y equivalencia con el candidato y pide autoridad;
  nunca los descartes automáticamente.

## Operación y despliegue en Windows

Los helpers canónicos prevalecen sobre fragmentos antiguos de runbooks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
powershell -ExecutionPolicy Bypass -File scripts\stack_down.ps1 -IncludeScheduled
powershell -ExecutionPolicy Bypass -File scripts\stack_up.ps1
```

No arranques procesos persistentes manualmente y no mates Python genérico.

Preflight productivo:

```powershell
.\.venv\Scripts\python.exe -m agente_bolsa.main status
.\.venv\Scripts\python.exe -m agente_bolsa.main kernel-status --json
.\.venv\Scripts\python.exe -m agente_bolsa.main broker-status
.\.venv\Scripts\python.exe -m agente_bolsa.main portfolio-status
.\.venv\Scripts\python.exe -m agente_bolsa.main schedule-status
.\.venv\Scripts\python.exe -m agente_bolsa.main operational-health --json
powershell -ExecutionPolicy Bypass -File scripts\stack_status.ps1
```

En Windows, `.venv\Scripts\python.exe` puede ser un launcher cuyo hijo usa el
binario físico de Python base. No lo clasifiques como segundo scheduler solo por
la ruta del ejecutable. Reconstruye el árbol padre-hijo y verifica actividad,
`sys.prefix`, PID, token de inicio, listener y lock. Un stack válido puede ser:

```text
wrapper PowerShell -> launcher .venv -> runtime Python base
```

El lock debe pertenecer al runtime efectivo, no necesariamente al launcher.
No borres un lock si no has demostrado que su propietario está muerto o es un
PID reutilizado.

### Operación Raspberry y snapshot de migración

La migración Raspberry tiene un gate read-only reproducible:

```powershell
& ".\.venv\Scripts\python.exe" scripts\raspberry_preflight.py `
  --identity "$env:USERPROFILE\.ssh\codex_raspberry_ed25519" `
  --require-windows-stopped --require-core-restart-zero `
  --sqlite-receipt .\sqlite-cold-snapshot.json --json
```

`raspberry_preflight.py` bloquea si falla identidad del host, estabilidad de
arranque (600 s por defecto), `/dev/sda1` ext4/rw y UUID, I/O o procesos `D`,
bytes/inodos/memoria, core Docker, imagen candidata, flags PAPER en cada
contenedor, receipt SQLite o exclusividad Windows. No ejecuta Compose, no borra
locks, no abre la SQLite activa y no toca `whale-copy`.

`--require-core-restart-zero` es obligatorio en el preflight de corte: diferencia
un contenedor healthy en la lectura actual de un core que ha tenido reinicios.
Sin esa bandera, el contador se muestra como advertencia read-only; con ella,
cualquier reinicio acumulado o contador unavailable bloquea el corte.

`Test-NetConnection` al puerto 22 no demuestra que Raspberry sea operable:
tambien debe completarse el banner SSH y una lectura autenticada. Un timeout
durante el banner es `precondition_not_met`; no se deben reiniciar servicios,
limpiar locks ni tocar discos para recuperarlo a ciegas.

El healthcheck del scheduler dentro de la imagen debe ser ligero y no debe
ejecutar `schedule-status` completo: en ARM64 esa orden puede superar el
timeout y devolver 137 aunque el contenedor no este marcado `OOMKilled`.
`scripts/container_scheduler_health.py` valida solamente el lock
`p-l47b1.scheduler-lock.v1`, el PID vivo/no zombie y la linea de comandos del
scheduler. Es una sonda de liveness, no una prueba de salud funcional; el
preflight sigue obligado a comprobar SQLite, recursos, leases, politica PAPER,
jobs y exclusividad antes del corte. La imagen solo puede declararse candidata
con esta mejora despues de reconstruirla y verificar que el script existe en
`/app/scripts/`.

El snapshot se crea únicamente después de detener canónicamente los escritores:

```powershell
& ".\.venv\Scripts\python.exe" scripts\sqlite_cold_snapshot.py `
  --source .\data\state\agente_bolsa.sqlite3 `
  --destination-dir <backup-no-existente> `
  --source-host Windows-Productivo --target-host Raspberryi5 `
  --target-mount /var/lib/agente-bolsa `
  --target-device-uuid <uuid-confirmado> --writers-stopped --json
```

La receipt v2 separa origen y destino, conserva los sidecars WAL/SHM presentes,
valida `quick_check`/`integrity_check`, registra hashes y nunca sobrescribe.
Un proceso `D` de `whale-copy`, presión de memoria, reinicio reciente o health
core fallido implica `precondition_not_met`: preservar el backup, no reparar a
ciegas y volver a Windows mediante el helper canónico si ya se inició el corte.
La fotografía fechada y el rollback están en
`docs/informe_codex_p_l89_raspberry_docker.md`.

Despliegue:

1. precondiciones read-only;
2. `stack_down.ps1 -IncludeScheduled`;
3. merge `--no-ff` del ensayo exacto;
4. suite, Ruff, NUL, diff, configuración, kernel y smoke aislado;
5. `stack_up.ps1`;
6. primera comprobación de salud;
7. segunda comprobación al menos 75 segundos después;
8. commit posterior exclusivamente documental, si hace falta;
9. confirmar producción y worktrees limpios.

Después del arranque exige:

- HTTP raíz y `/health` = 200;
- un scheduler lógico, PID/lock/token coherentes y heartbeat fresco;
- un único listener web;
- paper activo, live false, auto-apply false;
- kernel sellado y configuración válida;
- hash de configuración sensible intacto;
- lease postmarket vacío o terminal recuperado por la ruta normal;
- cero alertas críticas, procesos duplicados, órdenes inesperadas o
  `database is locked`.

Un bootstrap posterior al cierre puede terminar `skipped` por
`market_not_ready` o `session_already_completed`. No ejecutes postmarket,
reconciliación u outcomes manualmente para “validar” un despliegue.

## Auditorías y análisis

- Formula una pregunta y denominadores antes de consultar datos.
- Usa unidades canónicas: para operaciones suele ser `broker_order_id`; fills,
  señales, candidatos, recomendaciones y planes son denominadores separados.
- No cuentes filas genéricas del reporter como eventos canónicos.
- Comprueba schema, event ID, cycle/session ID y content hash.
- Contrasta `agent_events` histórico con `runtime_state` latest sin mezclarlos.
- Publica conflictos por separado y conserva el original.
- `0`, `null`, `unavailable`, `ambiguous`, `not_applicable` y `not_generated`
  tienen significados distintos.
- No unas posiciones con órdenes por símbolo si falta `broker_order_id`.
- Distingue datos stale de datos actuales y declara `generated_at`, `as_of`,
  `consumer_read_at` y edad cuando sean relevantes.
- No juzgues aprendizaje con outcomes inmaduros ni P/L intradía.
- Un informe posterior al ciclo no demuestra que fuese consumido por el ciclo.
- `affects_operational_scan=true` en telemetría no prueba que exista un gate.
- Para causalidad, exige identidad exacta y evidencia de productor, evento y
  consumidor.

## Documentación

- Actualiza `docs/plan_mejoras_y_tareas.md` como fuente única de estado/backlog.
- Actualiza `docs/RELEVO_DIRECCION_TECNICA.md` con la secuencia siguiente.
- Mantén un único informe por lote; amplíalo en vez de crear planes paralelos.
- Consulta `docs/guia_proyecto_y_operacion.md` para explicar apartados,
  rutas, políticas, persistencia, Docker, Raspberry, salud y rollback.
- Consulta `docs/informe_codex_p_l89_raspberry_docker.md` para el estado fechado
  de la migración Raspberry; no deduzcas `deployed` de una etiqueta de imagen.
- Registra causa raíz, contrato, denominadores, seguridad, validaciones,
  commits/trees, límites y siguiente paso.
- No marques `deployed` antes de verificar el stack real.
- No marques `verified` si la evidencia es solo sintética o `collecting`.
- Evita fijar en este fichero la versión/HEAD actuales: cambian con cada lote.

## Dictámenes y entrega

Usa dictámenes precisos como:

- `precondition_not_met`
- `ready_for_implementation`
- `ready_for_integration_rehearsal`
- `ready_for_closed_market_full_validation`
- `ready_for_closed_market_deployment`
- `deployed`
- `partially_verified_*`
- `needs_fix`
- `blocked`

Todo informe final debe indicar, según aplique:

- fecha/hora y estado XNYS;
- producción y candidato: versión, HEAD, tree y limpieza;
- worktree/rama/commits;
- causa raíz y garantías de paridad;
- pruebas exactas, skips preexistentes y gates omitidos;
- estado de scheduler, PID/lock, heartbeat, HTTP, kernel y configuración;
- estado de lease/postmarket;
- hash sensible esperado/observado sin revelar secretos;
- confirmación de no broker/red/LLM/escrituras/reinicio/push cuando corresponda;
- trabajo pendiente y precondición del siguiente paso.

No confundas “muchas pruebas focales” con suite completa. No sumes baterías
solapadas como si fueran pruebas únicas sin declararlo.

## Checklist de cierre

Antes de terminar una tarea, confirma:

- [ ] alcance respetado y mercado considerado;
- [ ] cambios ajenos preservados;
- [ ] identidad y temporalidad exactas;
- [ ] persistencia idempotente/conflict-safe;
- [ ] paridad de trading demostrada;
- [ ] tests y gates proporcionales al riesgo;
- [ ] versión y documentación coherentes;
- [ ] producción/servicios intactos o despliegue validado dos veces;
- [ ] sin secretos, push o mutaciones no autorizadas;
- [ ] siguiente paso y sus precondiciones explícitos.

## Política de rigor proporcional y presupuesto de validación (P-L86Q)

Clasifica cada lote antes de actuar:

- **N0 — documentación/copy:** texto, runbook o formato sin cambio de contrato.
- **N1 — UI aislada:** presentación sin nueva fuente, persistencia, proceso ni
  efecto operativo.
- **N2 — contrato/fuente/persistencia:** cambios de datos, carriers, identidad,
  temporalidad o almacenamiento, sin alterar autoridad de trading.
- **N3 — trading/riesgo/protegidos/configuración/despliegue:** cualquier cambio
  en esas fronteras o en servicios productivos.

Los presupuestos de validación son blandos y proporcionales: N0 requiere
revisión y `git diff --check`; N1 requiere focales de UI, lint/NUL y diff; N2
requiere caracterización, focales, regresiones y gates proporcionales; N3
requiere el DoD completo, preflight cerrado, paridad, integración y salud
postarranque. Mercado abierto, seguridad y AGENTS prevalecen sobre el nivel.

Detén el lote y consulta si aparece una dependencia nueva, una frontera
protegida, persistencia/esquema, proceso/servicio adicional, riesgo no
clasificado o un consumo superior a 2x el presupuesto acordado. No amplíes el
alcance para hacer pasar un gate.

Ejecuta como máximo una suite completa por árbol funcional definitivo. La
evidencia previa puede heredarse después de demostrar identidad de objetos o
árbol y que los cambios posteriores son exclusivamente no semánticos. Cualquier
cambio semántico, ruta compartida o duda de equivalencia exige repetir los
gates proporcionales afectados; declarar una omisión no equivale a aprobarla.

## Caveman

For every task in this repository, invoke the `$caveman` skill and keep it active unless the user explicitly asks for normal mode.

Preserve exact errors, paths, commands, numbers, test results, safety warnings, limitations, and important evidence.
