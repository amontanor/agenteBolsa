from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.operational_learning import (
    audit_trade_memory_traceability,
    build_decision_memory,
    evaluate_shadow_rules,
)


def test_build_decision_memory_groups_fragmented_orders():
    memories = [
        {
            "memory_id": "m1",
            "trade_time": "2026-04-30T19:26:47Z",
            "trade_date": "2026-04-30",
            "symbol": "WELL",
            "side": "buy",
            "qty": 10,
            "price": 217.0,
            "notional": 2170.0,
            "open_pl": -5.0,
            "verdict": "loser_open",
            "features": {
                "score": 16,
                "distance_sma20": 0.09,
                "volume_zscore_20": -0.2,
                "rsi_14": 70,
            },
            "thesis": {"source_order": {"cycle_id": "cycle-1"}},
            "outcome": {"pl": -5.0},
        },
        {
            "memory_id": "m2",
            "trade_time": "2026-04-30T19:26:48Z",
            "trade_date": "2026-04-30",
            "symbol": "WELL",
            "side": "buy",
            "qty": 5,
            "price": 219.0,
            "notional": 1095.0,
            "open_pl": -2.0,
            "verdict": "loser_open",
            "features": {
                "score": 16,
                "distance_sma20": 0.09,
                "volume_zscore_20": -0.2,
                "rsi_14": 70,
            },
            "thesis": {"source_order": {"cycle_id": "cycle-1"}},
            "outcome": {"pl": -2.0},
        },
    ]

    decisions = build_decision_memory(memories)

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["orders"] == 2
    assert decision["qty"] == 15
    assert decision["avg_price"] == 217.6667
    assert decision["outcome"]["pl"] == -7.0
    assert decision["error_type"] == "execution_fragmentation"
    assert "extendida" in decision["feature_family"]


def test_shadow_rule_promotion_requires_walk_forward_stability(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.upsert_strategy_rule(
        {
            "rule_id": "rule_test_walk_forward",
            "name": "Test walk-forward",
            "description": "Rule for walk-forward stability test",
            "condition": {"all": [{"field": "side", "op": "==", "value": "buy"}]},
            "effect": "block_buy",
            "status": "shadow",
            "source": "test",
            "evidence": {},
            "metrics": {},
        }
    )
    values = (
        [-5.0] * 3
        + [1.0] * 3
        + [-5.0] * 3
        + [1.0] * 3
        + [1.0] * 8
    )
    for idx, pl in enumerate(values, start=1):
        trade_date = f"2026-05-{idx:02d}"
        store.save_trade_memory(
            {
                "memory_id": f"m{idx}",
                "trade_time": f"{trade_date}T15:30:00Z",
                "trade_date": trade_date,
                "symbol": f"S{idx}",
                "side": "buy",
                "qty": 1,
                "price": 100.0,
                "notional": 100.0,
                "verdict": "winner_open" if pl > 0 else "loser_open",
                "features": {},
                "thesis": {},
                "outcome": {"pl": pl, "verdict": "winner_open" if pl > 0 else "loser_open"},
            }
        )

    report = evaluate_shadow_rules(
        store,
        since_date="2026-05-01",
        settings=Settings(
            DATA_DIR=tmp_path,
            SHADOW_RULE_WF_WINDOW_SESSIONS=5,
            SHADOW_RULE_WF_MIN_CASES_PER_WINDOW=3,
            SHADOW_RULE_WF_MIN_WINDOWS=3,
            SHADOW_RULE_WF_MIN_STABLE_RATIO=0.67,
        ),
    )

    rule = report["metrics_by_rule"]["rule_test_walk_forward"]
    assert rule["cases"] == 20
    assert rule["net_shadow_pl"] > 0
    assert rule["walk_forward"]["eligible_windows"] == 4
    assert rule["walk_forward"]["stable_windows"] == 2
    assert rule["status"] == "shadow"


def test_traceability_audit_detects_future_signal_link(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="sig_future",
        source_run_id="scan_future",
        source="test",
        symbol="AAPL",
        signal_date="2026-05-14",
        decision="approved_buy",
        features={"score": 16},
        outcome={},
    )
    store.save_broker_order(
        broker_order_id="bo1",
        plan_id="plan1",
        cycle_id="cycle1",
        symbol="AAPL",
        side="buy",
        status="filled",
        payload={"plan": {"payload": {"recommendation": {"symbol": "AAPL"}}}},
    )
    store.save_trade_memory(
        {
            "memory_id": "tm1",
            "trade_time": "2026-05-13T15:30:00Z",
            "trade_date": "2026-05-13",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 1,
            "price": 100.0,
            "notional": 100.0,
            "verdict": "pending",
            "features": {},
            "thesis": {
                "source_order": {"broker_order_id": "bo1", "plan_id": "plan1", "cycle_id": "cycle1"},
                "signal": {"signal_id": "sig_future", "symbol": "AAPL", "signal_date": "2026-05-14"},
            },
            "outcome": {},
        }
    )

    audit = audit_trade_memory_traceability(store, since_date="2026-05-01")

    assert audit["complete"] is False
    assert audit["issue_counts"]["signal_after_trade"] == 1
