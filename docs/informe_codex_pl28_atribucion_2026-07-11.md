# P-L28 - atribucion normalizada por origen

P-L28B entrega un unico modelo `Origin` en `proposal_contract.py`. Todo
contrato nuevo exige `origin_role`, `origin_run_id`, `origin_kind`,
`evidence_class`, `producer`, `producer_version`, `observed_at` y
`source_event_ids`. La validacion es determinista, inmutable y previa a LLM,
codegen, WIP y experimentos.

El productor determinista `findings_to_proposals` conserva su rol, run y
procedencia dentro de `EvidenceCard` y `experiment_contract`; los historicos no
se reescriben ni se atribuyen por heuristica: permanecen `legacy_unattributed`
o `invalid_origin` al leerlos. El digest publica cobertura, runs y embudo por
rol; `useful_demonstrated` exige un impacto post-apply `PASSED`, no volumen.

`ALLOW_AUTO_APPLY_IMPROVEMENTS` sigue desactivado. Esta entrega no afirma
mejoras de profits ni cambia agentes, trading, estrategias, gates u ordenes.

## Correccion P-L28BR

`origin_identity_matches` verifica que cada copia conserva exactamente los ocho
campos de origen. La prueba de integración cubre la cadena contrato, propuesta,
experimento, artefacto, apply humano simulado y watchdog, manteniendo los
actores posteriores separados. Las etapas existentes que conservan
`experiment_contract` por referencia no se duplicaron. El estado de utilidad es
determinista: no_data, collecting, mostly_invalid, evaluable,
useful_demonstrated y no_improvement_demonstrated; volumen no demuestra valor.
La prueba de Store temporal invoca `ExperimentRunner._base_experiment`, persiste
y relee el experimento, y resuelve origin por `proposal_id`; esto demuestra la
referencia estable real sin crear una segunda copia de verdad en experimentos.

### Cierre de P-L28BR

Las pruebas de integración usan el `Store` temporal y las funciones reales de
persistencia de `CodegenPatchAgent`, transición de estado y evaluación
operativa del watchdog. Artefactos y experimentos guardan `proposal_id`; el
contrato persistido es la única fuente de `origin`, por lo que no se puede
crear una copia divergente. El límite seguro del apply humano se prueba antes
de toda mutación de Git: sin artefacto listo, `approve_and_apply_code_diff`
bloquea y no crea un cambio aplicado.

El digest lee propuestas, experimentos, artefactos y cambios aplicados en modo
solo lectura. Publica por rol runs únicos, propuestas, checks operativos,
rechazos, admisiones, experimentos, intentos/éxitos de codegen, estado listo,
applies, rollback, evaluación e impacto. `mostly_invalid` significa más del
50% de hallazgos atribuidos inválidos o inevaluables; `no_improvement_demonstrated`
requiere al menos dos evaluaciones completas sin PASSED. Un PASSED de docs no
cuenta como mejora demostrada. Legacy, origen corrupto y referencias ausentes
siguen separados y nunca reciben autor inferido.
