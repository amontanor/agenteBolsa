# Prompt P12 para Codex — 2-jul-2026 — el gate aceptó código nuevo sin tests

Contexto: el responsable inspeccionó `ci_artifact_9a6378dc448e` (P11) y lo RECHAZÓ:
el diff toca solo `digest.py` sin añadir ningún test para `latest_core_sleeve_signal`,
y la validación de sandbox solo ejecutó los 4 tests preexistentes de
`test_ci_phase3_digest.py`. `tests_ok=true` resultó engañoso: prueba que no rompe lo
viejo, no que lo nuevo funcione. El requisito de la propuesta (tests con línea real
del log) fue ignorado por el modelo y el gate no lo detectó. Dos partes.

## Parte 1 — Gate determinista: código nuevo exige tests

1. En el flujo de preview/validación de sandbox (`CodeDiffPreviewAgent` o donde
   corresponda), añade un check determinista: si el diff añade o modifica código en
   `src/` y la propuesta declara `test_requirement` (o el diff introduce funciones
   nuevas), el diff DEBE tocar también al menos un fichero en `tests/` y los
   `test_commands` deben ejecutar tests de ese fichero. Si no → el artefacto queda
   `REJECTED_BY_GATE` con razón `new_code_requires_tests`, nunca
   `READY_FOR_HUMAN_REVIEW`.
2. Marca `ci_artifact_9a6378dc448e` como rechazado
   (`rejected_by_human_review`, razón `new_code_without_tests`, actor `Responsable`)
   para que `review` no lo liste.
3. Tests del gate: diff solo-src con test_requirement → rechazado; diff src+tests
   cuyos test_commands ejercitan el fichero de tests del diff → pasa.

## Parte 2 — Cerrar el e2e con el contenido YA aprobado

Prioriza la ruta (a); solo si falla pasa a (b):

a. **Restaurar el artefacto de P10** (`ci_artifact_dda66b200e41`): su contenido fue
   aprobado por el responsable (digest.py + tests/test_ci_phase3_digest.py con
   líneas reales del log) y tú ya demostraste en P11 que su patch reparado aplica
   limpio con `--3way`. Repara su diff con el normalizador de mojibake, revalida en
   sandbox (aplicación + tests del diff + suite focalizada), verifica
   `git apply --check` contra el árbol real, y déjalo como ÚNICO artefacto
   `READY_FOR_HUMAN_REVIEW` (quita el estado superseded, registra la restauración
   con decisión auditable `restored_after_apply_fix`).
b. Si la revalidación de (a) falla por cualquier motivo (documenta cuál), regenera
   con `gen-diff` UNA última tanda (3 intentos), con el gate de la Parte 1 ya
   activo — así un diff sin tests no podrá llegar a la cola humana.

4. Cierra con la salida del `review` (debe listar UN solo artefacto, con tests que
   cubran `latest_core_sleeve_signal` usando la línea real del log) y los comandos
   `review`/`approve` para Antonio. NO ejecutes `approve`.

Informe: `docs/informe_codex_p12_gate_tests_<fecha>.md`.

Bloque de verificación obligatorio:
- `pytest tests\ -x -q` verde; `ruff check src tests scripts` limpio.
- Bump de `__version__`.
- `git apply --check` del artefacto final contra el árbol real: OK documentado.
- Commit(s) con diff revisable.
- Confirmar: `trading_mode=paper`, `allow_live_trading=false`,
  `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`, `core_sleeve.json` con `dry_run=true`.
- NO tocar los 6 ficheros del suelo de kernel.
