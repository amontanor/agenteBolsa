# Topologia de ramas y nexo comun

Fecha: 2026-10-29. Fuente de verdad para saber de donde debe partir cualquier
tarea nueva y que codigo corre en produccion.

## Regla

- **Nexo comun = `main`**. Toda tarea nueva crea su worktree desde `main` y no
  desde ramas antiguas.
- `main` apunta a la linea de **produccion (Jetson)**. Si una rama necesita
  partir de otra cosa, se declara explicitamente en el encargo.
- Produccion solo se declara `deployed` con la identidad imagen <-> codigo
  verificada (hashes byte a byte), salud doble y recibo de despliegue escrito.

## Lineas existentes (2026-10-29)

| linea | ref | version | estado |
|---|---|---|---|
| Produccion Jetson | `codex/jetson-prod-0.4.393` -> `main` | 0.4.393 | desplegada en el Jetson (`sha256:e490c91e...`) |
| Windows | `codex/astra` | 0.4.255 | integrada en el repo, sin servicio activo |
| Base Jetson previa | `codex/oct19-corrective-integration` | 0.4.381 | ancestro de la linea de produccion |

`codex/astra` y la linea Jetson **no son intercambiables**: divergen cientos de
commits y comparten solo el ancestro `main` antiguo. Un cambio hecho en
`codex/astra` no llega al Jetson sin portarlo y volver a construir imagen.

## Como se materializo la produccion

La imagen del Jetson se construyo con `patch` + `docker build` sobre
`agente-bolsa:0.4.381-arm64`, sin checkout git. El 2026-10-29 se extrajo el
codigo de la imagen, se aplico sobre
`codex/oct19-corrective-integration` (cuyos blobs coinciden exactamente con el
0.4.381 desplegado) y se verifico que los ficheros del commit coinciden byte a
byte con la imagen `0.4.393`. Commit: `c61f96a6`.

## Deuda conocida

- `origin/main` (`59fbffe4`, 2026-10-05) tiene un commit de carga del dashboard
  (`dashboard_loading.py`, `docs/dashboard_loading.md`) que **no** esta en
  ninguna de las dos lineas. No se ha integrado a ciegas.
- `main` local estaba en `8131155c` (2026-05-24), 964 commits por detras; por
  eso las tareas que partian de `main` no veian el trabajo nuevo.
- Ramas de trabajo antiguas (`codex/oct25-*`, `codex/dashboard-port-*`, etc.)
  siguen 300+ commits por detras y no deben usarse como base.
- No hay `push` realizado: `codex/astra` no tiene upstream y la linea Jetson es
  local. Publicar requiere decision del operador.
