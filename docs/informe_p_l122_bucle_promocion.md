# P-L122 — cierre determinista del bucle de promocion

## Dictamen

`ready_for_integration_rehearsal` (L3 de 4). No cambia trading, riesgo,
sizing, broker, ejecucion, configuracion ni auto-apply. No reescribe
historico: los cierres anaden filas de decision/evento y conservan el
original.

## Causa y contrato

Tres mecanismos existian pero nunca se ejecutaban juntos: `run_lifecycle`
nadie lo llamaba; las PENDING mas viejas que 14 dias nadie las cerraba;
los APPLIED quedaban con `impact_validation: PENDING` para siempre; los
veredictos PROMOTE/RETIRE de `promotion_readiness` nadie los consumia.

## Cambios (v0.4.229)

- Nuevo `continuous_improvement/promotion_loop.py` (stdlib, determinista):
  `close_stale_validations` (PENDING>14d a EXPIRED_PENDING con decision
  durable), `resolve_applied_impacts` (PASSED por supervivencia sin
  rollback del watchdog, FAILED con rollback; joven se salta),
  `sync_promotion_policies` (PROMOTE crea shadow con `auto_activatable`
  falso, jamas activa; RETIRE degrada a shadow por tag exacto; lo humano
  se preserva y se lista en `human_review`; evaluaciones durables en
  fase `promotion_sync`).
- `Store.update_continuous_improvement_validation_status`: UPDATE mas fila
  de decision, mismo patron que propuestas.
- Postmarket ejecuta lifecycle + cierres + impactos (fail-open, en
  `report["promotion_loop"]`). La revision semanal sincroniza politicas y
  las expone en el estado del job.
- Ventana del laboratorio intacta: los 29.987 bloqueos son throttle de
  diseno (solo opera con mercado abierto o +/-10 min); la cadencia se
  corrige programando el cierre en jobs que si corren, sin tocar el gate.

## QA

- Caracterizacion roja y verde (4 tests) mas guarda explicita (1 test).
- Regresiones: lifecycle/promotion/readiness/autonomy 62 passed (con los 5
  nuevos), reconciliacion/postmarket 19 passed, version policy verde.
- Ruff completo verde, NUL verde (493 archivos), `git diff --check` verde.
- Smoke aislado verde. Paridad de protegidos: sin tocar.

## Limites y siguiente

`guarded_active` a `active` sigue siendo solo humano. Con 0 APPLIED desde
julio no habra impactos que resolver hasta que L1 produzca admisiones.
Siguiente: L4 cuadro de mando de mejora diaria.
