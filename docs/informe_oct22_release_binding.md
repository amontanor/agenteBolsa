### Evidencia de capital recuperada —22oct19:53:46Madrid

Consulta canónica por rango de clave primaria, acotada/deadline, confirma123eventos
capital_allocation_shadow bajo un único policy_hash dc2810dc3b02e79187f9e74abd174dbb79e10e498f83e7598776938ea3bc7977.
Ventana13oct14:03UTC–21oct20:45UTC. Denominadores128BUY/128identidades verificadas,
sin denominadores ausentes y sin saturación. Son registros de recomendaciones,
no128oportunidades independientes ni compras maduras. Recibo
EF99/audit_oct22_capital_readiness_1955.json (hora efectiva en observed_at).
Los recibos de revisión no se escanearon y siguen unavailable, no ausentes.
El primer SELECT por event_type agotó deadline12s; se sustituyó por rango del
prefijo canónico indexado, sin añadir índices ni modificar producción.
No se acredita todavía cobertura de sesiones completas, controles maduros ni
reconciliación/protección. Conservar evidencia, no reiniciar shadow por defecto.

## Prioridad de capital —22oct19:52Madrid

El operador reitera aumentar el tamaño de las compras y reducir cash. Primer
escalón acordado: sustituir máximo fijo1000USD por máximo2,5%equity, manteniendo
15%cartera/3compras por día; después20% y25% con sus gates. Sobre equity de la
captura anterior69900,59USD,2,5%=1747,51USD (+74,75% sobre el tope fijo).
Es un techo: target, multiplicador aplicado una vez, stop, cash, reservas y
riesgo pueden reducirlo. No se garantiza ese importe ni una inversión mínima.

Revisión offline de los ZIP .369 y .376: capital_allocation_policy.py,
capital_ladder.py,position_sizing.py ytrade_decision.py son idénticos byte a byte.
Contrato SHA256 d7c56b25ef0930d0bdcc6e0e277c8f253353f9b87cec2904f01e199aa0eaa078.
Recibo EF99/audit_oct22_capital_contract_identity.json. No invalidar ni reiniciar
el período de evidencia por este despliegue sin otra causa. Tampoco confundir
paridad de código con cinco sesiones completas o aprobación económica.

Ruta comprobada: active_stage_limits sustituye el cap fijo de aprendizaje por
cap proporcional; cap_allocation_notional no vuelve a aplicar multiplicadores.
La etapa2 exige también20compras maduras/15controles por la escalera existente,
además de5sesiones completas,linaje>=95%,reconciliación y recibos canónicos.
El número de sesiones y compras elegibles actuales sigue unavailable: auditoría
readonly inicial falló en handshake SSH. El reintento schedule-status respondió
finalmente19:52:29Madrid: XNYS abierto, PID9/token2646 vivo; runtime unavailable
por WAL no acredita quietud. Se reintenta el colector; sin mutación remota.
Colector preparado EF99/audit_oct22_capital_readiness.py, SELECT acotado/deadline,
sin aprobar ni escribir remotamente. Reintentar con recibo timestamp nuevo.

Automatización existente actualizada y ACTIVE para22oct22:45Madrid, intento
único con pausa al concluir. Incluye recuperación persistente .376, QA restante,
revisión independiente y comprobación concreta de brecha para tamaño mayor.
No activa tamaño/adds/score automáticamente ni permite saltar riesgo/protección.
No se ha desplegado .376 ni activado el cap proporcional en esta continuación.

# Preparación de binding persistente de imagen —22 octubre 2026

## Cierre de revisión del coordinador

Se corrigieron los dos bloqueadores de revisión: se conserva Compose base y
override Raspberry y se añade docker-compose.release-binding.yml como tercera
capa, sin reemplazar puertos, montajes ni recursos. ExecStartPre ejecuta un
verificador host de biblioteca estándar que consulta docker image inspect con
argumentos separados y timeout, y rechaza ImageID/tag/plataforma incorrectos.
Rollback también exige inspect e ImageID independiente de .369.

Se añadió comprobación pura de paridad del Compose renderizado y pruebas que
rechazan cambios en puertos, volúmenes, recursos, entorno y servicios ajenos.
Se rechazan rutas con espacios, tabuladores y especificadores porcentuales de
systemd. El helper solo prepara archivos: no se ha instalado el drop-in.

QA final local del binding: 68 passed en1,74s con intérprete del proyecto,
PYTHONPATH exacto, DATA_DIR temporal, _env_file=None y red externa bloqueada.
Journal EF99/oct22_0376_binding_final_focal.jsonl. Ruff completo src/tests más
los dos scripts pasa, NUL580 y diff pasan. Un I001 de orden de imports se
corrigió; solo se repitió lint, sin repetir las pruebas por ese cambio no semántico.

Los cinco archivos de código protegidos siguen idénticos a la base .369. Los
archivos ENV productivos no se modificaron y sus hashes siguen iguales a la
captura del20. storage.py tiene
el mismo objetoGit d695761735b8cbacd74798d6d2fbc5bb86e65a07 que .369; la
diferencia de hash bruto con el paquete desplegado se debe solo a CRLF/LF,
comprobada byte a byte al normalizar. No se introduce una migración nueva por
este lote. El estado real del esquema y el backup frío siguen siendo gates
del corte; no ejecutar ensure_schema contra producción como preflight.

El harness inicial del digest usó alias Settings incorrectos y alcanzó una
SQLite local del checkout; se detuvieron solo sus procesos QA y se conserva
audit_oct22_local_harness_isolation_failure.json. Las cuatro tablas inspeccionadas
contenían exclusivamente filas fixture (78 señales,64recomendaciones,21órdenes,
1evento), sin acceso al broker ni cambios en Jetson. Ese ensayo queda invalidado.
El harness corregido exige DATA_DIR temporal por alias y verifica la ruta antes
de cualquier escritura. Dos corridas breves con datos temporales separados
reproducen la discrepancia agent_learning productor/CLI en base .369 y .376.
Cada ruta mantiene paridad semántica entre versiones, excluyendo únicamente
digest.as_of y digest.llm_status.as_of. Recibo
EF99/oct22_digest_small_semantic_parity.json. Son78señales sintéticas Windows,
no prueba de volumen ni ARM ni cierre de OOM. El proceso devuelve fallo ante
la discrepancia y nunca se acepta exit0 como sustituto del contenido del recibo.

Pendientes: fullsuite única del árbol final, configuración/smokes, volumen ARM
con digest entero, preflight de cierre y recuperación de kernel con los bytes
aprobados sin resellar. No reutilizar el script de corte .369 que exigía base
.364; preparar recuperación específica con rollback .369 y persistencia del
binding. La clave LLM caducada sigue requiriendo al operador; no la renueva .376.

Las secciones posteriores conservan la historia del lote y sus QA anteriores;
no se suman sus casos ni se hereda su aceptación a una implementación distinta.

### Integración y gates de cierre

Integrado con merge --no-ff en el checkout de ensayo oct19-integration;
HEAD funcional856740a074f7e6ac314abc1cd8339a834af51a78,
tree2311d35f47a7ab330d9d5cf2886c08d69162a715. El worktree auxiliar se movió a
EF99/oct22-release-binding para dejar limpio el candidato; no se borraron datos.
Paridad de objetos src/tests/scripts contra ca5e0262: el merge añade solo docs
del coordinador además de los commits revisados. El candidato reserva .376.

Focales correctivas heredadas de .375 ejecutadas sobre .376:51passed8,04s.
Primer intento19passed/1failed por WinError5 en replace atómico temporal dentro
del sandbox; recibo fallido preservado, reintento motivado fuera del sandbox
pasó. No se suman con las68focales de binding: hay solapamiento de versión.
Ruff completo, NUL580, diff y configuración aislada23agentes/6tareas verdes.
Fullsuite/smokes y cargaARM no ejecutados con mercado abierto.

El evento exacto pmr:pmr_3447a7786ac6:terminal:failed acredita database is locked
en postmarket20,1743,632s; no presentar todos los fallos como OOM. La consulta
inicial por prefijo se interrumpió por deadline10s; se sustituyó por lookup
exacto indexado y se conservó el fallo. No reparaciones en SQLite productiva.

Recuperación pendiente: el script histórico deploy_oct13_0369_cut.py NO sirve
sin revisión, pues espera base .364 y kernel activo ok. No eliminar su guard.
Este incidente tiene autorización específica del operador para resolver la
violación causada por imagen .321 y desplegar después. La preparación debe
verificar los bytes del candidato y rollback .369 contra el manifiesto vigente,
conservar la violación actual en el recibo y usar un procedimiento de recuperación
revisado. No resellar ni montar datos o secretos productivos en contenedores QA.
El corte sigue exigiendo XNYS cerrado, postmarket terminal, quietud real y margen;
la autorización no permite fabricar quietud ni ocultar otro gate fallido.

**Dictamen:** `partially_verified_release_binding_prepared`. XNYS permaneció
abierto durante el lote. Se preparó un helper offline para la futura ventana
cerrada; no se ejecutaron Docker, Compose, SSH, red, systemd, servicios,
producción ni despliegue.

## Causa y contrato

La captura de arranque confirma que `agente-bolsa.service` conserva
`AGENTE_BOLSA_IMAGE=agente-bolsa:0.4.321-arm64` en el `EnvironmentFile` persistente
y que su `ExecStart` hace `up -d` sin servicios explícitos. El Compose activo
resolvió así la imagen antigua aunque el candidato fuese distinto. La solución
conserva `docker-compose.yml` base y `docker-compose.raspberry.override.yml`
originales, y añade `docker-compose.release-binding.yml` como tercer y último
fichero `-f`, con la referencia exacta para `scheduler`, `web` y `auxiliary`.
El drop-in usa `up -d --no-deps scheduler web auxiliary`; `ExecStop` enumera los
mismos servicios y conserva `runtime.env` solo como fuente de entorno del
servicio.

El gate exige un único registro de `docker image inspect`, el `Id` real con
formato `sha256:<64 hex>`, tag exacto `agente-bolsa:0.4.376-arm64`,
`linux/arm64` y coincidencia con el ImageID esperado. `RepoDigests` se conserva
como procedencia de registry independiente; nunca sustituye a `Id`.

La preparación no confía en `Environment=AGENTE_BOLSA_IMAGE`: la tercera capa
fija la imagen y evita que el valor antiguo del `runtime.env` seleccione otra.
El drop-in añade un `ExecStartPre` que ejecuta el verificador host de stdlib.
Este llama `docker image inspect <tag>` con lista de argumentos y timeout,
comprueba tag, ImageID exacto y `linux/arm64`, y falla antes de Compose si el
tag mutable cambió. No arranca ninguna imagen. Rollback usa el mismo verificador
con el ImageID exacto de `.369`, obtenido de su propio inspect obligatorio.
No se edita `.env`, `runtime.env`, el kernel ni los servicios, y no se resella
ningún manifest.

## Implementación

- `src/agente_bolsa/release_binding.py` contiene validación pura, renderizado
  determinista, receipt de identidad y plan explícito de rollback.
- `scripts/prepare_release_binding.py` recibe un fixture/receipt de
  `docker image inspect`, genera artefactos locales y devuelve JSON; no invoca
  Docker, Compose, SSH, systemd ni red.
- `scripts/verify_release_binding.py` es el verificador host autónomo de stdlib
  copiado junto a cada binding; solo inspecciona imágenes y devuelve fallo antes
  del arranque.
- La versión candidata reservada es `0.4.376`.
- Rollback aprobado: `agente-bolsa:0.4.369-arm64`, con override y drop-in
  separados y verificación obligatoria de la imagen antes de usarlo. La imagen
  actual `.321` queda excluida: `kernel-status` confirmó violación en
  `broker.py` y `execution.py`, por lo que no es rollback seguro.

El comando de preparación produce:

```text
docker-compose.release-binding.yml
systemd/agente-bolsa.service.d/10-release-binding.conf
verify_release_binding.py
rollback/docker-compose.release-binding.yml
rollback/systemd/agente-bolsa.service.d/10-release-binding.conf
rollback/verify_release_binding.py
release-binding.json
```

## Evidencia y límites

Base exacta: `53c2c9b26012c9f8135e1238e147932fc339031a`.
Commits funcionales: `b1cdedc0` (`feat`), `59867d0f` (`test`), `878a1bc4`
(`fix`), `de26dbed` (`fix`) y `43a1652e` (`fix`). Árbol funcional probado:
`d480ae8193193649ba6d30175696c25cf9ed025e`.
Worktree aislado:
`oct19-integration/oct22-release-binding`, rama
`codex/oct22-release-binding`. El checkout coordinador
`oct19-integration` conserva sus cambios documentales sin tocar.

QA offline focal:

- `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -m pytest tests/test_release_binding.py -q`: **17 passed** tras el ajuste semántico.
- Ruff focal sobre helper, script y tests: **All checks passed**.
- `git diff --check`: **verde**.
- CLI ejercida con fixtures JSON sintéticos de `.376` y rollback `.369`: generó
  los siete artefactos y receipt con `image_id` separado de
  `registry_repo_digests`.
- Gates negativos cubiertos: identidad ausente, tag faltante, ImageID stale,
  arquitectura/OS incorrectos, referencias malformadas, inyección de rutas y
  rollback no aprobado.

No se ejecutaron suite completa, smoke, broker, LLM, yfinance, mercado,
preflight productivo, Docker, systemd, despliegue ni cambios de configuración.
La aceptación de release queda pendiente de ventana XNYS cerrada, fullsuite y
gates operativos independientes; este lote solo deja preparada la identidad y
persistencia del binding.
