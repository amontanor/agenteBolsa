import json
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.codegen_nightly import eligible_codegen_proposals
from agente_bolsa.continuous_improvement.findings_to_proposals import (
    OBSERVATION_FAMILY_REJECTION_REASON,
    build_code_change_candidates,
    classify_finding_proposal,
    persist_findings_to_proposals,
    settle_observation_execution_family,
)
from agente_bolsa.storage import Store


def _settings(tmp_path, **overrides):
    values = {
        "DATA_DIR": tmp_path,
        "IMPROVEMENT_DRY_RUN": True,
        "ALLOW_AUTO_APPLY_IMPROVEMENTS": False,
        "ALLOW_LIVE_TRADING": False,
        "CONTINUOUS_IMPROVEMENT_WORKSPACE_DIR": Path.cwd(),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_findings_to_proposals_creates_at_most_two_codegen_ready_items(tmp_path):
    settings = _settings(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "lab_book.json").write_text('{"enabled": false}', encoding="utf-8")
    run_dir = tmp_path / "research" / "codegen_nightly"
    run_dir.mkdir(parents=True)
    (run_dir / "runs.jsonl").write_text(
        json.dumps({"ineligible": [{"reason": "not_code_change"} for _ in range(15)]}) + "\n",
        encoding="utf-8",
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    result = persist_findings_to_proposals(settings=settings, store=store, limit=10, dry_run=False)

    assert result["dry_run"] is False
    assert len(result["created"]) == 2
    eligible = eligible_codegen_proposals(settings=settings, store=store)
    assert len(eligible["eligible"]) == 2


def test_findings_to_proposals_dedupes_existing_candidates(tmp_path):
    settings = _settings(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "lab_book.json").write_text('{"enabled": false}', encoding="utf-8")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()

    first = persist_findings_to_proposals(settings=settings, store=store, limit=3, dry_run=False)
    second = persist_findings_to_proposals(settings=settings, store=store, limit=3, dry_run=False)

    assert len(first["created"]) >= 1
    assert second["created"] == []
    assert second["duplicates"]


def test_measured_finding_builds_complete_contract_and_operational_check_stays_separate(tmp_path):
    settings = _settings(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "lab_book.json").write_text('{"enabled": false}', encoding="utf-8")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    preview = persist_findings_to_proposals(settings=settings, store=store, dry_run=True)
    candidate = preview["candidates"][0]
    assert classify_finding_proposal(candidate) == "evidence_experiment"
    assert candidate["evidence_card"] == candidate["experiment_contract"]
    assert classify_finding_proposal({"payload": {"finding_kind": "operational_check"}}) == "operational_check"
    assert build_code_change_candidates([{"finding_id": "lab_book_digest_visibility", "value": 0}]) == []


def test_observation_execution_family_settlement_rejects_active_family(tmp_path):
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    store.create_continuous_improvement_cycle(
        {
            "cycle_id": "ci_cycle_obs",
            "trace_id": "trace",
            "job_id": "job",
            "status": "COMPLETED",
            "mode": "test",
            "dry_run": True,
        }
    )
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": "ci_prop_obs",
            "cycle_id": "ci_cycle_obs",
            "fingerprint": "obs-fp",
            "proposal_type": "MONITORING_CHANGE",
            "target_component": "continuous_improvement",
            "target_identifier": "observation_execution_rate",
            "status": "READY_TO_APPLY",
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": {"target_identifier": "observation_execution_rate"},
            "guard": {},
        }
    )
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": "ci_prop_micro_lotes",
            "cycle_id": "ci_cycle_obs",
            "fingerprint": "obs-fp-micro",
            "proposal_type": "MONITORING_CHANGE",
            "target_component": "continuous_improvement",
            "target_identifier": "Ejecucion Segura de Observaciones en Micro-Lotes",
            "status": "VALIDATING",
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": {"target_identifier": "Ejecucion Segura de Observaciones en Micro-Lotes"},
            "guard": {},
        }
    )

    preview = settle_observation_execution_family(store=store, dry_run=True)
    applied = settle_observation_execution_family(store=store, dry_run=False)

    assert preview["active_proposals"] == 2
    assert set(applied["rejected"]) == {"ci_prop_obs", "ci_prop_micro_lotes"}
    assert store.continuous_improvement_proposal("ci_prop_obs")["status"] == "REJECTED"
    decisions = store.continuous_improvement_decisions(proposal_id="ci_prop_obs")
    assert decisions[0]["reason"] == OBSERVATION_FAMILY_REJECTION_REASON
