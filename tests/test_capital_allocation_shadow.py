import copy
from dataclasses import asdict
from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.eventing import EventReporter
from agente_bolsa.models import PortfolioSnapshot
from agente_bolsa.storage import Store
from agente_bolsa.tools.capital_allocation_policy import load_capital_allocation_policy
from agente_bolsa.tools.capital_allocation_shadow import (
    build_capital_allocation_shadow,
    persist_capital_allocation_shadow,
    shadow_content_hash,
)


def _inputs(tmp_path):
    s = Settings(_env_file=None, DATA_DIR=str(tmp_path), ALLOW_LIVE_TRADING=False,
                 ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    lineage = {"cycle_id": "cycle", "candidate_id": "candidate", "signal_capture_id": "capture",
               "recommendation_id": "rec"}
    rec = {"symbol": "AAPL", "action": "buy", "recommendation_id": "rec", "decision_lineage": lineage}
    plan = {"notional": 1000, "recommendation": rec, "decision_lineage": lineage,
            "risk_decision": {"approved": True, "checks": {"position_sizing": {
                "max_risk_notional": 20000, "adjusted_target_notional": 2500,
                "available_position_room": 5000, "available_buying_power": 200_000}}}}
    portfolio = PortfolioSnapshot(account_id="paper", status="ACTIVE", currency="USD", cash=3000,
        portfolio_value=100_000, buying_power=200_000, positions=[], open_orders=[])
    policy = load_capital_allocation_policy(tmp_path, s)
    return s, rec, plan, portfolio, policy


def _build(tmp_path, **overrides):
    _, rec, plan, portfolio, policy = _inputs(tmp_path)
    args = {"cycle_id": "cycle", "policy": policy, "portfolio": portfolio, "recommendations": [rec],
            "plans": [plan], "funnel": {"content_hash": "legacy", "details": []},
            "captured_at": datetime(2026, 10, 12, 12, tzinfo=timezone.utc)}
    args.update(overrides)
    return build_capital_allocation_shadow(**args)


def test_shadows_are_not_orders_or_proven_executable_capacity(tmp_path):
    s, rec, plan, portfolio, policy = _inputs(tmp_path)
    before = copy.deepcopy([rec, plan, asdict(portfolio)])
    x = _build(tmp_path)
    assert x["details"][0]["variants"]["2"]["hypothetical_notional"] == 2500
    assert x["details"][0]["baseline_notional"] == 1000
    assert x["details"][0]["variants"]["2"]["executable"] is False
    assert not x["can_authorize_size"] and not x["can_change_orders"]
    assert x["details"][0]["broker_protection"] == "unavailable"
    assert before == [rec, plan, asdict(portfolio)]


def test_missing_account_and_identity_cannot_become_zero_or_symbol_join(tmp_path):
    _, rec, plan, _, _ = _inputs(tmp_path)
    rec["decision_lineage"]["candidate_id"] = "different"
    x = _build(tmp_path, portfolio=None, recommendations=[rec])
    assert x["account"]["equity"] is None
    assert x["details"][0]["baseline_notional"] is None
    assert x["details"][0]["variants"]["2"]["hypothetical_notional"] is None


def test_duplicate_exact_identity_does_not_resolve_to_a_plan(tmp_path):
    _, rec, _, _, _ = _inputs(tmp_path)
    x = _build(tmp_path, recommendations=[rec, copy.deepcopy(rec)])
    assert x["denominators"]["verified_buy_identities"] == 0
    assert all(row["baseline_notional"] is None for row in x["details"])


def test_append_only_retry_is_idempotent_and_changed_input_creates_conflict(tmp_path):
    s, _, _, _, _ = _inputs(tmp_path)
    st = Store(s.database_path, s.agent_logs_dir)
    st.ensure_schema()
    x = _build(tmp_path)
    assert persist_capital_allocation_shadow(st, x)["status"] == "inserted"
    replay = {**x, "captured_at": "2026-10-12T12:01:00Z"}
    assert persist_capital_allocation_shadow(st, replay)["status"] == "idempotent"
    changed = copy.deepcopy(x)
    changed["account"]["cash"] = 4000
    changed["content_hash"] = shadow_content_hash(changed)
    assert persist_capital_allocation_shadow(st, changed)["status"] == "conflict"


def test_post_route_shadow_failure_does_not_change_legacy_funnel(tmp_path, monkeypatch):
    from agente_bolsa import cycle_runner as cr

    s, rec, plan, portfolio, _ = _inputs(tmp_path)
    st = Store(s.database_path, s.agent_logs_dir)
    st.ensure_schema()
    reporter = EventReporter(st, verbose=False)
    kwargs = {"store": st, "reporter": reporter, "phase_a": None, "run_id": "cycle",
              "recommendations": [rec], "plans": [plan], "account": {"equity": 100_000}}
    first = cr._persist_capital_deployment_funnel_shadow(**kwargs)
    monkeypatch.setattr(cr, "persist_capital_allocation_shadow", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("injected")))
    second = cr._persist_capital_deployment_funnel_shadow(**kwargs, portfolio_snapshot=portfolio,
                                                        allocation_settings=s)
    assert first["content_hash"] == second["content_hash"]
    assert first["denominators"] == second["denominators"]
    assert second["persist_status"] == "idempotent"


def test_shadow_reserves_projected_batch_and_local_pending(tmp_path):
    _, rec, plan, _, _ = _inputs(tmp_path)
    second = copy.deepcopy(rec)
    second["recommendation_id"] = "rec2"
    second["decision_lineage"]["recommendation_id"] = "rec2"
    second["decision_lineage"]["candidate_id"] = "candidate2"
    second_plan = copy.deepcopy(plan)
    second_plan["recommendation"] = second
    second_plan["decision_lineage"] = second["decision_lineage"]
    observation = {"kind": "portfolio_reservations", "pending_buy_notional": 1000,
                   "pending_plan_reservations_complete": True}
    result = _build(tmp_path, recommendations=[rec, second], plans=[plan, second_plan],
                    allocation_observations=[observation])
    amounts = [row["variants"]["2"]["hypothetical_notional"] for row in result["details"]]
    assert amounts == [2000, 0]
    assert sum(amounts) <= 2000
    assert result["details"][1]["variants"]["2"]["planned_buy_notional_before"] == 2000


def test_compact_frontier_preserves_exact_candidate_binding(tmp_path):
    detail = {"identity_key": "cycle|buy|capture|rec", "candidate_id": "candidate",
              "recommendation_id": "rec", "action": "buy", "primary_drop_reason": "health"}
    result = _build(tmp_path, funnel={"details": [detail]})
    assert result["details"][0]["first_effective_boundary"] == "health"
    detail["candidate_id"] = "other"
    result = _build(tmp_path, funnel={"details": [detail]})
    assert result["details"][0]["first_effective_boundary"] is None
