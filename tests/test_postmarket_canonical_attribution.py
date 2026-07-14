from __future__ import annotations

from datetime import datetime, timezone

from agente_bolsa.config import Settings
from agente_bolsa.models import AgentEvent
from agente_bolsa.storage import Store
from agente_bolsa.tools.adaptive_tuning import (
    adaptive_config_path,
    promote_post_market_improvements,
)
from agente_bolsa.tools.post_market_review import (
    _canonical_trade_evaluations,
    _evaluate_trade,
    _llm_attribution_conflicts,
    _session_candidate_attribution,
    build_post_market_review,
)


def _order(order_id: str, symbol: str, cycle: str, trigger: str, *, recommendation_id: str) -> dict:
    return {
        "broker_order_id": order_id,
        "plan_id": f"plan-{order_id}",
        "cycle_id": cycle,
        "symbol": symbol,
        "side": "sell",
        "payload": {
            "plan": {
                "plan_id": f"plan-{order_id}",
                "payload": {
                    "recommendation": {
                        "recommendation_id": recommendation_id,
                        "decision_lineage": {
                            "lineage_id": f"lineage-{order_id}",
                            "signal_id": f"signal-{order_id}",
                            "candidate_id": f"candidate-{order_id}",
                            "cycle_id": cycle,
                            "decision_source": "deterministic",
                        },
                    },
                    "risk_decision": {"checks": {"trigger": trigger}},
                },
            }
        },
    }


def _trade(order_id: str, symbol: str, time: str, qty: float, price: float, realized_pl: float) -> dict:
    return {
        "order_id": order_id,
        "symbol": symbol,
        "side": "sell",
        "time": time,
        "date": time[:10],
        "qty": qty,
        "price": price,
        "notional": qty * price,
        "realized_pl": realized_pl,
        "realized_plpc": realized_pl / 100,
    }


def test_two_orders_and_three_fragments_are_two_canonical_evaluations():
    aiz = _order("bo-aiz", "AIZ", "cycle-1", "time_stop_v2", recommendation_id="rec-aiz")
    crwd = _order("bo-crwd", "CRWD", "cycle-2", "time_stop_v2", recommendation_id="rec-crwd")
    rows = [
        _evaluate_trade(_trade("bo-aiz", "AIZ", "2026-07-13T10:00:00Z", 3, 10, -3), portfolio_positions={}, local_orders={}, local_orders_by_id={"bo-aiz": aiz}),
        _evaluate_trade(_trade("bo-aiz", "AIZ", "2026-07-13T10:01:00Z", 2, 11, -2), portfolio_positions={}, local_orders={}, local_orders_by_id={"bo-aiz": aiz}),
        _evaluate_trade(_trade("bo-crwd", "CRWD", "2026-07-13T10:02:00Z", 1, 20, 1), portfolio_positions={}, local_orders={}, local_orders_by_id={"bo-crwd": crwd}),
    ]
    canonical, metrics = _canonical_trade_evaluations(rows)

    assert metrics["broker_orders"] == 2
    assert metrics["activity_fragments"] == 3
    assert metrics["canonical_trade_evaluations"] == 2
    assert metrics["duplicate_fragment_count"] == 1
    aiz_eval = next(item for item in canonical if item["broker_order_id"] == "bo-aiz")
    assert aiz_eval["exit_trigger"] == "time_stop_v2"
    assert aiz_eval["exit_origin"] == "automatic_time_stop"
    assert aiz_eval["verdict"] == "venta_automatica_con_perdida"
    assert next(item for item in canonical if item["broker_order_id"] == "bo-crwd")["activity_count"] == 1


def test_llm_cannot_override_deterministic_exit_origin():
    row = {"broker_order_id": "bo-aiz", "exit_trigger": "time_stop_v2", "exit_origin": "automatic_time_stop"}
    assert _llm_attribution_conflicts([row], {"exit_attributions": [{"broker_order_id": "bo-aiz", "exit_trigger": "manual"}]}) == 1
    assert row["exit_origin"] == "automatic_time_stop"
    assert row["llm_attribution_conflict"] is True


def test_missing_order_id_is_not_joined_by_symbol_or_date():
    rows = [
        {"symbol": "AIZ", "side": "sell", "time": "1", "qty": 1, "price": 1, "notional": 1},
        {"symbol": "AIZ", "side": "sell", "time": "2", "qty": 1, "price": 1, "notional": 1},
    ]
    canonical, metrics = _canonical_trade_evaluations(rows)
    assert len(canonical) == 2
    assert metrics["legacy_unverified_count"] == 2
    assert metrics["duplicate_fragment_count"] == 0


def test_session_ledger_keeps_learning_experiment_and_dedupes_rejections(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for index in range(83):
        store.save_trade_recommendation(
            recommendation_id=f"rec-{index}", cycle_id=f"cycle-{index % 7}", symbol=f"S{index}",
            action="buy", confidence=0.6, payload={
                "cohort": "learning_experiment",
                "decision_lineage": {"signal_id": f"learning_experiment:2026-07-13:UNKNOWN:S{index}"},
            },
        )
    with store.connect() as conn:
        conn.execute("UPDATE trade_recommendations SET created_at = '2026-07-13T12:00:00+00:00'")
    for index in range(14):
        store.record_agent_event(
            AgentEvent(
                agent="scheduler", event_type="paper_auto_trade_completed", cycle_id=f"cycle-{index // 2}",
                payload={"rejected_order_plans": [{"symbol": "AIZ", "stage": "position_sizing", "reason": "capacity"}]},
                created_at=datetime(2026, 7, 13, 18, index, tzinfo=timezone.utc),
            )
        )
    ledger = _session_candidate_attribution(store, "2026-07-13", [])
    assert ledger["recommendations_raw"] == 83
    assert ledger["recommendations_unique"] == 83
    assert ledger["learning_experiment_included"] is True
    assert ledger["rejected_plans_raw"] == 14
    assert ledger["rejected_plans_unique"] == 7
    assert ledger["non_executed_candidates"] == 83


def test_postmarket_suggestion_cannot_change_adaptive_config(tmp_path):
    settings = Settings(DATA_DIR=tmp_path / "data", ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    settings.ensure_runtime_dirs()
    path = adaptive_config_path(settings)
    path.write_bytes(b'{"version":1,"parameters":{}}\n')
    before = path.stat()
    result = promote_post_market_improvements(
        settings,
        {"session_date": "2026-07-13", "proposed_improvements": [{"id": "x", "auto_apply": True}]},
    )
    after = path.stat()
    assert result["status"] == "blocked_by_policy"
    assert path.read_bytes() == b'{"version":1,"parameters":{}}\n'
    assert before.st_mtime_ns == after.st_mtime_ns


def test_build_postmarket_review_publishes_canonical_attribution_without_rewriting_config(tmp_path, monkeypatch):
    settings = Settings(DATA_DIR=tmp_path / "data", ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
    settings.ensure_runtime_dirs()
    path = adaptive_config_path(settings)
    path.write_bytes(b'{"version":1,"parameters":{}}\n')
    before = path.stat()
    portfolio = type("Portfolio", (), {"positions": [], "portfolio_value": 1.0})()
    aiz = _order("bo-aiz", "AIZ", "cycle-aiz", "time_stop_v2", recommendation_id="rec-aiz")
    crwd = _order("bo-crwd", "CRWD", "cycle-crwd", "time_stop_v2", recommendation_id="rec-crwd")
    history = {
        "trades": [
            _trade("bo-aiz", "AIZ", "2026-07-13T10:00:00Z", 3, 10, -3),
            _trade("bo-aiz", "AIZ", "2026-07-13T10:01:00Z", 2, 11, -2),
            _trade("bo-crwd", "CRWD", "2026-07-13T10:02:00Z", 1, 20, 1),
        ],
        "days": [{"date": "2026-07-13", "buy_notional": 0, "sell_notional": 81, "realized_pl": -4, "realized_plpc": -0.04}],
        "local_broker_orders": [aiz, crwd],
        "summary": {"unrealized_pl": 0},
    }
    monkeypatch.setattr("agente_bolsa.tools.post_market_review.BrokerClientFactory.alpaca_portfolio_snapshot", lambda self: portfolio)
    monkeypatch.setattr("agente_bolsa.tools.post_market_review.build_trade_history", lambda *args, **kwargs: history)
    monkeypatch.setattr("agente_bolsa.tools.post_market_review._build_learning_pipeline", lambda *args, **kwargs: ({"updated": 1}, {}, {"path": None, "health": {}, "digest": {}}))
    monkeypatch.setattr("agente_bolsa.tools.post_market_review.build_operational_learning_review", lambda *args, **kwargs: {})
    monkeypatch.setattr("agente_bolsa.tools.post_market_review.promote_post_market_improvements", lambda *args, **kwargs: {"status": "blocked_by_policy", "promoted": []})
    report = build_post_market_review(settings, settings.data_dir / "reports", "pm-test", session_date="2026-07-13", use_llm=False)
    assert report["summary"]["trades_evaluated"] == 2
    assert report["execution_attribution"]["broker_orders"] == 2
    assert report["execution_attribution"]["activity_fragments"] == 3
    assert report["execution_attribution"]["automatic_exit_count"] == 2
    assert report["mandatory_market_review"]["recommendations_reviewed"]["non_executed_candidates"] == 0
    after = path.stat()
    assert before.st_mtime_ns == after.st_mtime_ns
    assert path.read_bytes() == b'{"version":1,"parameters":{}}\n'
