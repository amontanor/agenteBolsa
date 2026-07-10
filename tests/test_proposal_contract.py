from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agente_bolsa.continuous_improvement.proposal_contract import (
    classify_experiment,
    validate_experiment_contract,
)


def _proposal(tmp_path, **contract_overrides):
    target = tmp_path / "docs" / "target.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("baseline\n", encoding="utf-8")
    contract = {
        "change_class": "reliability",
        "hypothesis_id": "hyp_timeout_recurrence",
        "evidence_refs": ["docs/evidence.md"],
        "metric_name": "failure_rate",
        "baseline": 0.2,
        "target": 0.1,
        "evaluation_window": "30 sessions",
        "min_sample": 30,
        "target_paths": ["docs/target.md"],
        "rollback": "git revert",
    }
    contract.update(contract_overrides)
    return {
        "proposal_type": "CODE_CHANGE",
        "target_component": "docs",
        "target_identifier": "docs/target.md",
        "payload": {
            "expected_impact": "Reduce failure_rate from 0.2 to 0.1.",
            "target_files": ["docs/target.md"],
            "experiment_contract": contract,
        },
    }


def test_complete_contract_is_admitted(tmp_path):
    result = validate_experiment_contract(_proposal(tmp_path), workspace=tmp_path)

    assert result["valid"] is True
    assert result["failures"] == []


def test_missing_metric_path_and_stale_evidence_are_rejected(tmp_path):
    proposal = _proposal(
        tmp_path,
        metric_name="",
        target_paths=["docs/missing.md"],
        evidence_as_of=(datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
    )
    proposal["target_identifier"] = "docs/missing.md"
    proposal["payload"]["target_files"] = ["docs/missing.md"]

    result = validate_experiment_contract(proposal, workspace=tmp_path)

    assert "missing_metric_name" in result["failures"]
    assert "target_path_missing:docs/missing.md" in result["failures"]
    assert "evidence_stale" in result["failures"]


def test_historical_experiments_are_classified_without_rewrite(tmp_path):
    proposal = _proposal(tmp_path)
    evidence = {"status": "PASSED", "metrics": {"failure_rate": 0.08}}
    operational = {"status": "PASSED", "metrics": {}}
    failed = {"status": "FAILED", "metrics": {}}

    assert classify_experiment(evidence, proposal) == "evidence_experiments"
    assert classify_experiment(operational, proposal) == "operational_checks"
    assert classify_experiment(failed, proposal) == "failed_runs"
