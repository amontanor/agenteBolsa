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
Un receipt válido debe usar el schema `p-l89.sqlite-cold-snapshot.v1`, incluir
`quick_check=ok`, `integrity_check=ok`, hostname, montaje, UUID y SHA-256, y se
verifica localmente mediante `--sqlite-receipt` contra el fichero snapshot real,
su tamaño y sus sidecars.
La herramienta `scripts/sqlite_cold_snapshot.py` queda preparada para la
ventana autorizada: exige `--writers-stopped`, no sobrescribe, no ejecuta
`VACUUM`/checkpoint/backfill, copia la base y sidecars presentes, valida la
copia y escribe el receipt dentro del directorio nuevo. No se ejecutó sobre la
Raspberry en este lote.
