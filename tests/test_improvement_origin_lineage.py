from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.codegen import CodegenPatchAgent, CodegenPatchResponse
from agente_bolsa.continuous_improvement.digest import (
    build_lab_digest,
    build_origin_utility_metrics,
    origin_utility_status,
)
from agente_bolsa.continuous_improvement.experiments import ExperimentRunner
from agente_bolsa.continuous_improvement.proposal_contract import (
    Origin,
    origin_identity_matches,
    validate_origin,
)
from agente_bolsa.storage import Store
from agente_bolsa.tools.change_watchdog import _evaluate_operational_change


def origin(**overrides):
    value = {"origin_role": "findings_to_proposals", "origin_run_id": "run-1", "origin_kind": "deterministic", "evidence_class": "observability", "producer": "continuous_improvement.findings_to_proposals", "producer_version": "0.4.159", "observed_at": "2026-07-12T00:00:00+00:00", "source_event_ids": ["event-1"]}
    value.update(overrides)
    return value


def temporary_store(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state" / "test.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs" / "agents", ALLOW_LIVE_TRADING=False, ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def proposal(proposal_id, *, role="findings_to_proposals", run="run-1", change_class="observability", status="READY_TO_APPLY"):
    metric_name = {"trading": "expectancy", "reliability": "availability", "observability": "coverage", "docs": "documentation consistency"}[change_class]
    contract = {
        "change_class": change_class,
        "hypothesis_id": f"hyp-{proposal_id}",
        "evidence_refs": [f"event-{proposal_id}"],
        "metric_name": metric_name,
        "baseline": 0.5,
        "target": 0.6,
        "evaluation_window": "30 sessions",
        "min_sample": 30,
        "target_paths": ["src/agente_bolsa/continuous_improvement/digest.py"],
        "rollback": "human revert",
        "origin": origin(origin_role=role, origin_run_id=run, evidence_class=change_class),
    }
    return {"proposal_id": proposal_id, "cycle_id": "cycle", "fingerprint": f"fp-{proposal_id}", "proposal_type": "CODE_CHANGE", "target_component": "continuous_improvement", "target_identifier": contract["target_paths"][0], "status": status, "priority": "LOW", "risk_level": "LOW", "payload": {"experiment_contract": contract, "target_paths": contract["target_paths"], "expected_impact": "availability measured against the declared baseline"}}


def test_origin_model_is_immutable_and_serializes_stably():
    model = Origin(**origin())
    with pytest.raises(FrozenInstanceError):
        model.origin_role = "human_operator"  # type: ignore[misc]
    assert model.as_dict() == origin()


@pytest.mark.parametrize("field,value", [("origin_role", "unknown"), ("origin_run_id", ""), ("origin_kind", "robot"), ("evidence_class", "other"), ("producer", ""), ("producer_version", ""), ("observed_at", "bad"), ("source_event_ids", [1])])
def test_origin_rejects_each_invalid_field(field, value):
    assert validate_origin(origin(**{field: value}), change_class="observability")["valid"] is False


def test_origin_identity_is_exact_across_simulated_end_to_end_stages():
    original = origin()
    proposal = {"experiment_contract": {"origin": original}}
    experiment = {"proposal_id": "proposal-1", "input": {"origin": proposal["experiment_contract"]["origin"]}}
    artifact = {"proposal_id": "proposal-1", "payload": {"origin": experiment["input"]["origin"]}}
    applied = {"proposal_id": "proposal-1", "decision": {"experiment_contract": {"origin": artifact["payload"]["origin"]}, "applied_by": "human_operator"}}
    watchdog = {"evaluated_by": "change_watchdog", "origin": applied["decision"]["experiment_contract"]["origin"]}
    assert all(origin_identity_matches(original, stage) for stage in (proposal["experiment_contract"]["origin"], experiment["input"]["origin"], artifact["payload"]["origin"], applied["decision"]["experiment_contract"]["origin"], watchdog["origin"]))
    assert applied["decision"]["applied_by"] != original["origin_role"]
    assert watchdog["evaluated_by"] != original["origin_role"]


def test_origin_identity_rejects_overwrite_corruption_and_legacy():
    assert not origin_identity_matches(origin(), origin(origin_role="human_operator"))
    assert not origin_identity_matches(origin(), {"origin_role": "findings_to_proposals"})


def test_real_store_experiment_resolves_origin_through_proposal_id(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state" / "test.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs" / "agents", ALLOW_LIVE_TRADING=False, ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    contract = {"change_class": "observability", "hypothesis_id": "hyp-origin", "origin": origin()}
    proposal = {"proposal_id": "proposal-origin", "cycle_id": "cycle-origin", "fingerprint": "origin-fp", "proposal_type": "MONITORING_CHANGE", "target_component": "continuous_improvement", "target_identifier": "origin", "status": "PENDING", "priority": "LOW", "risk_level": "LOW", "payload": {"experiment_contract": contract}}
    store.upsert_continuous_improvement_proposal(proposal)
    persisted = store.continuous_improvement_proposal("proposal-origin")
    ExperimentRunner(settings, store)._base_experiment(proposal=persisted, cycle_id="cycle-origin", initiative_id=None, experiment_type="data_quality_review", status="PENDING", input_payload={}, period={}, metrics={}, result={})
    experiment = store.continuous_improvement_experiments(proposal_id="proposal-origin", limit=1)[0]
    resolved = store.continuous_improvement_proposal(experiment["proposal_id"])
    assert origin_identity_matches(origin(), resolved["payload"]["experiment_contract"]["origin"])


def test_real_codegen_artifact_persistence_keeps_origin_by_proposal_reference(tmp_path):
    settings = Settings(DATA_DIR=tmp_path, DATABASE_PATH=tmp_path / "state" / "test.sqlite3", AGENT_LOGS_DIR=tmp_path / "logs" / "agents", ALLOW_LIVE_TRADING=False, ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    proposal = {"proposal_id": "proposal-artifact", "cycle_id": "cycle", "fingerprint": "fp-artifact", "proposal_type": "CODE_CHANGE", "target_component": "docs", "target_identifier": "docs/x.md", "status": "READY_TO_APPLY", "priority": "LOW", "risk_level": "LOW", "payload": {"experiment_contract": {"change_class": "observability", "hypothesis_id": "hyp-artifact", "origin": origin()}}}
    store.upsert_continuous_improvement_proposal(proposal)
    CodegenPatchAgent()._save_artifact(store, proposal_id="proposal-artifact", artifact_type="diff", content_text="diff --git a/docs/x.md b/docs/x.md", payload={"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True})
    artifact = store.continuous_improvement_proposal_artifact("proposal-artifact")
    resolved = store.continuous_improvement_proposal(artifact["proposal_id"])
    assert artifact["proposal_id"] == "proposal-artifact"
    assert resolved["payload"]["experiment_contract"]["hypothesis_id"] == "hyp-artifact"
    assert origin_identity_matches(origin(), resolved["payload"]["experiment_contract"]["origin"])


def test_real_codegen_constructor_uses_monkeypatched_generator_without_losing_reference(tmp_path, monkeypatch):
    settings, store = temporary_store(tmp_path)
    item = proposal("generated")
    store.upsert_continuous_improvement_proposal(item)

    class FakeClient:
        def generate_json(self, *_args, **_kwargs):
            return SimpleNamespace(
                ok=True,
                payload=CodegenPatchResponse(file_edits=[{"path": "docs/x.md", "content": "x"}]),
                llm_call_id="fake-call",
                provider="fake",
                model="fake-model",
            )

    agent = CodegenPatchAgent(client=FakeClient())

    def ready_preview(**_kwargs):
        return agent._save_artifact(
            store,
            proposal_id="generated",
            artifact_type="code_diff_preview",
            content_text="diff",
            payload={"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True},
        )

    monkeypatch.setattr(agent._preview, "generate", ready_preview)
    result = agent.generate_for_proposal(settings=settings, store=store, proposal_id="generated")
    persisted = store.continuous_improvement_proposal(result["artifact"]["proposal_id"])
    assert result["status"] == "READY_FOR_HUMAN_REVIEW"
    assert persisted["payload"]["experiment_contract"]["hypothesis_id"] == "hyp-generated"
    assert origin_identity_matches(item["payload"]["experiment_contract"]["origin"], persisted["payload"]["experiment_contract"]["origin"])


def test_real_ready_transition_and_safe_human_apply_boundary(tmp_path):
    settings, store = temporary_store(tmp_path)
    item = proposal("ready")
    store.upsert_continuous_improvement_proposal(item)
    # This is the same transition used by the preview lifecycle; it only writes status/audit data.
    store.update_continuous_improvement_proposal_status("ready", status="READY_TO_APPLY", actor="CodeDiffPreviewAgent", reason="reviewed")
    reread = store.continuous_improvement_proposal("ready")
    assert reread["status"] == "READY_TO_APPLY"
    assert origin_identity_matches(item["payload"]["experiment_contract"]["origin"], reread["payload"]["experiment_contract"]["origin"])
    # No ready artifact: approve_and_apply's real pre-mutation guard blocks before Git/write operations.
    from agente_bolsa.continuous_improvement.human_apply import approve_and_apply_code_diff
    result = approve_and_apply_code_diff(settings=settings, store=store, proposal_id="ready", actor="human_operator", backup=False)
    assert result["status"] == "BLOCKED"
    assert store.continuous_improvement_applied_changes(proposal_id="ready") == []
    assert settings.allow_auto_apply_improvements is False


def test_watchdog_real_operational_evaluation_preserves_author_and_separates_evaluator(tmp_path):
    _, store = temporary_store(tmp_path)
    item = proposal("watch", change_class="reliability")
    store.upsert_continuous_improvement_proposal(item)
    change = {"applied_change_id": "change-watch", "proposal_id": "watch", "cycle_id": "cycle", "status": "APPLIED", "change_type": "CODE_CHANGE", "target_key": "origin", "decision": {"experiment_contract": {**item["payload"]["experiment_contract"], "metric_name": "availability", "baseline": 0.9, "target": 0.95, "min_sample": 2}, "post_apply_metrics": {"availability": 0.96, "sample": 2}}}
    result = _evaluate_operational_change(store, change, change["decision"]["experiment_contract"], "reliability")
    assert result["metrics"]["status"] == "PASSED"
    assert result["attribution"]["attribution_status"] == "attributed"
    assert origin_identity_matches(item["payload"]["experiment_contract"]["origin"], result["attribution"]["origin"])
    assert result["attribution"]["evaluated_by"] != result["attribution"]["origin"]["origin_role"]


def test_real_origin_funnel_deduplicates_runs_and_keeps_legacy_and_invalid_separate(tmp_path):
    _, store = temporary_store(tmp_path)
    first = proposal("one", role="findings_to_proposals", run="same", change_class="trading")
    second = proposal("two", role="findings_to_proposals", run="same", change_class="reliability", status="REJECTED")
    third = proposal("three", role="evidence_validator", run="other", change_class="docs")
    legacy = proposal("legacy")
    legacy["payload"]["experiment_contract"].pop("origin")
    corrupt = proposal("corrupt")
    corrupt["payload"]["experiment_contract"]["origin"]["origin_kind"] = "bad"
    for item in (first, second, third, legacy, corrupt):
        store.upsert_continuous_improvement_proposal(item)
    ExperimentRunner(Settings(DATA_DIR=tmp_path), store)._base_experiment(proposal=store.continuous_improvement_proposal("one"), cycle_id="cycle", initiative_id=None, experiment_type="evidence_experiment", status="PENDING", input_payload={}, period={}, metrics={}, result={})
    CodegenPatchAgent()._save_artifact(store, proposal_id="one", artifact_type="diff", content_text="diff", payload={"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True})
    store.save_continuous_improvement_applied_change({"applied_change_id": "applied-one", "proposal_id": "one", "cycle_id": "cycle", "status": "APPLIED", "change_type": "CODE_CHANGE", "target_key": "x", "decision": {"experiment_contract": first["payload"]["experiment_contract"], "impact_validation": {"status": "PASSED"}}})
    output = build_lab_digest(store, days=36500, data_dir=tmp_path)
    funnel = output["origin_utility"]
    role = funnel["origins"]["findings_to_proposals"]
    assert role["unique_runs"] == 1
    assert role["experiments_created"] == 1
    assert role["codegen_attempted"] == role["codegen_succeeded"] == 1
    assert role["demonstrated_improvements"] == 1
    assert funnel["legacy_unattributed_count"] == 1
    assert funnel["invalid_origin_count"] == 1
    assert role["utility_status"] == "useful_demonstrated"


def test_real_digest_utility_states_are_data_derived():
    assert build_origin_utility_metrics([], [])["origins"] == {}
    base = proposal("collecting", change_class="observability")
    collecting = build_origin_utility_metrics([base], [])
    assert collecting["origins"]["findings_to_proposals"]["utility_status"] == "collecting"


@pytest.mark.parametrize("metrics,status", [({}, "no_data"), ({"findings": 1}, "collecting"), ({"findings": 4, "invalid_or_inevaluable": 3}, "mostly_invalid"), ({"findings": 2, "post_apply_evaluated": 1}, "evaluable"), ({"findings": 2, "post_apply_evaluated": 1, "demonstrated_improvements": 1}, "useful_demonstrated"), ({"findings": 2, "post_apply_evaluated": 2}, "no_improvement_demonstrated")])
def test_utility_states_do_not_treat_volume_as_improvement(metrics, status):
    assert origin_utility_status(metrics) == status
