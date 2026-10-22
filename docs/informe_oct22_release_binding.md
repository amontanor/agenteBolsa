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
prepara una capa de override con la referencia exacta de release para
`scheduler`, `web` y `auxiliary`, y un drop-in con rutas absolutas de ambos
ficheros Compose y `up -d --no-deps scheduler web auxiliary`. `ExecStop` enumera
los mismos servicios y conserva el `runtime.env` solo como fuente de entorno del
servicio.

El gate exige un único registro de `docker image inspect`, el `Id` real con
formato `sha256:<64 hex>`, tag exacto `agente-bolsa:0.4.376-arm64`,
`linux/arm64` y coincidencia con el ImageID esperado. `RepoDigests` se conserva
como procedencia de registry independiente; nunca sustituye a `Id`.

La preparación no confía en `Environment=AGENTE_BOLSA_IMAGE`: el override fija
la imagen y evita que el valor antiguo del `runtime.env` seleccione otra. No se
edita `.env`, `runtime.env`, el kernel ni los servicios, y no se resella ningún
manifest.

## Implementación

- `src/agente_bolsa/release_binding.py` contiene validación pura, renderizado
  determinista, receipt de identidad y plan explícito de rollback.
- `scripts/prepare_release_binding.py` recibe un fixture/receipt de
  `docker image inspect`, genera artefactos locales y devuelve JSON; no invoca
  Docker, Compose, SSH, systemd ni red.
- La versión candidata reservada es `0.4.376`.
- Rollback aprobado: `agente-bolsa:0.4.369-arm64`, con override y drop-in
  separados y verificación obligatoria de la imagen antes de usarlo. La imagen
  actual `.321` queda excluida: `kernel-status` confirmó violación en
  `broker.py` y `execution.py`, por lo que no es rollback seguro.

El comando de preparación produce:

```text
docker-compose.raspberry.override.yml
systemd/agente-bolsa.service.d/10-release-binding.conf
rollback/docker-compose.raspberry.override.yml
rollback/systemd/agente-bolsa.service.d/10-release-binding.conf
release-binding.json
```

## Evidencia y límites

Base exacta: `53c2c9b26012c9f8135e1238e147932fc339031a`.
Commits funcionales: `b1cdedc0` (`feat`), `59867d0f` (`test`) y `878a1bc4`
(`fix`). Árbol funcional probado: `ed96cba37bfb14e25380b2be96d051183a6f22c8`.
Worktree aislado:
`oct19-integration/oct22-release-binding`, rama
`codex/oct22-release-binding`. El checkout coordinador
`oct19-integration` conserva sus cambios documentales sin tocar.

QA offline focal:

- `C:\Antonio\Bref\agenteBolsa\.venv\Scripts\python.exe -m pytest tests/test_release_binding.py tests/test_p59c_llm_selected_authority.py -q`: **60 passed**.
- Ruff focal sobre helper, script y tests: **All checks passed**.
- `git diff --check`: **verde**.
- CLI ejercida con fixture JSON sintético: generó los cinco artefactos y receipt
  con `image_id` separado de `registry_repo_digests`.
- Gates negativos cubiertos: identidad ausente, tag faltante, ImageID stale,
  arquitectura/OS incorrectos, referencias malformadas, inyección de rutas y
  rollback no aprobado.

No se ejecutaron suite completa, smoke, broker, LLM, yfinance, mercado,
preflight productivo, Docker, systemd, despliegue ni cambios de configuración.
La aceptación de release queda pendiente de ventana XNYS cerrada, fullsuite y
gates operativos independientes; este lote solo deja preparada la identidad y
persistencia del binding.
