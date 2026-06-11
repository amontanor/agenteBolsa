import json

from agente_bolsa.config import Settings
from agente_bolsa.storage import Store
from agente_bolsa.tools.counterfactual_analysis import (
    build_fallback_blocker_report,
    build_decision_compare_report,
    build_missed_opportunities_report,
    build_selector_replay_report,
    build_signal_postmortem_report,
    build_session_retrospective_report,
    build_winner_coverage_report,
)
from agente_bolsa.main import _print_counterfactual_summary, build_parser


def _save_buy_order(store: Store, *, plan_id: str, cycle_id: str, symbol: str, created_at: str) -> None:
    store.save_broker_order(
        broker_order_id=f"bo_{plan_id}",
        plan_id=plan_id,
        cycle_id=cycle_id,
        symbol=symbol,
        side="buy",
        status="filled",
        payload={
            "plan": {
                "plan_id": plan_id,
                "notional": 1000.0,
                "payload": {
                    "entry_price": 100.0,
                    "qty": 10.0,
                    "recommendation": {"symbol": symbol, "action": "buy", "confidence": 0.9},
                },
            }
        },
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE broker_orders SET created_at = ? WHERE broker_order_id = ?",
            (created_at, f"bo_{plan_id}"),
        )


def test_new_cli_commands_are_parseable():
    parser = build_parser()

    args = parser.parse_args(["learning-daily-run"])
    assert args.command == "learning-daily-run"

    args = parser.parse_args(["learning-health"])
    assert args.command == "learning-health"

    args = parser.parse_args(["learning-digest"])
    assert args.command == "learning-digest"

    args = parser.parse_args(["policy-candidates"])
    assert args.command == "policy-candidates"

    args = parser.parse_args(["learning-promotions"])
    assert args.command == "learning-promotions"

    args = parser.parse_args(["learning-postmortem"])
    assert args.command == "learning-postmortem"

    args = parser.parse_args(["missed-opportunities"])
    assert args.command == "missed-opportunities"

    args = parser.parse_args(["decision-compare", "--policy", "proposed"])
    assert args.command == "decision-compare"

    args = parser.parse_args(["walk-forward-validate"])
    assert args.command == "walk-forward-validate"

    args = parser.parse_args(["session-retrospective"])
    assert args.command == "session-retrospective"

    args = parser.parse_args(["selector-replay"])
    assert args.command == "selector-replay"

    args = parser.parse_args(["winner-coverage-report"])
    assert args.command == "winner-coverage-report"


def test_counterfactual_summary_prints_winner_coverage_details(capsys):
    _print_counterfactual_summary(
        "COBERTURA DE GANADORAS",
        {
            "path": "winner_coverage_test.json",
            "period": {"from": "2026-05-26", "to": "2026-05-27"},
            "summary": {
                "winners_considered": 3,
                "selected_any": 2,
                "selected_majority": 1,
                "fallback_buy_any": 1,
                "fallback_buy_majority": 1,
                "coverage_buckets": {"captured_all": 1, "near_miss": 1},
                "fallback_blocker_summary": [{"reason": "sma20_extension_no_exception", "sessions": 7}],
                "selection_miss_summary": [{"reason": "rank_outside_selection_limit", "sessions": 14}],
            },
            "top_winner_coverage": [
                {
                    "symbol": "DELL",
                    "signal_date": "2026-05-26",
                    "return_5d": 0.4269,
                    "coverage_bucket": "captured_all",
                    "selected_sessions": 14,
                    "fallback_buy_sessions": 14,
                    "reports_on_date": 14,
                    "best_selection_rank": 2,
                }
            ],
        },
    )

    output = capsys.readouterr().out
    assert "Ganadoras=3" in output
    assert "Bloqueadores principales" in output
    assert "Misses de seleccion principales" in output
    assert "DELL 2026-05-26 ret5d=42.69%" in output


def test_missed_opportunities_report_only_lists_non_executed_winners(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan1:AAPL",
        source_run_id="scan1",
        source="test",
        symbol="AAPL",
        signal_date="2026-04-28",
        decision="candidate",
        features={"score": 15},
        outcome={"available": True, "matured": True, "return_5d": 0.08, "verdict": "winner_open"},
    )
    store.save_signal_outcome(
        signal_id="scan1:MSFT",
        source_run_id="scan1",
        source="test",
        symbol="MSFT",
        signal_date="2026-04-28",
        decision="approved_buy",
        features={"score": 13},
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )
    _save_buy_order(store, plan_id="p1", cycle_id="c1", symbol="MSFT", created_at="2026-04-28T15:30:00+00:00")

    report = build_missed_opportunities_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "missed_test",
        since_date="2026-04-28",
        top=10,
    )

    assert report["summary"]["missed_opportunities"] == 1
    assert report["top_missed_opportunities"][0]["symbol"] == "AAPL"
    assert report["top_missed_opportunities"][0]["flags"]["ranking_failure"] is True


def test_signal_postmortem_distinguishes_selected_for_llm_from_candidate_only(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.build_learning_status", lambda *args, **kwargs: {"available": True})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan1:SEL",
        source_run_id="scan1",
        source="test",
        symbol="SEL",
        signal_date="2026-04-28",
        decision="candidate",
        features={"score": 15, "selected_for_llm": True, "selection_score": 0.08, "selection_rank": 1},
        outcome={"available": True, "matured": True, "return_5d": 0.01, "verdict": "flat"},
    )
    store.save_signal_outcome(
        signal_id="scan1:RAW",
        source_run_id="scan1",
        source="test",
        symbol="RAW",
        signal_date="2026-04-28",
        decision="candidate",
        features={"score": 14, "selected_for_llm": False},
        outcome={"available": True, "matured": True, "return_5d": 0.0, "verdict": "flat"},
    )
    store.save_signal_outcome(
        signal_id="scan1:HOLD",
        source_run_id="scan1",
        source="test",
        symbol="HOLD",
        signal_date="2026-04-28",
        decision="hold",
        features={"score": 16, "selected_for_llm": True},
        gate={"llm": {"action": "hold", "reason": "no edge"}},
        outcome={"available": True, "matured": True, "return_5d": 0.0, "verdict": "flat"},
    )

    report = build_signal_postmortem_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "postmortem_selected_stage",
        since_date="2026-04-28",
        full=True,
    )

    assert report["summary"]["selected_for_llm"] == 2
    assert report["summary"]["considered_by_llm"] == 1
    assert report["summary"]["candidate_only"] == 1
    assert report["summary"]["cohorts"]["selected_for_llm"] == 1
    assert report["summary"]["cohorts"]["candidate_only"] == 1
    assert report["summary"]["cohorts"]["considered_by_llm"] == 1


def test_decision_compare_blocks_duplicate_current_executions(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    for suffix, ret in [("1", -0.04), ("2", -0.01)]:
        store.save_signal_outcome(
            signal_id=f"scan2:NVDA:{suffix}",
            source_run_id="scan2",
            source="test",
            symbol="NVDA",
            signal_date="2026-04-29",
            decision="approved_buy",
            features={"score": 16},
            outcome={"available": True, "matured": True, "return_5d": ret, "verdict": "loser_open"},
        )
    _save_buy_order(store, plan_id="p1", cycle_id="c2", symbol="NVDA", created_at="2026-04-29T15:30:00+00:00")
    _save_buy_order(store, plan_id="p2", cycle_id="c2", symbol="NVDA", created_at="2026-04-29T15:31:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "compare_test",
        since_date="2026-04-29",
        policy="proposed",
    )

    summary = report["summary"]
    assert summary["current"]["executed"] == 2
    assert summary["proposed"]["executed"] == 1
    assert summary["blocked_by_policy"] == 1
    assert summary["avoided_losers"] == 1
    assert summary["delta_net_opportunity"] == 0.01


def test_decision_compare_blocks_same_day_duplicate_across_different_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_a:NVDA",
        source_run_id="scan_a",
        source="test",
        symbol="NVDA",
        signal_date="2026-04-29",
        decision="approved_buy",
        features={"score": 16, "rsi_14": 68, "volume_zscore_20": 1.0},
        outcome={"available": True, "matured": True, "return_5d": -0.04, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan_b:NVDA",
        source_run_id="scan_b",
        source="test",
        symbol="NVDA",
        signal_date="2026-04-29",
        decision="approved_buy",
        features={"score": 15, "rsi_14": 67, "volume_zscore_20": 0.8},
        outcome={"available": True, "matured": True, "return_5d": -0.01, "verdict": "loser_open"},
    )
    _save_buy_order(store, plan_id="p1", cycle_id="c2", symbol="NVDA", created_at="2026-04-29T15:30:00+00:00")
    _save_buy_order(store, plan_id="p2", cycle_id="c3", symbol="NVDA", created_at="2026-04-29T17:31:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "compare_same_day_test",
        since_date="2026-04-29",
        policy="proposed",
    )

    summary = report["summary"]
    assert summary["current"]["executed"] == 2
    assert summary["proposed"]["executed"] == 1
    assert summary["blocked_by_policy"] == 1
    assert summary["avoided_losers"] == 1
    assert summary["delta_net_opportunity"] == 0.01


def test_decision_compare_blocks_weak_rsi_weak_volume_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_weak:FDX",
        source_run_id="scan_weak",
        source="test",
        symbol="FDX",
        signal_date="2026-04-29",
        decision="approved_buy",
        features={"score": 16, "rsi_14": 60.0, "volume_zscore_20": -0.5},
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )
    _save_buy_order(store, plan_id="p_weak", cycle_id="c_weak", symbol="FDX", created_at="2026-04-29T15:30:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "compare_weak_profile_test",
        since_date="2026-04-29",
        policy="proposed",
    )

    summary = report["summary"]
    assert summary["current"]["executed"] == 1
    assert summary["proposed"]["executed"] == 0
    assert summary["blocked_by_policy"] == 1
    assert summary["avoided_losers"] == 1
    assert summary["delta_net_opportunity"] == 0.03


def test_decision_compare_reports_rank_shadow_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_rank:LOW",
        source_run_id="scan_rank",
        source="test",
        symbol="LOW",
        signal_date="2026-05-01",
        decision="approved_buy",
        features={"score": 10, "return_20d": -0.01, "distance_sma20": -0.02, "volume_zscore_20": -0.5},
        outcome={"available": True, "matured": True, "return_5d": -0.04, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan_rank:HIGH",
        source_run_id="scan_rank",
        source="test",
        symbol="HIGH",
        signal_date="2026-05-01",
        decision="candidate",
        features={"score": 18, "return_20d": 0.08, "distance_sma20": 0.03, "volume_zscore_20": 1.2},
        outcome={"available": True, "matured": True, "return_5d": 0.06, "verdict": "winner_open"},
    )
    _save_buy_order(store, plan_id="p_rank", cycle_id="c_rank", symbol="LOW", created_at="2026-05-01T15:30:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "rank_shadow_test",
        since_date="2026-05-01",
        policy="proposed",
    )

    rank_shadow = report["summary"]["rank_shadow"]
    assert rank_shadow["candidate_replacements"] == 1
    assert rank_shadow["positive_replacements"] == 1
    assert rank_shadow["delta_net_opportunity"] == 0.1
    assert report["summary"]["regime_summary"]


def test_decision_compare_rank_shadow_uses_priority_not_only_raw_score(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_rank2:EXEC",
        source_run_id="scan_rank2",
        source="test",
        symbol="EXEC",
        signal_date="2026-05-01",
        decision="approved_buy",
        features={
            "score": 16,
            "return_20d": 0.02,
            "distance_sma20": 0.13,
            "volume_zscore_20": -0.6,
            "rsi_14": 60.0,
            "chart_patterns": {"bullish_confirmed_count": 0},
        },
        outcome={"available": True, "matured": True, "return_5d": -0.03, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan_rank2:ALT",
        source_run_id="scan_rank2",
        source="test",
        symbol="ALT",
        signal_date="2026-05-01",
        decision="candidate",
        features={
            "score": 15,
            "return_20d": 0.08,
            "distance_sma20": 0.03,
            "volume_zscore_20": 1.2,
            "rsi_14": 70.0,
            "chart_patterns": {"bullish_confirmed_count": 1},
        },
        outcome={"available": True, "matured": True, "return_5d": 0.04, "verdict": "winner_open"},
    )
    _save_buy_order(store, plan_id="p_rank2", cycle_id="c_rank2", symbol="EXEC", created_at="2026-05-01T15:30:00+00:00")

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "rank_shadow_priority_test",
        since_date="2026-05-01",
        policy="proposed",
    )

    rank_shadow = report["summary"]["rank_shadow"]
    assert rank_shadow["candidate_replacements"] == 1
    assert rank_shadow["positive_replacements"] == 1
    assert rank_shadow["delta_net_opportunity"] == 0.07
    example = rank_shadow["examples"][0]
    assert example["replace_symbol"] == "EXEC"
    assert example["with_symbol"] == "ALT"
    assert example["with_score"] < example["replace_score"]
    assert example["with_priority"] > example["replace_priority"]


def test_decision_compare_uses_trade_memory_for_executed_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan_tm:AAPL",
        source_run_id="scan_tm",
        source="test",
        symbol="AAPL",
        signal_date="2026-05-02",
        decision="approved_buy",
        features={"score": 16},
        outcome={"available": False, "matured": False, "reason": "sin barras posteriores"},
    )
    _save_buy_order(store, plan_id="p_tm", cycle_id="c_tm", symbol="AAPL", created_at="2026-05-02T15:30:00+00:00")
    store.save_trade_memory(
        {
            "memory_id": "tm_aapl",
            "trade_time": "2026-05-02T15:30:00Z",
            "trade_date": "2026-05-02",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 10,
            "price": 100,
            "notional": 1000,
            "realized_pl": None,
            "realized_plpc": None,
            "open_pl": -25,
            "open_plpc": -0.025,
            "verdict": "loser_open",
            "features": {},
            "thesis": {},
            "outcome": {"pl": -25, "plpc": -0.025, "verdict": "loser_open"},
        }
    )

    report = build_decision_compare_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "trade_memory_test",
        since_date="2026-05-02",
        policy="proposed",
    )

    assert report["summary"]["current"]["matured"] == 1
    assert report["summary"]["current"]["losers"] == 1
    assert report["summary"]["current"]["avg_return_5d"] == -0.025


def test_session_retrospective_aggregates_daily_results(tmp_path, monkeypatch):
    monkeypatch.setattr("agente_bolsa.tools.counterfactual_analysis.update_signal_outcomes", lambda *args, **kwargs: {"updated": 0})
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    store.save_signal_outcome(
        signal_id="scan3:AMZN:1",
        source_run_id="scan3",
        source="test",
        symbol="AMZN",
        signal_date="2026-04-30",
        decision="approved_buy",
        features={"score": 15},
        outcome={"available": True, "matured": True, "return_5d": -0.02, "verdict": "loser_open"},
    )
    store.save_signal_outcome(
        signal_id="scan3:AMZN:2",
        source_run_id="scan3",
        source="test",
        symbol="AMZN",
        signal_date="2026-04-30",
        decision="approved_buy",
        features={"score": 14},
        outcome={"available": True, "matured": True, "return_5d": 0.01, "verdict": "flat"},
    )
    _save_buy_order(store, plan_id="p1", cycle_id="c3", symbol="AMZN", created_at="2026-04-30T15:30:00+00:00")
    _save_buy_order(store, plan_id="p2", cycle_id="c3", symbol="AMZN", created_at="2026-04-30T15:31:00+00:00")

    report = build_session_retrospective_report(
        Settings(DATA_DIR=tmp_path),
        store,
        tmp_path / "reports",
        "retro_test",
        since_date="2026-04-30",
        end_date="2026-04-30",
        sessions=8,
        policy="proposed",
    )

    assert report["summary"]["sessions"] == 1
    session = report["sessions"][0]
    assert session["blocked_by_new_policy"] == 1
    assert session["delta_fragmentation"] == 1
    assert "rank_shadow_replacements" in session
    assert "aggregate_rank_shadow_delta" in report["summary"]


def test_selector_replay_marks_tracked_symbols_selected(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "closed_market_technical_study_test.json"
    report_path.write_text(
        """
        {
          "run_id": "mkt_test",
          "as_of": "2026-06-02T17:00:00+00:00",
          "top_longs": [{"symbol": "QCOM"}],
          "top_shorts": [],
          "all_candidates": [
            {
              "symbol": "QCOM",
              "direction": "long",
              "score": 15,
              "setup_quality": "strong",
              "relative_return_20d": 0.22,
              "technical_state": {
                "close": 110.0,
                "return_20d": 0.18,
                "sma_20": 100.0,
                "rsi_14": 79.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.8,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}]
              },
              "risk_plan": {"entry_price": 110.0, "stop_loss": 103.0, "take_profit": 120.5}
            },
            {
              "symbol": "PLAIN",
              "direction": "long",
              "score": 12,
              "setup_quality": "strong",
              "relative_return_20d": 0.02,
              "technical_state": {
                "close": 100.0,
                "return_20d": 0.03,
                "sma_20": 98.0,
                "rsi_14": 60.0,
                "macd": 1.0,
                "macd_signal": 0.9,
                "volume_zscore_20": 0.0,
                "chart_patterns": []
              },
              "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0}
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    report = build_selector_replay_report(
        Settings(DATA_DIR=tmp_path),
        reports_dir,
        "selector_replay_test",
        since_date="2026-06-02",
        end_date="2026-06-02",
        limit=5,
        symbols=["QCOM"],
        full=True,
    )

    assert report["summary"]["sessions_scanned"] == 1
    tracked = report["summary"]["tracked_symbols"][0]
    assert tracked["symbol"] == "QCOM"
    assert tracked["selected_sessions"] == 1
    assert tracked["best_rank"] == 1
    session_tracked = report["sessions"][0]["tracked_symbols"][0]
    assert session_tracked["selected"] is True
    assert session_tracked["selection_rank"] == 1
    assert session_tracked["score_rank"] == 1


def test_selector_replay_exposes_rank_for_tracked_symbol_outside_limit(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "closed_market_technical_study_test.json"
    report_path.write_text(
        """
        {
          "run_id": "mkt_test",
          "as_of": "2026-06-02T17:00:00+00:00",
          "top_longs": [{"symbol": "QCOM"}, {"symbol": "CSCO"}],
          "top_shorts": [],
          "all_candidates": [
            {
              "symbol": "QCOM",
              "direction": "long",
              "score": 15,
              "setup_quality": "strong",
              "relative_return_20d": 0.22,
              "technical_state": {
                "close": 110.0,
                "return_20d": 0.18,
                "sma_20": 100.0,
                "rsi_14": 79.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.8,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}]
              },
              "risk_plan": {"entry_price": 110.0, "stop_loss": 103.0, "take_profit": 120.5}
            },
            {
              "symbol": "CSCO",
              "direction": "long",
              "score": 14,
              "setup_quality": "strong",
              "relative_return_20d": 0.08,
              "technical_state": {
                "close": 104.0,
                "return_20d": 0.11,
                "sma_20": 100.0,
                "rsi_14": 67.0,
                "macd": 1.5,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.2,
                "chart_patterns": [
                  {"bias": "bullish", "status": "confirmed"},
                  {"bias": "bullish", "status": "confirmed"}
                ]
              },
              "risk_plan": {"entry_price": 104.0, "stop_loss": 98.0, "take_profit": 113.0}
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    report = build_selector_replay_report(
        Settings(DATA_DIR=tmp_path),
        reports_dir,
        "selector_replay_test_ranked",
        since_date="2026-06-02",
        end_date="2026-06-02",
        limit=1,
        symbols=["CSCO"],
        full=True,
    )

    tracked = report["sessions"][0]["tracked_symbols"][0]
    assert tracked["symbol"] == "CSCO"
    assert tracked["selected"] is False
    assert tracked["selected_rank"] is None
    assert tracked["selection_rank"] == 2
    assert tracked["selection_reason"] is not None
    assert tracked["selection_score"] is not None


def test_selector_replay_uses_top_long_rank_alignment_from_report(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "closed_market_technical_study_test.json"
    report_path.write_text(
        """
        {
          "run_id": "mkt_test",
          "as_of": "2026-06-02T17:00:00+00:00",
          "top_longs": [{"symbol": "CSCO"}],
          "top_shorts": [],
          "all_candidates": [
            {
              "symbol": "CSCO",
              "direction": "long",
              "score": 15,
              "setup_quality": "strong",
              "technical_state": {
                "close": 107.0,
                "return_20d": 0.16,
                "return_60d": 0.18,
                "sma_20": 100.0,
                "rsi_14": 69.5,
                "macd": 1.6,
                "macd_signal": 1.0,
                "volume_zscore_20": -1.8,
                "chart_patterns": [
                  {"bias": "bullish", "status": "confirmed"},
                  {"bias": "bullish", "status": "confirmed"}
                ]
              },
              "risk_plan": {"entry_price": 107.0, "stop_loss": 101.0, "take_profit": 116.0}
            },
            {
              "symbol": "PLAIN",
              "direction": "long",
              "score": 16,
              "setup_quality": "strong",
              "relative_return_20d": 0.02,
              "technical_state": {
                "close": 100.0,
                "return_20d": 0.03,
                "sma_20": 98.0,
                "rsi_14": 60.0,
                "macd": 1.0,
                "macd_signal": 0.9,
                "volume_zscore_20": 0.0,
                "chart_patterns": []
              },
              "risk_plan": {"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0}
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    report = build_selector_replay_report(
        Settings(DATA_DIR=tmp_path),
        reports_dir,
        "selector_replay_test_alignment",
        since_date="2026-06-02",
        end_date="2026-06-02",
        limit=2,
        symbols=["CSCO"],
        full=True,
    )

    tracked = report["sessions"][0]["tracked_symbols"][0]
    assert tracked["symbol"] == "CSCO"
    assert tracked["selected"] is True
    assert tracked["selection_reason"] is not None
    assert "top_long_alignment" in tracked["selection_reason"]


def test_winner_coverage_report_summarizes_top_winner_capture(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    store.upsert_learning_observation(
        {
            "observation_id": "obs_qcom",
            "signal_date": "2026-06-02",
            "symbol": "QCOM",
            "source_family": "closed_market_study",
            "source_run_ids": ["mkt_test"],
            "best_signal_id": "sig_qcom",
            "best_score": 15,
            "decision": "candidate",
            "explanation": "winner",
            "llm_considered": False,
            "approved_buy": False,
            "blocked_entry_quality": False,
            "blocked_backtest": False,
            "executed_buy": False,
            "duplicate_count": 1,
            "rank_path": [{"stage": "candidate"}],
            "features": {
                "score": 15,
                "return_20d": 0.18,
                "rsi_14": 79.0,
                "distance_sma20": 0.10,
                "volume_zscore_20": -0.8,
                "chart_patterns": {"bullish_confirmed_count": 1},
            },
            "gate": {},
            "outcome": {"return_5d": 0.42, "matured": True, "available": True},
            "execution": {},
        }
    )
    (reports_dir / "closed_market_technical_study_test.json").write_text(
        """
        {
          "run_id": "mkt_test",
          "as_of": "2026-06-02T17:00:00+00:00",
          "top_longs": [{"symbol": "QCOM"}],
          "top_shorts": [],
          "all_candidates": [
            {
              "symbol": "QCOM",
              "direction": "long",
              "score": 15,
              "setup_quality": "strong",
              "relative_return_20d": 0.22,
                  "technical_state": {
                    "close": 108.0,
                    "return_20d": 0.18,
                    "return_60d": 0.25,
                    "sma_20": 100.0,
                    "rsi_14": 79.0,
                    "macd": 2.0,
                    "macd_signal": 1.0,
                    "volume_zscore_20": 1.2,
                    "chart_patterns": [{"bias": "bullish", "status": "confirmed"}]
                  },
                  "risk_plan": {"entry_price": 108.0, "stop_loss": 101.0, "take_profit": 119.0}
                }
              ]
            }
        """.strip(),
        encoding="utf-8",
    )

    report = build_winner_coverage_report(
        Settings(DATA_DIR=tmp_path),
        store,
        reports_dir,
        "winner_coverage_test",
        since_date="2026-06-02",
        end_date="2026-06-02",
        top_n=5,
        full=True,
    )

    assert report["summary"]["winners_considered"] == 1
    assert report["summary"]["selected_any"] == 1
    assert report["summary"]["fallback_buy_any"] == 1
    assert report["summary"]["coverage_buckets"]["captured_all"] == 1
    assert report["summary"]["fallback_blocker_summary"] == []
    winner = report["top_winner_coverage"][0]
    assert winner["symbol"] == "QCOM"
    assert winner["selected_sessions"] == 1
    assert winner["best_selected_rank"] == 1
    assert winner["fallback_buy_sessions"] == 1
    assert winner["best_fallback_rank"] == 1
    assert winner["coverage_bucket"] == "captured_all"


def test_winner_coverage_report_surfaces_fallback_blockers(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    store.upsert_learning_observation(
        {
            "observation_id": "obs_ddog",
            "signal_date": "2026-06-02",
            "symbol": "DDOG",
            "source_family": "closed_market_study",
            "source_run_ids": ["mkt_test"],
            "best_signal_id": "sig_ddog",
            "best_score": 15,
            "decision": "candidate",
            "explanation": "winner",
            "llm_considered": False,
            "approved_buy": False,
            "blocked_entry_quality": False,
            "blocked_backtest": False,
            "executed_buy": False,
            "duplicate_count": 1,
            "rank_path": [{"stage": "candidate"}],
            "features": {
                "score": 15,
                "return_20d": 0.24,
                "rsi_14": 76.0,
                "distance_sma20": 0.10,
                "volume_zscore_20": 0.8,
                "chart_patterns": {"bullish_confirmed_count": 1},
            },
            "gate": {},
            "outcome": {"return_5d": 0.42, "matured": True, "available": True},
            "execution": {},
        }
    )
    (reports_dir / "closed_market_technical_study_test.json").write_text(
        """
        {
          "run_id": "mkt_test",
          "as_of": "2026-06-02T17:00:00+00:00",
          "top_longs": [{"symbol": "DDOG"}],
          "top_shorts": [],
          "all_candidates": [
            {
              "symbol": "DDOG",
              "direction": "long",
              "score": 15,
              "setup_quality": "strong",
                  "technical_state": {
                    "close": 120.0,
                    "return_20d": 0.24,
                    "return_60d": 0.25,
                    "sma_20": 100.0,
                    "rsi_14": 76.0,
                    "macd": 2.0,
                    "macd_signal": 1.0,
                    "volume_zscore_20": 0.8,
                    "chart_patterns": [{"bias": "bullish", "status": "confirmed"}]
                  },
                  "risk_plan": {"entry_price": 120.0, "stop_loss": 113.0, "take_profit": 130.5}
                }
              ]
            }
        """.strip(),
        encoding="utf-8",
    )

    report = build_winner_coverage_report(
        Settings(DATA_DIR=tmp_path),
        store,
        reports_dir,
        "winner_coverage_test_blocked",
        since_date="2026-06-02",
        end_date="2026-06-02",
        top_n=5,
        full=True,
    )

    winner = report["top_winner_coverage"][0]
    assert winner["symbol"] == "DDOG"
    assert winner["selected_sessions"] == 1
    assert winner["fallback_buy_sessions"] == 0
    assert winner["fallback_blockers"][0]["reason"].startswith("sma20_extension_no_exception")
    assert report["summary"]["fallback_blocker_summary"][0]["reason"].startswith("sma20_extension_no_exception")


def test_winner_coverage_report_surfaces_selection_miss_reasons(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    store.upsert_learning_observation(
        {
            "observation_id": "obs_smci",
            "signal_date": "2026-06-02",
            "symbol": "SMCI",
            "source_family": "closed_market_study",
            "source_run_ids": ["mkt_test"],
            "best_signal_id": "sig_smci",
            "best_score": 12,
            "decision": "candidate",
            "explanation": "near miss",
            "llm_considered": False,
            "approved_buy": False,
            "blocked_entry_quality": False,
            "blocked_backtest": False,
            "executed_buy": False,
            "duplicate_count": 1,
            "rank_path": [{"stage": "candidate"}],
            "features": {"score": 12},
            "gate": {},
            "outcome": {"return_5d": 0.35, "matured": True, "available": True},
            "execution": {},
        }
    )
    candidates = []
    for index in range(25):
        candidates.append(
            {
                "symbol": f"AAA{index}",
                "direction": "long",
                "score": 18,
                "setup_quality": "strong",
                "technical_state": {
                    "close": 105.0,
                    "return_20d": 0.10,
                    "sma_20": 100.0,
                    "rsi_14": 65.0,
                    "macd": 2.0,
                    "macd_signal": 1.0,
                    "volume_zscore_20": 1.0,
                    "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
                },
                "risk_plan": {"entry_price": 105.0, "stop_loss": 100.0, "take_profit": 115.0},
            }
        )
    candidates.append(
        {
            "symbol": "SMCI",
            "direction": "long",
            "score": 1,
            "setup_quality": "strong",
            "relative_return_20d": 0.0,
            "technical_state": {
                "close": 112.0,
                "return_20d": 0.01,
                "sma_20": 100.0,
                "rsi_14": 55.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": -0.8,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}],
            },
            "risk_plan": {"entry_price": 112.0, "stop_loss": 106.0, "take_profit": 124.0},
        }
    )
    (reports_dir / "closed_market_technical_study_test.json").write_text(
        json.dumps(
            {
                "run_id": "mkt_test",
                "as_of": "2026-06-02T17:00:00+00:00",
                "top_longs": [],
                "top_shorts": [],
                "all_candidates": candidates,
            }
        ),
        encoding="utf-8",
    )

    report = build_winner_coverage_report(
        Settings(DATA_DIR=tmp_path),
        store,
        reports_dir,
        "winner_coverage_test_selection_miss",
        since_date="2026-06-02",
        end_date="2026-06-02",
        top_n=5,
        full=True,
    )

    winner = report["top_winner_coverage"][0]
    assert winner["symbol"] == "SMCI"
    assert winner["selected_sessions"] == 0
    assert winner["selection_miss_reasons"][0]["reason"] == "rank_outside_selection_limit"
    assert report["summary"]["selection_miss_summary"][0]["reason"] == "rank_outside_selection_limit"


def test_winner_coverage_report_surfaces_bearish_direction_miss(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    store.upsert_learning_observation(
        {
            "observation_id": "obs_axon",
            "signal_date": "2026-06-02",
            "symbol": "AXON",
            "source_family": "closed_market_study",
            "source_run_ids": ["mkt_test"],
            "best_signal_id": "sig_axon",
            "best_score": 11,
            "decision": "candidate",
            "explanation": "bearish reversal",
            "llm_considered": False,
            "approved_buy": False,
            "blocked_entry_quality": False,
            "blocked_backtest": False,
            "executed_buy": False,
            "duplicate_count": 1,
            "rank_path": [{"stage": "candidate"}],
            "features": {"score": 11},
            "gate": {},
            "outcome": {"return_5d": 0.28, "matured": True, "available": True},
            "execution": {},
        }
    )
    (reports_dir / "closed_market_technical_study_test.json").write_text(
        json.dumps(
            {
                "run_id": "mkt_test",
                "as_of": "2026-06-02T17:00:00+00:00",
                "top_longs": [],
                "top_shorts": [{"symbol": "AXON"}],
                "all_candidates": [
                    {
                        "symbol": "AXON",
                        "direction": "short",
                        "score": 11,
                        "setup_quality": "strong",
                        "technical_state": {
                            "close": 90.0,
                            "return_20d": -0.05,
                            "sma_20": 100.0,
                            "rsi_14": 50.0,
                            "chart_patterns": [{"bias": "bearish", "status": "confirmed"}],
                        },
                        "risk_plan": {"entry_price": 90.0, "stop_loss": 95.0, "take_profit": 80.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_winner_coverage_report(
        Settings(DATA_DIR=tmp_path),
        store,
        reports_dir,
        "winner_coverage_test_bearish_miss",
        since_date="2026-06-02",
        end_date="2026-06-02",
        top_n=5,
        full=True,
    )

    winner = report["top_winner_coverage"][0]
    assert winner["selection_miss_reasons"][0]["reason"] == "bearish_direction"
    assert winner["selection_miss_examples"][0]["directions"] == ["short"]


def test_winner_coverage_report_recognizes_constructive_extension_fallback_buy(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    store.upsert_learning_observation(
        {
            "observation_id": "obs_ddog_constructive",
            "signal_date": "2026-06-02",
            "symbol": "DDOG",
            "source_family": "closed_market_study",
            "source_run_ids": ["mkt_constructive"],
            "best_signal_id": "sig_ddog_constructive",
            "best_score": 13,
            "decision": "candidate",
            "explanation": "winner",
            "llm_considered": False,
            "approved_buy": False,
            "blocked_entry_quality": False,
            "blocked_backtest": False,
            "executed_buy": False,
            "duplicate_count": 1,
            "rank_path": [{"stage": "candidate"}],
            "features": {
                "score": 13,
                "return_20d": 0.2322,
                "rsi_14": 74.12,
                "distance_sma20": 0.1208,
                "volume_zscore_20": 0.83,
                "chart_patterns": {"bullish_confirmed_count": 1},
            },
            "gate": {},
            "outcome": {"return_5d": 0.42, "matured": True, "available": True},
            "execution": {},
        }
    )
    (reports_dir / "closed_market_technical_study_constructive.json").write_text(
        """
        {
          "run_id": "mkt_constructive",
          "as_of": "2026-06-02T17:00:00+00:00",
          "top_longs": [{"symbol": "DDOG"}],
          "top_shorts": [],
          "all_candidates": [
            {
              "symbol": "DDOG",
              "direction": "long",
              "score": 13,
              "setup_quality": "strong",
              "technical_state": {
                "close": 112.08,
                "return_20d": 0.2322,
                "return_60d": 0.25,
                "sma_20": 100.0,
                "rsi_14": 74.12,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 0.83,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}]
              },
              "risk_plan": {"entry_price": 112.08, "stop_loss": 106.0, "take_profit": 130.32}
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    report = build_winner_coverage_report(
        Settings(DATA_DIR=tmp_path),
        store,
        reports_dir,
        "winner_coverage_test_constructive",
        since_date="2026-06-02",
        end_date="2026-06-02",
        top_n=5,
        full=True,
    )

    winner = report["top_winner_coverage"][0]
    assert winner["symbol"] == "DDOG"
    assert winner["selected_sessions"] == 1
    assert winner["fallback_buy_sessions"] == 1
    assert winner["best_fallback_rank"] == 1
    assert winner["fallback_blockers"] == []
    assert report["summary"]["fallback_buy_any"] == 1
    assert report["summary"]["fallback_blocker_summary"] == []


def test_fallback_blocker_report_summarizes_blocker_outcomes(tmp_path):
    store = Store(tmp_path / "state.sqlite3", tmp_path / "logs")
    store.ensure_schema()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    store.upsert_learning_observation(
        {
            "observation_id": "obs_qcom_blocked",
            "signal_date": "2026-06-02",
            "symbol": "QCOM",
            "source_family": "closed_market_study",
            "source_run_ids": ["mkt_qcom"],
            "best_signal_id": "sig_qcom",
            "best_score": 15,
            "decision": "candidate",
            "explanation": "winner",
            "llm_considered": False,
            "approved_buy": False,
            "blocked_entry_quality": False,
            "blocked_backtest": False,
            "executed_buy": False,
            "duplicate_count": 1,
            "rank_path": [{"stage": "candidate"}],
            "features": {
                "score": 15,
                "return_20d": 0.18,
                "rsi_14": 79.0,
                "distance_sma20": 0.08,
                "volume_zscore_20": 1.2,
                "chart_patterns": {"bullish_confirmed_count": 1},
            },
            "gate": {},
            "outcome": {"return_5d": 0.18, "matured": True, "available": True},
            "execution": {},
        }
    )
    (reports_dir / "closed_market_technical_study_qcom.json").write_text(
        """
        {
          "run_id": "mkt_qcom",
          "as_of": "2026-06-02T17:00:00+00:00",
          "top_longs": [{"symbol": "QCOM"}],
          "top_shorts": [],
          "all_candidates": [
            {
              "symbol": "QCOM",
              "direction": "long",
              "score": 15,
              "setup_quality": "strong",
              "relative_return_20d": 0.22,
              "technical_state": {
                "close": 120.0,
                "return_20d": 0.18,
                "return_60d": 0.25,
                "sma_20": 100.0,
                "rsi_14": 79.0,
                "macd": 2.0,
                "macd_signal": 1.0,
                "volume_zscore_20": 1.2,
                "chart_patterns": [{"bias": "bullish", "status": "confirmed"}]
              },
              "risk_plan": {"entry_price": 120.0, "stop_loss": 113.0, "take_profit": 130.5}
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    report = build_fallback_blocker_report(
        Settings(DATA_DIR=tmp_path),
        store,
        reports_dir,
        "fallback_blockers_test",
        since_date="2026-06-02",
        end_date="2026-06-02",
        full=True,
    )

    assert report["summary"]["selected_blocked_sessions"] == 1
    group = report["summary"]["blocker_groups"][0]
    assert group["reason"] == "sma20_extension_no_exception"
    assert group["matured"] == 1
    assert group["avg_return_5d"] == 0.18
    assert group["wins_10pct"] == 1
    assert group["negative"] == 0
    assert group["top_examples"][0]["symbol"] == "QCOM"
    extension_cohort = report["summary"]["extension_cohorts"][0]
    assert extension_cohort["matured"] == 1
    assert extension_cohort["avg_return_5d"] == 0.18
    assert extension_cohort["top_symbols"][0] == {"symbol": "QCOM", "sessions": 1}
    assert "confirmed_pattern" in extension_cohort["signature"]["selection_reason"]
    assert extension_cohort["signature"]["score"] == 15
    assert extension_cohort["signature"]["rank_band"] == "01-05"
    assert extension_cohort["signature"]["return_20d_band"] == "0.15-0.20"
    assert extension_cohort["signature"]["rsi_14_band"] == "75.00-80.00"
    assert extension_cohort["signature"]["sma20_extension_band"] == "0.20-0.22"
    assert extension_cohort["signature"]["relative_strength_available"] is True
