from agente_bolsa.tools.signal_learning import (
    _indicator_tags,
    build_learning_status,
    record_signal_candidates,
    update_signal_decisions,
)
from agente_bolsa.models import TradeRecommendation


def test_record_signal_candidates_persists_features(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "scan-1",
        "all_candidates": [
            {
                "symbol": "AAPL",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "last_date": "2026-04-27",
                "technical_state": {
                    "close": 100,
                    "sma_20": 95,
                    "sma_200": 80,
                    "rsi_14": 72,
                    "macd": 2,
                    "macd_signal": 1,
                    "return_20d": 0.08,
                    "volume_zscore_20": 1.2,
                    "chart_patterns": [{"bias": "bullish", "status": "confirmed", "label": "doble suelo"}],
                },
                "risk_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 115},
            }
        ],
    }

    count = record_signal_candidates(store, report, source="test")
    rows = store.signal_outcomes()

    assert count == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["features"]["score"] == 15
    assert rows[0]["features"]["distance_sma20"] > 0


def test_update_signal_decisions_marks_blocked_entry_quality(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan-1:AAPL",
        source_run_id="scan-1",
        source="test",
        symbol="AAPL",
        signal_date="2026-04-27",
        decision="candidate",
        features={"score": 10},
    )

    updated = update_signal_decisions(
        store,
        source_run_id="scan-1",
        recommendations=[
            TradeRecommendation(symbol="AAPL", action="buy", confidence=0.9, reason="test")
        ],
        entry_quality_gate=[
            {"symbol": "AAPL", "action": "buy", "approved": False, "reason": "score bajo", "checks": {}}
        ],
        backtest_gate=[],
    )
    row = store.signal_outcomes()[0]

    assert updated == 1
    assert row["decision"] == "blocked_entry_quality"
    assert row["gate"]["entry_quality_gate"]["reason"] == "score bajo"


def test_learning_status_groups_indicator_tags(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan-1:AAPL",
        source_run_id="scan-1",
        source="test",
        symbol="AAPL",
        signal_date="2026-04-27",
        decision="approved_buy",
        features={
            "score": 15,
            "rsi_14": 72,
            "distance_sma20": 0.05,
            "macd_diff": 1.0,
            "volume_zscore_20": 1.2,
            "chart_patterns": {"bullish_confirmed_count": 1},
        },
        outcome={"verdict": "winner_open", "return_5d": 0.03},
    )

    report = build_learning_status(store)
    tags = {item["tag"] for item in report["best_indicators"]}

    assert report["signals"] == 1
    assert report["decisions"]["approved_buy"] == 1
    assert "score:gte15" in tags
    assert "chart_confirmed:yes" in tags


def test_indicator_tags_bucket_extreme_rsi():
    tags = _indicator_tags(
        {
            "features": {
                "score": 13,
                "rsi_14": 90,
                "distance_sma20": 0.2,
                "macd_diff": -1,
                "volume_zscore_20": -0.5,
                "chart_patterns": {"bullish_confirmed_count": 0},
            }
        }
    )

    assert "rsi:gt85" in tags
    assert "sma20_dist:gt12pct" in tags
    assert "macd:non_positive" in tags
