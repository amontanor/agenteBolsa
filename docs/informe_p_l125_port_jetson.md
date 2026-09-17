# P-L125 — port del bucle de mejora P-L120..P-L123 a la linea Jetson (0.4.298)

## Dictamen

`deployed` en Jetson (ver cierre). Sin cambios de trading, riesgo, sizing,
broker, ejecucion ni credenciales. Sin backfill ni reescritura.

## Contexto

La linea viva esta en Jetson (`0.4.297-arm64`, sana 28h), fuera del checkout
Windows (0.4.230). La linea Jetson habia relajado gobernanza
(`contract_required_all` por defecto `False`) y trae `lesson_evidence.py` y
`promotion_followup.py` (promocion solo humana, sin auto-aplicacion).

## Port

- Imagen incremental `FROM agente-bolsa:0.4.297-arm64` + 14 ficheros
  (4 nuevos, 10 con inserciones en anclas verificadas 1:1).
- 12/13 hunks directos; 1 adaptado (`revalidate` Jetson evoluciono con
  filtro ACTIVE/WEAKENED propio).
- Error propio intermedio: doble aplicacion del patch duplico el parser
  CLI (`spy-eod-coverage`) y puso los contenedores en restart-loop.
  Rollback inmediato a 0.4.297 (200/200), reconstruccion limpia con
  guarda anti-duplicados y smoke con `build_parser()`. Sin impacto (mercado
  cerrado, 0 ordenes).
- Imagen: `agente-bolsa:0.4.298-arm64`,
  digest `sha256:ec089141ec451e54f8294e47e341fe2cb8101bc84f25b92f16c6b0f36d011edd`.
- Version `0.4.298` + comentario P-L125.

## QA

- `py_compile` de todo el arbol portado.
- Smoke en contenedor temporal sin volumenes: version, imports, parser CLI,
  validacion de contrato, cierre de validaciones y cuadro con veredicto.
- Suite completa Windows (mismo codigo): 2531 passed, 2 preexistentes
  clasificados.
- Salud 1 y 2 (200/200, scheduler 0.4.298 verificado por `docker exec`) y
  observacion OOM 600 s: 0 reinicios, 0 OOMKilled, memoria estable ~5,4 GiB
  libres, whale-copy y copyradar intactos.

## Notas operativas

- `init-db` falla igual en 0.4.297 y 0.4.298 (preexistente, fuera de alcance);
  el despliegue arranca scheduler/web/auxiliary con `--no-deps`.
- `AGENTE_BOLSA_IMAGE` se fija por entorno en la invocacion (los `.env` son
  600/root); release copiado a `/opt/agente-bolsa/releases/0.4.298/deploy/`.
- Rollback: relanzar con `0.4.297-arm64` (imagen conservada).
