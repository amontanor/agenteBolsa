# NVIDIA Jetson Orin — acceso y plan de migración

Fecha de registro: 2026-08-14  
Propósito: conservar los datos operativos del Jetson y la secuencia segura para trasladar agenteBolsa sin mezclar servicios Docker.

## 1. Equipo

- Equipo: NVIDIA Jetson Orin Nano, 8 GB.
- Sistema operativo: Ubuntu 24.04.4 LTS (Noble Numbat).
- Arquitectura: ARM64 / `aarch64`.
- Escritorio: Ubuntu GNOME.
- Sesión gráfica: X11.
- GPU: NVIDIA Orin.
- Driver NVIDIA: 595.78.
- CUDA: 13.2.
- Usuario Linux: `antonio`.

El modelo exacto, JetPack/L4T, Docker y almacenamiento deben verificarse por SSH antes de instalar o desplegar nada.

## 2. Red

| Interfaz | Dirección | Estado/prioridad |
|---|---|---|
| Wi-Fi `wlP1p1s0` | `192.168.1.186/24` | activa; ruta actual |
| Ethernet `enP8p1s0` | `192.168.1.187/24` | preparada, pero actualmente `DOWN` |

- Red prevista: `192.168.1.0/24`.
- Gateway/DNS: `192.168.1.1`.
- La observación actual confirma Wi-Fi activa en `192.168.1.186`; Ethernet no debe darse por disponible hasta ver enlace y dirección.
- Si el Jetson cambia de red, las IP fijas deberán adaptarse.
- Usar Ethernet cuando esté conectado y verificado; mientras tanto, usar `192.168.1.186`.

### Estado de interfaces comunicado por el operador

```text
usuario: antonio
arquitectura: aarch64
wlP1p1s0: UP 192.168.1.186/24
enP8p1s0: DOWN (sin dirección activa observada)
lo: UNKNOWN 127.0.0.1/8 ::1/128
can0: DOWN
l4tbr0: DOWN 192.168.55.1/24 (bridge L4T interno)
usb0: DOWN
usb1: DOWN
docker0: DOWN 172.17.0.1/16
IPv6 global observada en wlP1p1s0:
  2a0c:5a84:780b:aa00:b7b8:e022:d105:f7e4/64
  2a0c:5a84:780b:aa00:8057:bb5c:b7a8:2af5/64
```

`192.168.55.1` pertenece al bridge L4T del Jetson y `172.17.0.1` al bridge
Docker; no son direcciones LAN para publicar los servicios. Antes de elegir
una URL de despliegue hay que confirmar listener, ruta y firewall efectivos.

## 3. Acceso remoto

### SSH

```text
ssh antonio@192.168.1.186
ssh antonio@192.168.1.187   # solo cuando Ethernet esté conectado
```

- Puerto: `22`.
- Usuario: `antonio`.
- La contraseña no se almacena en este documento ni debe aparecer en logs, prompts o informes. Usar el gestor de credenciales o entrada interactiva del operador.
- El acceso automatizable desde Windows ya quedó verificado con una clave
  Ed25519 dedicada (`codex_jetson_ed25519`, privada solo en el equipo local).
  La clave privada no se copia al repositorio ni al Jetson.
- Huella TLS/RDP comunicada por el operador:

```text
2c:c3:06:36:53:61:e2:b1:d2:d7:44:2e:52:0b:36:69:4b:c6:c7:4d:80:68:44:38:06:fc:40:7d:b9:49:06:6d
```

Huellas de host OpenSSH comunicadas por el operador (verificar contra el
servidor antes de aceptar una conexión nueva):

```text
ED25519 MD5:73:81:ac:da:43:ad:f5:ad:f9:4e:c0:5b:a6:49:54:1a
ED25519 SHA256:5VXTgp/+5IhJ8nmFgfL1RUr9qLLLPSRJqH5VOFOBPLI
```

### RDP / escritorio remoto

- Servicio: GNOME Remote Desktop.
- Puerto: `3389`.
- Control remoto habilitado; no es view-only.
- Remote Login configurado y servicio habilitado.
- Desde Windows: `mstsc` → `192.168.1.186` (Wi-Fi) o `192.168.1.187` (Ethernet).
- RDP es opcional para la migración; la administración debe hacerse por SSH.
- No se utiliza Chrome Remote Desktop: el paquete `amd64` no corresponde al Jetson `arm64`.

## 4. Preflight obligatorio del Jetson

Antes de copiar datos, construir imágenes o iniciar servicios, comprobar por SSH:

```bash
cat /proc/device-tree/model
uname -m
free -h
cat /etc/os-release
cat /etc/nv_tegra_release 2>/dev/null || true
docker version
docker compose version
findmnt
lsblk -f
df -h
timedatectl status
```

El preflight debe confirmar:

- SSH autenticado y estable, sin basarse solo en TCP/22.
- `aarch64`, memoria disponible, swap y ausencia de presión crítica.
- Docker/Compose operativos y capaces de ejecutar ARM64.
- Almacenamiento persistente suficiente, preferiblemente SSD, con montaje y UUID identificados.
- Hora/NTP correctos.
- Puertos libres y ningún agenteBolsa previo o scheduler duplicado.
- `PAPER=true`, `live=false` y `auto-apply=false`.
- Ausencia de credenciales en salidas de diagnóstico.

### Resultado del preflight remoto actual

- SSH autenticado: correcto (`antonio`, `aarch64`, hostname `antonio`).
- Docker Engine: `29.1.3`, operativo.
- Docker Compose: instalado y operativo, versión `2.40.3+ds1-0ubuntu1~24.04.1`
  para ARM64.
- Permisos: `antonio` pertenece al grupo `docker` (`gid 111`) y puede consultar
  el daemon sin elevar privilegios.
- Memoria observada: aproximadamente `7,3 GiB` disponibles en el equipo de
  8 GB; almacenamiento libre observado: aproximadamente `424 GiB` en el SSD.
- JetPack/L4T observado: `R39.2.1`.
- Contenedores Docker y agenteBolsa previo: ninguno activo en el Jetson en la
  lectura realizada (`docker ps` vacío).

El bloqueo de preparación del host queda resuelto. La instalación se realizó
desde `ports.ubuntu.com/ubuntu-ports` y quedó registrada; no se instaló ningún
driver ni se modificó el kernel. La siguiente acción es repetir el preflight
completo y comprobar la imagen/Compose de agenteBolsa antes de desplegar.

Si faltan Docker, Compose, credenciales aprobadas o permisos de sistema, el dictamen es `authority_required`/`precondition_not_met`; no instalar paquetes, drivers ni cambiar el kernel a ciegas.

### Estado de staging de la migración

- Rutas privilegiadas creadas en `/opt/agente-bolsa`, `/etc/agente-bolsa` y
  `/var/backups/agente-bolsa`, con ownership comprobado.
- Archivos Compose no secretos transferidos a
  `/opt/agente-bolsa/releases/0.4.242/deploy/`.
- El bundle saneado no contiene SQLite, WAL/SHM, `.env` real ni secretos.
- La imagen ARM64 fue construida y verificada con el commit operativo
  `d4dcb075`/tree `5d311cc`:
  `agente-bolsa:0.4.242-arm64`.
- Digest completo de imagen:
  `sha256:42a7b88d7f4f31c9c434795b8b6eea09ceeed1d27458622db96a71a384303a42`.
- Las rutas persistentes privilegiadas ya están creadas; `application.env` aún
  no existe. No se ha iniciado ningún contenedor y Windows/Raspberry siguen
  disponibles como rollback.
- La comprobación remota `sudo -n true` confirma que la elevación sigue siendo
  interactiva; el agente no puede introducir la contraseña. El provisionado del
  env requiere una única intervención del operador en la consola SSH.
- Dictamen actual: `authority_required`/`precondition_not_met` hasta provisionar
  de forma segura el env real y completar snapshot, configuración y health.

## 5. Artefacto actual de agenteBolsa

La candidata preparada para ARM64 es:

- Versión: `0.4.242`.
- Commit base: `d8629489`.
- Tree base: `9159be36`.
- Commit operativo ARM64: `d4dcb075` (tree `5d311cc`).
- Worktree: `C:\Antonio\Bref\agenteBolsa_worktrees\pl90r10_arm64_oom_guard`.
- Cambio funcional: executor global APScheduler limitado a 2 workers.
- No cambia jobs, cadencias, contratos, trading, riesgo, selección, sizing, exits, política ni credenciales.
- Validación local: `2524 passed`, `1 skipped`, `1 warning`; Ruff, NUL, diff, focales, smoke fake y configuración aislada verdes.

Docker Desktop/WSL no estaba disponible en Windows, por lo que la imagen ARM64 y su digest deben construirse/verificarse en el Jetson o mediante un builder ARM64. No se acepta una etiqueta sin digest, commit y arquitectura comprobados.

## 6. Secuencia de migración

1. Completar el preflight Jetson y registrar versión, commit, tree, imagen, digest, Compose y configuración no secreta.
2. Construir en el Jetson `agente-bolsa:0.4.242-arm64` o verificar una imagen equivalente generada exactamente desde `d8629489`/`9159be36`.
3. Verificar que Compose, aliases, release, labels, digest y contenedores forman una única fuente de verdad.
4. Revalidar la Raspberry `192.168.1.234`, donde el scheduler sufrió OOM/`exit 137`; no asumir que su runtime actual es paritario.
5. Detener canónicamente solo los escritores de agenteBolsa cuando proceda y crear un snapshot frío SQLite con WAL/SHM, `quick_check`, `integrity_check`, hashes y receipt. No hacer backfill, `VACUUM` ni checkpoint manual.
6. Transferir el snapshot validado al almacenamiento del Jetson; comprobar hashes antes de restaurar.
7. Evitar dos instancias agenteBolsa activas. Mantener Windows detenido y cortar la Raspberry solo cuando el snapshot y el Jetson estén listos.
8. Arrancar únicamente el Compose del Jetson con `PAPER=true`, `live=false`, `auto-apply=false`.
9. Verificar raíz HTTP, `/_stcore/health` y `/kindle` con HTTP 200, listener único, scheduler/auxiliary únicos, PID/lock/token/heartbeat, leases terminales y ausencia de `database locked` u órdenes inesperadas.
10. Ejecutar dos healthchecks separados al menos 75 segundos y observar al menos 600 segundos sin OOM, `exit 137`, nuevos reinicios, fallos críticos ni divergencia de Compose/runtime.
11. Dictamen `deployed` solo con identidad, snapshot, paridad y salud demostrados. Si falla, rollback auditable sin `reset`, borrado de locks ni copia de manifiestos.

## 7. Coordinación con `whale-copy` / proyecto BTC

Existe otro proyecto Docker independiente, cuyo agente se encuentra en el proyecto BTC, tarea **“Importar proyecto desde ChatGPT”**.

Reglas para evitar interferencias:

- Las migraciones de agenteBolsa y `whale-copy` no deben ejecutarse en paralelo sobre el mismo Docker host.
- Inventariar en el Jetson cada Compose/proyecto, contenedor, red, volumen, bind, puerto y healthcheck antes de actuar.
- Nunca usar `docker compose down` global ni comandos que afecten a todos los proyectos.
- Usar nombres de proyecto Compose, redes, volúmenes y puertos explícitos y separados.
- Detener temporalmente solo el proyecto identificado y autorizado, registrando su estado, y restaurarlo al finalizar con `/ready`/health 200.
- No mezclar sus datos, rollback, imágenes, credenciales ni informes con agenteBolsa.
- Si ambos proyectos compiten por memoria/CPU/IO, medir cada uno por separado y documentar el efecto; no ocultar un OOM de agenteBolsa deteniendo el otro servicio sin registrar la prueba.

## 8. Seguridad y criterios de cierre

- No guardar contraseñas, tokens, `.env` ni cuerpos sensibles en este documento.
- No hacer push.
- No modificar `kernel.py`, broker, execution, risk, config protegida o `.env` sin autoridad específica.
- No declarar migración completada por el mero hecho de que Docker arranque.
- El cierre debe incluir fecha/XNYS, versión/commit/tree/digest, snapshot, paridad, tests/gates, salud, flags PAPER/live/auto-apply, estado de Raspberry/Windows/whale-copy y omisiones.
