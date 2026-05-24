from agente_bolsa.tools.signal_learning import (
    _outcome_for_signal,
    _combo_key,
    _indicator_tags,
    build_learning_status,
    record_signal_candidates,
    update_signal_decisions,
)
from agente_bolsa.models import TradeRecommendation
import pandas as pd


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
    assert rows[0]["features"]["source_rank"] == 1
    assert rows[0]["features"]["score_rank"] == 1
    assert rows[0]["features"]["score_rank_percentile"] == 1.0


def test_record_signal_candidates_persists_score_rank_independent_of_source_order(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "scan-ranks",
        "all_candidates": [
            {
                "symbol": "LOW",
                "direction": "long",
                "score": 10,
                "setup_quality": "strong",
                "last_date": "2026-04-27",
                "technical_state": {"close": 100, "sma_20": 95},
                "risk_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 115},
            },
            {
                "symbol": "HIGH",
                "direction": "long",
                "score": 18,
                "setup_quality": "strong",
                "last_date": "2026-04-27",
                "technical_state": {"close": 100, "sma_20": 95},
                "risk_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 115},
            },
        ],
    }

    record_signal_candidates(store, report, source="test")
    rows = {row["symbol"]: row for row in store.signal_outcomes()}

    assert rows["LOW"]["features"]["source_rank"] == 1
    assert rows["LOW"]["features"]["score_rank"] == 2
    assert rows["HIGH"]["features"]["source_rank"] == 2
    assert rows["HIGH"]["features"]["score_rank"] == 1


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


def test_learning_status_reports_combinations_and_maturity(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    features = {
        "score": 15,
        "rsi_14": 55,
        "distance_sma20": 0.03,
        "macd_diff": 1.0,
        "volume_zscore_20": 1.5,
        "chart_patterns": {"bullish_confirmed_count": 1},
    }
    store.save_signal_outcome(
        signal_id="scan-1:AAPL",
        source_run_id="scan-1",
        source="test",
        symbol="AAPL",
        signal_date="2026-04-27",
        decision="approved_buy",
        features=features,
        outcome={
            "verdict": "winner_open",
            "return_1d": 0.01,
            "return_3d": 0.02,
            "return_5d": 0.03,
            "return_10d": 0.04,
            "mfe_10d": 0.05,
            "mae_10d": -0.01,
        },
    )

    report = build_learning_status(store)

    assert report["resolved"] == 1
    assert report["pending"] == 0
    assert report["maturity"]["enough_for_rules"] is False
    assert report["best_combinations"][0]["key"] == _combo_key({"features": features})
    assert report["best_combinations"][0]["avg_return_10d"] == 0.04


def test_learning_status_reports_setup_stats(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan-setup:AAPL",
        source_run_id="scan-setup",
        source="test",
        symbol="AAPL",
        signal_date="2026-04-27",
        decision="approved_buy",
        features={
            "score": 18,
            "event_momentum_long": True,
            "return_20d": 0.4,
            "volume_zscore_20": 3.0,
            "chart_patterns": {"bullish_confirmed_count": 1},
        },
        outcome={"verdict": "winner_open", "return_5d": 0.08, "return_10d": 0.1},
    )

    report = build_learning_status(store)

    assert report["setup_stats"][0]["setup"] == "event_momentum"
    assert report["worst_setups"][0]["setup"] == "event_momentum"


def test_outcome_for_signal_marks_matured_when_future_bars_exist():
    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
            "High": [100, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111],
            "Low": [99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
        },
        index=pd.date_range("2026-04-27", periods=11, freq="D"),
    )
    signal = {
        "signal_date": "2026-04-27",
        "features": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 120.0},
    }

    outcome = _outcome_for_signal(signal, frame)

    assert outcome["available"] is True
    assert outcome["matured"] is True
    assert outcome["bars_seen"] == 10
    assert outcome["matured_horizons"]["10d"] is True
    assert outcome["return_5d"] == 0.05
    assert outcome["verdict"] == "winner_open"


def test_outcome_for_signal_keeps_pending_when_history_is_short():
    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103],
            "High": [100, 102, 103, 104],
            "Low": [99, 100, 101, 102],
            "Close": [100, 101, 102, 103],
        },
        index=pd.date_range("2026-04-27", periods=4, freq="D"),
    )
    signal = {
        "signal_date": "2026-04-27",
        "features": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 120.0},
    }

    outcome = _outcome_for_signal(signal, frame)

    assert outcome["available"] is True
    assert outcome["matured"] is False
    assert outcome["bars_seen"] == 3
    assert outcome["matured_horizons"]["5d"] is False
    assert outcome["return_3d"] == 0.03
    assert outcome["verdict"] == "pending"
