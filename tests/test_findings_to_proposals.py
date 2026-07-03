import json

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.codegen_nightly import eligible_codegen_proposals
from agente_bolsa.continuous_improvement.findings_to_proposals import (
    OBSERVATION_FAMILY_REJECTION_REASON,
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
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_findings_to_proposals_creates_at_most_three_codegen_ready_items(tmp_path):
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
    assert len(result["created"]) == 3
    eligible = eligible_codegen_proposals(settings=settings, store=store)
    assert len(eligible["eligible"]) == 3


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
