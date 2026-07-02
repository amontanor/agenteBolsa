from __future__ import annotations

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import ready_for_human_approval_requests
from agente_bolsa.storage import Store


def _store(tmp_path) -> Store:
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _proposal(store: Store, proposal_id: str) -> None:
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": proposal_id,
            "cycle_id": "ci_cycle_p4",
            "fingerprint": f"fp_{proposal_id}",
            "proposal_type": "CODE_CHANGE",
            "target_component": "continuous_improvement",
            "target_identifier": "demo",
            "status": "READY_TO_APPLY",
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": {"rollback_plan": "Restore previous file."},
            "guard": {"status": "READY_TO_APPLY", "reasons": []},
        }
    )
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": f"ci_artifact_{proposal_id}",
            "proposal_id": proposal_id,
            "artifact_type": "code_diff_preview",
            "content_text": "diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n+++ b/docs/x.md\n",
            "payload": {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True, "target_paths": ["docs/x.md"]},
        }
    )


def test_pide_aprobacion_excludes_applied_and_rolled_back_proposals(tmp_path):
    store = _store(tmp_path)
    _proposal(store, "ci_prop_applied")
    _proposal(store, "ci_prop_rolled")
    _proposal(store, "ci_prop_open")
    store.save_continuous_improvement_applied_change(
        {
            "applied_change_id": "ci_applied_done",
            "proposal_id": "ci_prop_applied",
            "cycle_id": "ci_cycle_p4",
            "status": "APPLIED",
            "change_type": "CODE_CHANGE",
            "target_key": "docs/x.md",
        }
    )
    store.save_continuous_improvement_applied_change(
        {
            "applied_change_id": "ci_applied_rolled",
            "proposal_id": "ci_prop_rolled",
            "cycle_id": "ci_cycle_p4",
            "status": "ROLLED_BACK",
            "change_type": "CODE_CHANGE",
            "target_key": "docs/x.md",
        }
    )

    requests = ready_for_human_approval_requests(store)

    assert [item["proposal_id"] for item in requests] == ["ci_prop_open"]
