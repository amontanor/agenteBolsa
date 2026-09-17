# Despliegue autonomo en Jetson (procedimiento verificado P-L125)

Destino: `antonio@192.168.1.186` por SSH, Docker. Verificado el 2026-09-17
con el port 0.4.297 -> 0.4.298.

## Requisitos previos (una sola vez)

- Clave Ed25519 dedicada en el equipo local (`~/.ssh/codex_jetson_ed25519`).
  No se copia al repositorio ni al Jetson.
- `antonio` con sudo sin contrasena en el Jetson
  (`/etc/sudoers.d/antonio-nopasswd`). Sin esto, los pasos con `sudo -n`
  fallan y hay que pedir consola al operador.
- `BatchMode=yes` en SSH: nunca pedir contrasena ni aceptar huellas nuevas
  a ciegas (verificar contra las del documento de acceso).

## Reglas de seguridad

- Solo lectura primero: `docker ps`, `docker inspect`, `docker logs`,
  `free`, `dmesg`. Nada se toca sin preflight.
- Jamas `docker compose down` global ni comandos sobre todos los proyectos
  (convive con `whale-copy` y `copyradar`).
- Jamas `docker run` con la imagen de produccion para "mirar dentro":
  el entrypoint arranca el sistema. Para inspeccionar: `docker create` +
  `docker cp` (no arranca nada). Los contenedores temporales se eliminan.
- Rollback = relanzar con la imagen anterior (se conserva siempre).
- Prohibido: tocar `/etc/agente-bolsa/*.env` (600/root), credenciales en
  logs/informes, `VACUUM`/checkpoint/backfill sobre SQLite viva.

## Secuencia de despliegue de una nueva version

1. Preflight read-only: `hostname`, `uname -m`, `docker ps`,
   `free -m`, `df -h`, version/imagen de `agente-bolsa-*-1`.
2. Extraer fuente de la imagen viva a `/tmp` (`docker create` + `docker cp`).
3. Aplicar cambios con `patch -p1` (falla en voz alta ante conflicto real;
   jamas aplicar dos veces: verificar duplicados con `grep -c` antes de
   construir). `py_compile` de todo el arbol.
4. Subir version en `src/agente_bolsa/__init__.py` con comentario del lote.
5. Construir imagen incremental `FROM <anterior>` + solo ficheros cambiados:
   `docker build -t agente-bolsa:<ver>-arm64 .`. Registrar digest.
6. Smoke en contenedor temporal sin volumenes y con entrypoint anulado:
   `docker run --rm --entrypoint python3 -v /tmp/qa.py:/tmp/qa.py
   <imagen> /tmp/qa.py` con: version, imports, `build_parser()` (detecta
   subparsers duplicados), validacion pura de contrato y cuadro con veredicto.
7. Copiar `deploy/` a `/opt/agente-bolsa/releases/<ver>/deploy/` (auditoria).
8. Arrancar (init-db falla preexistente: usar `--no-deps`):
   `cd /opt/agente-bolsa/releases/<base>/deploy &&
   sudo -n AGENTE_BOLSA_IMAGE=agente-bolsa:<ver>-arm64 docker compose
   --env-file /etc/agente-bolsa/runtime.env up -d --no-deps scheduler web auxiliary`
9. Salud 1: `docker ps` (imagen nueva), web `:8081/` y `/_stcore/health`
   HTTP 200, version por `docker exec <scheduler> python3 -c`.
10. Salud 2 a +75 s y observacion OOM 600 s: `RestartCount=0`,
    `OOMKilled=false`, `free -m` estable, `dmesg` sin OOM, vecinos intactos.
11. Dictamen `deployed` solo con todo lo anterior. Informe unico del lote.

## Lecciones P-L125

- El `patch` doble aplico `main.py` dos veces y causo restart-loop;
  se detecto por `docker logs` (argparse) y se hizo rollback en minutos.
- La linea Jetson trae `lesson_evidence.py` / `promotion_followup.py`
  (promocion solo humana) y `contract_required_all` por defecto `False`:
  antes de portar, comparar filosofias, no solo codigo.
- Puerto Jetson `:8081` -> contenedor `:8501` (no `:8501` en el host).
