# Informe único — identidad y autoridad de `gate_evaluation` (14-oct-2026)

## Dictamen

Lote N2 aislado, todavía pendiente de revisión e integración por dirección. No
se declara listo ni se autoriza despliegue. El cambio conserva observaciones
contradictorias para diagnóstico y deja la medición fuera de los denominadores
de aprendizaje cuando la identidad o la autoridad no son resolubles.

## Base y alcance

- Worktree: `C:/Users/utopi/.codex/worktrees/oct14-gate-identity/agenteBolsa`
- Rama: `codex/oct14-gate-identity`
- Base exacta: `2999414f0dd506e69e75435965de5c3bb64d9056`
- Versión reservada: `0.4.370`
- Archivos funcionales: `src/agente_bolsa/tools/gate_evaluation.py` y
  `src/agente_bolsa/tools/gate_effectiveness_reporting.py`.
- No se cambian planes, órdenes, cantidades, riesgo, aprendizaje activo,
  configuración, broker, servicios ni producción.

## Corrección

Cuando existe una terminal observada y el mismo candidato tiene un plan final
exacto, el snapshot conserva `terminal_gate` y el estado bloqueado dentro de
`gate_path`, pero publica `decision="unavailable"` y
`authority_conflict=true`. No se transforma la contradicción en rechazo
efectivo ni en admisión.

El matching de `rejected_order_plans` filtra por gate y usa `_find_row`; varias
filas compatibles o cualquier contradicción producen `conflict` y no se elige
la primera fila. `build_gate_effectiveness_quality` cuenta snapshots en
`conflicts` y los excluye de gates, maduración, cobertura y denominadores de
aprendizaje. El informe postmarket expone snapshots procesados, elegibles y
conflictos excluidos.

## Evidencia

Commits separados:

- `5ee725e2` — implementación funcional.
- `f9fb50e4` — focales y regresiones.
- Commit documental posterior — este informe.

Pruebas aisladas, con el intérprete del proyecto, `PYTHONPATH` del worktree y
`DATA_DIR` temporal:

- `tests/test_gate_evaluation_snapshot.py`
- `tests/test_gate_effectiveness_postmarket.py`
- `tests/test_p37b_capture_contract.py`
- `tests/test_p41r_sequential_integration.py`
- Resultado: `32 passed in 3.98s`.
- Ruff focal: `All checks passed!`.
- `scripts/check_no_nulls.py src tests`: `OK (0 archivos)`.
- `git diff --check`: verde.

No se ejecutaron suite completa, smoke, QA ARM, jobs, red, broker, LLM ni
producción. Mercado y operación no fueron modificados.

## Límites pendientes

Snapshots legacy sin ciclo o sin identidad completa pueden quedar
`unavailable/conflict`; no se añade inferencia por símbolo, fecha u orden. El
consumidor y sus denominadores requieren revisión de dirección antes de
integración. Los commits muestran el aviso conocido de `geometric-repack` por
la referencia ajena
`refs/codex/turn-diffs/captures/1786628847747/4ee266fa-eceb-479d-a4a7-b513226192d9/base`;
no se modificó esa referencia.

## Cierre de revisión de dirección

La exclusión de conflictos se realiza en una pasada, conservando orden y
referencias originales, sin buscar cada snapshot en una lista de diccionarios
profundos (coste cuadrático). Con Pythonproyecto, PYTHONPATH exacto, DATA_DIR
temporal y socket.connect/create_connection bloqueados:32passed en4.35s.
Ruff src/tests completo verde; NUL sin argumentos571archivos (la comprobación
previa0archivos no acreditaba cobertura). Versión0.4.370 alineada. Cambios
preparados para ensayo de integración; fullsuite/smoke/ARM y paridad combinada
siguen pendientes, sin despliegue ni autoridad de ejecución nueva.
