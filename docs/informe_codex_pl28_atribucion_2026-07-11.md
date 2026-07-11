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
