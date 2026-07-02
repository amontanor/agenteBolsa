from __future__ import annotations

from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.digest import (
    EXECUTABLE,
    PROSE,
    build_lab_digest,
    classify_proposal_quality,
    format_lab_digest_text,
    write_lab_digest_file,
)
from agente_bolsa.storage import Store


def _settings(tmp_path):
    return Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs" / "agents",
        ALPACA_API_KEY="key",
        ALPACA_SECRET_KEY="secret",
        ALLOW_LIVE_TRADING=False,
        TRADING_MODE="paper",
        ALLOW_AUTO_APPLY_IMPROVEMENTS=False,
    )


def _store(tmp_path) -> Store:
    settings = _settings(tmp_path)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _proposal(
    store: Store,
    proposal_id: str,
    *,
    status: str = "READY_TO_APPLY",
    target_component: str = "settings",
    target_identifier: str = "max_orders_per_cycle",
    payload: dict | None = None,
    created_at: str = "2026-06-30T10:00:00+00:00",
) -> None:
    payload = payload or {
        "current_value": "4",
        "proposed_value": "8",
        "rationale": "Currently max_orders_per_cycle is 4; proposed 8.",
        "initiative_key": "software:max_orders_per_cycle",
    }
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": proposal_id,
            "cycle_id": "ci_cycle_phase3",
            "fingerprint": f"fp_{proposal_id}",
            "proposal_type": "PARAMETER_CHANGE",
            "target_component": target_component,
            "target_identifier": target_identifier,
            "status": status,
            "priority": "LOW",
            "risk_level": "LOW",
            "payload": payload,
            "guard": {"status": status, "reasons": []},
            "created_at": created_at,
        }
    )


def test_lab_digest_writes_markdown_file_with_approval_section(tmp_path):
    store = _store(tmp_path)
    _proposal(store, "ci_prop_ready")
    store.save_continuous_improvement_proposal_artifact(
        {
            "artifact_id": "ci_artifact_ready",
            "proposal_id": "ci_prop_ready",
            "artifact_type": "code_diff_preview",
            "content_text": "diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n+++ b/docs/x.md\n",
            "payload": {"status": "READY_FOR_HUMAN_REVIEW", "tests_ok": True, "target_paths": ["docs/x.md"]},
        }
    )

    result = write_lab_digest_file(
        store,
        tmp_path / "reports",
        days=7,
        run_date=datetime(2026, 7, 2, tzinfo=timezone.utc).date(),
        now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )

    path = tmp_path / "reports" / "ci_digest_2026-07-02.md"
    assert result["ok"] is True
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "KPI funnel - ultimas 4 semanas" in text
    assert "Calidad de propuestas - medicion sin enforcement" in text
    assert "PIDE APROBACIÓN" in text
    assert "ci_prop_ready" in text
    assert "docs/x.md" in text


def test_lab_digest_kpis_from_synthetic_database(tmp_path):
    store = _store(tmp_path)
    _proposal(store, "ci_prop_a", created_at="2026-06-29T10:00:00+00:00")
    _proposal(store, "ci_prop_b", status="PENDING", created_at="2026-06-30T10:00:00+00:00")
    store.save_continuous_improvement_experiment(
        {
            "experiment_id": "ci_exp_a",
            "proposal_id": "ci_prop_a",
            "cycle_id": "ci_cycle_phase3",
            "status": "PASSED",
            "created_at": "2026-06-30T12:00:00+00:00",
        }
    )
    store.save_continuous_improvement_applied_change(
        {
            "applied_change_id": "ci_applied_a",
            "proposal_id": "ci_prop_b",
            "cycle_id": "ci_cycle_phase3",
            "status": "APPLIED",
            "change_type": "CODE_CHANGE",
            "target_key": "docs/x.md",
            "created_at": "2026-07-01T12:00:00+00:00",
        }
    )
    store.update_continuous_improvement_proposal_status(
        "ci_prop_a",
        status="READY_TO_APPLY",
        actor="DecisionCommitteeAgent",
        reason="synthetic decision",
        payload={},
    )

    digest = build_lab_digest(store, days=7, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc))
    current_week = digest["kpi_funnel"]["weeks"][-1]

    assert current_week["week_start"] == "2026-06-29"
    assert current_week["proposals"] == 2
    assert current_week["experiments"] == 1
    assert current_week["applied_changes"] == 1
    assert current_week["proposal_to_experiment_pct"] == 50.0
    assert current_week["experiment_to_applied_pct"] == 100.0
    assert digest["kpi_funnel"]["wip_current"]["total"] >= 1


def test_proposal_quality_classifier_executable_and_prose_cases():
    executable_parameter = {
        "target_identifier": "max_orders_per_cycle",
        "payload": {"current_value": "4", "proposed_value": "8"},
    }
    executable_diff = {
        "payload": {"file_edits": [{"path": "docs/x.md", "old": "a", "new": "b"}]},
    }
    executable_shadow = {
        "payload": {
            "promotion_state": "shadow",
            "entry": "rsi_14 < 35",
            "exit": "time stop 5d",
            "stop_loss": "2 ATR",
        }
    }
    executable_metric_target = {
        "target_identifier": "outcome_attribution",
        "payload": {"expected_impact": {"metric": "attributed_outcomes", "current_value": 0, "target_value": 80}},
    }
    prose = {
        "target_identifier": "quality",
        "payload": {"rationale": "Improve the system with better proposals and more focus."},
    }

    assert classify_proposal_quality(executable_parameter)["class"] == EXECUTABLE
    assert classify_proposal_quality(executable_diff)["class"] == EXECUTABLE
    assert classify_proposal_quality(executable_shadow)["class"] == EXECUTABLE
    assert classify_proposal_quality(executable_metric_target)["class"] == EXECUTABLE
    assert classify_proposal_quality(prose)["class"] == PROSE


def test_format_lab_digest_ends_with_pide_aprobacion_section(tmp_path):
    store = _store(tmp_path)
    digest = build_lab_digest(store, days=1, now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc))

    text = format_lab_digest_text(digest)

    assert text.splitlines()[-2] == "PIDE APROBACIÓN"
    assert text.splitlines()[-1] == "- No hay propuestas READY_FOR_HUMAN_REVIEW con tests_ok=true."
