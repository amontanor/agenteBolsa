# Auditoria N2: memoria de artifacts de origin utility

Fecha de medicion: 2026-10-10 (Europe/Madrid). Checkout aislado:
`C:\Users\utopi\.codex\worktrees\bolsa-origin-memory-oct10\agenteBolsa`.

Base de trabajo: commit `1a3333a49db77898cecf1670813b4e23d445ac00`.
La rama de trabajo es `codex/oct10-origin-memory`; no se modifico produccion,
configuracion, schema, aprobacion, aprendizaje, candidatos, scores, gates,
economia, broker, riesgo ni los worktrees protegidos.

## Cambio acotado

`Store.iter_continuous_improvement_proposal_artifact_summaries` en
`src/agente_bolsa/storage.py:7458` ejecuta la misma consulta de artifacts con
`ORDER BY updated_at DESC LIMIT ?`, pero proyecta solamente `proposal_id` y
`payload_json`. Lee con `_decision_context_read_connection`, mantiene
`PRAGMA busy_timeout=30000` y `PRAGMA query_only=ON`, consume por `fetchmany`
de 512 filas y cierra cursor y conexion en exito, error SQL/JSON y cierre
temprano del generador.

La consulta se ejecuta una sola vez en una conexion, cursor y snapshot. El
iterador lee por `fetchmany` de 512 filas y decodifica cada `payload_json` al
avanzar; `drain()` consume el resto del mismo cursor cuando debe diferirse un
error del consumidor. Asi un JSON/SQL invalido posterior conserva prioridad
sobre un fallo del consumidor del primer payload, y un fallo de propuesta se
produce despues de drenar la lectura de artifacts, como en el lector completo.
Ningun `content_text` ni lista completa de payloads se conserva en memoria; no
se repite la consulta ni se abre un segundo snapshot. `close()` cierra cursor y
conexion y vacia tambien las filas del ultimo lote; hay regresiones para cierre
normal, temprano y por error.

El lector completo `continuous_improvement_proposal_artifacts` no cambia.
`build_lab_digest` selecciona la proyeccion en
`src/agente_bolsa/continuous_improvement/digest.py:65` y conserva fallback al
lector completo cuando un fake o Store antiguo no expone la API nueva. El
consumidor solo usa el `proposal_id` y `payload.status`/`payload.tests_ok` que
ya usaba; mantiene la identidad literal `tests_ok is True`, cuenta duplicados
en el mismo orden de lectura y descarta IDs sin propuesta coincidente.

La ruta de aprobacion humana sigue seleccionando `content_text` en
`ready_for_human_approval_requests` (`digest.py:869`). Una regresion prueba que
el texto completo sigue produciendo `src/demo.py` como target. No se trunca ni
resume stdout en este lote.

## Evidencia de paridad y errores

`tests/test_origin_artifact_projection.py` cubre:

- JSON nulo/falsy (`None`, cadena vacia, `0`, `false`) y literales JSON
  `0`/`false`/`null`, conservando la expresion previa `or "{}"`.
- orden recibido, parametro `LIMIT`, ties, batch `fetchmany`, proposal ID
  ausente, duplicado y no coincidente.
- fallos sinteticos de SQL, PRAGMA/setup y decode JSON, con cierre verificable
  de cursor/conexion; tambien cierre temprano del generador.
- precedencia de decode: un primer payload JSON-lista y un segundo JSON invalido
  producen `JSONDecodeError` antes de cualquier `.get` del consumidor; tambien
  se verifica que el mismo cursor se drena antes de un error en proposals y que
  un error del consumidor se difiere hasta cerrar/drainar ese cursor.
- equivalencia de los campos proyectados con el lector completo en la misma
  base SQLite temporal y preservacion de `content_text` para aprobacion.
- consumo de generador, verdad literal de `tests_ok`, y fallback de fakes sin
  la API nueva.

Comando final de regresion (salida y exit code persistidos en
`docs/artifacts/oct10_origin_focal_pytest.log`):

```text
C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -m pytest -q tests/test_origin_artifact_projection.py tests/test_ci_digest_reuse.py tests/test_improvement_origin_lineage.py
39 passed in 2.43s
exitcode=0
```

El script `scripts/measure_origin_memory_oct10.py` conserva la comparacion
contra el lector completo de la base, no contra dos rutas nuevas solamente.
Usa `git show` de bytes sin normalizar y escribe sus hashes en
`docs/artifacts/oct10_origin_memory_measurement.json`:

- blob bruto del lector base: `da8e3ebc081a210995415dfb664fd342203aff95563e562d80fb0d3224759d67`;
- AST del lector completo base y actual: ambos
  `090946ae7abca6f1e2a73299602bd6f5591ab77282efcfc99e40d51f2a1086d0`;
- AST de `build_origin_utility_metrics` base:
  `e382450264f98531ca8c4f7d213aad572d8fb47ca72bccf8af0fed252b76bd18`;
- AST actual de `build_origin_utility_metrics`:
  `f5909acdf7689b607d82e411efe68778c83cde87dcaa4b34b2a8d6b435243572`;
- AST de la nueva proyeccion:
  `841b8d70905b8c9b76d5abf0c3ed4bacfc1a536d13930bcb5b5ff239b78a172b`;
- blob bruto actual de `storage.py`:
  `9be1c91a4112fbe34be6227856f8a2e86f4d8983`.

## Medicion local

Se crearon 16 artifacts temporales con `content_text` sintetico de 262144
bytes cada uno (4,194,304 bytes totales). Cada modo corrio en un proceso
hijo efectivo con `sys.executable` y `sys.prefix` del entorno del proyecto,
instalando antes de importar `agente_bolsa.storage` guards para
`socket.socket`, `socket.create_connection`, `socket.getaddrinfo` y
`socket.gethostbyname`. No se construyo `Settings` ni se consulto `_env_file`;
no hubo broker, LLM ni consulta de produccion.

| modo | PID | filas | content retenido | pico tracemalloc |
| --- | ---: | ---: | ---: | ---: |
| lector completo | 25560 | 16 | 4,194,304 B | 4,221,673 B |
| proyeccion | 49704 | 16 | 0 B | 17,376 B |

La medicion acredita que esta ruta no materializa `content_text` en el
proceso medido. Es una fixture pequena y `tracemalloc`, no RSS de Windows ni
memoria cgroup; no demuestra que el OOM productivo este resuelto. El lector
proyectado aun decodifica cada `payload_json`, y el digest sigue cargando otras
listas de 50000/200000 filas fuera de este lote. El artifact declara tambien
que la limpieza del SQLite temporal es best-effort porque el lector completo
conserva su comportamiento de conexion existente hasta terminar el proceso.

## Dictamen

El cambio minimo reproducible es una proyeccion separada y por lotes para
origin utility, con cierre explicito y fallback legacy. La paridad de orden,
limite, payload, IDs y aprobacion humana queda cubierta por pruebas y por la
comparacion contra el lector base. El resultado reduce el objeto grande
`content_text` de esta rama del digest, pero deja como hotspots independientes
la materializacion de propuestas/experimentos/applied y el decode de payloads;
no se afirma resolver el OOM de produccion ni se propone elevar el limite como
sustituto.
