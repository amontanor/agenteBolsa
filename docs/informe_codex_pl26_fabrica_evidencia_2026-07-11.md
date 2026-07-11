# P-L26 - Fabrica de evidencia verificable

Version: 0.4.152 (P-L26B)

## Diagnostico P-L26A

La lectura de 1.893 propuestas encontro 0% de contratos completos, 89% de prosa
en la muestra oficial de 200, cero elegibles en el ultimo codegen y cero de tres
applies activos con evaluacion suficiente. P-L26A fue solo lectura.

## Entrega P-L26B

`EvidenceCard` conserva de forma inmutable la procedencia y los diez campos del
contrato. `proposal_contract.py` valida clase, evidencia, metrica por clase,
direccion baseline/target, muestra minima 30, ventana, rutas, rollback y
peticiones de relajar seguridad. `findings_to_proposals.py` ya no inventa
baseline ni target: los recibe del hallazgo medido y descarta comprobaciones
insuficientes antes de admision, LLM o codegen.

La admision reutiliza `cast_governance`, cuenta solo contratos validos y mantiene
los topes de dos por dia y dos de WIP nuevo. Los 14 registros no terminales
legacy permanecen intactos y aparecen como deuda historica. El digest publica
cumplimiento contractual, prosa, rechazos pre-LLM, evidencia admitida, checks,
fallos, legacy, WIP, elegibilidad codegen y cobertura post-apply.

## Evidencia determinista

Los fixtures pasan de 0% a 100% de contratos completos entre nuevas admisiones
de evidencia y de 89% historico a 0% de prosa admitida. Cada campo ausente tiene
motivo estable; rutas inexistentes/protegidas, seguridad y direccion incompatible
se rechazan. Docs queda `NON_QUALIFYING` para autonomia/beneficio y el contrato
viaja intacto al watchdog existente. No se afirma mejora real de profits.

## Limites

No se modifican estrategias, senales, ranking, gates, ordenes, exposicion,
limites, horarios, modelos ni timeouts. `ALLOW_AUTO_APPLY_IMPROVEMENTS=false`
continua siendo requisito y el apply de codigo permanece humano.
