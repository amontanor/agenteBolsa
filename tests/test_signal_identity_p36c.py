from agente_bolsa.models import TradeRecommendation
from agente_bolsa.storage import Store
from agente_bolsa.tools.decision_lineage import build_decision_lineage
from agente_bolsa.tools.signal_learning import record_signal_candidates


def test_canonical_signal_id_survives_producer_to_lineage_without_unknown(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    candidate = {
        "symbol": "FDS",
        "direction": "long",
        "strategy_name": "builtin_breakout",
        "strategy_version": "v1",
        "last_date": "2026-07-13",
        "technical_state": {"close": 100},
        "risk_plan": {"entry_price": 100, "stop_loss": 90, "take_profit": 120},
    }
    report = {"run_id": "signal-run", "all_candidates": [candidate]}
    assert record_signal_candidates(store, report, source="learning_experiment") == 1
    persisted = store.signal_outcome_by_id(candidate["signal_id"])
    recommendation = TradeRecommendation(symbol="FDS", action="buy", confidence=0.8, reason="test")
    lineage = build_decision_lineage(
        recommendation,
        {"selected_candidates": [candidate]},
        cycle_id="decision-cycle",
        policy_version="v",
    )
    assert lineage["signal_id"] == persisted["signal_id"]
    assert lineage["signal_id"] == "learning_experiment:2026-07-13:BUILTIN_BREAKOUT:FDS"
    assert lineage["signal_source_run_id"] == "signal-run"
    assert lineage["cycle_id"] == "decision-cycle"
    assert lineage["lineage_status"] == "verified"
