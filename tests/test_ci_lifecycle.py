"""Tests del ciclo de vida del laboratorio (Etapa 7)."""

from datetime import datetime, timedelta, timezone

from agente_bolsa.config import Settings
from agente_bolsa.continuous_improvement.lifecycle import (
    flow_report,
    resolve_initiatives,
    run_lifecycle,
    sweep_stale_tasks,
)
from agente_bolsa.storage import Store


def _setup(tmp_path, **overrides):
    settings = Settings(DATA_DIR=tmp_path, **overrides)
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def _iso_ago(*, hours: float = 0.0, days: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours, days=days)).isoformat()


def _seed_task(store, task_id, status, *, created_at=None, dependency_ids=None, initiative_id=None):
    store.create_continuous_improvement_task(
        {
            "task_id": task_id,
            "cycle_id": None,
            "event_id": "evt",
            "agent_name": "TechnicalAnalystAgent",
            "domain": "trading",
            "status": status,
            "priority": "MEDIUM",
            "dependency_ids": dependency_ids or [],
            "payload": {"initiative_id": initiative_id} if initiative_id else {},
        }
    )
    if created_at:
        # Forzar antiguedad directamente en SQLite (created_at no es editable via API).
        with store.connect() as conn:
            conn.execute(
                "UPDATE continuous_improvement_agent_tasks SET created_at = ? WHERE task_id = ?",
                (created_at, task_id),
            )


def _seed_initiative(store, key, status, *, created_at=None, updated_at=None, **extra):
    initiative_id = f"ini_{key.replace(':', '_')}"
    store.upsert_continuous_improvement_initiative(
        {
            "initiative_id": initiative_id,
            "initiative_key": key,
            "title": key,
            "domain": "trading",
            "status": status,
            "owner_agent": "TechnicalAnalystAgent",
            "priority": "MEDIUM",
            "target_metric": extra.get("target_metric", "false_positive_rate"),
            "baseline_value": extra.get("baseline_value"),
            "current_value": extra.get("current_value"),
            "expected_impact": "",
            "risk_level": "LOW",
            "evidence": [],
            "linked_event_ids": [],
            "linked_task_ids": [],
            "linked_hypothesis_ids": [],
            "linked_proposal_ids": [],
            "linked_validation_ids": [],
            "latest_decision": {},
            "next_action": "",
        }
    )
    with store.connect() as conn:
        if created_at:
            conn.execute(
                "UPDATE continuous_improvement_initiatives SET created_at = ? WHERE initiative_id = ?",
                (created_at, initiative_id),
            )
        if updated_at:
            conn.execute(
                "UPDATE continuous_improvement_initiatives SET updated_at = ? WHERE initiative_id = ?",
                (updated_at, initiative_id),
            )
    return initiative_id


def test_sweep_cancels_expired_tasks_and_dead_dependents(tmp_path):
    settings, store = _setup(tmp_path, CI_TASK_TTL_HOURS=48)
    _seed_task(store, "old_task", "RUNNING", created_at=_iso_ago(hours=72))
    _seed_task(store, "fresh_task", "RUNNING", created_at=_iso_ago(hours=2))
    _seed_task(store, "waiting_task", "WAITING_DEPENDENCY", created_at=_iso_ago(hours=2), dependency_ids=["old_task"])

    result = sweep_stale_tasks(store, settings)

    assert "old_task" in result["expired"]
    assert "waiting_task" in result["cancelled_dependents"]
    statuses = {t["task_id"]: t["status"] for t in store.continuous_improvement_tasks(limit=100)}
    assert statuses["old_task"] == "CANCELLED"
    assert statuses["waiting_task"] == "CANCELLED"
    assert statuses["fresh_task"] == "RUNNING"


def test_stalled_initiative_expires(tmp_path):
    settings, store = _setup(tmp_path, CI_INITIATIVE_TTL_DAYS=5, CI_INITIATIVE_STALL_DAYS=3)
    _seed_initiative(store, "trading:vieja", "VALIDATING", created_at=_iso_ago(days=8), updated_at=_iso_ago(days=4))
    _seed_initiative(store, "trading:fresca", "VALIDATING", created_at=_iso_ago(days=1), updated_at=_iso_ago(hours=2))

    result = resolve_initiatives(store, settings)

    expired_keys = {item["initiative_key"] for item in result["expired"]}
    assert "trading:vieja" in expired_keys
    assert "trading:fresca" not in expired_keys
    rows = {row["initiative_key"]: row for row in store.continuous_improvement_initiatives(limit=50)}
    assert rows["trading:vieja"]["status"] == "REJECTED"
    assert rows["trading:vieja"]["latest_decision"]["decision"] == "EXPIRED"


def test_churning_initiative_expires_even_when_normalizer_refreshes_updated_at(tmp_path):
    settings, store = _setup(tmp_path, CI_INITIATIVE_TTL_DAYS=5, CI_INITIATIVE_STALL_DAYS=3)
    initiative_id = _seed_initiative(
        store,
        "software:runtime_reliability",
        "VALIDATING",
        created_at=_iso_ago(days=9),
        updated_at=_iso_ago(hours=0.1),
    )
    store.upsert_continuous_improvement_proposal(
        {
            "proposal_id": "ci_prop_churn",
            "cycle_id": "ci_cycle_churn",
            "fingerprint": "fp_churn",
            "proposal_type": "CODE_CHANGE",
            "target_component": "continuous_improvement",
            "target_identifier": "runtime_reliability",
            "status": "WAITING_HUMAN_REVIEW",
            "priority": "HIGH",
            "risk_level": "LOW",
            "payload": {"initiative_key": "software:runtime_reliability"},
            "guard": {"status": "WAITING_HUMAN_REVIEW"},
        }
    )
    store.update_continuous_improvement_initiative(
        initiative_id,
        linked_proposal_ids=["ci_prop_churn"],
        latest_decision={"decision": "PENDING", "source": "AutonomyNormalizer"},
        next_action="Revalidar y promover a READY_TO_APPLY o REJECTED.",
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE continuous_improvement_initiatives SET created_at = ?, updated_at = ? WHERE initiative_id = ?",
            (_iso_ago(days=9), _iso_ago(hours=0.1), initiative_id),
        )

    result = resolve_initiatives(store, settings)

    assert result["expired"][0]["initiative_key"] == "software:runtime_reliability"
    initiative = store.continuous_improvement_initiative(initiative_id)
    proposal = store.continuous_improvement_proposal("ci_prop_churn")
    assert initiative["status"] == "REJECTED"
    assert initiative["latest_decision"]["reason"].startswith("churn de decisiones")
    assert proposal["status"] == "REJECTED"


def test_initiative_with_open_tasks_is_not_expired(tmp_path):
    settings, store = _setup(tmp_path, CI_INITIATIVE_TTL_DAYS=5, CI_INITIATIVE_STALL_DAYS=3)
    initiative_id = _seed_initiative(
        store, "trading:con_tareas", "VALIDATING", created_at=_iso_ago(days=8), updated_at=_iso_ago(days=4)
    )
    _seed_task(store, "live_task", "RUNNING", created_at=_iso_ago(hours=1), initiative_id=initiative_id)

    result = resolve_initiatives(store, settings)

    assert result["expired"] == []


def test_monitoring_initiative_closes_with_outcome(tmp_path):
    settings, store = _setup(tmp_path, CI_MONITORING_CLOSE_DAYS=5)
    _seed_initiative(
        store,
        "trading:monitor",
        "MONITORING",
        created_at=_iso_ago(days=12),
        updated_at=_iso_ago(days=6),
        baseline_value=10,
        current_value=4,
        target_metric="false_positive_rate",
    )

    result = resolve_initiatives(store, settings)

    assert len(result["closed"]) == 1
    outcome = result["closed"][0]["outcome"]
    assert outcome["improved"] is True  # 4 < 10 en una metrica a reducir.
    rows = {row["initiative_key"]: row for row in store.continuous_improvement_initiatives(limit=50)}
    assert rows["trading:monitor"]["status"] == "CLOSED"


def test_flow_report_counts_wip_and_throughput(tmp_path):
    settings, store = _setup(tmp_path)
    _seed_initiative(store, "trading:abierta", "VALIDATING", created_at=_iso_ago(days=2))
    _seed_initiative(store, "trading:cerrada", "CLOSED", updated_at=_iso_ago(days=1))

    report = flow_report(store)

    assert report["wip"] == 1
    assert report["resolved_last_7d"] == 1
    assert report["oldest_open_days"] >= 1.9


def test_run_lifecycle_is_idempotent(tmp_path):
    settings, store = _setup(tmp_path, CI_TASK_TTL_HOURS=48, CI_INITIATIVE_TTL_DAYS=5, CI_INITIATIVE_STALL_DAYS=3)
    _seed_task(store, "old_task", "RUNNING", created_at=_iso_ago(hours=72))
    _seed_initiative(store, "trading:vieja", "OPEN", created_at=_iso_ago(days=9), updated_at=_iso_ago(days=5))

    first = run_lifecycle(store, settings)
    second = run_lifecycle(store, settings)

    assert first["tasks"]["expired"] == ["old_task"]
    assert second["tasks"]["expired"] == []
    assert len(first["initiatives"]["expired"]) == 1
    assert second["initiatives"]["expired"] == []
    assert second["flow"]["wip"] == 0
