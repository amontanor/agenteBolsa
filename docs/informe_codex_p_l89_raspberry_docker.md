# Informe Ãºnico de migraciÃ³n Raspberry â€” agenteBolsa

## Dictamen

`precondition_not_met`. No estÃ¡ desplegada la versiÃ³n candidata en Raspberry.

El corte no se ejecuta porque la validaciÃ³n actual de XNYS devuelve `is_open=true`
(`2026-08-12 16:00`, Europe/Madrid), mientras la secuencia autorizada exige
mercado cerrado, postmarket terminal y ausencia de jobs competidores. AdemÃ¡s,
la Raspberry estÃ¡ bajo presiÃ³n severa: RAM libre aproximada de 31 MiB, 963 MiB
de swap usada, load average aproximado `13.27/13.95/11.86`, scheduler antiguo
a ~194% CPU y su healthcheck excede 60 segundos. Arrancar el candidato ahora no
serÃ­a una migraciÃ³n segura.

## Identidad y candidato

- Windows base verificada: HEAD `0e4e1194fc4cb0347c9d1e3b9369ff6a34e25840`,
  tree `67e8b0a70b4427421a5e346e85ff57cb5e1755f1`, versiÃ³n `0.4.226`.
- Checkout principal Windows: limpio y sin cambios.
- Worktree candidato: rama `codex/raspberry-parity-20260812`,
  commit `42b8dfc1d5c295aec51775690db1b0f683a55f5c`,
  tree `7c204e6c79b52865ade17544ff53ef02fd7fefef`, versiÃ³n `0.4.230`.
- Se preservan sin cambios los carriers P-L89B y protegidos:
  `cycle_runner.py`,
  `tools/canonical_eod_account_snapshot.py`,
  `tools/capital_deployment_funnel_shadow.py`,
  `kernel.py`, broker, execution, risk y config.
- SHA-256 de los tres carriers en el candidato:
  `268d3481524243039e83cf6af8f99343156cce79d8743adf3f7aa335f65857bb`,
  `b79da93eff04db7a61408541e80100b6fc135e36d939ca0b8638164cbcbc014b`,
  `4e7d7b76213a39bfd1882c8977e504da432c5d8967d2298fe0cd8fae8eb878dc`.

Los cambios se limitan a infraestructura Docker/ARM64, supervisor Linux,
runtime paths, Compose/override, exclusiÃ³n de secretos y la versiÃ³n candidata.
No hay push.

## ValidaciÃ³n local

- Focales Docker/supervisor/runtime/P-L89B: `27 passed`.
- Focales versiÃ³n/web: `77 passed`.
- Suite completa del Ã¡rbol final: `2506 passed, 1 skipped, 1 warning`
  en `898.30 s`.
- Ruff de archivos modificados: correcto.
- Ruff completo: bloqueado por una importaciÃ³n preexistente en
  `scripts/check_no_nulls.py`; el mismo fallo se reproduce en la base y no se
  modificÃ³ ese archivo.
- `scripts/check_no_nulls.py`: correcto, 484 archivos.
- `git diff --check`: correcto.
- `validate-agent-config --json`: `ok=true`.
- `kernel-status --json`: `unsealed`, sin violaciones, esperado en worktree
  aislado sin manifiesto productivo.
- Build `linux/arm64`: correcto.

## Imagen y transferencia

- Tag: `agente-bolsa:0.4.230-arm64`.
- Imagen local: `linux/arm64`, revisiÃ³n OCI
  `42b8dfc1d5c295aec51775690db1b0f683a55f5c`, ID
  `sha256:34ab6321a1e3704d6051506e45e7648f83a1a7490e17d0a4e98ee848f7cb4141`.
- Tar local/remoto: 1.677.926.912 bytes,
  SHA-256
  `ec7099b7a1dfd4080705faa43a53d5fa455f34bcff8d117a0cf77ef312a8e625).
- Staging remoto: `/var/lib/agente-bolsa/.staging/`; el USB sigue montado
  en `/var/lib/agente-bolsa`, ext4 UUID
  `1a8cb7c0-3a65-4d72-866f-340db4c6bafc), aproximadamente 209 GiB libres.
- Raspberry cargÃ³ la imagen como descriptor
  `sha256:c9745ce004fa44be7590a59e543f64faaacd8c7cbc24862bcadefdeeab9a19ff`
  (ID local distinto por la importaciÃ³n OCI, mismas capas SHA-256, config,
  arquitectura y revisiÃ³n). La importaciÃ³n quedÃ³ terminada; no queda un
  `docker load` activo.
- El contenedor efÃ­mero de comprobaciÃ³n informÃ³ `aarch64 0.4.230`.
- No se copiaron secretos.

## Raspberry antes del corte

- Host confirmado: `Raspberryi5`, `aarch64`, IP `192.168.1.234`.
- Docker sigue en la microSD; el USB solo aloja datos/staging.
- Compose candidato instalado en:
  `/opt/agente-bolsa/deploy/docker-compose.yml` y
  `docker-compose.raspberry.override.yml`.
- Hashes instalados:
  - Compose: `c098bd0c4a862e73732c2eb19f1a674d6a7af5f44a39d117a17082d2054c4796`.
  - Override: `7ca81b52c8f1c70b44a4808d6787e56c410170dd5a79cd05612d787053d3e182`.
- `docker compose config --quiet`: correcto usando
  `/etc/agente-bolsa/application.env` sin imprimir secretos.
- ConfiguraciÃ³n efectiva mantenida: Alpaca PAPER,
  `AUTO_PAPER_TRADING=true`,
  `REQUIRE_HUMAN_APPROVAL=false`,
  `ALLOW_LIVE_TRADING=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- El candidato publicarÃ­a el panel en `0.0.0.0:8081 -> 8501) dentro de la
  LAN privada y usarÃ­a `/_stcore/health`; `/health` continÃºa siendo HTML
  Streamlit, no un JSON semÃ¡ntico.
- La configuraciÃ³n protegida aÃºn apunta a
  `agente-bolsa:0.4.229-arm64`; no se cambiÃ³ el env ni se hizo `up`.

Contenedores observados tras preparar la imagen:

- `agente-bolsa-web-1`: imagen `0.4.229-arm64`, healthy, aÃºn enlazado a
  `127.0.0.1:8081).
- `agente-bolsa-auxiliary-1`: imagen `0.4.229-arm64`, healthy.
- `agente-bolsa-scheduler-1`: imagen `0.4.229-arm64`, unhealthy; sus
  healthchecks terminan repetidamente por timeout de 60 s.
- `whale-copy`: independiente, unhealthy/reiniciÃ¡ndose; muestra avisos IBKR
  502/timeout. No se detuvo ni modificÃ³.

La SQLite activa y sus WAL/SHM no se restauraron ni reescribieron en este lote.
No se ejecutaron backfill, VACUUM, checkpoint ni reparaciÃ³n.

## Mutaciones realizadas

- CreaciÃ³n del worktree y commit local del candidato.
- Build local de una imagen ARM64.
- Copia verificada del tar al staging del USB.
- Carga de la imagen en Docker Raspberry.
- InstalaciÃ³n de los dos Compose candidatos.
- No se detuvo ningÃºn contenedor, no se reiniciÃ³ Docker, no se arrancÃ³ el
  candidato, no se arrancÃ³ Windows, no se tocÃ³ whale-copy, SQLite, credenciales,
  otros discos, firewall ni Git remoto.

## Rollback y siguiente ventana

El rollback efectivo actual es no realizar el corte: los contenedores antiguos
siguen ejecutÃ¡ndose y `application.env` conserva la imagen `0.4.229-arm64`.
La imagen y el staging candidato se conservan para reintentar; no se puede
declarar que la migraciÃ³n estÃ© activa.

Para la siguiente ventana cerrada:

1. Confirmar XNYS cerrado, postmarket/reconciliaciÃ³n terminales, leases vacÃ­os y
   ausencia de jobs activos.
2. Resolver o demostrar que desapareciÃ³ la presiÃ³n de recursos y que el
   scheduler pasa su healthcheck; no iniciar sobre un scheduler unhealthy.
3. Hacer snapshot frÃ­o autorizado de SQLite vigente justo antes del corte,
   incluyendo sidecars si existen, y validar hash/integridad sin checkpoint
   manual.
4. Validar de nuevo env, Compose, digest y exclusividad.
5. Detener Windows con el helper canÃ³nico solo cuando Raspberry estÃ© preparada;
   mantener una Ãºnica instancia.
6. Cambiar la etiqueta a `0.4.230-arm64`, arrancar solo agenteBolsa y medir
   dos saludes separadas al menos 75 s: servicios healthy/restart 0, scheduler
   Ãºnico, lock/heartbeat, SQLite/WAL/SHM, HTTP raÃ­z, `/kindle`,
   `/_stcore/health`, LAN privada en `192.168.1.234:8081`, flags PAPER y
   cero Ã³rdenes inesperadas.
7. Si falla cualquier gate, detener solo agenteBolsa Raspberry y reanudar
   Windows por el helper canÃ³nico, sin restaurar una SQLite antigua.

No ejecutar `run-once`, `job-once` ni `decide-once`.

## Preflight de cierre 2026-08-12 (22:31-22:34 Europe/Madrid)

**Dictamen: `precondition_not_met`.** XNYS aparece cerrado a las 22:31:31,
pero no se inicia el corte porque el host y la exclusividad de instancias no
quedan demostrados.

Evidencia read-only obtenida:

- La Raspberry sigue siendo `Raspberryi5`, `aarch64`. El montaje es
  `/dev/sda1` sobre `/var/lib/agente-bolsa`, `ext4`, `rw,noatime`; el dispositivo
  es el SanDisk `3.2Gen1`, serie `00010123090725114448`, UUID
  `1a8cb7c0-3a65-4d72-866f-340db4c6bafc`. Hay aproximadamente 209 GB libres y
  1% de inodos usados.
- El host acaba de arrancar: `uptime -s` indica `2026-08-12 22:32:08`. El
  kernel registra la enumeracion USB del SanDisk a las 22:32:09 y el montaje
  ext4 a las 22:32:21. No hay errores I/O de USB visibles en el filtro reciente,
  pero no existe aun una ventana de estabilidad suficiente. El root de la
  microSD tambien mostro limpieza de huerfanos en solo lectura antes de
  remontarse `rw`.
- Recursos actuales: raiz 27 GB libres, USB 209 GB libres, 1% de inodos, RAM
  disponible aproximada 911 MiB y swap zram 1.8 GiB libre. Docker reporta los
  contenedores antiguos `healthy`, pero el supervisor auxiliary conserva un
  proceso de la comprobacion SQLite read-only en estado `D` (PID 5427) tras
  superar 60 s; no se lo mata ni se reinicia el contenedor a ciegas.
- La lectura ligera de SQLite confirma `journal_mode=wal`, `schema_version=88`
  y acceso read-only al esquema. `PRAGMA quick_check(1)` no termino en 60 s y
  queda `unavailable` para este preflight; no se hizo checkpoint, VACUUM,
  reparacion ni escritura de datos.
- La instancia Raspberry activa sigue en `agente-bolsa:0.4.229-arm64`. La
  candidata `0.4.230-arm64` permanece cargada con descriptor
  `sha256:c9745ce004fa44be7590a59e543f64faaacd8c7cbc24862bcadefdeeab9a19ff`.
  Los flags efectivos leidos siguen siendo PAPER:
  `AUTO_PAPER_TRADING=true`, `REQUIRE_HUMAN_APPROVAL=false`,
  `ALLOW_LIVE_TRADING=false` y `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- En Windows, `schedule-status` observo un lock cuyo propietario estaba vivo;
  inmediatamente despues `stack_status.ps1` mostro el scheduler `CORRIENDO`
  con wrapper PowerShell y Python activos, aunque marco el lock como huerfano.
  Esta contradiccion impide demostrar que Windows esta detenido y que no hay
  competidor. No se detuvo ningun proceso.
- El checkout principal conserva el artefacto no versionado `.playwright-cli/`;
  no se inspecciono fuera de su inventario ni se elimino/restauro.

No se cambio Compose/env, no se hizo snapshot frio, no se detuvieron ni
arrancaron stacks, no se toco `whale-copy`, no se modifico SQLite/WAL/SHM, no
se limpiaron locks y no se hizo push. El siguiente intento requiere que el
operador confirme un host estable tras este arranque, resuelva la prueba
SQLite bloqueada y demuestre Windows detenido/exclusividad; despues se repite
el preflight sin esperar indefinidamente.

## Preflight automatizado posterior 2026-08-12 (23:21 Europe/Madrid)

Se ejecutó `scripts/raspberry_preflight.py` en modo estrictamente read-only,
con SSH por la clave autorizada y sin receipt de SQLite. El helper devuelve
código `2` y `ok=false` por estas razones:

- el host volvió a arrancar a las `23:15:16`; a las `23:21` llevaba solo 455
  segundos, por debajo del mínimo operativo de 600 segundos;
- la integridad de SQLite queda `unavailable` hasta aportar un receipt de
  snapshot frío validado; la base activa conserva WAL/SHM y el helper no la
  abre, repara ni somete a `quick_check` online;
- el USB sí pasa identidad y montaje: SanDisk `/dev/sda1`, ext4, `rw`, UUID
  `1a8cb7c0-3a65-4d72-866f-340db4c6bafc`, aproximadamente 224 GB libres;
- no se observaron errores I/O/USB/ext4 ni procesos en estado `D` durante esta
  lectura; los tres contenedores core estaban `running/healthy` con la imagen
  antigua `0.4.229-arm64`;
- la imagen candidata `0.4.230-arm64` está disponible y conserva la revisión
  `42b8dfc1`; los flags efectivos siguen siendo PAPER y live/auto-apply false.

El script queda como gate reproducible: no modifica archivos remotos, no
detiene procesos, no ejecuta Compose, no limpia locks y no toca `whale-copy`.
Un receipt válido debe usar el schema `p-l89.sqlite-cold-snapshot.v2`, incluir
`quick_check=ok`, `integrity_check=ok`, hostname, montaje, UUID y SHA-256, y se
verifica localmente mediante `--sqlite-receipt` contra el fichero snapshot real,
su tamaño y sus sidecars.
La herramienta `scripts/sqlite_cold_snapshot.py` queda preparada para la
ventana autorizada: exige `--writers-stopped`, no sobrescribe, no ejecuta
`VACUUM`/checkpoint/backfill, copia la base y sidecars presentes, valida la
copia y escribe el receipt dentro del directorio nuevo. No se ejecutó sobre la
Raspberry en este lote.

## Preflight estricto 2026-08-12 (23:37 Europe/Madrid)

Se repitio el helper despues de superar la estabilidad minima, con
`--require-windows-stopped`, siempre en modo read-only. El resultado fue
`exit_code=2`, `ok=false`, con los siguientes hechos:

- host `Raspberryi5`, `aarch64`, uptime `1306 s`; el gate de estabilidad paso;
- `/dev/sda1` sigue siendo el USB esperado, ext4/rw, UUID
  `1a8cb7c0-3a65-4d72-866f-340db4c6bafc`, sin errores I/O/USB/ext4 recientes ni
  procesos en estado `D`;
- el core Docker esta `running/healthy`, la candidata
  `agente-bolsa:0.4.230-arm64` esta cargada con digest
  `sha256:c9745ce004fa44be7590a59e543f64faaacd8c7cbc24862bcadefdeeab9a19ff`
  y revision de imagen `42b8dfc1d5c295aec51775690db1b0f683a55f5c`;
- las flags requeridas pasan individualmente en scheduler, auxiliary y web:
  PAPER activo, `AUTO_PAPER_TRADING=true`, `REQUIRE_HUMAN_APPROVAL=false`,
  `ALLOW_LIVE_TRADING=false` y `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`;
- siguen bloqueantes `sqlite_integrity: falta --sqlite-receipt` y
  `windows_exclusivity`: scheduler/web continuan activos y el web Windows
  publica `0.0.0.0:8501`.

La lectura no detuvo Windows, no creo snapshot, no reinicio ni arranco stacks,
no toco SQLite/WAL/SHM, `whale-copy`, Compose, locks ni firewall. El siguiente
paso autorizado es detener canonicamente Windows solo dentro del corte, generar
la snapshot fria con `--writers-stopped`, validarla y repetir el preflight antes
de cualquier cambio de imagen en Raspberry.

## Reconciliacion del preflight 2026-08-12 (23:42 Europe/Madrid)

Tras corregir la resolucion del `stack_status.ps1`, el preflight estricto
volvio a devolver `exit_code=2`, `ok=false`, pero `windows_exclusivity` quedo
en `active=['scheduler','web'], foreign=[]`. La aparente foreign process de la
lectura de las 23:37 era un falso positivo por auditar Windows desde el
worktree candidato en lugar del checkout principal.

En esta lectura el host llevaba `1591 s`, el gate de inodos paso con `1%`, el
USB y el kernel storage pasaron, no habia procesos `D`, el core Docker estaba
healthy, la imagen candidata y sus flags PAPER pasaban. Los dos bloqueantes
reales son la ausencia de `--sqlite-receipt` y que scheduler/web Windows siguen
activos. No hubo mutaciones.

## Corte abortado y rollback 2026-08-12 (23:46-23:53 Europe/Madrid)

El preflight fisico de las 23:46:28 tenia todos los gates de host/USB/Docker
verdes salvo la falta de receipt. Con XNYS cerrado, postmarket de la sesion
terminal, reconciliacion completada sin cambios/errores y sin foreign Windows,
se ejecuto `scripts/stack_down.ps1 -IncludeScheduled` a las 23:46:34.
Scheduler y web quedaron parados; el lock no se borro y paso a
`stale_dead_owner` con PID muerto.

Se produjo una primera copia de SQLite, pero su receipt apunto por error al
directorio temporal `.partial-*`; no se consumio como evidencia y permanece
sin usar. Tras corregir la herramienta y separar origen de destino, la segunda
snapshot fria valida quedo en:

`C:\Antonio\Bref\agenteBolsa_backups\raspberry-cut-20260812-2350\`

Receipt `p-l89.sqlite-cold-snapshot.v2`, `journal_mode=wal`,
`quick_check=ok`, `integrity_check=ok`:

| Fichero | Bytes | SHA-256 |
|---|---:|---|
| `agente_bolsa.sqlite3` | 1.777.291.264 | `7fab2f7f1b854d20cd6e5b752687d741e8edae50e7dd58dfdaf4ad337fc324af` |
| `agente_bolsa.sqlite3-wal` | 477.207.272 | `66632ef2e2604da422fae9d1fbe7c911a3653182934723bd10d98af0724e6061` |
| `agente_bolsa.sqlite3-shm` | 32.768 | `e5e00a5e876a70ebf35b644e2c00a082da06f16860efe4ec9643651e39829a82` |

La receipt fue validada contra los ficheros reales a las 23:50:16. Todos los
gates pasaron, incluida exclusividad Windows, salvo dos bloqueos externos:

- proceso `D` de `whale-copy`, PID `13492`, bloqueado en I/O;
- memoria disponible `257.298.432` bytes, inferior al umbral operativo de
  `268.435.456` bytes.

No se detuvo ni modifico `whale-copy`, no se transfirio la base, no se cargo la
imagen ni se arranco Compose Raspberry. Se ejecuto rollback mediante
`scripts/stack_up.ps1` a las 23:50:31. A las 23:51:17 el scheduler Windows
tenia PID vivo y token coincidente; el checkout principal aun usa el helper
antiguo que muestra `lock_orphan=true`, aunque `schedule-status` confirma
`owner_alive` y `token_match=true`. El helper corregido esta en el worktree
`codex/operational-hardening`.

A las 23:52:55 la Raspberry respondio tras un reinicio no iniciado por este
lote (`uptime=0 min`, `whale-copy running/health=starting`). El preflight de
las 23:53:31 devolvio `exit_code=2`: uptime `67 s`, scheduler/web core
`unhealthy`, receipt SQLite valida y Windows activo por rollback. No se infiere
la causa del reinicio; requiere una auditoria posterior con el host estable.

Dictamen del corte: `precondition_not_met`. Raspberry continua en
`0.4.229-arm64`; Windows quedo restaurado, pero no se puede afirmar
exclusividad porque Raspberry conserva sus contenedores antiguos y el preflight
posterior los vio `unhealthy`. La candidata `0.4.230-arm64` y el backup frio
quedan preservados para otra ventana. No hubo push ni cambios en `whale-copy`,
SQLite remota, firewall, otros discos o credenciales.

## Auditoria read-only posterior al reinicio 2026-08-12 (23:56 Europe/Madrid)

La Raspberry respondio por SSH con uptime aproximado de 4 minutos. El USB
continuaba montado como `/dev/sda1 ext4 rw,noatime`. `whale-copy` estaba
`running/healthy`, con `restarts=0`, pero el host todavia no superaba el gate de
estabilidad de 600 s. `journalctl --list-boots` solo conserva el boot actual y
la consulta filtrada del boot anterior no aporto evidencia de OOM, I/O,
watchdog, thermal o panic; la causa del reinicio queda `unavailable`, no se
atribuye a ningun componente. No se ejecutaron reinicios, reparaciones,
limpiezas ni cambios remotos.

## Auditoria read-only 2026-08-13 00:07-00:08 Europe/Madrid

Con la receipt correcta `receipt.json`, el preflight Raspberry devolvio
`ok=true` sin `--require-windows-stopped`: host `Raspberryi5`/`aarch64`, uptime
894 s, `/dev/sda1` SanDisk ext4/rw con UUID esperado, 224 GB libres, 1% de
inodos, sin errores I/O recientes ni procesos `D`, memoria disponible ~941 MB,
SQLite presente con WAL/SHM y snapshot validado con SHA-256
`7fab2f7f1b854d20cd6e5b752687d741e8edae50e7dd58dfdaf4ad337fc324af`.

El core activo sigue siendo `0.4.229-arm64`; web, auxiliary y scheduler estaban
`healthy`, pero el scheduler acumulaba `37` reinicios y aproximadamente 178%
de CPU en la muestra. Estar healthy en esa lectura no borra el historial ni
satisface la validacion post-corte exigida de `restart=0`. Las flags observadas
por contenedor siguen siendo PAPER: `TRADING_MODE=paper`,
`AUTO_PAPER_TRADING=true`, `REQUIRE_HUMAN_APPROVAL=false`,
`ALLOW_LIVE_TRADING=false` y `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.

Windows permanece activo y unico en su checkout local segun `schedule-status`:
PID `28008`, estado `owner_alive` y token coincidente. Se corrigio
`stack_common.ps1` para aceptar `CreationDate` como `DateTime` en PowerShell
moderno y tolerar el redondeo de hasta un segundo de FILETIME; la regresion
focal y el preflight pasaron (`16 passed`) y `stack_status.ps1` ya informa
`lock_ok=true`. Esto corrige observabilidad, no detiene ni reinicia Windows.

El candidato contiene el commit operativo `611da4b1` con la sonda ligera del
scheduler, pero la imagen remota
`sha256:c9745ce004fa44be7590a59e543f64faaacd8c7cbc24862bcadefdeeab9a19ff`
corresponde a la construccion anterior `42b8dfc1`; no se puede afirmar que
contenga la sonda. El build ARM64 local queda pendiente porque Docker Desktop
no estaba disponible (`dockerDesktopLinuxEngine` ausente). No hubo mutaciones
remotas, carga de imagen, Compose, cambios de env, SQLite, `whale-copy` ni
push. Dictamen vigente: `precondition_not_met` / no desplegado.

## Preflight estricto 2026-08-13 00:17 Europe/Madrid

Se ejecuto el helper read-only con `--require-windows-stopped`,
`--require-core-restart-zero` y la receipt fria validada. El resultado fue
`ok=false`, con todos los gates fisicos, SQLite, imagen, flags PAPER y salud
actual del core en verde. Los dos bloqueos exactos fueron:

- `docker_core_restart_history`: scheduler Raspberry `37`, auxiliary `0`, web
  `0`.
- `windows_exclusivity`: scheduler y web Windows activos; procesos foreign
  vacios.

La Raspberry tenia uptime `1525 s`, `/dev/sda1` ext4/rw, ~224 GB libres,
memoria disponible ~419 MB y sin errores I/O/procesos `D`, pero el scheduler
consumia ~123% CPU en esa muestra. La SQLite activa mantenia WAL/SHM y no fue
tocada. No se detuvo Windows, no se reinicio Docker, no se cambio Compose/env,
no se modifico `whale-copy` y no se hizo push. El siguiente corte requiere
resolver ambos bloqueos, reconstruir la imagen con `611da4b1` y repetir este
preflight antes de cualquier parada/arranque.

## Auditoria de conectividad 2026-08-13 00:22 Europe/Madrid

Una nueva ejecucion no pudo completar el preflight: `ssh_exit_255`, timeout
durante el intercambio de banner SSH contra `192.168.1.234`. `Test-NetConnection`
si confirma TCP/22 accesible y ARP resuelve la Raspberry, por lo que no se
confunde red TCP con operabilidad SSH. Se hizo un unico reintento acotado y
fallo igual. No se ejecutaron comandos remotos, reinicios, limpiezas ni cambios
en Docker, SQLite, discos o `whale-copy`; el estado remoto queda `unavailable`
y el dictamen permanece `precondition_not_met`.

El build local sigue pendiente por un bloqueo independiente: Docker Desktop
`4.33.1` informa `WSL update required` y `wsl update failed` porque la
actualizacion elevada fue denegada. El daemon no responde aunque el proceso y
el pipe existan. No se ejecuto `wsl --update`, no se modifico la instalacion de
Docker y se requiere autoridad administrativa del operador para resolverlo.

## Auditoria unica de identidad y reinicios 2026-08-13 22:41 Europe/Madrid

**Dictamen: `precondition_not_met`.** Este lote no desplego, no reinicio
agenteBolsa, no cambio Compose/env, no borro locks, no escribio SQLite y no
inicio la migracion a Jetson.

### Estado operativo revalidado

- Windows: HEAD `3ebff4e298d67472a9c26380dc407f9f5210639b`, tree
  `d4071dcb23b6560711eadec069e7a5796adc8f11`, version `0.4.226`; checkout
  principal sin cambios tracked (solo existe `.playwright-cli/` sin trackear).
  Scheduler y web Windows siguen detenidos; el lock local es de un proceso
  muerto y no se elimino.
- XNYS: cerrado; siguiente apertura observada `2026-08-14 15:30`
  Europe/Madrid. No se ejecuto postmarket, reconciliacion, job-once ni smoke
  productivo.
- Raspberry: `Raspberryi5`, `aarch64`, SSH/Docker operativos, Docker `29.7.2`,
  Compose `v5.4.0`. `/dev/sda1` SanDisk ext4 `rw`, UUID
  `1a8cb7c0-3a65-4d72-866f-340db4c6bafc`, montado en
  `/var/lib/agente-bolsa`; aproximadamente 197 GB libres, 1% de inodos y sin
  errores de almacenamiento recientes ni procesos en estado `D`.
- SQLite: receipt previa valida, hash
  `7fab2f7f1b854d20cd6e5b752687d741e8edae50e7dd58dfdaf4ad337fc324af`, con
  14 sidecars observados. No se creo snapshot frio nuevo porque los escritores
  no se detuvieron canonicamente.
- Runtime real: los tres contenedores core ejecutan
  `agente-bolsa:0.4.241-arm64`, imagen `sha256:94b03ac1ea7a7558c40540b6d52b37f7e9541a1293e44ba01e93ddb6053f9019`,
  revision OCI `1e5c3c322c442a6183cbdf3ff3fa89d516beb1f8`, tree de su rama
  `5660da9d1717cdb571432f1cfbd12f3518a7b6c6`.
- Compose/env efectivo del release remoto, sin embargo, resuelve
  `AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.229-arm64`. Es una divergencia de
  fuente de verdad: no se acepta corregirla mediante reinicio a ciegas.
- Flags observadas en los contenedores: PAPER, `AUTO_PAPER_TRADING=true`,
  `REQUIRE_HUMAN_APPROVAL=false`, `ALLOW_LIVE_TRADING=false` y
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- HTTP LAN del runtime activo fue accesible anteriormente en `192.168.1.234:8081`;
  esta fotografia no lo considera evidencia de despliegue valido porque la
  identidad Compose/runtime y la estabilidad fallan.

### Causa confirmada de los reinicios

La evidencia ya no es solo una hipotesis de memoria:

- Preflight estricto a las 22:37: `ok=false` por
  `docker_core_restart_history` (scheduler `9`, auxiliary `0`, web `0`) y
  memoria disponible `118063104` bytes, inferior al minimo de 256 MiB.
- Eventos Docker read-only en los ultimos 30 minutos muestran repetidamente
  `oom`, seguido de `die exitCode=137` y `start` del scheduler.
- `dmesg` registra varios `Memory cgroup out of memory`, con procesos Python
  de aproximadamente 1.0 GiB y un `docker-init` del scheduler terminado.
- El cgroup del scheduler llego a `memory.max=1073741824`; la lectura mostró
  `memory.current` practicamente en ese limite y swap del contenedor usada.
- `OOMKilled=false` en la lectura posterior solo describe el proceso que esta
  vivo despues del reinicio; no invalida los eventos OOM/137 ya registrados.

Factores contribuyentes observados, no causas primarias demostradas: trabajos
APScheduler solapados/missed (`maximum number of running instances reached`),
latencia del proveedor LLM con respuestas 429 y carga elevada de SQLite/CPU.
El experimento autorizado anterior de detener solo `whale-copy` libero unos
27 MiB y no evito los reinicios; por tanto no explica el fallo.

### Reconciliacion del candidato

- Candidato solicitado: `agente-bolsa:0.4.230-arm64`, digest remoto cargado
  `sha256:c9745ce004fa44be7590a59e543f64faaacd8c7cbc24862bcadefdeeab9a19ff`,
  revision `42b8dfc1d5c295aec51775690db1b0f683a55f5c`, commit
  `42b8dfc1`, tree `7c204e6c79b52865ade17544ff53ef02fd7fefef`.
- El worktree `codex/raspberry-parity-20260812` esta limpio, pero el
  merge-base con el Windows actual es `0e4e1194`, no el HEAD productivo
  `3ebff4e2`. No es un candidato basado exactamente en Windows actual.
- Frente al Windows actual, el candidato difiere en 25 rutas e incluye la
  eliminacion de `scripts/raspberry_preflight.py`,
  `scripts/sqlite_cold_snapshot.py` y documentacion operativa, ademas de
  cambios Docker/entrypoint/supervisor/runtime paths. Debe reconstruirse desde
  el HEAD Windows exacto antes de considerarlo candidato.
- Los carriers P-L89B y protegidos comparados por objeto siguen identicos:
  `cycle_runner.py`, snapshot EOD, funnel de capital, `kernel.py`, `config.py`,
  broker, execution y risk. Esta evidencia parcial no convierte el candidato
  divergente en desplegable.
- La evidencia QA registrada para el candidato antiguo (`2506 passed`, un
  skip, una warning, build ARM64) se conserva como evidencia historica del
  tree `7c204e6c`, no como validacion del runtime actual `1e5c3c32`.

### Estado de whale-copy

`whale-copy` sigue siendo un proyecto independiente: contenedor
`whale-copy:codex-20260812234736`, red `whale-copy-ibkr`, puerto `8080` y bind
`/var/lib/whale-copy:/data`. Se detuvo y arranco una sola vez en este lote con
los comandos exactos `docker stop whale-copy` y `docker start whale-copy`, sin
usar `docker compose down`. Tras la restauracion recupero health `healthy` y
`/ready` HTTP 200; en una lectura intermedia aparecio `unhealthy` por timeout,
pero la lectura final lo vio healthy. No se mezclo su estado con el rollback de
agenteBolsa ni se modificaron sus datos. Su watchdog systemd mantiene una
incidencia separada de permisos, fuera de este lote.

### Siguiente lote autorizado

1. Mantener Windows como fallback recuperable, sin arrancar dos schedulers.
2. Crear un candidato nuevo desde HEAD Windows `3ebff4e2`, conservar toda la
   documentacion/preflight/snapshot y portar solo infraestructura ARM64
   necesaria; repetir comparacion de protegidos y P-L89B.
3. Resolver la identidad unica Compose/env/release/digest antes de cualquier
   corte.
4. Aislar y medir la causa de carga de los jobs/LLM/SQLite en un entorno
   controlado; no subir limites ni cambiar politica sin evidencia y revision.
5. Solo con estabilidad, snapshot frio y todos los gates verdes se podra
   preparar el artefacto para Jetson. Jetson queda expresamente fuera de este
   lote.

## P-L90R10 - candidata limpia ARM64 y guard de OOM (13-ago-2026)

Dictamen global: `precondition_not_met`; candidato local `ready_for_jetson`
como fuente de build, no como imagen desplegable. Raspberry no se ha mutado ni
promovido y Jetson no se ha conectado.

### Candidata e identidad

- Base exacta: Windows HEAD `3ebff4e298d67472a9c26380dc407f9f5210639b`, tree
  `d4071dcb23b6560711eadec069e7a5796adc8f11`, v0.4.226.
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl90r10_arm64_oom_guard`,
  rama `codex/pl90r10-arm64-oom-guard`.
- Candidato: commit `d8629489d9200585248d7149964109dd57e1ce03`, tree
  `9159be36443865e1c729dd123b03ffbc80d5e43b`, v0.4.242.
- La cadena fuente queda preparada como version -> commit -> tree -> Compose
  candidato -> imagen esperada `agente-bolsa:0.4.242-arm64`; no existe aun
  digest de imagen porque Docker Desktop/WSL no tiene engine disponible.

### Cambio mínimo y límites

Se limitó el executor por defecto de APScheduler a `max_workers=2`,
conservando jobs, cadencias, `max_instances=1`, `coalesce=True`, selección,
decisión, sizing, exits, riesgo, broker, modelo, flags y credenciales. Se
portaron únicamente los soportes operativos ARM64/Docker necesarios:
Compose aislado, entrypoint, rutas de intérprete en contenedor, supervisor
auxiliar, sonda de scheduler ligera y preflight parametrizado para 0.4.242.
Los objetos de `kernel.py`, `config.py`, broker, execution, risk, cycle runner,
snapshot EOD y funnel de capital coinciden con la base; no se modificaron
políticas ni SQLite.

### Evidencia de OOM y validación local

La causa previa de reinicios queda confirmada por `oom -> exit 137 -> start`,
`dmesg` con memory-cgroup OOM y límite de scheduler de 1 GiB. Antes de aplicar
el candidato se observaron 118-136 MiB disponibles, swap muy usada y hasta 11
reinicios acumulados; los solapamientos APScheduler/missed y respuestas LLM
429 son factores contribuyentes, no la causa primaria. No hay métrica
post-mitigación de Raspberry porque el candidato no se ha desplegado.

Validación del worktree final: `2524 passed, 1 skipped, 1 warning` en
`890.15 s`; focales ARM64/scheduler/preflight/health/supervisor/version y smoke
fake del ciclo verdes; `ruff check src tests` y scripts afectados verdes;
`check_no_nulls` y `git diff --check` verdes. El warning es externo
(`websockets.legacy` deprecated). La validación Docker/build ARM64 queda
pendiente por engine local no disponible.

### Estado operativo y siguiente paso

Raspberry conserva el runtime anterior 0.4.241, con su historial de OOM/restart;
Windows está detenido y recuperable. No se creó snapshot frío nuevo, no se
copió SQLite/WAL/SHM, no se ejecutó Compose, no se reinició ningún stack y no
se tocó `whale-copy`, que queda independiente. Antes de cualquier corte se
requiere recuperar Docker/WSL o usar un builder ARM64 autorizado, construir y
verificar el digest 0.4.242, ejecutar `compose config`, preflight estricto con
restart=0, snapshot frío con escritores detenidos y salud prolongada. Después,
la Jetson requiere IP/SSH autenticados, almacenamiento, sistema/JetPack,
Docker, puertos y exclusividad propios; no se inicia esa fase a ciegas.

### Relectura read-only 2026-08-13 23:31 CEST

### Preflight Jetson 2026-08-14 - bloqueado por autenticación SSH

El operador indicó Jetson Wi-Fi `192.168.1.186`, pero la huella presentada por
el host es `MD5 73:81:ac:da:43:ad:f5:ad:f9:4e:c0:5b:a6:49:54:1a` y
`SHA256:5VXTgp/+5IhJ8nmFgfL1RUr9qLLLPSRJqH5VOFOBPLI`; la consola local del
Jetson confirmó que esta es la huella correcta. Dictamen `precondition_not_met`:
el acceso remoto desde Windows aún no está autenticado; no se
autenticó ni se ejecutó ningún comando remoto en Jetson, no se transfirió el
artefacto y no se tocó Raspberry, Windows, datos ni Docker.

La lectura local de Windows a las 13:25 CEST mostró XNYS cerrado, pero el
scheduler estaba vivo con lock/token válidos; por tanto tampoco se cumple la
exclusividad requerida para snapshot/corte. Hay que confirmar la identidad/IP
del Jetson y detener Windows canónicamente dentro de la ventana autorizada
antes de reanudar.

### Preflight Jetson actualizado 2026-08-14 13:40 CEST

La huella SSH quedó confirmada por la consola local y la clave pública ya
permite autenticación desde Windows. El Jetson es aarch64, JetPack R39.2.1,
GPU Orin, Docker Engine activo, buildx 0.30.1, 7.3 GiB RAM, 424 GiB libres
en NVMe y reloj sincronizado. No hay contenedores ni imágenes agenteBolsa.

El lote queda bloqueado por infraestructura: `antonio` no pertenece al grupo
`docker`, el socket es `root:docker` y Docker devuelve `permission denied`;
tampoco está instalado `docker compose`/`docker-compose`. No se instalaron
paquetes ni se modificaron grupos. Raspberry, Windows, SQLite y whale-copy
siguen sin mutaciones en esta fase.

La Raspberry sigue sin mutaciones: `/dev/sda1` es el SanDisk objetivo, ext4/rw,
UUID esperado y 197 GiB libres; `mmcblk0p2` continúa siendo el rootfs. El
runtime sigue en `agente-bolsa:0.4.241-arm64`; scheduler, auxiliary y web están
puntualmente healthy, pero el scheduler ya acumula `restart=23` y usa 907.6 MiB
de 1 GiB. La memoria disponible subió a 286 MiB, con 1.1 GiB de swap usada;
esto no elimina el historial OOM ni satisface `restart=0`. `whale-copy` está
healthy y continúa independiente. Dictamen permanece `precondition_not_met`.

### Preflight y build Jetson actualizado 2026-08-14

El bloqueo inicial del host Jetson quedó resuelto por el operador: Compose V2
`2.40.3+ds1-0ubuntu1~24.04.1` está instalado, `antonio` pertenece al grupo
`docker` (gid 111), el acceso SSH por clave funciona y `docker ps` está vacío.
No se instalaron drivers, no se cambió el kernel ni se tocó firewall.

Preflight read-only confirmado: Jetson Orin Nano aarch64, Ubuntu 24.04.4,
JetPack/L4T R39.2.1, GPU Orin operativa, Docker Engine 29.1.3, buildx 0.30.1,
aproximadamente 7.3 GiB de RAM, sin swap, NVMe ext4/rw con unos 424 GiB
libres, reloj sincronizado, Wi-Fi `192.168.1.186` activa y Ethernet sin
enlace. No hay contenedores, volúmenes, imágenes agenteBolsa ni otro proyecto
Docker en el destino.

La candidata ARM64 final está en
`C:\Antonio\Bref\agenteBolsa_worktrees\pl90r10_arm64_oom_guard`, commit
`d4dcb075db8f8a5285a1f2e35cfe23fb64c55df9`, tree
`5d311ccceb62a7a95c950f6d3237d527a36e6a1d`, v0.4.242. Se añadió únicamente
envolvente operativa ARM64/Docker sobre la mitigación autorizada del executor
APScheduler (`SCHEDULER_MAX_WORKERS=2`); no se modificaron trading, riesgo,
selección, sizing, exits, broker, modelo, política ni credenciales.

La imagen se construyó nativamente en Jetson sin iniciar servicios:
`agente-bolsa:0.4.242-arm64`, digest de imagen/manifest
`sha256:42a7b88d7f4f31c9c434795b8b6eea09ceeed1d27458622db96a71a384303a42`,
config digest `sha256:9efde97ca3aa27aedbfbc7795b239f62e3c08ecce443786da6f3b95768568d51`.
La imagen contiene `scripts/container_scheduler_health.py`, reporta versión
0.4.242 y pasó la comprobación efímera sin red; Compose candidato pasó
`config --quiet` con el env de ejemplo. El bundle de build transferido,
sin `.env`, secretos ni SQLite, tiene SHA-256
`46a0ddfdf3958a3ab3fbd1a6f2b5d63066cdfb62708f045cfbd608be3e4b740`.

El lote se detiene antes de preparar persistencia: `/opt/agente-bolsa`,
`/etc/agente-bolsa` y `/var/lib/agente-bolsa` requieren creación privilegiada
y la sesión remota no tiene `sudo` no interactivo. Tampoco existe todavía un
`application.env` real con credenciales aprobadas. No se copiaron secretos,
SQLite/WAL/SHM ni datos productivos; Windows/Raspberry siguen como rollback y
no se arrancó Compose. Dictamen: `authority_required` / `precondition_not_met`.
Para reanudar, el operador debe crear las rutas con el comando indicado en el
relevo y provisionar el env por el canal seguro existente; después se hará el
snapshot frío con escritores detenidos, se validará la configuración efectiva
y solo entonces se ejecutará el corte controlado.

### Continuación tras preparar rutas privilegiadas 2026-08-14

El operador creó correctamente las rutas persistentes en el Jetson. Se
transfirieron solo los cuatro archivos no secretos de `deploy/` a
`/opt/agente-bolsa/releases/0.4.242/deploy/`; sus hashes remotos son:
`application.env.example` `75bb40df9623202e7ac9b6273391d488cfac839f84777e042f085d617c85b1ea`,
`deploy.env.example` `e5b68681d12cb9413d30f800eda1675ab1fb7c900ed5f38df6aaa2d70c74e2bf`,
`docker-compose.raspberry.override.yml`
`1828c87e7063aaaa45832323194f92df355d85b0eae3cf78d425f55bb16d99c3` y
`docker-compose.yml`
`c9fecf83d00f791dbdcac683e53b0b2754a8ff7cd4075a2534d1699c8aff6fd1`.
La comprobación remota confirma que `/etc/agente-bolsa/application.env` sigue
ausente, por lo que no se puede validar configuración efectiva ni arrancar.

### Inventario redacted y reconciliación de configuración 2026-08-14

El inventario del candidato/example clasifica como operativas las claves de
ruta, calendario, proveedor, modelos y URLs; como seguridad PAPER:
`TRADING_MODE`, `ALLOW_LIVE_TRADING`, `ALPACA_PAPER`, `AUTO_PAPER_TRADING`,
`REQUIRE_HUMAN_APPROVAL`, `ALLOW_AUTO_APPLY_IMPROVEMENTS`,
`REQUIRE_HUMAN_APPROVAL_FOR_HIGH_RISK` y
`REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES`; y como secretas las claves/token
`OPENCODE_API_KEY`, `IMPROVEMENT_LLM_API_KEY`, `ALPACA_API_KEY`,
`ALPACA_SECRET_KEY` y demás variables con `*_KEY`/`*_TOKEN`.

La comparación read-only del `.env` efectivo de Windows confirmó, sin revelar
secretos: `DATA_DIR=data`, `LOCAL_TIMEZONE=Europe/Madrid`, `MARKET_CALENDAR=XNYS`,
`TRADING_MODE=paper`, `BROKER=alpaca`, `ALPACA_PAPER=true`,
`AUTO_PAPER_TRADING=true`, `REQUIRE_HUMAN_APPROVAL=false`,
`ALLOW_LIVE_TRADING=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, proveedor
LLM `opencode-zen`, mejora continua habilitada y `IMPROVEMENT_DRY_RUN=false`.
El example no es reutilizable: fija `AUTO_PAPER_TRADING=false`,
`REQUIRE_HUMAN_APPROVAL=true` y contiene placeholders de secretos; además
omite muchas claves efectivas de Windows. No se debe completar por defecto.

Identidad completa de la imagen remota: repo digest
`agente-bolsa@sha256:42a7b88d7f4f31c9c434795b8b6eea09ceeed1d27458622db96a71a384303a42`,
Image ID igual al digest, `linux/arm64`, label revision
`d4dcb075db8f8a5285a1f2e35cfe23fb64c55df9`.
Compose redacted renderizado sin arrancar: proyecto `agente-bolsa`, red
`agente-bolsa-net`, servicios `init-db`, `scheduler`, `auxiliary` y `web`,
bind `/var/lib/agente-bolsa:/data`, web `0.0.0.0:8081 -> 8501`; el healthcheck
del scheduler usa la sonda ligera y el de web `/_stcore/health`. El render
usó el example únicamente para inspección y mostró sus flags inseguros de
demostración; no es una validación de producción.

Dictamen sigue `authority_required` / `precondition_not_met`: falta un
`application.env` efectivo aprobado. Debe transferirse por el canal seguro
autorizado, sin imprimirlo; después se hará la validación redacted, snapshot
frío y corte solo con escritores detenidos y gates verdes.
Dictamen sigue `authority_required` / `precondition_not_met`: falta un
`application.env` efectivo aprobado. Debe transferirse por el canal seguro
autorizado, sin imprimirlo; después se hará la validación redacted, snapshot
frío y corte solo con escritores detenidos y gates verdes.

### Transferencia autorizada pendiente de sudo interactivo 2026-08-14

La comprobación remota read-only confirma `sudo_noninteractive=no`,
`/etc/agente-bolsa/application.env=absent` y ningún contenedor Jetson. No se
creó staging ni se transfirió el `.env`; se detiene antes de copiar para no
dejar secretos temporales. El operador debe ejecutar el bloque único del
relevo, que usa SSH cifrado, instala como `root:root` con modo `600` y elimina
el staging aunque la instalación falle.
Dictamen operativo del corte: `authority_required` / `precondition_not_met`.
Windows fue detenido canónicamente y no queda ningún escritor activo; el lock
Windows queda huérfano y no se ha borrado. El snapshot frío local está en
`C:\Antonio\Bref\agenteBolsa_backups\jetson-cutover-20260814-1457` con receipt
`p-l89.sqlite-cold-snapshot.v2`, `quick_check=ok`, `integrity_check=ok`,
`journal_mode=wal` y hashes:

- SQLite: `b33450595512f9d697d3bd4a1767a9586abdec142b22274cb76673e7f7002857`
- WAL: `8dc6275d6348c83e67969eddb3bea6f505bacc7dee1a8ff3e0700e8a24841ae9`
- SHM: `94eef1e3c6cc209efc7acf2718a4bbca701a00889528c83f005695c82a72be0e`
- receipt: `75a92e979861bdbaaf170eb326f316422195a99a066d5104dfb341114acca5e3`

Los cuatro ficheros se transfirieron al `/var/lib/agente-bolsa` del Jetson y
los hashes remotos coinciden; la copia remota pasó `quick_check=ok`,
`integrity_check=ok`, `journal_mode=wal`. No se hizo backfill, VACUUM,
checkpoint ni reparación.

El arranque no se ejecutó porque Compose debe leer el env `root:root 600` y la
sesión requiere `sudo` interactivo. No se rebajaron permisos ni se arrancaron
contenedores; Windows permanece detenido para preservar exclusividad hasta que
el operador ejecute el comando de relevo y Codex pueda hacer las validaciones
post-arranque.

### Intento de arranque 2026-08-14 - Compose corregido antes de `up`

El comando inicial no arrancó contenedores: `config` falló porque se pasó
`/etc/agente-bolsa/application.env` como `--env-file` de Compose. Ese archivo
es el env de servicio, no el archivo de interpolación del proyecto; por ello
Compose cayó al valor por defecto relativo y buscó
`deploy/deploy/application.env.example`. La comprobación read-only posterior
confirma `docker ps` vacío y el env intacto `root:root 600`, 5637 bytes.

La corrección mínima es usar `deploy/deploy.env.example` como `--env-file` de
Compose; ese archivo apunta el `env_file` del servicio a
`/etc/agente-bolsa/application.env`. No se cambió código, env, datos, imagen,
red ni volúmenes.
La causa queda demostrada por el entorno efectivo del contenedor
`DATA_DIR=data` y los logs del entrypoint: `mkdir: cannot create directory
‘data’: Read-only file system`. El bind `/data` era correcto; el problema era
que el merge YAML del servicio reemplazaba el mapa `environment` del anchor y
dejaba prevalecer `DATA_DIR` del env Windows.

Corrección operativa mínima aplicada en
`deploy/docker-compose.raspberry.override.yml`: `DATA_DIR=/data` explícito en
`init-db`, `scheduler`, `web` y `auxiliary`. Commit `1d09ce13804b052323212b34443deb6df96cb3d7`,
tree `414e49991948716c9bdf0286467143fed0aab45c`; hash del override
`08ee9b4957c7307bbdc9316a919c211809a730bfc7c299db5fa7ba70bc588a93`, igual en
Windows y Jetson. No se modificaron código funcional, imagen, digest, env ni
SQLite.

El primer `up` terminó antes de iniciar servicios dependientes; `init-db`
salió 1, `OOMKilled=false`, y no hay contenedores activos. Siguiente paso:
revalidar `config` y recrear solo este Compose con el override corregido.
### Corrección de ruta SQLite antes del segundo arranque 2026-08-14

La primera ejecución tras el fix Compose reveló una segunda discrepancia: el
bind `/var/lib/agente-bolsa:/data` hace que la ruta efectiva sea
`/var/lib/agente-bolsa/state/agente_bolsa.sqlite3`, pero la snapshot se había
copiado inicialmente en la raíz del bind. `init-db` creó allí una SQLite nueva
de 581632 bytes; se detuvo el stack antes de continuar y esa copia, sus
sidecars y `scheduler.lock` se conservaron en
`/var/lib/agente-bolsa/misconfigured-initdb-20260814-1531/`.

La snapshot histórica original permanecía intacta en la raíz con los hashes
del receipt. Se restauró sin sobrescritura destructiva en `state/`; los hashes
SQLite/WAL/SHM coinciden y la copia en la ruta efectiva pasó
`quick_check=ok`, `integrity_check=ok`, `journal_mode=wal`. Los cuatro
contenedores fueron detenidos selectivamente por nombre; no se tocó otro
proyecto, volumen ni SQLite externa.

El stack queda parado antes del segundo `up`. El siguiente arranque debe usar
el Compose ya corregido y validar que `init-db` usa la SQLite histórica de
1.803.337.728 bytes, no la copia de diagnóstico.

### Estado factual del arranque Jetson 2026-08-14

**Dictamen:** `partially_verified_kernel_unsealed`; no se declara `deployed`.

El arranque corregido se ejecutó únicamente con el Compose de agenteBolsa y el
override de ARM64. El runtime actual es:

- host `antonio@192.168.1.186`, `aarch64`, Docker 29.1.3, Compose 2.40.3;
- imagen `agente-bolsa:0.4.242-arm64`, `linux/arm64`, digest completo
  `sha256:42a7b88d7f4f31c9c434795b8b6eea09ceeed1d27458622db96a71a384303a42`;
- código de imagen: commit `d4dcb075`, tree funcional `5d311cc`;
- corrección exclusivamente operativa de Compose: commit
  `1d09ce13804b052323212b34443deb6df96cb3d7`, tree
  `414e49991948716c9bdf0286467143fed0aab45c`, override SHA-256
  `08ee9b4957c7307bbdc9316a919c211809a730bfc7c299db5fa7ba70bc588a93`;
- configuración protegida: `/etc/agente-bolsa/application.env`, `root:root`,
  modo `600`, 5637 bytes, SHA-256
  `8e9bef2d8130071d9f9cb4796365ad32d97a3176be540867c2c5531679ed0171`;
- flags efectivos redacted: `TRADING_MODE=paper`, `BROKER=alpaca`,
  `ALPACA_PAPER=true`, `AUTO_PAPER_TRADING=true`,
  `REQUIRE_HUMAN_APPROVAL=false`, `ALLOW_LIVE_TRADING=false` y
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`;
- red propia `agente-bolsa-net`, bind persistente `/var/lib/agente-bolsa:/data`
  y dashboard publicado únicamente en `0.0.0.0:8081 -> 8501`.

Los cuatro servicios finalizaron con estado correcto: `init-db` salió `0`, y
`scheduler`, `auxiliary` y `web` están `healthy`, `RestartCount=0` y
`OOMKilled=false`. El scheduler tiene un único proceso lógico y
`container_scheduler_health.py` devuelve código `0`. Se verificaron dos
lecturas separadas por más de 75 segundos, con raíz HTTP, `/health`,
`/_stcore/health` y `/kindle` en `200`, incluida la URL LAN
`192.168.1.186:8081`. No hay segundo listener `8501` en el host ni errores
críticos, `database locked`, OOM o `exit 137` en los logs revisados.

La snapshot fría sigue siendo la receipt
`p-l89.sqlite-cold-snapshot.v2`, SQLite SHA-256
`b33450595512f9d697d3bd4a1767a9586abdec142b22274cb76673e7f7002857`, WAL
`8dc6275d6348c83e67969eddb3bea6f505bacc7dee1a8ff3e0700e8a24841ae9` y SHM
`94eef1e3c6cc209efc7acf2718a4bbca701a00889528c83f005695c82a72be0e`.
La copia efectiva en `state/` pasó `quick_check` e `integrity_check`. Desde el
arranque se observaron únicamente incrementos append-only de runtime
(`agent_events`, `llm_usage` y `runtime_state`); `broker_orders=138`,
`order_plans=102` y el `schema_hash` permanecen iguales a la snapshot. No se
hizo backfill, VACUUM, checkpoint ni reparación.

El único gate pendiente es el kernel: en Jetson,
`kernel-status --json` devuelve `ok=false`, `status=unsealed`,
`violations=[]`, con `expected=null` para los tres ficheros protegidos y `.env`
porque falta `data/state/kernel_manifest.json` en el bind productivo. Windows
sí devuelve `ok=true` y `sealed_at=2026-08-05T23:11:51.479232+00:00`; los hashes
actuales de los ficheros protegidos coinciden. El manifiesto local validado de
Windows tiene SHA-256
`0542cc1028a216bca711dfb6921878888fb9bcfd04d5e26e3672a86eb87e8ce3`.
No se ejecutó `kernel-seal` ni se copió el manifiesto para ocultar el gate.

Windows permanece detenido por el helper canónico y su lock huérfano se
conserva sin borrarlo; Raspberry y `whale-copy` no se tocaron. El siguiente
paso requiere una decisión operativa explícita sobre cómo provisionar el
manifiesto productivo ya validado o aceptar formalmente la semántica
`unsealed`. Hasta entonces, Jetson está técnicamente activo como única
instancia PAPER, pero el lote no supera el criterio de aceptación final.

### Revisión canónica del manifiesto 2026-08-14

Se revalidó el procedimiento del repositorio: `kernel-seal` regenera el
manifiesto leyendo los cuatro ficheros relativos al root de la aplicación,
incluido `.env`; no existe un procedimiento documentado para copiarlo o
fabricarlo durante una migración. En la imagen ARM64 el secreto se entrega
correctamente mediante `env_file` desde `/etc/agente-bolsa/application.env`,
pero no existe `/app/.env`. Por ello `kernel-status` muestra `.env` con hash
`null`.

Se evaluó una corrección exclusivamente de Compose para montar el env como
`/app/.env:ro`, pero se descartó antes de transferirla o reiniciar: el fichero
fuente es `root:root 600` y los contenedores ejecutan como UID no root, de modo
que el proceso no podría leerlo. Cambiar permisos, ejecutar el stack como root,
copiar secretos o modificar `kernel.py` son decisiones distintas y no están
autorizadas por este lote. El ensayo local fue revertido de forma auditable; el
worktree candidato vuelve al tree `414e49991948716c9bdf0286467143fed0aab45c`
(HEAD de revert `714e5942af4a94cbe7c6d8ef21ab313b00ee3e1e`) y no se transfirió
al Jetson.

No se ejecutó `kernel-seal`, no se alteró el runtime, no se reinició ningún
servicio y no se modificaron datos. El dictamen permanece
`authority_required / precondition_not_met` para el cierre formal: hace falta
una decisión humana sobre una integración protegida que permita verificar el
hash del env efectivo, o una aceptación explícita del estado `unsealed`. No se
libera todavía el handoff para desplegar `whale-copy`.

### Candidata P-L90R10B ARM64 preparada 2026-08-14

Se autorizó la modificación protegida mínima para verificar el env externo. La
candidata funcional queda en versión `0.4.243`, commit de código/imagen
`bf3306bff6401fa89f0fefd70907e2e9ce18f0e1`, tree funcional
`42fa127079b83e47df6f9f5814706139eeb66c94`. `kernel.py` acepta únicamente la
ruta explícita no secreta `AGENTE_BOLSA_KERNEL_ENV_PATH`; si está declarada y
el carrier falta o no es legible, `kernel-seal` falla y no crea manifiesto.
`kernel-status` detecta ausencia, mismatch, permisos y divergencia de ruta.

El Compose ARM64 transporta el fichero mediante un secret efímero Docker desde
`/etc/agente-bolsa/application.env` a `/run/secrets/application.env`, sin copia
en imagen ni volumen persistente, y fija
`AGENTE_BOLSA_KERNEL_ENV_PATH=/run/secrets/application.env`. La fuente sigue
siendo `root:root 600`. `deploy.env.example` apunta a
`agente-bolsa:0.4.243-arm64`; su hash SHA-256 es
`3b4ae56c82da9ae6229c31fb968122326f31a2a6f1075cd1742a8b3732450ef3` y el
override tiene hash
`feded9b7fad919873752811685464bf5ab1f2083466d70e546a6570275c9004f`.

Validación local: focales kernel/operational-health/version `70 passed`, Ruff,
NUL y diff-check verdes. La única suite completa se ejecutó una vez, agotó
604 segundos sin resultado y dejó un proceso hijo que fue detenido
selectivamente; no se repitió. La evidencia completa previa del árbol 0.4.242
se conserva para las rutas no afectadas y el timeout queda como gate omitido/no
concluyente del candidato nuevo.

La imagen se construyó en Jetson como `linux/arm64`, label revision
`bf3306bff6401fa89f0fefd70907e2e9ce18f0e1`, manifest/index digest
`sha256:8d36f420b668f6b1be6826d81296b846cf03d2b46e098ad7ada6a78cfcf21fbe` y
config digest observado en build
`sha256:943fdbfb1a6f027b339164ff4f25dd0e089771706940f24baabb8bc04da3d823`.
La imagen antigua `0.4.242` sigue ejecutándose; aún no hay corte ni
`kernel-seal` nuevo. Los dos archivos Compose candidatos están en staging
remoto con sus hashes y requieren una sesión `sudo` interactiva para que
Compose pueda leer el origen `root:600`, validar configuración y recrear solo
agenteBolsa. No tocar whale-copy ni liberar su handoff hasta completar esa
operación y los gates finales.

### P-L90R10B — resultado real del corte y bloqueo operativo 2026-08-14

El corte de `0.4.243` fue ejecutado por el operador en Jetson, pero no queda
aceptado como `deployed`: `agente-bolsa-web-1` y `agente-bolsa-auxiliary-1`
están `healthy`, `init-db` terminó con código `0`, pero
`agente-bolsa-scheduler-1` permanece `Restarting (0)`, `RestartCount=15`,
`OOMKilled=false`, `exit=0`. Los endpoints web `/:200`, `/health:200`,
`/_stcore/health:200` y `/kindle:200` no compensan un scheduler que no está
vivo; no se ejecutó `kernel-seal`.

La causa inmediata demostrada es un lock legado: `state/scheduler.lock` tenía
`pid=7`, `owner_process_token=null` y `created_at=2026-08-14T18:13:54Z`,
mientras el contenedor nuevo inició a las `19:12:58Z` y reutilizó el PID 7.
La lógica de exclusividad interpreta el PID vivo dentro del nuevo namespace
como propietario anterior y sale limpiamente con código 0. No se borró ni
movió el lock durante XNYS abierto; la recuperación queda pendiente para el
corte cerrado, después de confirmar que el propietario anterior está muerto y
que el PID fue reutilizado.

También quedó demostrada una segunda precondición: el secret local Docker es un
bind de `/etc/agente-bolsa/application.env` (`root:root 600`) y el proceso
`uid=1000(app)` no puede leerlo (`Permission denied`). No se cambiarán permisos,
usuario de servicio ni se copiará el secreto. La corrección candidata añade un
carrier no secreto `AGENTE_BOLSA_KERNEL_ENV_SHA256`; `kernel-seal` exige leer
el fichero real, mientras el runtime no root compara el digest sellado contra
ese carrier y reporta `env_carrier_source=declared_sha256`.

### P-L90R10C — candidata ARM64 preparada, sin corte por mercado abierto

La candidata limpia es `0.4.244`, commit `84b85501b67b750a28e1cbb75775322852a99bc7`,
tree `f66f4cc10a1e3e4d2645e58e753f7a53a2881523`, worktree
`pl90r10_arm64_oom_guard`. Cambia únicamente el contrato observacional del
carrier externo y el Compose/env operativo: añade el digest no secreto
`8e9bef2d8130071d9f9cb4796365ad32d97a3176be540867c2c5531679ed0171` y reserva
la imagen `agente-bolsa:0.4.244-arm64`. Focales/regresiones: `72 passed`;
Ruff, NUL y `git diff --check`: verdes. La suite completa anterior agotó 604 s
sin resultado y no se repitió por la instrucción operativa vigente.

La imagen se construyó nativamente en Jetson como `linux/arm64`: manifest/index
`sha256:22afb9c8846e3b9dbb1417fef51ffa33da20d4b0dd4c02ace1acc7844edcc021`,
config `sha256:06c37a2059f4f7c7eba31f708899e8f40c29e5f228b4072d4f0524bab627c`,
label revision `84b85501b67b750a28e1cbb75775322852a99bc7`. El bundle transferido
sin secretos tiene SHA-256
`aaf8ab067af082b08d7f723cde5472074fafefb5c564a4dd9a6e40ce54ec19f1`.
El release staging remoto `/opt/agente-bolsa/releases/0.4.244` ya existe con
propietario `antonio:antonio`; aún no se ha recreado ningún contenedor con él.

El preflight Windows del `2026-08-14 21:26 Europe/Madrid` confirma
`XNYS.is_open=true` y cierre a las `22:00`. Por ello no se detuvieron escritores,
no se creó una snapshot fría nueva y no se hizo corte durante la sesión. La
snapshot anterior sigue conservada con su receipt, pero no se afirma que sea
la fotografía fría final posterior a los últimos writes. Windows continúa
detenido como rollback; Raspberry y `whale-copy` siguen intactos.

Dictamen actual: `precondition_not_met / rollback_required`, no `deployed` y
sin handoff para `whale-copy`. Tras el cierre, el lote debe verificar
postmarket/leases/jobs terminales, detener canónicamente solo agenteBolsa, crear
una snapshot fría nueva con WAL/SHM e integridad, apartar el lock legado demostrado
stale, ejecutar `config` y `up` únicamente del Compose `0.4.244`, ejecutar
`kernel-seal` autorizado como root dentro del scheduler y validar
`kernel-status=ok`, dos saludos separados >=75 s, scheduler único, PAPER y
ausencia de OOM/locks/órdenes inesperadas. Si falla cualquier gate, detener
solo el Compose Jetson y conservar Windows como rollback; no tocar
`whale-copy`, no hacer `down` global, no backfill/VACUUM/checkpoint ni push.

### P-L90R10C - cierre operativo Jetson 2026-08-14 21:48 Europe/Madrid

Dictamen: `deployed`, con la limitacion de validacion documentada abajo. El
corte fue autorizado por el operador sin esperar al cierre de XNYS. Se detuvo
selectivamente el stack anterior de agenteBolsa y se recreo unicamente el
Compose de agenteBolsa; no se uso `docker compose down` global. Windows queda
detenido como rollback; Raspberry, `whale-copy` y ngrok no se tocaron.

Identidad unica verificada: v0.4.244, commit
`84b85501b67b750a28e1cbb75775322852a99bc7`, tree
`f66f4cc10a1e3e4d2645e58e753f7a53a2881523`, imagen `linux/arm64`, manifest/index
`sha256:22afb9c8846e3b9dbb1417fef51ffa33da20d4b0dd4c02ace1acc7844edcc021`,
config `sha256:06c37a2059f4f7c7eba31f708899e8f40c29e5f228b4072d4f0524bab627c`
y label revision coincidente con el commit. El Compose activo usa el release
`/opt/agente-bolsa/releases/0.4.244`, red propia y dashboard en `0.0.0.0:8081`.

El `kernel-seal` canonico se ejecuto una vez en un contenedor efimero con
privilegios de escritura limitados al manifiesto y al carrier real. Resultado
`kernel-status --json`: `ok`, `violations=[]`,
`env_path=/run/secrets/application.env`, `env_carrier_source=declared_sha256`.
Los hashes efectivos de `kernel.py`, `broker.py`, `execution.py` y del env
externo coinciden con los esperados; el env sigue siendo `root:root 600` y su
hash es `8e9bef2d8130071d9f9cb4796365ad32d97a3176be540867c2c5531679ed0171`.
No se encontro copia persistente de `application.env` o `.env` bajo el
directorio de datos.

Gates runtime:

- Healthcheck 1: `2026-08-14T19:44:40Z`.
- Healthcheck 2: `2026-08-14T19:48:35Z`, separado mas de 75 segundos.
- scheduler, auxiliary y web: `healthy`, `RestartCount=0`, `OOMKilled=false`;
  `init-db`: salida `0`.
- Sonda ligera `container_scheduler_health.py`: retorno `0`; el lock activo
  pertenece al scheduler nuevo, con `pid=7` y token nulo, semantica admitida en
  Linux por este runtime. No hay scheduler duplicado.
- Flags redacted: `TRADING_MODE=paper`, `BROKER=alpaca`,
  `ALPACA_PAPER=true`, `AUTO_PAPER_TRADING=true`,
  `REQUIRE_HUMAN_APPROVAL=false`, `ALLOW_LIVE_TRADING=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`.
- LAN `192.168.1.186:8081`: `/`, `/health`, `/_stcore/health` y `/kindle`
  respondieron `200`. `/health` devuelve el shell HTML de Streamlit; la sonda
  semantica efectiva es `/_stcore/health`, tambien `200`.
- Listener unico del dashboard en `0.0.0.0:8081`; no se abrieron puertos nuevos.
- Logs desde el arranque: `database locked=0` y `OOM/exit137=0` en scheduler,
  auxiliary y web. Conteos SQLite read-only: `broker_orders=138`,
  `order_plans=102`; no se ejecuto ningun run-once/job-once/decide-once ni se
  observaron ordenes inesperadas.

Persistencia y rollback: el snapshot frio v2
`/home/antonio/agente-bolsa-backups/p-l90r10c-20260814T2126Z/receipt.json`
esta en estado `ok`, con `quick_check=ok`, `integrity_check=ok`,
`journal_mode=wal`, SQLite de `1803575296` bytes y SHA-256
`b47857b7048d87b7b1448c651dd83b9c0867e5168fa6d9a0e9e012552aaf18fb`.
El almacenamiento efectivo es NVMe ext4/rw UUID
`fb906e91-e733-456e-ad67-2b18476762c1`, con aproximadamente 408 GiB libres y
sin swap. La SQLite activa se inspecciono solo en modo lectura; su tamano era
`1803620352` bytes. Si aparece un fallo posterior, el rollback autorizado es
detener solo el Compose Jetson de agenteBolsa y reactivar Windows mediante su
helper canonico; no borrar locks ni reparar SQLite a ciegas.

Limitaciones: la suite completa previa agoto 604 s y no se repitio por el
presupuesto operativo; el cierre se basa en los focales/regresiones `72 passed`,
Ruff/NUL/diff verdes, la identidad de imagen, kernel y los gates runtime
anteriores. No se libera automaticamente `whale-copy`: queda habilitado el
handoff para su lote independiente, con su propio namespace, puertos,
preflight y rollback.

### P-L90R10D - preflight y bloqueo de sudo 2026-08-14 22:59 Europe/Madrid

Dictamen: `precondition_not_met` pendiente de una accion interactiva del
operador. XNYS esta cerrado y la proxima apertura observada es el 2026-08-17
a las 15:30 Europe/Madrid. No se ha tocado Windows, Raspberry, whale-copy ni
ngrok en este lote.

La candidata local esta en el worktree `pl90r10_arm64_oom_guard`, commit
`1e400e9adf51946680bfb642354559a0f6eea71e`, tree
`474eb2232029820e35be0afa8221eaebb1731739`, v0.4.245. Focales de scheduler:
`18 passed`; Ruff, NUL y `git diff --check` verdes. La imagen Jetson es
`linux/arm64`, digest `sha256:7a2266d86b5726bbb5cec4b9c1c139eafa553cf87d8bdcd4da851eeafd1763c2`,
config `sha256:35a4959e45d936bf38a8cb26ae6e60fd7266d4cbc3b8080e276baa1068b7d228`,
revision `1e400e9a...` y version `0.4.245`. La prueba ARM64 de lock legado
tokenless con mismo PID paso y dejo token de inicio Linux en el nuevo lock.

Preflight Jetson read-only: SSH autenticado, Docker 29.1.3, Compose 2.40.3,
NVMe `/dev/nvme0n1p1` ext4 montado en `/` con UUID
`fb906e91-e733-456e-ad67-2b18476762c1`, aproximadamente 403 GiB libres, 2%
de inodos usados y sin errores criticos recientes en `dmesg`. Memoria
available aproximada 5.1 GiB, sin swap. No hay contenedores agentes activos;
los cuatro contenedores 0.4.244 estan detenidos tras el snapshot. El env
externo sigue `root:root 600`, 5637 bytes, sin imprimir valores.

Snapshot fria actual v2: receipt
`/home/antonio/agente-bolsa-backups/p-l90r10d-20260814T203544Z/receipt.json`,
estado `ok`, quick/integrity `ok`, journal WAL, tamano `1808719872` y hash
`98d1ae5c1397d4870966f6c438fbfeedfe598e916ecc8fbcc0955913ddfdadf6`.

Bloqueo exacto: `docker compose ... config --quiet` como `antonio` devuelve
`open /etc/agente-bolsa/application.env: permission denied`; `sudo -n` no esta
autorizado. No se cambio el modo del secreto, no se limpio el lock muerto y no
se inicio la imagen 0.4.245. El scheduler-status local observa
`stale_dead_owner` y runtime state no disponible por WAL/sidecar; queda como
gate pendiente de resolver mediante el arranque controlado, no mediante
limpieza o reparacion implicita.

Accion unica pendiente: ejecutar el bloque sudo interactivo entregado al
operador para validar el hash, renderizar Compose y recrear exclusivamente
agenteBolsa. Hasta recibir su salida, el dictamen no es `deployed`.

### P-L90R10D - cierre Fase 2 2026-08-14 23:12 Europe/Madrid

Dictamen final: `deployed`. Tras el bloque sudo del operador, el release
`/opt/agente-bolsa/releases/0.4.245` quedo activo en Jetson. Arranque
`2026-08-14T21:01:38Z`; lectura final `2026-08-14T21:12:11Z`, mas de diez
minutos despues.

Identidad: commit `1e400e9adf51946680bfb642354559a0f6eea71e`, tree
`474eb2232029820e35be0afa8221eaebb1731739`, v0.4.245, imagen ARM64
`sha256:7a2266d86b5726bbb5cec4b9c1c139eafa553cf87d8bdcd4da851eeafd1763c2`,
config `sha256:35a4959e45d936bf38a8cb26ae6e60fd7266d4cbc3b8080e276baa1068b7d228`.
Scheduler, auxiliary y web permanecen `healthy`, `RestartCount=0`,
`OOMKilled=false`; `init-db` termino `0`. El probe ligero del scheduler retorno
`0` y el lock contiene PID 7 con `owner_process_token=3693728`, coherente y
tokenizado en Linux.

`kernel-status --json` es `ok`, sin violaciones; `env_path` es
`/run/secrets/application.env`, `env_carrier_source=declared_sha256`, y los
hashes protegidos coinciden. Flags redacted: PAPER/Alpaca activos,
`AUTO_PAPER_TRADING=true`, `REQUIRE_HUMAN_APPROVAL=false`,
`ALLOW_LIVE_TRADING=false`, `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`. El env
externo conserva `root:root 600` y el hash esperado, sin exponer valores.

Healthcheck 1: `21:03:28Z`; healthcheck 2: `21:05:44Z`; observacion final a
`21:12:11Z`. No hubo reinicios, OOM/exit137 ni `database locked` en scheduler,
auxiliary o web. Hay un unico listener del dashboard en `0.0.0.0:8081`.
URLs literales limpias, local Jetson y LAN `192.168.1.186:8081`, respondieron:
`/ 200`, `/health 200`, `/_stcore/health 200` y `/kindle 200`. No se ejecutaron
run-once, job-once, postmarket, reconciliacion, probes de broker/LLM ni ciclos
manuales.

Snapshot de rollback: receipt v2
`/home/antonio/agente-bolsa-backups/p-l90r10d-20260814T203544Z/receipt.json`,
quick/integrity `ok`, WAL, hash
`98d1ae5c1397d4870966f6c438fbfeedfe598e916ecc8fbcc0955913ddfdadf6`.
Windows sigue detenido como fallback; Raspberry, whale-copy y ngrok no se han
modificado. La ventana Docker queda liberada explicitamente para que
`whale-copy` inicie su lote independiente con preflight, namespace, puertos,
health y rollback propios; no se inicia en este lote.

### P-L90R10E - preflight de corte definitivo Windows 2026-08-15 02:08 Europe/Madrid

Dictamen: `precondition_not_met`. El Jetson esta sano y Windows ya no ejecuta
los servicios de agenteBolsa, pero no se ha aplicado aun el corte administrativo
porque la sesion del operador no esta elevada (`elevated=False`). No se ha
ejecutado `stack_down.ps1`, no se han deshabilitado tareas y no se ha borrado ni
limpiado ningun lock. Raspberry, Jetson, whale-copy y ngrok no se han tocado en
este lote.

Preflight read-only: XNYS cerrado; siguiente apertura observada
`2026-08-17T15:30:00+02:00`. El checkout Windows permanece en HEAD
`3ebff4e298d67472a9c26380dc407f9f5210639b`, tree
`d4071dcb23b6560711eadec069e7a5796adc8f11`; sus cambios documentales y
`.playwright-cli/` son preexistentes y se conservan. `stack_status.ps1` muestra
scheduler y web `PARADO`; el lock de scheduler tiene PID `13140` muerto y se
clasifica como huerfano, sin eliminarlo. No hay listeners Windows en 8080,
8081, 8501, 4002, 5000, 8000 ni procesos persistentes confirmados de
agenteBolsa/whale-copy. La lectura SQLite read-only muestra el laboratorio
`IDLE`, lease postmarket reciente adquirido y liberado, y ningun runtime/job
activo; el runtime local permanece `unavailable` por sidecar WAL/SHM. No se
ejecutaron ciclos, postmarket, reconciliacion, broker, LLM ni mantenimiento.

Tareas Windows: `AgenteBolsaScheduler` y `AgenteBolsaWeb` estan `Ready` y
habilitadas; `AgenteBolsaDBMaintenance` tambien esta `Ready` y habilitada, con
accion escritora `run_db_maintenance.ps1 -Mode apply` y proxima ejecucion
observada `2026-08-16 03:00`. Esta tercera tarea debe deshabilitarse junto con
Scheduler/Web para que la ventana de rollback de siete dias no pueda abrir ni
modificar SQLite automaticamente. No existe escritor Windows de whale-copy que
parar.

El Jetson `192.168.1.186` sigue activo por systemd y read-only sano: agenteBolsa
v0.4.245 ARM64 y whale-copy estan `healthy`, `RestartCount=0`, `OOMKilled=false`;
la imagen agenteBolsa mantiene digest
`sha256:7a2266d86b5726bbb5cec4b9c1c139eafa553cf87d8bdcd4da851eeafd1763c2`, el
dashboard escucha en `0.0.0.0:8081` y whale-copy en `127.0.0.1:8082`. El NVMe
`/dev/nvme0n1p1` es ext4/rw, UUID
`fb906e91-e733-456e-ad67-2b18476762c1`, con aproximadamente 403 GiB libres;
`/`, `/health`, `/_stcore/health` y `/kindle` devolvieron 200 localmente.

Rollback localizado: receipt local
`C:\Antonio\Bref\agenteBolsa_backups\jetson-cutover-20260814-1457\receipt.json`
esta `ok`, con `quick_check=ok`, `integrity_check=ok` y hash
`b33450595512f9d697d3bd4a1767a9586abdec142b22274cb76673e7f7002857`; la
receipt v2 remota vigente es
`/home/antonio/agente-bolsa-backups/p-l90r10d-20260814T203544Z/receipt.json`,
con hash `98d1ae5c1397d4870966f6c438fbfeedfe598e916ecc8fbcc0955913ddfdadf6`.

Accion administrativa única pendiente, desde una PowerShell elevada en la
raiz del checkout:

```powershell
$ErrorActionPreference = 'Stop'
Set-Location 'C:\Antonio\Bref\agenteBolsa'
powershell -ExecutionPolicy Bypass -File .\scripts\stack_status.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\stack_down.ps1 -IncludeScheduled
Disable-ScheduledTask -TaskName 'AgenteBolsaScheduler','AgenteBolsaWeb','AgenteBolsaDBMaintenance' | Out-Null
Get-ScheduledTask -TaskName 'AgenteBolsaScheduler','AgenteBolsaWeb','AgenteBolsaDBMaintenance' |
  Select-Object TaskName,State,@{Name='Enabled';Expression={$_.Settings.Enabled}}
```

El bloque no toca procesos Python genericos, otros proyectos, Jetson ni
whale-copy. Tras recibir su salida, hay que verificar en lectura cero tareas
habilitadas, cero escritores/listeners/leases Windows y mantener Windows
conservado siete dias como fallback; solo entonces el dictamen podra ser
`deployed_windows_stopped`.

### P-L90R10E - cierre Fase 5 Windows 2026-08-15 08:33 Europe/Madrid

Dictamen final: `deployed_windows_stopped`. La parada canonica y la
deshabilitacion administrativa se completaron; Windows queda conservado siete
dias como rollback, sin borrar instalacion, `.env`, configuracion, SQLite ni
snapshots.

Verificacion final read-only Windows: `stack_status.ps1` muestra Scheduler,
Web y supervisores `PARADO`. `AgenteBolsaScheduler`, `AgenteBolsaWeb` y
`AgenteBolsaDBMaintenance` aparecen `Disabled`/`Enabled=False`. No hay procesos
Python persistentes del proyecto, listeners en 8080/8081/8501/4002/5000/8000
ni escritor Windows de whale-copy. El laboratorio esta `IDLE`; los eventos de
lease observados estan emparejados y el ultimo es `lease_released`. El lock
`data/state/scheduler.lock` conserva PID `13140`, propietario muerto; se deja
intacto y solo se documenta. Los sidecars SQLite se conservan sin checkpoint,
VACUUM, backfill ni reparacion.

Verificacion final read-only Jetson `192.168.1.186`: systemd permanece activo;
agenteBolsa v0.4.245 ARM64 y whale-copy estan `healthy`,
`RestartCount=0`, `OOMKilled=false`. `/`, `/health`, `/_stcore/health` y
`/kindle` devuelven 200 localmente y por LAN. No se reinicio ni modifico el
Jetson en esta fase.

Se mantienen las receipts de rollback local y remota ya validadas:
`C:\Antonio\Bref\agenteBolsa_backups\jetson-cutover-20260814-1457\receipt.json`
con hash `b33450595512f9d697d3bd4a1767a9586abdec142b22274cb76673e7f7002857`,
y `/home/antonio/agente-bolsa-backups/p-l90r10d-20260814T203544Z/receipt.json`
con hash `98d1ae5c1397d4870966f6c438fbfeedfe598e916ecc8fbcc0955913ddfdadf6`.
No hubo push ni se tocaron Raspberry, whale-copy, ngrok, SQLite historica o
los locks.

### P-L90R10F - preflight ngrok 2026-08-15 09:02 Europe/Madrid

Dictamen: `needs_authority`. El preflight read-only del Jetson esta verde para
los servicios, pero `ngrok` no esta instalado: `command -v ngrok` no encontro
binario, no existe agente/proceso ngrok, no hay unidad systemd ngrok activa y
`127.0.0.1:4040/api/tunnels` no esta disponible. No se han creado tuneles, no
se ha tocado Docker, systemd de agenteBolsa/whale-copy, firewall ni Jetson.

Los destinos confirmados son agenteBolsa `127.0.0.1:8081` (LAN
`192.168.1.186:8081`) y whale-copy `127.0.0.1:8082`; ambos servicios devuelven
HTTP 200 en sus sondas locales. Los cuatro contenedores estan healthy,
`RestartCount=0` y `OOMKilled=false`; las unidades de ambos proyectos siguen
activas. No se ha recibido ni mostrado ningun authtoken.

La documentación oficial vigente indica que el plan Free permite hasta tres
endpoints online y un dominio de desarrollo, por lo que dos endpoints HTTP
son compatibles; tambien advierte del interstitial para tráfico HTML del plan
Free. Se usara un unico agente con dos endpoints y `ngrok start --all` cuando
el binario y el authtoken esten provisionados, sin guardar el secreto en Git o
en este informe.

Accion unica pendiente del operador: instalar el binario oficial ARM64 en el
Jetson desde una terminal con sudo interactivo. No pegar el authtoken en chat;
se provisionara despues por entrada interactiva/secret channel. El bloque
oficial de instalación queda en el relevo técnico. Tras su salida, repetiré
preflight ngrok, creare solo la unidad/configuracion ngrok y validare las dos
URLs desde el exterior.

### P-L90R10F - cierre ngrok 2026-08-15 09:16 Europe/Madrid

Dictamen final: `deployed_ngrok`. Un unico agente ngrok esta `enabled/active`,
con un solo proceso y dos endpoints HTTPS activos:

- agenteBolsa: `https://fbd3-2a0c-5a84-780b-aa00-9951-66f7-f23f-b066.ngrok-free.app`
  -> `http://127.0.0.1:8081`
- whale-copy: `https://43dc-2a0c-5a84-780b-aa00-9951-66f7-f23f-b066.ngrok-free.app`
  -> `http://127.0.0.1:8082`

Comprobacion externa desde Windows, usando el header documentado para saltar el
interstitial HTML del plan Free: agenteBolsa `/`, `/health`, `/_stcore/health`
y `/kindle` respondieron 200; whale-copy `/`, `/ready` y `/health` respondieron
200. La sonda real de agenteBolsa es `/_stcore/health`; `/health` sigue siendo
el shell HTML de Streamlit. La sonda JSON de whale-copy devuelve `healthy`.

La unidad `ngrok-agente-bolsa-whale.service` tiene `MainPID=78942`,
`ExecMainStatus=0`, `Restart=always` y arranque habilitado. Configuracion y
token: `/etc/ngrok/ngrok-auth.yml` y
`/etc/ngrok/ngrok-endpoints.yml`, ambos `root:root 600`; la copia de usuario y
los staging temporales fueron eliminados. El API local de ngrok escucha solo
en `127.0.0.1:4040`; no se abrio firewall ni puertos entrantes.

Los cuatro contenedores permanecen healthy, `RestartCount=0`, `OOMKilled=false`,
las flags PAPER no cambiaron y la sonda de scheduler sigue correcta. No se
reiniciaron Docker, agenteBolsa, whale-copy ni el Jetson. `jetson-ops` es
sintacticamente valido; su alias historico consulta `ngrok.service`, mientras
la unidad operativa real es la unidad ngrok aislada anterior.

Rollback exacto: `sudo systemctl disable --now
ngrok-agente-bolsa-whale.service`; eliminar solo los dos ficheros de
configuracion ngrok si se solicita. Para reactivar: `sudo systemctl enable
--now ngrok-agente-bolsa-whale.service`. No tocar Docker, datos ni los otros
servicios.
