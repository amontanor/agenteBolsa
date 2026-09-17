"""P-L122 caracterizacion: el bucle de promocion debe cerrarse (rojo)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agente_bolsa.continuous_improvement.promotion_loop import (
    close_stale_validations,
    resolve_applied_impacts,
    sync_promotion_policies,
)


def _store(tmp_path):
    from agente_bolsa.config import Settings
    from agente_bolsa.storage import Store

    settings = Settings(_env_file=None, DATA_DIR=tmp_path, ALLOW_LIVE_TRADING=False, TRADING_MODE="paper")
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return store


def _old(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _validation(validation_id, created_at, status="PENDING"):
    return {
        "validation_id": validation_id,
        "proposal_id": "ci_prop_x",
        "cycle_id": "ci_cycle_x",
        "status": status,
        "validation_type": "deterministic",
        "payload": {},
        "created_at": created_at,
    }


def test_close_stale_validations_expires_only_old_pending(tmp_path):
    store = _store(tmp_path)
    store.save_continuous_improvement_validation(_validation("ci_val_old", _old(20)))
    store.save_continuous_improvement_validation(_validation("ci_val_fresh", _old(2)))
    result = close_stale_validations(store)
    assert result["expired"] == 1
    assert result["expired_ids"] == ["ci_val_old"]
    by_id = {v["validation_id"]: v for v in store.continuous_improvement_validations(limit=10)}
    assert by_id["ci_val_old"]["status"] == "EXPIRED_PENDING"
    assert by_id["ci_val_fresh"]["status"] == "PENDING"
    decisions = store.continuous_improvement_decisions(proposal_id="ci_prop_x", limit=10)
    assert any(d["reason"] == "pending_validation_expired" for d in decisions)


def _applied(applied_id, updated_days_ago, *, status="APPLIED", impact="PENDING"):
    return {
        "applied_change_id": applied_id,
        "initiative_id": None,
        "proposal_id": "ci_prop_x",
        "cycle_id": "ci_cycle_x",
        "status": status,
        "change_type": "CODE_CHANGE",
        "target_key": "docs/x.md",
        "before": {},
        "after": {},
        "rollback": {},
        "decision": {"impact_validation": {"status": impact}},
        "validation_ids": [],
        "error": None,
        "created_at": _old(updated_days_ago + 1),
        "updated_at": _old(updated_days_ago),
    }


def test_resolve_applied_impacts_marks_survivors_and_rollback():
    import json

    store = _store(__import__("tempfile").mkdtemp())
    store.save_continuous_improvement_applied_change(_applied("ci_applied_old", 20))
    store.save_continuous_improvement_applied_change(_applied("ci_applied_new", 2))
    store.save_continuous_improvement_applied_change(_applied("ci_applied_rb", 20, status="ROLLED_BACK"))
    result = resolve_applied_impacts(store, clean_days=15)
    assert result["passed"] == ["ci_applied_old"]
    assert result["failed"] == []
    assert result["skipped"] == ["ci_applied_new"]
    changes = {c["applied_change_id"]: c for c in store.continuous_improvement_applied_changes(limit=10)}
    assert changes["ci_applied_old"]["decision"]["impact_validation"]["status"] == "PASSED"


def test_sync_promotion_policies_creates_shadow_never_active(tmp_path):
    store = _store(tmp_path)
    evaluations = [
        {"kind": "setup", "key": "confirmed_pattern", "verdict": "PROMOTE_CANDIDATE",
         "metrics": {"matured_10d": 25, "alpha_10d": 0.02, "expectancy_10d": 0.03}, "sessions": 12},
        {"kind": "tag", "key": "rsi:60_75", "verdict": "HOLD", "metrics": {}, "sessions": 3},
    ]
    result = sync_promotion_policies(store, evaluations=evaluations)
    assert result["shadowed"] == ["auto_setup_confirmed_pattern"]
    assert result["demoted"] == []
    assert result["human_review"] == []
    policies = {p["policy_id"]: p for p in store.learning_policy_candidates()}
    created = policies["auto_setup_confirmed_pattern"]
    assert created["status"] == "shadow"
    assert created["auto_activatable"] in (0, False)


def test_sync_promotion_policies_demotes_and_requests_review(tmp_path):
    store = _store(tmp_path)
    store.upsert_learning_policy_candidate({
        "policy_id": "shadow_penalty_rsi_60_75",
        "name": "Shadow penalty for rsi:60_75",
        "policy_type": "feature_shadow",
        "status": "guarded_active",
        "scope": "global",
        "auto_activatable": False,
        "evidence": {"tag": "rsi:60_75"},
        "metrics": {},
        "notes": "",
        "promoted_at": None,
        "last_evaluated_at": _old(30),
        "created_at": _old(60),
        "updated_at": _old(30),
    })
    evaluations = [
        {"kind": "tag", "key": "rsi:60_75", "verdict": "RETIRE_CANDIDATE",
         "metrics": {"matured_5d": 8, "alpha_5d": -0.03}, "sessions": 6},
    ]
    result = sync_promotion_policies(store, evaluations=evaluations)
    assert result["demoted"] == ["shadow_penalty_rsi_60_75"]
    policies = {p["policy_id"]: p for p in store.learning_policy_candidates()}
    assert policies["shadow_penalty_rsi_60_75"]["status"] == "shadow"
