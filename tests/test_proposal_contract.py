from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from agente_bolsa.continuous_improvement.proposal_contract import (
    EvidenceCard,
    classify_experiment,
    historical_contract_class,
    validate_experiment_contract,
)


def _proposal(tmp_path, **contract_overrides):
    target = tmp_path / "docs" / "target.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("baseline\n", encoding="utf-8")
    (tmp_path / "docs" / "evidence.md").write_text("evidence\n", encoding="utf-8")
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
        "origin": {
            "origin_role": "findings_to_proposals",
            "origin_run_id": "test-run",
            "origin_kind": "deterministic",
            "evidence_class": "reliability",
            "producer": "tests.test_proposal_contract",
            "producer_version": "test",
            "observed_at": "2026-07-11T00:00:00+00:00",
            "source_event_ids": [],
        },
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


@pytest.mark.parametrize(
    ("field", "value", "failure"),
    [
        ("change_class", "", "change_class_invalid"),
        ("hypothesis_id", "", "missing_hypothesis_id"),
        ("evidence_refs", [], "missing_evidence_refs"),
        ("metric_name", "improve", "metric_name_vague"),
        ("baseline", None, "invalid_baseline"),
        ("target", None, "invalid_target"),
        ("evaluation_window", "", "missing_evaluation_window"),
        ("min_sample", 29, "invalid_min_sample"),
        ("target_paths", [], "missing_target_paths"),
        ("rollback", "", "missing_rollback"),
    ],
)
def test_each_required_contract_field_has_deterministic_rejection(tmp_path, field, value, failure):
    result = validate_experiment_contract(_proposal(tmp_path, **{field: value}), workspace=tmp_path)
    assert failure in result["failures"]


def test_contract_rejects_wrong_direction_protected_path_and_safety_relaxation(tmp_path):
    proposal = _proposal(
        tmp_path,
        baseline=0.1,
        target=0.2,
        improvement_direction="decrease",
        target_paths=["src/agente_bolsa/tools/risk.py"],
    )
    proposal["target_identifier"] = "src/agente_bolsa/tools/risk.py"
    proposal["payload"]["target_files"] = ["src/agente_bolsa/tools/risk.py"]
    proposal["payload"]["proposed_value"] = "disable gate and enable live trading"
    result = validate_experiment_contract(proposal, workspace=tmp_path)
    assert "target_not_below_baseline" in result["failures"]
    assert any(item.startswith("target_path_forbidden") for item in result["failures"])
    assert "safety_relaxation_requested" in result["failures"]


def test_evidence_card_is_immutable_and_historical_rows_remain_unverifiable():
    card = EvidenceCard("docs", "hyp", ("docs/x.md",), "delivery_verified", 0, 1, "delivery", 30, ("docs/x.md",), "revert", "finding")
    with pytest.raises(FrozenInstanceError):
        card.metric_name = "other"
    legacy = {"payload": {"proposed_value": "prosa antigua"}}
    before = dict(legacy["payload"])
    assert historical_contract_class(legacy) == "unverifiable_legacy"
    assert legacy["payload"] == before
