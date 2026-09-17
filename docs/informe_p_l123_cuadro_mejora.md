# P-L123 — dedupe de lecciones y cuadro de mejora diaria

## Dictamen

`ready_for_integration_rehearsal` (L4 de 4). No cambia trading, riesgo,
sizing, broker, ejecucion ni configuracion. El freno humano
(`pause_all`/`resume_all`, kill switch) queda intacto.

## Causa y contrato

5.570 lecciones con duplicacion semantica EN/ES y 948 ACTIVE sin exigir
frescura alimentaban contexto del LLM sin garantia de evidencia. El digest
contaba actividad sin responder si hubo mejora real.

## Cambios (v0.4.230)

- `lesson_distiller.dedupe_lessons`: agrupa por clave semantica
  (scope|setup|n|decided|winners), conserva la mas fresca y retira el resto
  con `duplicate_of` (nunca borra). `revalidate_lessons` ignora duplicados
  para no reactivarlos. `relevant_lessons` exige ACTIVE con evidencia de
  como maximo 14 dias y sin marca de duplicado (direccion conservadora:
  menos contexto ruidoso en `trade_decision`).
- `curate_lessons` incluye `deduped` (aditivo).
- Nuevo `tools/improvement_dashboard.py`: `build_improvement_dashboard`
  responde sistema-vs-SPY (con cobertura y provisional), aprendizaje del
  dia (observaciones, lecciones netas, experimentos netos) y mejora real
  (admitidas, aplicados, promociones, impactos medidos, caducadas).
  Veredicto SI solo con mejora real del dia; RESULTADO y PROCESO
  separados en el markdown.
- `build_autonomy_digest` suma seccion "Mejora de hoy" y clave
  `improvement` (aditivo; `pause_all`/`resume_all` sin cambios).

## QA

- Caracterizacion roja y verde (3 tests).
- Regresiones: lessons/curator/digest 14 passed, trade_decision 129
  passed, version policy verde.
- Ruff completo verde, NUL verde (495 archivos), `git diff --check` verde.
- Smoke aislado verde. Paridad de protegidos: sin tocar.

## Limites y siguiente

Con el stack parado desde el 14-ago no hay lecciones frescas en produccion:
al rearrancar, `relevant_lessons` devolvera vacio hasta la primera
revalidacion, y el cuadro marcara provisional hasta recibir recibos SPY.
Siguiente unico: ensayo de integracion combinado L120-L123, suite
completa, preflight y despliegue con XNYS cerrado.
