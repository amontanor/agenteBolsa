# Topologia de ramas, releases y despliegue

Fecha: 2026-10-29. Documento de referencia del modelo de trabajo. Las reglas
operativas viven en `AGENTS.md`; esto explica el porqué y el estado real.

## Modelo

- **`main` es el tronco.** Representa la version desplegada en produccion
  (Jetson). Toda tarea nueva parte de `main`.
- Cada lote usa una rama corta `codex/<lote>` en su propio worktree, integrada
  con `merge --no-ff` y cerrada con fast-forward a `main`.
- Cada release se identifica con un tag anotado `prod-jetson-<version>` cuyo
  mensaje contiene: commit, arbol, imagen `sha256:...`, fecha del recibo y
  resultado de la doble salud. Sin tag no hay release.
- El recibo (`data/deployment_receipts.jsonl`) es la prueba que consume la UI:
  version, imagen, `source_head`, `source_tree` y hora Europe/Madrid.

## Estado (2026-10-29)

| ref | version | papel |
|---|---|---|
| `main` | 0.4.393 | tronco y produccion Jetson |
| `codex/jetson-prod-0.4.393` | 0.4.393 | rama de integracion de la release vigente |
| `codex/astra` | 0.4.255 | legado: linea Windows, no desplegable en Jetson |
| `codex/oct19-corrective-integration` | 0.4.381 | base exacta del codigo que corria antes |
| `origin/main` | 0.4.3xx | 1 commit huerfano (`dashboard_loading`), no integrado |

## Como se verifica una release

1. El commit del tag `prod-jetson-<ver>` debe contener el codigo que corre:
   extraer `/app/src/agente_bolsa` de la imagen y comparar `sha256` con el
   arbol del commit. Si no coincide byte a byte, no es la misma release.
2. `docker inspect` da el `image_id` que debe figurar en el recibo.
3. La UI muestra `Despliegue verificado: <fecha>`; si muestra
   «no disponible», falta el recibo.

Asi se cerro el hueco del 29-oct: la imagen 0.4.393 se construyo con parches
sueltos y el codigo solo existia en `/tmp`. Se materializo en el commit
`c61f96a6` sobre `codex/oct19-corrective-integration` (cuyos blobs son
identicos al 0.4.381 desplegado) y se verifico que los 10 ficheros del arbol
coinciden con la imagen `sha256:e490c91e...`.

## Deuda conocida

- `origin/main` (`59fbffe4`, 2026-10-05) contiene un intento anterior de carga
  del dashboard (`dashboard_loading.py`, `docs/dashboard_loading.md`) que no
  esta en `main`. Queda preservado como historia; no se integra a ciegas
  porque P-L158C..G lo sustituye con medicion. Si se publica `main`, este
  commit debe integrarse con `-s ours` para conservar historia sin reimportar
  codigo muerto.
- `codex/astra` (0.4.255) y `main` (0.4.393) divergen: no hay merge entre
  lineas. Portar cualquier cambio de una a otra exige lote propio, pruebas y
  nueva imagen.
- Ramas `codex/oct*`, `codex/dashboard-port-*` y similares siguen 300+ commits
  atras: congeladas. No se borran sin autorizacion del operador.
- No hay push realizado. `main` se publica por fast-forward cuando el operador
  lo pida; nunca con `--force`.
