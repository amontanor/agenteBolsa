# Cobertura real de símbolos — 7 de octubre de 2026

Dictamen: `ready_for_integration_rehearsal`, candidato aislado N2. No desplegado.
La causa es que `symbols_with_data=len(candidates)` cuenta salidas de estrategias;
varias estrategias pueden producir más candidatos que símbolos solicitados.
El campo legacy se conserva exactamente para mantener paridad de consumidores.

## Identidad y alcance

- Worktree: `C:/Users/utopi/.codex/worktrees/bolsa-coverage-oct07/agenteBolsa`.
- Rama: `codex/oct07-symbol-coverage`.
- Base runtime: `1adc3cec2b68a6a02eb8b3dd38e78846f1120cc2`.
- Tree base: `4d118b504b305e45f45a06d9aaffa063079abaf7`; versión `0.4.321`.
- Base limpia antes de trabajar. Sin bump: diferido expresamente por dirección
  técnica hasta resolver la divergencia de versión `.340` y preparar integración.
- Estado XNYS aportado por dirección técnica: abierto a las 20:49:36 Madrid,
  cierre 22:00; lock vivo, runtimeview `unavailablewal`. No se reconsultó producción.
- Scheduler, HTTP, kernel, configuración, leases y postmarket no auditados aquí.

## Contrato

`build_symbol_coverage` añade únicamente `symbol_coverage` al informe existente.
`requested_symbols_count` cuenta símbolos únicos normalizados (strip/uppercase)
antes de truncar presentación. `delivered_symbols_count` usa exclusivamente la
lista canónica `market_data.symbols_with_data`, intersectada con solicitud original.
SPY agregado sólo como benchmark queda excluido; SPY solicitado sí cuenta.
`coverage_ratio` divide ambos contadores y permanece entre 0 y 1. Una solicitud
vacía no inventa ratio: devuelve `unavailable`.

`candidate_count` cuenta todos los candidatos activos; `unique_candidate_symbols_count`
cuenta sus símbolos únicos normalizados. Ambos preceden top_n y permanecen
separados de cobertura. Shadow conserva su flujo y no entra en estos contadores.

Metadata ausente o lista inválida produce `unavailable`, con contador delivered y
ratio `null`. También se rechazan símbolos ajenos a solicitud/benchmark, contador
canónico contradictorio y solapamiento delivered/missing. No se infiere delivery
por candidatos ni se convierte ausencia en cero. Lista canónica vacía válida sí
permite cero conocido. No se altera metadata, advertencias ni candidatos.

## Evidencia

Commits separados: `dcdd12c0` caracterización, `1dd65440` implementación,
`bf525a3d` QA. Tree funcional probado:
`f870f277d68b0732043925bd6327e536004d0c03`.

Caracterización sobre base: 1 failed en 0.75 s, `KeyError: 'symbol_coverage'`;
el legacy ya devolvía 4 candidatos sobre 2 símbolos únicos.

Python: `C:/Antonio/Bref/agenteBolsa/.venv/Scripts/python.exe`.
PYTHONPATH: `C:/Users/utopi/.codex/worktrees/bolsa-coverage-oct07/agenteBolsa/src`.

Comando focal final:
`python -m pytest tests/test_oct07_symbol_coverage.py tests/test_reporting_and_universe.py tests/test_strategy_registry.py -q`
Resultado: **27 passed en 2.33 s**, sin skips.
Incluye múltiples estrategias, duplicados/case/espacios, SPY extra/solicitado,
metadata ausente/inválida/contradictoria, denominadores antes de top_n, reloj
congelado y comparación completa contra fuente Git exacta de base. Sin el campo
nuevo, todos los campos del informe coinciden exactamente con base: candidatos,
scores, orden, top lists, warnings, tool requests y metadata.

Ruff focal: `All checks passed!`. NUL: `OK (538 archivos)` antes del último test
QA; diff sin errores. Los tests nuevos no instancian Settings (por tanto no leen
.env ni requieren _env_file); DATA_DIR/output temporales, discover/download dobles.
No broker, red, LLM, servicios, SQLite productiva, reinicios, merge ni push.

## Límites y siguiente paso

Suite completa, smoke, validación de configuración, kernel y salud operativa
omitidos por alcance aislado y XNYS abierto. Evidencia sintética no demuestra
cobertura runtime ni readiness operativa. Paridad demostrada en productor; riesgo,
ejecución y consumidores no tienen diff, sin afirmar prueba end-to-end operativa.
Revisar contrato e integrar en ensayo exacto; resolver versión reservada y ejecutar
gates proporcionales en ventana autorizada antes de cualquier despliegue.

## Intento anticipado de validación — 7-oct-2026, 22:37 Madrid

Dictamen: `precondition_not_met`. El operador pidió ejecutar inmediatamente la automatización prevista para las 23:00; se ejecutó su preflight en este chat, sin esperar al horario.

Hechos verificados en producción, solo lectura: XNYS cerrado a las 22:37:01 Madrid, próxima apertura 8-oct15:30; paquete activo0.4.321, paper true, live false. No hay eventos post_market_review_started/completed/failed del7-oct en la consulta acotada. Estado latest postmarket `skipped`, pmr_78fd692e3f98, actualizado21:51:38 Madrid, motivo mercado aún no apto. post_market_review_last_session sigue2026-10-05. La sesión7-oct no cumple terminal completed/failed; un skipped previo al cierre no lo sustituye.

Candidatos: los cuatro worktrees estaban limpios al iniciar este intento, con los HEAD/tree previamente documentados. Se detuvo antes de suites, smoke, integración o versión. Imagen/diferencia.340, kernel, configuración completa, leases y ausencia de procesos de validación no se declaran comprobados en este intento: el preflight terminó por la precondición anterior. El campo auto-apply del sondeo resultó unavailable, no false verificado.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_preflight_live.json; SQLite mediante Store.read_connection, mode=ro/query_only; sin reparaciones ni mutación productiva. No se fuerza postmarket, reconciliación o ciclo; sin órdenes, reinicios, despliegue ni promoción. Sólo se añaden estas notas documentales.

La automatización `validar-mejoras-bolsa-tras-cierre` quedó PAUSED tras este intento, tal como ordena su prompt; no volverá a ejecutarse a las23:00. La revisión del12-oct sigue programada. Siguiente condición: diagnosticar por qué no consta terminal de postmarket y volver a comprobarlo junto a los demás gates; no marcar completada la validación ni los candidatos como desplegados.

## Validación de las 23:05 — 7-oct-2026

Dictamen: `precondition_not_met`. Sondeo a las 23:05:22–23:05:24 Madrid: XNYS cerrado, próxima apertura 8-oct 15:30. Producción 0.4.321, paper=true, allow_live_trading=false, allow_auto_apply_improvements=false. Imagen sha256:8ff2bedce363751c33e8e0acd37eae4095358a8f4edf65c08f28fcfaf069d1ae, running, arranque 22:52:55, RestartCount=2; causa de reinicios unavailable, sin intervención desde este intento. Lock vivo PID6/token305725. schedule-status no acredita jobs inactivos: runtime unavailable/wal_mode_or_sidecar_present.

Bloqueo confirmado por Store.read_connection mode=ro/query_only: lease post_market_coordination:active, sesión 2026-10-07, run pmr_b2deee2ab986, bootstrap, stage=outcome_update, actualizado 22:54:32. Started a las 22:54:15, sin terminal completed/failed en últimas 3000 filas (ventana 20:36–23:02 Madrid); last_session sigue 5-oct. Otros started a las 22:47:59 y 22:51:22 no prueban procesos simultáneos. Lease persistido activo no demuestra progreso, pero incumple el gate de ausencia de leases.

Cuatro candidatos limpios antes de esta nota, separados sobre 1adc3cec/.321: postmarket HEAD d4956030705933d32c062b347658d9eb4e795d73/tree 1e22c25327414be9e2751508b5b5732bc32374e7; exit-audit HEAD 8bece4d45de1d9f00e463e2b512d8553e407e443/tree 01f7db8cd76d6cd261ac314a6498acb6b4e40fa4; cobertura HEAD 5cdc9d83f7ffd392c6479d518301256a7d2588f9/tree 5559ac5ed76420359d98312c13fc1b7751df884d; observación HEAD 2cd1425fd728105c04a40843518f6937a7dbbb54/tree e638955373e2f052f8b76a4e0b3ff886eae1884c. Sin bump/release. Divergencia histórica .340 no resuelta; checkout C:/Antonio/Bref/agenteBolsa observado ahora b411e9a7445bfa4da6de8329e668d30864090522, paquete .253, cambios ajenos preservados; no representa identidad del Jetson.

Detenido antes de asignar validaciones, suites, smoke, integración o cambios funcionales. Focales anteriores no repetidos ni declarados validación operativa. Kernel/configuración completa, exclusividad de procesos y demás gates no aprobados. Sólo lectura productiva y documentación local, diff --check; sin órdenes, broker/LLM desde tests, protegidos, históricos, locks, producción, reinicios, merge, promoción o despliegue. Automatización validar-mejoras-bolsa-tras-cierre PAUSED tras este intento; estudio del 12-oct sin cambios. Siguiente: terminal de sesión y ausencia de lease/job/retry antes de reprogramar; no forzar cierre ni borrar leases.

Evidencia: C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_validation_2305_live.json y audit_validation_2305_image.txt; timestamps originales UTC.
