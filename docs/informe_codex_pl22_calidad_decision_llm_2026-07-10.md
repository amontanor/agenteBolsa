# P-L22 — Calidad auditable de decisiones LLM

Fecha: 2026-07-10

## Resultado

El aviso previo de fallback LLM no distinguia un error del modelo de una compra
determinista que solo completaba capacidad tras una respuesta LLM correcta. Se ha
anadido el informe versionado `latest_llm_decision_quality.json` y se integra en
`production-health` y en el digest diario, sin cambiar ninguna ruta de trading.

## Fotografia inicial

- Decisiones conocidas en siete dias: 302.
- LLM real: 118.
- Deterministas: 184 (60,93%).
- Tras fallo LLM verificable: 7, todos `invalid_response_or_schema`.
- Relleno de capacidad tras LLM correcto: 167.
- Sin causa historica verificable: 10, declaradas `unknown`.

El 60,93% no prueba una indisponibilidad del LLM: la mayor parte corresponde a
`capacity_fill_after_llm_ok`. Los siete fallos verificables requieren seguimiento
observacional; este lote no cambia proveedor, prompt, timeout, routing, gates,
limites ni ordenes.

## Evidencia y verificacion

El clasificador usa exclusivamente los campos ya persistidos en
`trade_recommendations`: `source`, `decision_origin`,
`capacity_fill_reason_code` y `model_info.decision_fallback_error`. Los registros
que no contienen causa siguen siendo `unknown`; no se infiere una explicacion.

Pruebas anadidas: LLM real, timeout, red/proveedor, JSON/esquema,
presupuesto/circuit-breaker, legacy sin evidencia, capacity-fill tras LLM correcto
y persistencia del alias `latest`.
