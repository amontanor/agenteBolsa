# Auditoría de memoria `ci_digest` — 8-oct-2026

## Dictamen

`needs_fix`. Existe evidencia productiva de que el auxiliar lanzó el digest
diario y terminó con `returncode=-9` dentro de un cgroup de 256 MiB. El código
del commit auditado conserva varias lecturas históricas materializadas y
serializa el digest completo; esto constituye una causa probable y reproducible
de un pico de memoria superior al margen disponible. La causa exacta del kill,
la consulta o la asignación que cruzó el límite no queda demostrada por las
evidencias actuales.

La corrección mínima debe acotar memoria mediante lectura por lotes y
acumuladores, reutilizar las lecturas ya cargadas y reducir el sobrecoste de la
respuesta JSON del supervisor, conservando todos los datos históricos,
denominadores y campos económicos/de aprendizaje. No recomiendo recortar por
fecha, limitar más los historiales ni descartar outcomes para ocultar el OOM.

## Identidad, alcance y operación

- Base auditada: `52cc0fa5921ff690cfec4d08d5eda5c9c1bbccb1`.
- Tree de base: `28a76ff51aa66139c02700ce0f86789842b51b4c`.
- Versión del commit: `0.4.348`.
- Worktree aislado: `C:\Users\utopi\.codex\worktrees\oct08-digest-memory-audit\agenteBolsa`.
- Worktree creado desde el objeto exacto; queda detached en la infraestructura
  gestionada. La consulta `git status` de estos worktrees devuelve
  `fatal: this operation must be run in a work tree`, por lo que el estado Git
  no puede declararse limpio con esa orden. No se modificaron fuentes,
  configuración, locks, histórico ni producción.
- Contexto comunicado: 8-oct, XNYS cerrado; PMR de 8-oct sin terminal, sin
  autorización para fullsuite, smoke u operación. Producción sigue en `.321` y
  `auxiliary` unhealthy.

La evidencia local disponible en
`C:\Users\utopi\.codex\worktrees\ef99\agenteBolsa\goal_fix_auxiliary_*.txt`
registra:

- límite del auxiliar: `268435456` bytes; swap límite `536870912`;
- `ci_digest` inició a `2026-10-08T06:30:00Z` y el supervisor registró a
  `06:34:35Z`: `ERROR RuntimeError: ci_digest devolvio returncode=-9`;
- `memory.events`: `max 13008`, `oom 14`, `oom_kill 1`, `oom_group_kill 0`;
- `auxiliary` seguía vivo con heartbeat fresco; lectura posterior mostró
  `11.54MiB / 256MiB` para ese contenedor.

Estos datos son compatibles con que el hijo one-shot de `ci_digest` fuese
matado por presión de memoria. `oom_kill=1` es contador agregado del cgroup y
no identifica por sí solo el proceso ni la línea causante. No hay traceback de
Python ni medición de RSS por fase en el registro, así que no se afirma una
causa exacta. El informe histórico `docs/informe_p_l141_port_jetson.md:141`
atribuye otro incidente de septiembre a `database or disk is full`; no es
evidencia causal para este OOM de octubre.

## Hechos de código

### Importación de la CLI

`src/agente_bolsa/main.py:18-149` importa eagermente el digest, scheduler,
broker, ejecución, backtests, aprendizaje, estudios, reporting y varias rutas
de herramientas antes de resolver el subcomando. Una medición aislada, sin
SQLite ni servicios, trazó durante `import agente_bolsa.main`:

```text
main_import_current_bytes=86812948
main_import_peak_bytes=94803241
```

Es memoria Python trazada, no una lectura de RSS productiva; demuestra que el
proceso nace con un presupuesto importante ya consumido.

### Materialización principal del digest

`build_lab_digest` carga cuatro listas con `limit=50000`
(`src/agente_bolsa/continuous_improvement/digest.py:86-89`): propuestas,
experimentos, applied changes y decisiones. Los lectores de `storage.py`
ejecutan `fetchall()` y deserializan cada `payload_json`
(`storage.py:6679-6763`, `storage.py:7736-7784`, y
`storage.py:7817-7850`). Más adelante vuelve a cargar artifacts con
`limit=50000` (`digest.py:241`; `storage.py:7255-7279`). Los límites son
ventanas máximas por tabla, no garantías de memoria acotada.

Mientras esas listas siguen vivas, el digest llama:

- `build_decision_context_quality` (`digest.py:245`), que materializa hasta
  50.000 recomendaciones, 50.000 planes, 200.000 observaciones y 200.000
  outcomes (`tools/decision_context.py:440-448`). Sus lectores hacen
  `fetchall()` y cargan JSON completo (`storage.py:3206-3232`,
  `storage.py:3473-3498`, `storage.py:4738-4781`, `storage.py:4964-5014`).
- `build_comparable_control_quality` (`digest.py:246`), que vuelve a leer hasta
  50.000 recomendaciones y 200.000 outcomes y crea `outcomes_by_id`
  (`tools/comparable_controls.py:741-779`).
- `build_research_mode_usage` (`digest.py:230`), que lee hasta 5.000 ciclos y
  luego hace `llm_usage ... ORDER BY created_at DESC` sin `LIMIT`, seguido de
  `fetchall()` (`digest.py:770-845`). Su ventana temporal reduce el dominio
  lógico, pero no garantiza una lectura físicamente acotada.
- `ready_for_human_approval_requests` (`digest.py:158`), que vuelve a cargar
  propuestas y applied changes con `limit=50000` (`digest.py:862-870`) mientras
  las copias de `build_lab_digest` siguen retenidas. Esta duplicación ocurre
  aunque la salida final sólo conserva una proyección pequeña por solicitud.
- `performance_daily(limit=0)` (`digest.py:201-205`). En
  `storage.py:5781-5817`, `limit=0` omite la cláusula `LIMIT` y hace
  `fetchall()` de todo el histórico.

Además, los digests de telemetría canónica y learning shadow leen ventanas de
`agent_events` de hasta 50.000 (`tools/canonical_operation_telemetry.py:642`,
`storage.py:2506-2562`; `storage.py:2569-2613`). `build_agent_run_productivity`
usa `iter_agent_events` por lotes (`agent_run.py:342-356`), lo cual es una
garantía positiva; su estado por `agent_run_id` sigue reteniendo un resumen por
run y no resuelve las listas anteriores.

### Salida del hijo y supervisor

El comando `continuous-improvement-lab digest --out ... --json` siempre incluye
el digest completo en `_print_json` (`main.py:3278-3294`), incluso cuando ya
escribió el Markdown solicitado. `json.dumps(..., indent=2)` crea otra
representación grande.

El supervisor ejecuta el hijo con `stdout=subprocess.PIPE`, conserva todo
`result.stdout`, lo escribe al log y después hace `json.loads(result.stdout)`
(`docker_supervisor.py:209-232`). Una caracterización sintética local con una
respuesta JSON de 10.000.024 bytes midió un pico trazado de `30.002.905`
bytes en `_run_json_command`: salida capturada, parseo y temporales de
serialización coexisten. No es una medición del digest real, pero demuestra el
factor de amplificación del sobre de stdout en el proceso padre.

## Caracterización focal

Sin red, broker, LLM, servicios ni SQLite productiva:

1. Un fake `Store` con cinco listas de 5.000 filas y payload de 4 KiB por fila
   pasó por `build_lab_digest` con helpers externos neutralizados. Con la
   asignación de fixtures incluida, `tracemalloc` observó `peak=120142159`
   bytes para 25.000 filas retenidas. El caso es sintético y no pretende
   extrapolar un RSS productivo; muestra que el patrón de retención escala con
   filas y payload.
2. `build_decision_context_quality` con 50.000 filas mínimas por cada una de
   sus cuatro fuentes (200.000 filas totales, menor que sus límites efectivos
   de 500.000) alcanzó `peak=275895833` bytes. No se usaron payloads grandes.
   Con payloads reales y el import eager, el margen de 256 MiB queda agotado
   antes de completar el resto del digest.
3. La medición de importación y la del supervisor anteriores son
   caracterizaciones locales de asignaciones Python, no pruebas de que una
   función concreta haya recibido el kill productivo.

## Hechos frente a hipótesis

Hechos:

- hubo un `SIGKILL` observado como `returncode=-9` durante el run de `ci_digest`;
- el cgroup registró `oom=14` y `oom_kill=1` con límite de 256 MiB;
- el auxiliar residente continuó vivo y con heartbeat fresco;
- el proceso hijo ejecuta una CLI con importación eager, lecturas `fetchall()` y
  respuesta JSON completa;
- las caracterizaciones reproducen picos que superan 256 MiB con límites y
  payloads sintéticos modestos.

Hipótesis fuerte, pendiente de fase/RSS productiva: el hijo cruzó el límite por
el pico combinado de importación, materialización de fuentes de aprendizaje,
duplicados temporales y serialización JSON. Los candidatos principales son
`build_decision_context_quality`, `performance_daily(limit=0)`, la recarga de
`ready_for_human_approval_requests` y el JSON completo; `llm_usage` sin límite
es un riesgo adicional.

No demostrado:

- qué consulta o fase fue última antes del kill;
- tamaño real de cada tabla/payload en la SQLite productiva a las 06:30Z;
- si `memory.events` fue incrementado exactamente por este hijo y no por otro
  proceso del cgroup;
- que el sitio, una cabecera, SQLite o `docker_supervisor` sean por sí solos
  la causa raíz.

## Mínimo acotado propuesto

Lote N2, sin tocar kernel, riesgo, broker, configuración protegida, política
activa ni histórico:

1. Añadir lectores internos por lotes (`fetchmany`) para las fuentes grandes y
   acumuladores equivalentes. En `decision_context`, contar cobertura,
   conflictos y contaminación por fuente sin conservar `records` y
   snapshots completos. En `comparable_controls`, conservar sólo el mapa
   mínimo `signal_id -> matured_horizons` necesario para madurez y recorrer
   recomendaciones/outcomes por lotes. Esto conserva denominadores y datos
   históricos; cambia la estrategia de materialización, no la selección de
   filas.
2. Pasar las listas ya cargadas de propuestas/applied changes a
   `ready_for_human_approval_requests` o extraer sólo sus IDs/estados una vez,
   eliminando la segunda lectura concurrente. Mantener la misma semántica de
   estado, provenance, targets y exclusiones.
3. Hacer que `performance_daily` use un iterador o una consulta agregada
   incremental cuando `limit=0` signifique “todo”; no convertirlo en un límite
   menor. Para `llm_usage`, agregar por SQL dentro de la ventana y ciclo o
   recorrer con `fetchmany`, preservando las mismas sumas y coste.
4. Para la invocación auxiliar con `--out`, devolver un sobre JSON pequeño
   (`ok`, `path`, estado/resumen) o una variante explícita de salida resumida;
   conservar el digest Markdown completo en el artefacto. El contrato CLI
   general debe seguir pudiendo pedir el digest completo. Así se elimina la
   copia padre de stdout sin truncar el informe.

Pruebas focales antes de integración:

- comparar resultado base y candidato sobre SQLite temporal con filas justo en
  los límites de chunk, incluyendo oldest/newest, payloads legacy, snapshots
  faltantes, outcomes maduros/inmaduros, conflictos y control sets. Comparar
  denominadores, hashes de snapshots, estados de learning, cobertura y todos
  los campos económicos; verificar que no desaparece la fila histórica más
  antigua;
- comparar `build_decision_context_quality` y
  `build_comparable_control_quality` materializado frente a streaming con
  fixtures pequeñas, sin recortar histórico, y probar que una excepción de
  lectura mantiene el estado fail-open existente;
- probar que una tabla `performance_daily` con más filas que el chunk conserva
  la misma serie y resumen, y que `llm_usage` conserva tokens/coste;
- probar `ci_digest --out --json` y `_run_json_command` con stdout grande: el
  artefacto completo permanece íntegro, el sobre resumido sigue siendo JSON
  válido y no hay truncamiento silencioso;
- medir RSS/tracemalloc por fase en un test focal o harness local con fixtures
  temporales. No ejecutar una suite completa, smoke operativo, broker, red,
  LLM, SSH, despliegue ni producción en esta ventana.

El primer lote debe instrumentar fase y RSS para confirmar el orden del pico.
Sólo después de esa medición se debe elegir entre streaming de
`decision_context`, eliminación de duplicados y sobre de stdout como cambio
funcional separado. El `returncode=-9` actual justifica endurecer memoria, pero
no autoriza afirmar una causa exacta ni desplegar.

## Validación y entrega de esta auditoría

- Lectura estática de `main.py`, `continuous_improvement/digest.py`,
  `storage.py`, `docker_supervisor.py` y consumidores auxiliares.
- Caracterizaciones sintéticas descritas arriba, Python del proyecto y
  `PYTHONPATH` del worktree exacto.
- No se ejecutaron fullsuite, smoke, `run-once`, postmarket, reconciliación,
  broker, red, LLM, SSH, Docker productivo, reinicio, merge ni push.
- No se modificaron archivos protegidos, configuración, versión, política,
  datos ni servicios. Este archivo es el único artefacto de la auditoría.


## Conservación por dirección técnica

La dirección repitió git status con el acceso al gitdir necesario: el árbol
tenía únicamente este informe untracked y HEAD detached52cc0fa5. Creó la rama
codex/oct08-digest-memory-audit sin cambiar base ni fuentes y conserva el
informe en commit documental. El fallo de status anterior era del acceso del
sandbox, no evidencia de corrupción del worktree. Los scripts de medición y
comandos reproducibles se han solicitado al autor; hasta recibirlos, las cifras
de tracemalloc se consideran evidencia comunicada y no reproducción propia.

## Propuesta posterior: lectura incremental de decision_context_quality

Auditoría independiente sobre fuente exacta7dce37e1 (HEAD documentalb15e5531):
la función conserva cuatro listas históricas, records, rec_snapshots y snapshots.
Propuesta futura no implementada ni integrada: iteradores fetchmany que devuelvan
diccionarios idénticos a los lectores legacy y acumuladores para coberturas;
first_hash_by_id más conflicted_ids para contar IDs con hashes distintos.
No reducir límites50000/50000/200000/200000, cambiar filtros, mover recent antes
del LIMIT, omitir campos o alterar orden/denominadores/históricos.

Antes de implementar se debe fijar contrato de snapshot: hoy las cuatro consultas
no comparten transacción. Una transacción común daría consistencia distinta bajo
escrituras y podría retener WAL más tiempo. Paridad sobre base estable no prueba
paridad temporal concurrente. Caracterización necesaria: payload completo contra
algoritmo anterior, diccionarios/orden exactos por reader, límites mayores que
batch_size, recursos/cierre ante error e interrupción, concurrencia determinista
y memoria sintética con comandos reproducibles. No hay mediciones nuevas de RSS
ni se afirma resuelto el OOM. La propuesta queda separada del candidato.352 ya
probado; no modifica su fuente ni sustituye los gates pendientes.
