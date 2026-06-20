import json

import pandas as pd

from agente_bolsa.config import Settings
from agente_bolsa.models import TradeRecommendation
from agente_bolsa.tools.signal_learning import (
    _combo_key,
    _indicator_tags,
    _outcome_for_signal,
    backfill_signal_candidates_from_reports,
    build_learning_status,
    record_signal_candidates,
    update_signal_decisions,
    update_signal_execution_status,
)


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
                "setup_name": "confirmed_pattern",
                "selection_score": 0.042,
                "selection_rank": 1,
                "selection_reason": "profile_edge_high_sample",
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
    assert rows[0]["features"]["selection_score"] == 0.042
    assert rows[0]["features"]["selection_rank"] == 1
    assert rows[0]["features"]["selection_reason"] == "profile_edge_high_sample"


def test_record_signal_candidates_persists_market_regime_from_report(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    report = {
        "run_id": "scan-regime",
        "market_state": {
            "market_regime": "bullish",
            "volatility_regime": "normal",
            "risk_posture": "constructive",
            "data_quality": {"status": "GOOD"},
        },
        "all_candidates": [
            {
                "symbol": "AAPL",
                "direction": "long",
                "score": 15,
                "setup_quality": "strong",
                "last_date": "2026-04-27",
                "technical_state": {"close": 100, "sma_20": 95},
                "risk_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 115},
            }
        ],
    }

    record_signal_candidates(store, report, source="test")
    features = store.signal_outcomes()[0]["features"]

    assert features["market_regime"] == "bullish"
    assert features["volatility_regime"] == "normal"
    assert features["risk_posture"] == "constructive"
    assert features["market_state_quality"] == "GOOD"


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


def test_record_signal_candidates_marks_selected_for_llm_and_copies_selection_metadata(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    base_candidate = {
        "symbol": "AAPL",
        "direction": "long",
        "score": 16,
        "setup_quality": "strong",
        "last_date": "2026-04-27",
        "technical_state": {"close": 100, "sma_20": 95},
        "risk_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 115},
    }
    report = {
        "run_id": "scan-selected",
        "selection_metadata": {"method": "selection_score_with_shrunk_learning_prior"},
        "all_candidates": [base_candidate],
        "selected_candidates": [
            {
                **base_candidate,
                "selection_score": 0.081,
                "selection_rank": 1,
                "selection_reason": "high_conviction_confirmed_momentum",
            }
        ],
    }

    record_signal_candidates(store, report, source="test")
    row = store.signal_outcomes()[0]

    assert row["features"]["selected_for_llm"] is True
    assert row["features"]["selection_score"] == 0.081
    assert row["features"]["selection_rank"] == 1
    assert row["features"]["selection_reason"] == "high_conviction_confirmed_momentum"
    assert row["features"]["selection_method"] == "selection_score_with_shrunk_learning_prior"


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


def test_update_signal_decisions_marks_soft_backtest_override(tmp_path):
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
        features={"score": 17},
    )

    updated = update_signal_decisions(
        store,
        source_run_id="scan-1",
        recommendations=[
            TradeRecommendation(symbol="AAPL", action="buy", confidence=0.9, reason="test")
        ],
        entry_quality_gate=[
            {
                "symbol": "AAPL",
                "action": "buy",
                "approved": True,
                "reason": "entry-quality aprobado",
                "checks": {
                    "score": 17,
                    "volume_zscore_20": 1.4,
                    "confirmed_bullish_patterns": 2,
                    "close_position_in_range": 0.85,
                    "sma20_distance": 0.18,
                    "rsi_14": 78,
                    "entry_score_v2": {"reward_risk": 1.6},
                },
            }
        ],
        backtest_gate=[
            {"symbol": "AAPL", "approved": False, "reason": "trades 5 < minimo 10", "checks": {}}
        ],
        settings=Settings(DATA_DIR=tmp_path),
    )
    row = store.signal_outcomes()[0]

    assert updated == 1
    assert row["decision"] == "approved_buy_soft_backtest"
    assert row["gate"]["backtest_soft_override"]["approved"] is True
    assert row["gate"]["backtest_gate"]["reason"] == "trades 5 < minimo 10"


def test_update_signal_decisions_keeps_hard_backtest_block_when_not_high_conviction(tmp_path):
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
        features={"score": 12},
    )

    update_signal_decisions(
        store,
        source_run_id="scan-1",
        recommendations=[
            TradeRecommendation(symbol="AAPL", action="buy", confidence=0.9, reason="test")
        ],
        entry_quality_gate=[
            {
                "symbol": "AAPL",
                "action": "buy",
                "approved": True,
                "reason": "entry-quality aprobado",
                "checks": {
                    "score": 12,
                    "volume_zscore_20": 0.2,
                    "confirmed_bullish_patterns": 0,
                    "entry_score_v2": {"reward_risk": 1.6},
                },
            }
        ],
        backtest_gate=[
            {"symbol": "AAPL", "approved": False, "reason": "trades 5 < minimo 10", "checks": {}}
        ],
        settings=Settings(DATA_DIR=tmp_path),
    )
    row = store.signal_outcomes()[0]

    assert row["decision"] == "blocked_backtest"


def test_update_signal_decisions_logs_backtest_near_miss_shadow(tmp_path):
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
        features={"score": 12},
    )

    update_signal_decisions(
        store,
        source_run_id="scan-1",
        recommendations=[
            TradeRecommendation(symbol="AAPL", action="buy", confidence=0.9, reason="test")
        ],
        entry_quality_gate=[
            {
                "symbol": "AAPL",
                "action": "buy",
                "approved": True,
                "reason": "entry-quality aprobado",
                "checks": {"entry_score_v2": {"reward_risk": 1.6}},
            }
        ],
        backtest_gate=[
            {"symbol": "AAPL", "approved": False, "reason": "trades 8 < minimo 10", "checks": {}}
        ],
        settings=Settings(DATA_DIR=tmp_path),
    )
    row = store.signal_outcomes()[0]

    assert row["decision"] == "blocked_backtest"
    assert row["gate"]["backtest_near_miss_shadow"]["rule_id"] == "trades_8_vs_10"
    assert row["gate"]["backtest_near_miss_shadow"]["mode"] == "shadow_only"


def test_update_signal_decisions_does_not_shadow_excluded_near_miss(tmp_path):
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
        features={"score": 12},
    )

    update_signal_decisions(
        store,
        source_run_id="scan-1",
        recommendations=[
            TradeRecommendation(symbol="AAPL", action="buy", confidence=0.9, reason="test")
        ],
        entry_quality_gate=[
            {
                "symbol": "AAPL",
                "action": "buy",
                "approved": True,
                "reason": "entry-quality aprobado",
                "checks": {"entry_score_v2": {"reward_risk": 1.6}},
            }
        ],
        backtest_gate=[
            {"symbol": "AAPL", "approved": False, "reason": "hit-rate 44.44% < minimo 45.00%", "checks": {}}
        ],
        settings=Settings(DATA_DIR=tmp_path),
    )
    row = store.signal_outcomes()[0]

    assert row["decision"] == "blocked_backtest"
    assert "backtest_near_miss_shadow" not in row["gate"]


def test_update_signal_execution_status_marks_plan_rejected(tmp_path):
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
        features={"score": 16},
        gate={"llm": {"action": "buy"}},
    )

    updated = update_signal_execution_status(
        store,
        source_run_id="scan-1",
        approved_symbols=["AAPL"],
        rejected_order_plans=[{"symbol": "AAPL", "stage": "position_sizing", "reason": "below_min_order_notional"}],
        effective_max_orders_per_cycle=4,
        effective_max_daily_buy_orders=4,
    )
    row = store.signal_outcomes()[0]

    assert updated == 1
    assert row["gate"]["execution"]["status"] == "plan_rejected"
    assert row["gate"]["execution"]["stage"] == "position_sizing"
    assert row["gate"]["execution"]["reason"] == "below_min_order_notional"


def test_update_signal_execution_status_marks_submitted(tmp_path):
    from agente_bolsa.storage import Store

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan-1:MSFT",
        source_run_id="scan-1",
        source="test",
        symbol="MSFT",
        signal_date="2026-04-27",
        decision="approved_buy",
        features={"score": 17},
        gate={"llm": {"action": "buy"}},
    )

    updated = update_signal_execution_status(
        store,
        source_run_id="scan-1",
        approved_symbols=["MSFT"],
        planned_symbols=["MSFT"],
        submitted=[{"symbol": "MSFT", "status": "accepted", "notional": 1000.0}],
        effective_max_orders_per_cycle=5,
        effective_max_daily_buy_orders=5,
    )
    row = store.signal_outcomes()[0]

    assert updated == 1
    assert row["gate"]["execution"]["status"] == "submitted"
    assert row["gate"]["execution"]["broker_status"] == "accepted"
    assert row["gate"]["execution"]["notional"] == 1000.0
    assert "backtest_soft_override" not in row["gate"]


def test_backfill_signal_candidates_from_reports_infers_selected_candidates(tmp_path):
    from agente_bolsa.storage import Store

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = {
        "run_id": "mkt_backfill_1",
        "as_of": "2026-05-28T22:12:17+02:00",
        "all_candidates": [
            {
                "symbol": "AAPL",
                "direction": "long",
                "score": 16,
                "setup_quality": "strong",
                "last_date": "2026-05-28",
                "technical_state": {"close": 100, "sma_20": 95},
                "risk_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 115},
            },
            {
                "symbol": "MSFT",
                "direction": "long",
                "score": 14,
                "setup_quality": "strong",
                "last_date": "2026-05-28",
                "technical_state": {"close": 200, "sma_20": 190},
                "risk_plan": {"entry_price": 200, "stop_loss": 190, "take_profit": 230},
            },
        ],
        "top_longs": [
            {
                "symbol": "AAPL",
                "direction": "long",
                "score": 16,
                "setup_quality": "strong",
                "last_date": "2026-05-28",
                "technical_state": {"close": 100, "sma_20": 95},
                "risk_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 115},
            }
        ],
        "top_shorts": [],
    }
    (reports_dir / "closed_market_technical_study_mkt_backfill_1.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    settings = Settings(DATA_DIR=tmp_path, ALLOW_SHORT_SELLING=False)

    result = backfill_signal_candidates_from_reports(
        settings,
        store,
        reports_dir,
        since_date="2026-05-01",
        end_date="2026-05-31",
    )
    rows = {row["symbol"]: row for row in store.signal_outcomes()}

    assert result["reports_saved"] == 1
    assert result["signals_saved"] == 2
    assert result["inferred_reports"] == 1
    assert rows["AAPL"]["features"]["selected_for_llm"] is True
    assert rows["AAPL"]["features"]["selection_method"] == "backfill_inferred_from_top_lists"
    assert rows["MSFT"]["features"]["selected_for_llm"] is False


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


def test_outcome_for_signal_includes_exit_policy_v2_partial_and_trailing():
    frame = pd.DataFrame(
        {
            "Close": [102, 105, 110, 109, 108, 107, 106, 105, 104, 103],
            "High": [104, 106, 111, 115, 114, 113, 112, 111, 110, 109],
            "Low": [99, 103, 108, 109, 107, 106, 105, 104, 103, 102],
        },
        index=pd.date_range("2026-01-02", periods=10, freq="D"),
    )
    signal = {
        "signal_date": "2026-01-01",
        "features": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 130.0},
    }

    outcome = _outcome_for_signal(signal, frame)
    policy = outcome["exit_policy_v2"]

    assert outcome["matured"] is True
    assert outcome["mfe_10d"] == 0.15
    assert outcome["mae_10d"] == -0.01
    assert policy["available"] is True
    assert policy["partial_taken"] is True
    assert policy["exit_reason"] == "trailing_stop"
    assert policy["exit_day"] == 4
    assert policy["return_pct"] == 0.075


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
