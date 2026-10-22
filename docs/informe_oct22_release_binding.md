# Preparación de binding persistente de imagen —22 octubre 2026

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
