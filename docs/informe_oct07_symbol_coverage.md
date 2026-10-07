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
