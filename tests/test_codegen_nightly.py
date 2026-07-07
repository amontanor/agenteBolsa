"""Tests del orquestador nightly de codegen revisable."""

import json
from datetime import datetime, timezone
from pathlib import Path

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.codegen import _is_low_risk_codegen_path
from agente_bolsa.continuous_improvement.codegen_nightly import (
    DEMO_CLEANUP_PROPOSAL_ID,
    P15_HOTFIX_COMMIT,
    P15_HOTFIX_PROPOSAL_ID,
    cleanup_codegen_states,
    load_codegen_nightly_config,
    run_codegen_nightly,
)
from agente_bolsa.continuous_improvement.digest import build_lab_digest, format_lab_digest_text
from agente_bolsa.storage import Store


def _settings(tmp_path: Path, **overrides):
    values = {
        "DATA_DIR": tmp_path,
        "TRADING_MODE": "paper",
        "ALLOW_LIVE_TRADING": False,
        "ALLOW_AUTO_APPLY_IMPROVEMENTS": False,
        "CORE_SLEEVE_DRY_RUN": True,
        "LAB_BOOK_ENABLED": False,
        "REQUIRE_HUMAN_APPROVAL_FOR_CODE_CHANGES": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _store(settings: Settings) -> Store:
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _ready_codegen_proposal(store: Store, proposal_id: str, target: str = "docs/generated.md") -> str:
    cycle_id = f"ci_cycle_{proposal_id}"
    payload = {
        "proposal_type": "CODE_CHANGE",
        "target_component": "docs",
        "target_identifier": target,
        "rationale": "Mejora documental de bajo riesgo.",
        "expected_impact": "Aumenta trazabilidad del laboratorio.",
        "risk_level": "LOW",
        "required_validations": ["tests"],
        "rollback_plan": "Eliminar el archivo generado.",
    }
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": proposal_id,
            "cycle_id": cycle_id,
            "fingerprint": proposal_id,
            "proposal_type": "CODE_CHANGE",
            "target_component": "docs",
            "target_identifier": target,
            "status": "READY_TO_APPLY",
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": payload,
            "guard": {"status": "READY_TO_APPLY"},
        }
    )
    store.save_continuous_improvement_validation(
        {
            "validation_id": f"ci_val_{proposal_id}",
            "proposal_id": proposal_id,
            "cycle_id": cycle_id,
            "status": "READY_TO_APPLY",
            "validation_type": "unit",
            "payload": {"objective_status": "READY_TO_APPLY"},
        }
    )
    return proposal_id


def _write_config(path: Path, **overrides) -> Path:
    config = load_codegen_nightly_config(path)
    config.update(overrides)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fake_ready_generator(calls: list[str]):
    def _generator(*, settings, store, proposal_id):  # noqa: ANN001
        calls.append(proposal_id)
        return {
            "ok": True,
            "status": "READY_FOR_HUMAN_REVIEW",
            "artifact": {
                "artifact_id": f"ci_artifact_{proposal_id}",
                "artifact_type": "code_diff_preview",
            },
        }

    return _generator


def test_codegen_nightly_blocks_when_auto_apply_is_not_false(tmp_path):
    settings = _settings(tmp_path, ALLOW_AUTO_APPLY_IMPROVEMENTS=True)
    store = _store(settings)
    _ready_codegen_proposal(store, "ci_prop_auto_apply_block")
    calls: list[str] = []

    result = run_codegen_nightly(
        settings=settings,
        store=store,
        config_path=tmp_path / "codegen_nightly.json",
        generator=_fake_ready_generator(calls),
    )

    assert result["status"] == "BLOCKED_AUTO_APPLY_ENABLED"
    assert calls == []
    assert result["approved_or_applied"] is False
    assert store.continuous_improvement_applied_changes(limit=10) == []


def test_codegen_nightly_blocks_when_human_gate_is_disabled(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _ready_codegen_proposal(store, "ci_prop_human_gate_block")
    config_path = _write_config(tmp_path / "codegen_nightly.json", human_gated=False)
    calls: list[str] = []

    result = run_codegen_nightly(
        settings=settings,
        store=store,
        config_path=config_path,
        generator=_fake_ready_generator(calls),
    )

    assert result["status"] == "BLOCKED_HUMAN_GATE_DISABLED"
    assert calls == []
    assert _is_low_risk_codegen_path("data/config/codegen_nightly.json") is False


def test_codegen_nightly_limits_attempts_to_daily_max_and_never_applies(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    for idx in range(3):
        _ready_codegen_proposal(store, f"ci_prop_daily_{idx}", f"docs/nightly_{idx}.md")
    config_path = _write_config(
        tmp_path / "codegen_nightly.json",
        max_proposals_per_day=2,
        daily_token_budget=64000,
        estimated_tokens_per_proposal=32000,
    )
    calls: list[str] = []

    result = run_codegen_nightly(
        settings=settings,
        store=store,
        config_path=config_path,
        generator=_fake_ready_generator(calls),
        now=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
    )

    assert result["status"] == "COMPLETED"
    assert len(calls) == 2
    assert result["successes"] == 2
    assert result["failures"] == 0
    assert result["ready_for_human_review"] == calls
    assert result["estimated_tokens_used"] == 64000
    assert result["approved_or_applied"] is False
    assert store.continuous_improvement_applied_changes(limit=10) == []
    for proposal_id in calls:
        assert store.continuous_improvement_proposal(proposal_id)["status"] == "READY_TO_APPLY"


def test_codegen_nightly_respects_token_budget(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _ready_codegen_proposal(store, "ci_prop_token_1", "docs/token_1.md")
    _ready_codegen_proposal(store, "ci_prop_token_2", "docs/token_2.md")
    config_path = _write_config(
        tmp_path / "codegen_nightly.json",
        max_proposals_per_day=2,
        daily_token_budget=32000,
        estimated_tokens_per_proposal=32000,
    )
    calls: list[str] = []

    result = run_codegen_nightly(
        settings=settings,
        store=store,
        config_path=config_path,
        generator=_fake_ready_generator(calls),
        now=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
    )

    assert len(calls) == 1
    assert result["estimated_tokens_used"] == 32000
    assert result["skipped"][0]["reason"] == "token_budget_exhausted"


def test_codegen_nightly_filters_targets_and_previous_rejections(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    good = _ready_codegen_proposal(store, "ci_prop_good", "docs/good.md")
    bad_target = _ready_codegen_proposal(store, "ci_prop_bad_target", "src/agente_bolsa/tools/risk.py")
    rejected = _ready_codegen_proposal(store, "ci_prop_rejected_once", "docs/rejected.md")
    rejected_decision = _ready_codegen_proposal(store, "ci_prop_rejected_decision", "docs/rejected_decision.md")
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": "ci_artifact_rejected_once",
            "proposal_id": rejected,
            "artifact_type": "code_diff_codegen_failed",
            "content_text": "",
            "payload": {"status": "FAILED"},
        }
    )
    store.save_continuous_improvement_decision(
        {
            "decision_id": "ci_decision_rejected_decision",
            "proposal_id": rejected_decision,
            "cycle_id": f"ci_cycle_{rejected_decision}",
            "decision": "REJECTED",
            "reason": "previous_manual_rejection",
            "actor": "test",
            "payload": {},
        }
    )
    calls: list[str] = []

    result = run_codegen_nightly(
        settings=settings,
        store=store,
        config_path=_write_config(tmp_path / "codegen_nightly.json", max_proposals_per_day=5),
        generator=_fake_ready_generator(calls),
    )

    assert calls == [rejected, good]
    reasons = {item["proposal_id"]: item["reason"] for item in result["ineligible"]}
    assert reasons[bad_target] == "target_outside_codegen_allowlist"
    assert rejected not in reasons
    assert reasons[rejected_decision] == "previous_codegen_rejection"


def test_codegen_nightly_retries_generation_failures_but_blocks_human_rejection_artifact(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    retryable = _ready_codegen_proposal(store, "ci_prop_retryable_failed", "docs/retryable.md")
    human_rejected = _ready_codegen_proposal(store, "ci_prop_human_rejected", "docs/human_rejected.md")
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": "ci_artifact_retryable_failed",
            "proposal_id": retryable,
            "artifact_type": "code_diff_codegen_failed",
            "content_text": "llm timeout",
            "payload": {"status": "FAILED"},
        }
    )
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": "ci_artifact_human_rejected",
            "proposal_id": human_rejected,
            "artifact_type": "code_diff_human_approval_rejected",
            "content_text": "rechazo humano",
            "payload": {"status": "REJECTED_BY_HUMAN_REVIEW"},
        }
    )
    calls: list[str] = []

    result = run_codegen_nightly(
        settings=settings,
        store=store,
        config_path=_write_config(tmp_path / "codegen_nightly.json", max_proposals_per_day=5),
        generator=_fake_ready_generator(calls),
    )

    assert retryable in calls
    reasons = {item["proposal_id"]: item["reason"] for item in result["ineligible"]}
    assert reasons[human_rejected] == "previous_codegen_rejection"


def test_codegen_cleanup_rejects_demo_and_verifies_p15_commit(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _ready_codegen_proposal(store, DEMO_CLEANUP_PROPOSAL_ID, "docs/ci_codegen_demo.md")
    _ready_codegen_proposal(store, P15_HOTFIX_PROPOSAL_ID, "docs/p15.md")
    store.update_continuous_improvement_proposal_status(
        P15_HOTFIX_PROPOSAL_ID,
        status="APPLIED",
        actor="CodexP15Hotfix",
        reason="hotfix",
        payload={"commit": P15_HOTFIX_COMMIT},
    )

    report = cleanup_codegen_states(store)

    assert report["changed"] == [
        {"proposal_id": DEMO_CLEANUP_PROPOSAL_ID, "status": "REJECTED", "reason": "demo_cleanup"}
    ]
    assert report["checks"][0]["ok"] is True
    assert report["inconsistent"] == []
    assert store.continuous_improvement_proposal(DEMO_CLEANUP_PROPOSAL_ID)["status"] == "REJECTED"
    decision = store.continuous_improvement_decisions(proposal_id=DEMO_CLEANUP_PROPOSAL_ID, limit=1)[0]
    assert decision["reason"] == "demo_cleanup"


def test_lab_digest_includes_codegen_nightly_queue(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    _ready_codegen_proposal(store, "ci_prop_digest_ready", "docs/digest_ready.md")
    calls: list[str] = []
    run_codegen_nightly(
        settings=settings,
        store=store,
        config_path=_write_config(tmp_path / "codegen_nightly.json"),
        generator=_fake_ready_generator(calls),
        now=datetime(2026, 7, 3, 3, 0, tzinfo=timezone.utc),
    )

    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 3, 4, 0, tzinfo=timezone.utc), data_dir=tmp_path)
    text = format_lab_digest_text(digest)

    assert digest["codegen_nightly"]["available"] is True
    assert "Codegen nightly" in text
    assert "Cola para aprobacion humana: ci_prop_digest_ready" in text


def test_lab_digest_excludes_terminal_codegen_artifacts_from_approval_queue(tmp_path):
    settings = _settings(tmp_path)
    store = _store(settings)
    proposal_id = _ready_codegen_proposal(store, "ci_prop_terminal_artifact", "docs/terminal.md")
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": "ci_artifact_terminal_ready",
            "proposal_id": proposal_id,
            "artifact_type": "code_diff_preview",
            "content_text": "diff --git a/docs/terminal.md b/docs/terminal.md\n",
            "payload": {
                "status": "READY_FOR_HUMAN_REVIEW",
                "tests_ok": True,
                "target_paths": ["docs/terminal.md"],
            },
        }
    )
    store.update_continuous_improvement_proposal_status(
        proposal_id,
        status="REJECTED",
        actor="test",
        reason="demo_cleanup",
        payload={},
    )

    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 3, 4, 0, tzinfo=timezone.utc), data_dir=tmp_path)

    assert digest["approval_requests"] == []
