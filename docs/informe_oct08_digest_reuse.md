# Reutilizacion de lecturas en `ci_digest` — lote N2

## Alcance y dictamen

Este lote aplica una reduccion acotada de memoria y consultas en `ready_for_human_approval_requests`. El helper conserva su contrato legacy: un caller que no entregue listas sigue leyendo propuestas y cambios aplicados con los mismos limites (`50000`), en el mismo orden y con la misma elegibilidad y validacion de provenance. `build_lab_digest` entrega las listas que ya cargo al principio del digest, evitando la segunda materializacion.

El cambio elimina una doble carga concreta. No demuestra ni promete resolver por completo el OOM de `ci_digest`: permanecen otras materializaciones grandes descritas en la auditoria independiente.

## Identidad y aislamiento

- Candidato exacto: `c7619f571b0430a252eba036cd55cffef790557a`.
- Tree del candidato: `4b45e5bb16d9fe1f8b7c5b5c9550a91b3fb49ae3`.
- Worktree nuevo: `C:\Users\utopi\.codex\worktrees\oct08-digest-reuse\agenteBolsa`.
- El worktree queda detached en la infraestructura gestionada. `git status`, `git diff`, `git add` y la creacion de commits fallan con `fatal: this operation must be run in a work tree`, aunque `rev-parse HEAD` y `rev-parse HEAD^{tree}` resuelven correctamente. Por eso no se fabrican hashes de commits.
- Solo se modifican `src/agente_bolsa/continuous_improvement/digest.py`, este informe y el test focal `tests/test_ci_digest_reuse.py`.

## Caracterizacion previa

Un `SpyStore` con una fila fija `READY_FOR_HUMAN_REVIEW`, `tests_ok=true`, `target_paths=["x"]`, una propuesta abierta y un cambio `APPLIED` mostro el comportamiento legacy:

```text
proposals       limit=50000
applied_changes limit=50000
artifacts       limit=200
requests = [{artifact_id: a-open, proposal_id: p-open, targets: [x],
             title: fixed title, updated_at: 2026-10-08T00:00:00+00:00}]
```

Los limites de las lecturas iniciales en `build_lab_digest` son tambien `50000` para propuestas y cambios aplicados; no se introduce cap ni truncado historico.

## Implementacion

`build_lab_digest` pasa `proposals` y `applied_changes` a `ready_for_human_approval_requests` mediante keywords internas. El helper acepta ambos parametros opcionales con `None` como unico sentinel de recarga:

- `None`: mantiene el comportamiento caller legacy y ejecuta la lectura `limit=50000`.
- `[]`: es una lista ya cargada y no provoca recarga.
- lista no vacia: se usa directamente para construir el mapa de propuestas y el conjunto de cambios terminales.

La consulta de artifacts sigue siendo `LIMIT ?` con el `limit` solicitado, conserva `ORDER BY updated_at DESC`, filtra `status`, `tests_ok`, provenance, estados terminales y rollback, y produce el mismo payload completo de `approval_requests`.

Hay una frontera temporal ya existente: el digest carga propuestas y cambios al inicio y el helper legacy los recargaba más tarde. Con reutilización, ambas decisiones usan el snapshot inicial del digest. El código tampoco ofrecía atomicidad entre lecturas separadas; bajo escrituras concurrentes no se afirma paridad de elegibilidad sin una prueba de concurrencia. `approval_requests` solo prepara propuestas para revisión humana; no concede autoridad de apply y las guards reales siguen revalidando el estado antes de aplicar.

## Verificacion focal

`tests/test_ci_digest_reuse.py` cubre:

1. Paridad exacta del payload completo, incluyendo `approval_requests`, entre llamada legacy y llamada con listas precargadas.
2. Que una lista vacia precargada no active una recarga.
3. Paridad del digest completo con una fixture fija: el modo base fuerza al helper legacy y el modo reuse usa las listas entregadas por `build_lab_digest`; ambos diccionarios son iguales.
4. Conteo de consultas: el modo base hace dos lecturas de propuestas y cambios aplicados; el modo reuse hace una de cada una. En ambos se mantiene una lectura de artifacts.

Comandos y resultados:

```text
PYTHONPATH=C:\Users\utopi\.codex\worktrees\oct08-digest-reuse\agenteBolsa\src
DATA_DIR=<vacio>
C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -m pytest -q tests/test_ci_digest_reuse.py
... [100%]  (3 passed; el runner Windows queda abierto despues del resumen y se interrumpio manualmente)

C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -m ruff check --no-cache \
  src\agente_bolsa\continuous_improvement\digest.py tests\test_ci_digest_reuse.py
All checks passed!

C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8'), filename=p) for p in ['src/agente_bolsa/continuous_improvement/digest.py','tests/test_ci_digest_reuse.py']]; print('ast ok')"
ast ok
```

No se ejecutaron suites largas, smoke, broker, LLM, red, SSH ni producción. El cambio no toca schema, configuración, límites históricos ni módulos protegidos.


## Cierre por dirección técnica

El acceso con revisión automática al gitdir resolvió el fallo del sandbox.
Rama codex/oct08-digest-reuse, commit funcional/QA
9a05e6cf698501a4e9e2a342c00483afd78bb153, tree
07c7239e9b59554111b09a8f3052a865977943a8. Reserva aislada0.4.349 y pin
coherente; no equivale a despliegue. El candidato inicial c7619f57 es la base,
no el HEAD funcional final. El worktree solo mantiene este informe pendiente
antes del commit documental de cierre.

La dirección no hereda como gate el runner interrumpido del autor. Ejecutó una
batería nueva por esa causa, con Python del proyecto, PYTHONPATH exacto,
DATA_DIR temporal, Settings con _env_file=None y bloqueo de red externo en
validate_oct08_isolated.py. Resultado terminal exit0:24passed en10.45s,
incluyendo reuse,phase3digest,digestP4,overlayshadow ypin de versión. Journal
local goal_fix_digest_reuse_journal.jsonl; salida goal_fix_digest_reuse_focal.txt.
Ruff focal ygit diff--check verdes. No suite completa,smoke ni producción.

La reducción probada es de dos lecturas/materializaciones, no una reducción
cuantificada de RSS productivo ni solución definitiva del OOM. Permanecen
las lecturas de contexto/control, históricos y serialización del digest.
No se afirma paridad bajo escrituras concurrentes: approval_requests usa las
listas del inicio; es una salida para revisión humana, no una instrucción
de aplicar. Ninguna ruta de apply se cambia con este lote.
