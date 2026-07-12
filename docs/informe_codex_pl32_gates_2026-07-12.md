# P-L32 - Ledger prospectivo del camino real de gates

## Entrega P-L32B

Version: 0.4.164. El collector central `tools/gate_evaluation.py` observa
los resultados ya emitidos por `cycle_runner._auto_paper_trade`; no llama de
nuevo a ningun gate, no recalcula thresholds y no cambia decisiones.

El orden sellado es: deterministic_review, adversarial_review, entry_quality,
backtest, guards operativos de mercado/investigacion/kill switch, confianza,
open order, posicion existente, duplicidad, sizing, geometria, riesgo,
capacidad diaria, cuota low-sample y pausa de estrategia. Los gates internos
de `build_order_plans` se representan solo cuando existe rechazo real.

El primer `blocked` es el `terminal_gate`; todo lo posterior es
`not_evaluated`. Un candidato admitido solo se marca `admitted` si llega a un
plan final. Las categorias eligibility, safety, capacity, operational y
portfolio permanecen separadas.

## Contrato y persistencia

Los snapshots usan `p-l32b.gate-evaluation.v1`, `snapshot_id` determinista y
`content_hash` independiente de `captured_at`. La identidad prefiere
`candidate_id`, luego `signal_id`; simbolo/action es debil y nunca es
verificado. El contexto de mercado y el `decision_context_snapshot` proceden
del mismo ciclo. Los outcomes se resuelven posteriormente por `signal_id` y
no forman parte del snapshot.

La persistencia reutiliza `features_json` de `signal_outcomes` y el payload de
recomendaciones. Es idempotente, informa conflictos y no completa historicos.
La telemetria es tolerante a fallos y no bloquea el flujo principal.

## Diagnostico

`gate-effectiveness-quality --json` filtra por fecha, gate y categoria. Sin
snapshots devuelve `collecting`, denominadores en cero de observaciones y no
interpreta resultados. Los historicos `gate_json` permanecen legacy y no se
convierten en snapshots prospectivos.

## Seguridad y limites

No se modifican gates, ranking, thresholds, limites, ordenes, estrategias,
stops/takes ni exposicion. No se ejecutan LLM, red, codegen o apply durante
las pruebas. No se incluyen returns, madurez, MFE/MAE, fills, slippage ni P&L.
