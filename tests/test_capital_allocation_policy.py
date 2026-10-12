import json
from datetime import datetime, timezone

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.capital_allocation_policy import (
    BASELINE_SOURCE_TREE,
    REGISTERED_AT,
    SCHEMA_VERSION,
    active_stage_limits,
    cap_allocation_notional,
    evaluate_allocation_readiness,
    evidence_content_hash,
    load_capital_allocation_policy,
    policy_fingerprint,
    receipt_content_hash,
)

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def _policy(stage=2):
    return {"schema_version": SCHEMA_VERSION, "stage": stage, "mode": "guarded_active",
            "enable_adds": False, "baseline_source_tree": BASELINE_SOURCE_TREE, "registered_at": REGISTERED_AT}


def _evidence(p):
    h = policy_fingerprint(p)
    return {"policy_hash": h, "as_of": "2026-10-20T10:00:00Z", "policy_registered_at": p["registered_at"],
            "completed_shadow_sessions": [
                {"session_id": f"2026-10-{day:02}", "closed_at": f"2026-10-{day:02}T20:00:00Z",
                 "calendar": "XNYS", "status": "completed", "policy_hash": h,
                 "coverage_start": f"2026-10-{day:02}T13:30:00Z", "coverage_end": f"2026-10-{day:02}T20:00:00Z",
                 "event_id": f"session-{day}", "content_hash": f"hash-{day}"}
                for day in [13, 14, 15, 16, 19]],
            "trading_mode": "paper", "alpaca_paper": True, "allow_live_trading": False,
            "allow_auto_apply_improvements": False, "lineage_coverage": 0.99,
            "quantities_reconciled": True, "broker_protection_reconciled": True,
            "critical_alerts": 0, "missing_critical_data": 0, "material_loss_windows": 0,
            "positive_windows": 2, "mature_buys": 50, "controls": 35}


def _write(tmp_path, p):
    d = tmp_path / "config"
    d.mkdir(exist_ok=True)
    (d / "capital_allocation_policy.json").write_text(json.dumps(p), encoding="utf-8")


def _settings(tmp_path):
    return Settings(_env_file=None, DATA_DIR=str(tmp_path), TRADING_MODE="paper",
                    ALPACA_PAPER=True, ALLOW_LIVE_TRADING=False,
                    ALLOW_AUTO_APPLY_IMPROVEMENTS=False, MAX_TOTAL_OPEN_RISK=0.03)


def _active(tmp_path, stage=2):
    p = _policy(stage)
    p["approval"] = {"human_approved": True, "approval_id": "operator-review",
                     "policy_hash": policy_fingerprint(p)}
    p["evidence"] = _evidence(p)
    if stage >= 3:
        p["evidence"]["comparison_windows"] = [
            {"start": "2026-10-13T00:00:00Z", "end": "2026-10-15T20:00:00Z",
             "net_excess_vs_control": 0.001, "drawdown_deterioration": 0.0,
             "costs_included": True, "identities_verified": True, "policy_hash": policy_fingerprint(p)},
            {"start": "2026-10-16T00:00:00Z", "end": "2026-10-19T20:00:00Z",
             "net_excess_vs_control": 0.002, "drawdown_deterioration": 0.01,
             "costs_included": True, "identities_verified": True, "policy_hash": policy_fingerprint(p)},
        ]
    s = _settings(tmp_path)
    st = Store(s.database_path, s.agent_logs_dir)
    st.ensure_schema()
    for session in p["evidence"]["completed_shadow_sessions"]:
        payload = {"policy_hash": policy_fingerprint(p), "review_status": "verified",
                   "session": {k: v for k, v in session.items() if k not in {"event_id", "content_hash"}}}
        payload["content_hash"] = receipt_content_hash(payload)
        session["content_hash"] = payload["content_hash"]
        st.record_append_only_event(event_id=session["event_id"], event_type="capital_allocation_session_reviewed",
                                    cycle_id=None, payload=payload)
    payload = {"policy_hash": policy_fingerprint(p), "review_status": "verified", "approval_id": "operator-review",
               "evidence_hash": evidence_content_hash(p["evidence"])}
    payload["content_hash"] = receipt_content_hash(payload)
    event_id = "evidence-" + str(stage)
    st.record_append_only_event(event_id=event_id, event_type="capital_allocation_evidence_reviewed", cycle_id=None, payload=payload)
    p["evidence"]["source_receipt"] = {"event_id": event_id, "content_hash": payload["content_hash"]}
    _write(tmp_path, p)
    return p, load_capital_allocation_policy(tmp_path, _settings(tmp_path), now=NOW)


def _cap(p, **overrides):
    args = {"desired_notional": 5000, "equity": 100_000, "cash": 50_000,
            "buying_power": 100_000, "current_exposure": 0.10, "pending_exposure": 0,
            "planned_exposure": 0, "pending_buy_notional": 0, "planned_buy_notional": 0}
    args.update(overrides)
    return cap_allocation_notional(p, **args)


def test_absent_policy_is_non_mutating_shadow(tmp_path):
    p = load_capital_allocation_policy(tmp_path, _settings(tmp_path), now=NOW)
    assert not p["active"] and p["status"] == "shadow"
    assert active_stage_limits(p) is None
    assert not (tmp_path / "config" / "capital_allocation_policy.json").exists()


def test_active_policy_requires_exact_approved_parameters_and_evidence(tmp_path):
    raw, p = _active(tmp_path)
    assert p["active"] and active_stage_limits(p)["exposure"] == 0.15
    raw["enable_adds"] = True
    _write(tmp_path, raw)
    p = load_capital_allocation_policy(tmp_path, _settings(tmp_path), now=NOW)
    assert not p["active"] and "human_approval_required" in p["reasons"]


@pytest.mark.parametrize("field,value", [("lineage_coverage", float("nan")),
    ("broker_protection_reconciled", False), ("critical_alerts", None),
    ("missing_critical_data", 1), ("quantities_reconciled", False), ("as_of", "2026-11-01T00:00:00Z")])
def test_evidence_missing_or_invalid_is_not_promoted(tmp_path, field, value):
    raw = _policy()
    e = _evidence(raw)
    e[field] = value
    assert not evaluate_allocation_readiness(e, stage=2, policy_hash=policy_fingerprint(raw), now=NOW)["eligible"]


def test_repeated_session_and_changed_policy_do_not_count(tmp_path):
    raw = _policy()
    e = _evidence(raw)
    e["completed_shadow_sessions"][-1] = e["completed_shadow_sessions"][0]
    assert not evaluate_allocation_readiness(e, stage=2, policy_hash=policy_fingerprint(raw), now=NOW)["eligible"]


@pytest.mark.parametrize("stage,count", [(3, 34), (4, 49)])
def test_ladder_mature_count_is_retained(tmp_path, stage, count):
    raw, _ = _active(tmp_path, stage)
    raw["evidence"]["mature_buys"] = count
    _write(tmp_path, raw)
    assert not load_capital_allocation_policy(tmp_path, _settings(tmp_path), now=NOW)["active"]


def test_overlapping_or_costless_windows_block_promotion(tmp_path):
    raw, p = _active(tmp_path, 3)
    assert p["active"]
    raw["evidence"]["comparison_windows"][1]["start"] = "2026-10-14T00:00:00Z"
    _write(tmp_path, raw)
    assert not load_capital_allocation_policy(tmp_path, _settings(tmp_path), now=NOW)["active"]


def test_cash_pending_and_batch_plans_prevent_margin_and_double_spending():
    value, checks = _cap({"stage": 2}, cash=3000, pending_buy_notional=1000, planned_buy_notional=1500)
    assert value == 500 and checks["cash_room"] == 500
    value, _ = _cap({"stage": 2}, cash=0, buying_power=200_000)
    assert value == 0


def test_stage_room_rounding_and_zero_never_force_buy():
    value, _ = _cap({"stage": 2}, current_exposure=0.14, pending_exposure=0.005, planned_exposure=0.004)
    assert 99.99 <= value <= 100
    assert _cap({"stage": 2}, desired_notional=0)[0] == 0
    assert _cap({"stage": 4})[0] == 2500


def test_higher_size_requires_separate_validated_quality_policy():
    p = {"stage": 3, "quality_policy_hash": "quality", "quality_policy_approved": True}
    assert _cap(p, high_tier={"eligible": True})[0] == 2500
    assert _cap(p, high_tier={"eligible": True, "authority": "validated_quality", "policy_hash": "quality"})[0] == 2500
    proven = {"eligible": True, "authority": "validated_quality", "policy_hash": "quality", "score": 85,
              "components_complete": True, "expectancy_validated": True, "costs_included": True,
              "identity_verified": True, "hard_gates_passed": True, "approval_token": "review", "evidence_id": "evidence"}
    assert _cap(p, high_tier=proven)[0] == 5000
    assert _cap(p, high_tier={**proven, "score": 84})[0] == 2500


@pytest.mark.parametrize("field", ["cash", "pending_buy_notional", "equity", "planned_exposure"])
def test_unknown_or_nan_sizing_inputs_fail_closed(field):
    assert _cap({"stage": 2}, **{field: float("nan")})[0] == 0


def test_live_or_auto_apply_and_excess_risk_are_blocked(tmp_path):
    raw, _ = _active(tmp_path)
    s = _settings(tmp_path).model_copy(update={"allow_live_trading": True})
    assert not load_capital_allocation_policy(tmp_path, s, now=NOW)["active"]
    s = _settings(tmp_path).model_copy(update={"max_risk_per_trade": 0.02})
    assert not load_capital_allocation_policy(tmp_path, s, now=NOW)["active"]
