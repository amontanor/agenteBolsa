from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agente_bolsa.config import Settings
from agente_bolsa.models import OrderPlan, RiskDecision, TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.daily_learning import _materialize_observations
from agente_bolsa.tools.decision_context import (
    SCHEMA_VERSION,
    build_decision_context_quality,
    build_decision_context_snapshot,
    copy_snapshot,
    normalize_decision_source,
    validate_decision_context_snapshot,
)


def make_store(tmp_path):
    settings = Settings(
        DATA_DIR=tmp_path,
        DATABASE_PATH=tmp_path / "state" / "test.sqlite3",
        AGENT_LOGS_DIR=tmp_path / "logs",
    )
    store = Store(settings.database_path, settings.agent_logs_dir)
    store.ensure_schema()
    return settings, store


def market_state(cycle_id="cycle-1", as_of="2026-07-12T09:00:00+00:00"):
    return {
        "run_id": cycle_id,
        "as_of": as_of,
        "prompt_version": "market_state.v2",
        "market_regime": "neutral",
        "volatility_regime": "low",
        "risk_posture": "balanced",
        "data_quality": {"status": "GOOD"},
    }


def recommendation(source="llm", **kwargs):
    return TradeRecommendation(
        symbol="AAPL",
        action="buy",
        confidence=0.7,
        reason="measured",
        source=source,
        **kwargs,
    )


def snapshot(rec=None, **kwargs):
    return build_decision_context_snapshot(
        rec or recommendation(),
        cycle_id=kwargs.pop("cycle_id", "cycle-1"),
        source_run_id=kwargs.pop("source_run_id", "source-1"),
        market_state=kwargs.pop("market_state", market_state()),
        captured_at=kwargs.pop("captured_at", datetime(2026, 7, 12, 10, tzinfo=timezone.utc)),
        identity_key=kwargs.pop("identity_key", "stable-key"),
        **kwargs,
    )


def test_same_cycle_market_state_is_admitted_and_hashed():
    item = snapshot()
    assert item["schema_version"] == SCHEMA_VERSION
    assert item["market_state_ref"]["cycle_id"] == item["cycle_id"]
    assert item["market_state_ref"]["status"] == "available"
    validate_decision_context_snapshot(item)


def test_different_cycle_market_state_is_rejected():
    with pytest.raises(ValueError, match="market_state_cycle_mismatch"):
        snapshot(market_state=market_state("cycle-2"))


def test_market_state_after_capture_is_rejected():
    with pytest.raises(ValueError, match="market_state_after_capture"):
        snapshot(market_state=market_state(as_of="2026-07-12T11:00:00+00:00"))


def test_missing_market_state_is_explicitly_unavailable():
    item = snapshot(market_state=None)
    assert item["market_state_ref"]["status"] == "unavailable"
    assert item["market_state_ref"]["cycle_id"] == "cycle-1"


def test_latest_report_cannot_replace_exact_state():
    exact = market_state("cycle-1")
    item = snapshot(market_state=exact)
    assert item["market_state_ref"]["run_id"] == "cycle-1"


def test_hash_excludes_capture_time_but_identity_is_stable():
    first = snapshot(captured_at=datetime(2026, 7, 12, 10, tzinfo=timezone.utc))
    second = snapshot(captured_at=datetime(2026, 7, 12, 10, 30, tzinfo=timezone.utc))
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["content_hash"] == second["content_hash"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("llm", "llm"),
        ("deterministic_fallback", "fallback"),
        ("deterministic_capacity_fill", "capacity_fill"),
        ("deterministic_hold_override", "hold_override"),
        ("deterministic", "deterministic"),
        ("", "unknown"),
    ],
)
def test_decision_source_normalization(raw, expected):
    assert normalize_decision_source(raw) == expected


def test_raw_source_is_preserved():
    item = snapshot(recommendation("deterministic_capacity_fill"))
    assert item["decision_source_raw"] == "deterministic_capacity_fill"
    assert item["decision_source"] == "capacity_fill"


def test_fallback_requires_stable_reason_code():
    with pytest.raises(ValueError, match="fallback_reason_required"):
        snapshot(recommendation("deterministic_fallback"))
    item = snapshot(recommendation("deterministic_fallback"), fallback_reason="quota exceeded")
    assert item["fallback_reason"] == "llm_quota"


def test_capacity_fill_is_not_fallback():
    item = snapshot(recommendation("deterministic_capacity_fill"))
    assert item["decision_source"] == "capacity_fill"
    assert item["fallback_reason"] is None


def test_unknown_source_does_not_infer_llm_considered():
    item = snapshot(recommendation("unknown"))
    assert item["decision_source"] == "unknown"
    assert item["llm_considered"] is None
    assert item["llm_response_status"] == "unavailable"


def test_llm_model_can_be_null():
    item = snapshot(recommendation("llm"), llm_considered=True, llm_model=None)
    assert item["llm_model"] is None


def test_agent_run_id_is_preserved_without_invention():
    item = snapshot(agent_run_id="agent_run_real")
    assert item["agent_run_id"] == "agent_run_real"
    assert snapshot()["agent_run_id"] is None


def test_exact_signal_link_is_verified_and_attached(tmp_path):
    _settings, store = make_store(tmp_path)
    signal_id = "learning_experiment:2026-07-12:BUILTIN_BREAKOUT:AAPL"
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="source-1",
        source="learning_experiment",
        symbol="AAPL",
        signal_date="2026-07-12",
        decision="candidate",
        features={"strategy_name": "builtin_breakout"},
        gate={},
        outcome={},
    )
    from agente_bolsa.cycle_runner import _decision_context_snapshot_for_recommendation

    rec = recommendation()
    rec = TradeRecommendation(
        **{
            **rec.__dict__,
            "decision_lineage": {"signal_id": signal_id, "signal_source_run_id": "source-1"},
        }
    )
    item = _decision_context_snapshot_for_recommendation(
        store,
        rec,
        cycle_id="cycle-1",
        source_run_id="source-1",
        market_state=market_state(),
        agent_run_id="agent_run_real",
        llm_model="model",
        identity_key="signal-key",
    )
    assert item["signal_link_status"] == "verified"
    assert store.signal_outcome_by_id(signal_id)["features"]["decision_context_snapshot"]["content_hash"] == item["content_hash"]


def test_unknown_signal_never_becomes_builtin_verified(tmp_path):
    _settings, store = make_store(tmp_path)
    signal_id = "learning_experiment:2026-07-12:BUILTIN_BREAKOUT:AAPL"
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="source-1",
        source="learning_experiment",
        symbol="AAPL",
        signal_date="2026-07-12",
        decision="candidate",
        features={},
        gate={},
        outcome={},
    )
    from agente_bolsa.cycle_runner import _decision_context_snapshot_for_recommendation

    rec = recommendation()
    rec = TradeRecommendation(**{**rec.__dict__, "decision_lineage": {"signal_id": "learning_experiment:2026-07-12:UNKNOWN:AAPL"}})
    item = _decision_context_snapshot_for_recommendation(
        store,
        rec,
        cycle_id="cycle-1",
        source_run_id="source-1",
        market_state=market_state(),
        agent_run_id=None,
        identity_key="unknown-key",
    )
    assert item["signal_link_status"] == "broken"
    assert "decision_context_snapshot" not in store.signal_outcome_by_id(signal_id)["features"]


def test_signal_without_id_is_unavailable():
    assert snapshot()["signal_link_status"] == "unavailable"


@pytest.mark.parametrize(
    "bad_key",
    ["return_1d", "mfe_10d", "mae_10d", "first_hit", "verdict", "execution_snapshot", "slippage"],
)
def test_post_decision_fields_are_rejected_even_nested(bad_key):
    item = snapshot()
    item["nested"] = {bad_key: 1}
    with pytest.raises(ValueError, match="post_decision_field"):
        validate_decision_context_snapshot(item)


def test_pre_decision_only_is_required():
    item = snapshot()
    item["pre_decision_only"] = False
    item["content_hash"] = "invalid"
    with pytest.raises(ValueError, match="not_pre_decision"):
        validate_decision_context_snapshot(item)


def test_copy_is_detached_and_validated():
    original = snapshot()
    copied = copy_snapshot(original)
    copied["market_state_ref"]["market_regime"] = "changed"
    assert original["market_state_ref"]["market_regime"] == "neutral"


def test_signal_snapshot_attachment_is_idempotent_and_conflicts_are_visible(tmp_path):
    _settings, store = make_store(tmp_path)
    signal_id = "signal-1"
    store.save_signal_outcome(
        signal_id=signal_id,
        source_run_id="source-1",
        source="test",
        symbol="AAPL",
        signal_date="2026-07-12",
        decision="candidate",
        features={},
        gate={},
        outcome={},
    )
    first = snapshot()
    assert store.attach_decision_context_snapshot(signal_id, first) == "attached"
    assert store.attach_decision_context_snapshot(signal_id, first) == "idempotent"
    different = snapshot(identity_key="different")
    assert store.attach_decision_context_snapshot(signal_id, different) == "conflict"


def test_observation_materialization_keeps_snapshot(tmp_path):
    _settings, store = make_store(tmp_path)
    item = snapshot()
    rows = [
        {
            "signal_id": "signal-1",
            "signal_date": "2026-07-12",
            "symbol": "AAPL",
            "source": "test",
            "source_run_id": "source-1",
            "decision": "candidate",
            "score": 10,
            "features": {"decision_context_snapshot": item},
            "gate": {},
            "outcome": {},
            "flags": {},
            "orders_same_day": 0,
            "created_at": "2026-07-12T09:00:00+00:00",
        }
    ]
    observations = _materialize_observations(store, rows)
    assert observations[0]["features"]["decision_context_snapshot"]["content_hash"] == item["content_hash"]


def test_plan_serialization_carries_same_snapshot():
    item = snapshot()
    rec = recommendation(decision_context_snapshot=item)
    plan = OrderPlan(
        symbol="AAPL",
        side="buy",
        notional=100.0,
        qty=1.0,
        entry_price=100.0,
        stop_loss=90.0,
        take_profit=130.0,
        recommendation=rec,
        risk_decision=RiskDecision(True, "ok", {}),
    )
    assert plan.recommendation.decision_context_snapshot["content_hash"] == item["content_hash"]


def test_legacy_signal_remains_without_snapshot(tmp_path):
    _settings, store = make_store(tmp_path)
    store.save_signal_outcome(
        signal_id="legacy",
        source_run_id="old",
        source="legacy",
        symbol="AAPL",
        signal_date="2026-01-01",
        decision="candidate",
        features={},
        gate={},
        outcome={},
    )
    assert "decision_context_snapshot" not in store.signal_outcome_by_id("legacy")["features"]


def test_digest_quality_has_explicit_denominators(tmp_path):
    _settings, store = make_store(tmp_path)
    item = snapshot()
    store.save_trade_recommendation(
        recommendation_id="rec-1",
        cycle_id="cycle-1",
        symbol="AAPL",
        action="buy",
        confidence=0.7,
        payload={"decision_context_snapshot": item},
    )
    quality = build_decision_context_quality(
        store,
        now=datetime.now(timezone.utc) + timedelta(seconds=1),
        days=1,
    )
    assert quality["recommendations_total_new"] == 1
    assert quality["recommendations_with_snapshot"] == 1
    assert quality["recommendation_snapshot_coverage"] == 1.0
    assert quality["post_decision_contamination_count"] == 0


def test_digest_without_new_records_is_collecting(tmp_path):
    _settings, store = make_store(tmp_path)
    quality = build_decision_context_quality(store, now=datetime.now(timezone.utc), days=1)
    assert quality["status"] == "collecting"
    assert quality["recommendation_snapshot_coverage"] is None


def test_no_network_or_llm_is_needed(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: pytest.fail("network"))
    item = snapshot()
    assert item["schema_version"] == SCHEMA_VERSION
