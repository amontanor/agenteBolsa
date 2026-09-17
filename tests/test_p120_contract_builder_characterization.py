"""P-L120 caracterizacion: el gate rechaza 100% por contrato ausente (rojo)."""
from __future__ import annotations

from agente_bolsa.continuous_improvement.proposal_contract import validate_experiment_contract
from agente_bolsa.continuous_improvement.schemas import ImprovementProposalPayload

EXPECTED_PRODUCTION_FAILURES = [
    "change_class_invalid",
    "origin_missing",
    "missing_hypothesis_id",
    "missing_metric_name",
    "missing_evaluation_window",
    "missing_evidence_refs",
    "invalid_baseline",
    "invalid_target",
    "metric_name_vague",
    "invalid_min_sample",
    "missing_target_paths",
]


def _orchestrator_raw():
    return {
        "proposal_type": "MONITORING_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": "digest",
        "payload": {
            "agent_name": "OrchestratorAgent",
            "proposed_value": "Mejorar la visibilidad del digest.",
            "rationale": "El digest podria ser mas claro.",
            "expected_impact": "mejorar",
        },
    }


def test_orchestrator_raw_rejected_with_production_failures():
    result = validate_experiment_contract(_orchestrator_raw())
    assert result["valid"] is False
    for failure in EXPECTED_PRODUCTION_FAILURES:
        assert failure in result["failures"], failure


def test_complete_contract_survives_proposal_schema_roundtrip(tmp_path):
    """Un contrato completo con origin debe sobrevivir a ImprovementProposalPayload."""
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "target.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "docs" / "evidence.md").write_text("y\n", encoding="utf-8")
    raw = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "continuous_improvement",
        "target_identifier": "docs/target.md",
        "current_value": "v",
        "proposed_value": "w",
        "rationale": "Reducir fallos medidos.",
        "expected_impact": "Reduce failure_recurrence from 0.2 to 0.1.",
        "risk_level": "LOW",
        "required_validations": ["tests"],
        "rollback_plan": "git revert",
        "target_files": ["docs/target.md"],
        "experiment_contract": {
            "change_class": "reliability",
            "hypothesis_id": "hyp_test",
            "evidence_refs": ["docs/evidence.md"],
            "metric_name": "failure_recurrence",
            "baseline": 0.2,
            "target": 0.1,
            "improvement_direction": "decrease",
            "evaluation_window": "30 ejecuciones deterministas",
            "min_sample": 30,
            "target_paths": ["docs/target.md"],
            "rollback": "git revert",
            "origin": {
                "origin_role": "findings_to_proposals",
                "origin_run_id": "test-run",
                "origin_kind": "deterministic",
                "evidence_class": "reliability",
                "producer": "tests",
                "producer_version": "test",
                "observed_at": "2026-09-17T00:00:00+00:00",
                "source_event_ids": ["evt_1"],
            },
        },
    }
    model = ImprovementProposalPayload.model_validate(raw)
    dumped = model.model_dump()
    contract = (dumped.get("experiment_contract") or {})
    assert contract.get("origin"), "origin se pierde en el schema"
    assert contract.get("improvement_direction") == "decrease"
    check = validate_experiment_contract(
        {"proposal_type": "CODE_CHANGE", "target_component": "x",
         "target_identifier": "docs/target.md",
         "payload": {"target_files": ["docs/target.md"],
                      "expected_impact": dumped.get("expected_impact"),
                      "experiment_contract": contract}},
        workspace=tmp_path,
    )
    assert check["valid"] is True, check["failures"]
