from dataclasses import asdict, replace

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.models import OrderSnapshot, PortfolioSnapshot, PositionSnapshot, TradeRecommendation
from agente_bolsa.tools import trade_decision as td


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(td, "build_buy_order_plans", lambda *a, **kw: [])
    settings = Settings(_env_file=None, DATA_DIR=tmp_path)
    portfolio = PortfolioSnapshot("paper", "ACTIVE", "USD", 10000, 20000, 20000,
                                  [PositionSnapshot("APO", 7, 805, 137.55, 115, -157.85, -0.164)], [])
    rec = TradeRecommendation("APO", "reduce", 0.99, "Deterioro objetivo bajista",
                              recommendation_id="rec_exact",
                              decision_lineage={"cycle_id": "cycle_exact", "signal_id": "signal_exact"})
    return settings, portfolio, rec


@pytest.mark.parametrize("change,reason", [
    ({"reason": "No es rotacion; deterioro objetivo"}, "ordinary_rotation_or_capital_release"),
    ({"confidence": 0.0}, "below_min_llm_confidence_to_trade"),
    ({"reason": "Esperar"}, "no_objective_exception"),
    ({"target_exposure_pct": 1.0}, "no_reduction_required"),
])
def test_rejected_exit_keeps_exact_identity_and_policy(case, change, reason):
    settings, portfolio, rec = case
    rec = replace(rec, **change)
    before = asdict(rec)
    rejected = []
    assert td.build_order_plans(settings, portfolio, [rec], rejected=rejected) == []
    assert len(rejected) == 1
    assert rejected[0]["reason"] == reason
    assert rejected[0]["recommendation_id"] == "rec_exact"
    assert rejected[0]["cycle_id"] == "cycle_exact"
    assert rejected[0]["signal_id"] == "signal_exact"
    assert "candidate_id" not in rejected[0]
    assert asdict(rec) == before


@pytest.mark.parametrize("state,reason", [
    ("missing", "position_unavailable_or_not_positive"),
    ("order", "symbol_has_open_order"),
    ("fraction", "quantity_below_execution_precision"),
])
def test_position_and_order_rejections(case, state, reason):
    settings, portfolio, rec = case
    if state == "missing":
        portfolio = replace(portfolio, positions=[])
    elif state == "order":
        portfolio = replace(portfolio, open_orders=[OrderSnapshot("o", "APO", "sell", 7, None, "stop", "new")])
    else:
        portfolio = replace(portfolio, positions=[replace(portfolio.positions[0], qty=1e-8)])
    rejected = []
    assert td.build_order_plans(settings, portfolio, [rec], rejected=rejected) == []
    assert rejected[0]["reason"] == reason


def test_capacity_marks_remaining_exits_not_evaluated(case, monkeypatch):
    settings, portfolio, rec = case
    monkeypatch.setattr(td, "_effective_buy_plan_limit", lambda *a: 0)
    rejected = []
    assert td.build_order_plans(settings, portfolio, [rec], rejected=rejected) == []
    assert rejected[0]["reason"] == "cycle_plan_limit_reached"
    assert rejected[0]["checks"]["exit_policy_evaluated"] is False


def test_accepted_exit_has_identical_economics_with_or_without_audit(case):
    settings, portfolio, rec = case
    rejected = []
    audited = td.build_order_plans(settings, portfolio, [rec], rejected=rejected)
    legacy = td.build_order_plans(settings, portfolio, [rec])
    assert len(audited) == len(legacy) == 1
    left, right = asdict(audited[0]), asdict(legacy[0])
    for field in ("plan_id", "created_at"):
        left.pop(field, None)
        right.pop(field, None)
    assert left == right
    assert rejected == []
